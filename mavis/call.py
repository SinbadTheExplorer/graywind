"""One phone-style call with Johnny over a WebSocket.

The browser sends each finished utterance as one binary message (WAV bytes).
Johnny transcribes it, streams an answer, speaks it sentence by sentence and
sends each sentence's audio back. One turn at a time.

A single receive loop runs for the whole call, alongside any turn in
progress, so End call is never stuck behind a slow answer: it cancels the
turn the moment it arrives.

Everything that touches the outside world (speech-to-text, the model, the
voice, canned lines) comes in through `CallDeps`, so tests run with fakes.
"""
import asyncio
import contextlib
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable


class AnswerError(Exception):
    """answer() could not produce a response."""


class ClientGone(Exception):
    """A send failed: the browser has left."""


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass
class CallDeps:
    transcribe: Callable[[bytes], Awaitable[str]]
    answer: Callable[[str], AsyncIterator[str]]
    synth: Callable[[str], bytes]                 # blocking; run in a thread
    canned: Callable[[str], bytes | None]         # "greeting" | "filler" | "dismissal"
    is_dismissal: Callable[[str], bool]
    make_cutter: Callable[[], Any]                # .push(text) / .flush() -> sentences
    filler_after: float = 2.0
    clock: Callable[[], float] = time.monotonic
    log: Callable[[str], None] = field(default=_stderr)


async def _send_json(ws, obj) -> None:
    try:
        await ws.send_json(obj)
    except Exception as exc:
        raise ClientGone() from exc


async def _send_bytes(ws, data: bytes) -> None:
    try:
        await ws.send_bytes(data)
    except Exception as exc:
        raise ClientGone() from exc


_DONE = ("done", None, None)


async def _produce(question: str, deps: CallDeps, queue: asyncio.Queue) -> None:
    """Answer -> sentences -> audio, in order, onto `queue`, then _DONE."""
    cutter = deps.make_cutter()

    async def speak(sentences):
        for sentence in sentences:
            try:
                wav = await asyncio.to_thread(deps.synth, sentence)
            except Exception as exc:  # one bad sentence must not end the answer
                deps.log(f"call: synth failed for {sentence!r}: {exc}")
                continue
            await queue.put(("audio", sentence, wav))

    try:
        async for delta in deps.answer(question):
            await speak(cutter.push(delta))
        await speak(cutter.flush())
    except AnswerError as exc:
        await queue.put(("error", str(exc), None))
    except Exception as exc:  # noqa: BLE001 -- reported to the caller, not raised
        deps.log(f"call: answer failed: {type(exc).__name__}: {exc}")
        await queue.put(("error", f"{type(exc).__name__}: {exc}", None))
    # Not in a `finally`: a cancelled producer must stop, not keep synthesising.
    await queue.put(_DONE)


async def _deliver(ws, deps: CallDeps, queue: asyncio.Queue, t0: float) -> None:
    """Send the producer's audio as it arrives, with one filler if it's slow."""
    started = deps.clock()
    first_sent = False
    filler_tried = False
    speaking = False
    while True:
        if not first_sent and not filler_tried:
            wait = max(0.0, deps.filler_after - (deps.clock() - started))
            try:
                item = await asyncio.wait_for(queue.get(), timeout=wait)
            except asyncio.TimeoutError:
                filler_tried = True
                filler = deps.canned("filler")
                if filler:
                    speaking = True
                    await _send_json(ws, {"type": "state", "state": "speaking"})
                    await _send_bytes(ws, filler)
                continue
        else:
            item = await queue.get()

        kind, text, wav = item
        if kind == "done":
            return
        if kind == "error":
            await _send_json(ws, {"type": "error", "message": text})
            continue
        if not first_sent:
            first_sent = True
            if not speaking:
                await _send_json(ws, {"type": "state", "state": "speaking"})
            deps.log(f"call: first audio {int((deps.clock() - t0) * 1000)} ms after utterance")
        await _send_json(ws, {"type": "caption", "text": text})
        await _send_bytes(ws, wav)


async def _turn(wav: bytes, deps: CallDeps, ws) -> bool:
    """One question and answer. True when the caller said goodbye."""
    t0 = deps.clock()
    await _send_json(ws, {"type": "state", "state": "thinking"})
    try:
        text = await deps.transcribe(wav)
    except Exception as exc:  # noqa: BLE001
        await _send_json(ws, {"type": "error", "message": str(exc)})
        await _send_json(ws, {"type": "state", "state": "listening"})
        return False

    text = (text or "").strip()
    if not text:
        await _send_json(ws, {"type": "state", "state": "listening"})
        return False
    await _send_json(ws, {"type": "heard", "text": text})

    if deps.is_dismissal(text):
        await _send_json(ws, {"type": "state", "state": "speaking"})
        line = deps.canned("dismissal")
        if line:
            await _send_bytes(ws, line)
        await _send_json(ws, {"type": "bye"})
        return True

    queue: asyncio.Queue = asyncio.Queue()
    producer = asyncio.create_task(_produce(text, deps, queue))
    try:
        await _deliver(ws, deps, queue, t0)
    finally:
        producer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer
    await _send_json(ws, {"type": "turn_done"})
    await _send_json(ws, {"type": "state", "state": "listening"})
    return False


async def _cancel(task) -> None:
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


async def run_call(ws, deps: CallDeps) -> None:
    """Run one call on an accepted, authenticated WebSocket until it ends."""
    start = deps.clock()
    receiving = turn = None
    try:
        await _send_json(ws, {"type": "state", "state": "speaking"})
        greeting = deps.canned("greeting")
        if greeting:
            await _send_bytes(ws, greeting)
        await _send_json(ws, {"type": "state", "state": "listening"})
        deps.log(f"call: greeting sent in {int((deps.clock() - start) * 1000)} ms")

        while True:
            if receiving is None:
                receiving = asyncio.create_task(ws.receive())
            waiting = {receiving} | ({turn} if turn else set())
            done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)

            if turn in done:
                finished, turn = turn, None
                exc = finished.exception()
                if isinstance(exc, ClientGone):
                    raise exc
                if exc is not None:
                    deps.log(f"call: failed: {type(exc).__name__}: {exc}")
                    await _send_json(ws, {"type": "error", "message": str(exc)})
                    await _send_json(ws, {"type": "state", "state": "listening"})
                elif finished.result():
                    deps.log("call: ended by caller (dismissal)")
                    return

            if receiving in done:
                msg, receiving = receiving.result(), None
                if msg.get("type") == "websocket.disconnect":
                    deps.log("call: closed")
                    return
                if msg.get("bytes") is not None:
                    if turn is not None:
                        deps.log("call: utterance ignored, busy")
                    else:
                        turn = asyncio.create_task(_turn(msg["bytes"], deps, ws))
                elif msg.get("text") is not None:
                    try:
                        data = json.loads(msg["text"])
                    except ValueError:
                        continue
                    if isinstance(data, dict) and data.get("type") == "end":
                        await _cancel(turn)
                        turn = None
                        await _send_json(ws, {"type": "bye"})
                        deps.log("call: ended by caller (end button)")
                        return
    except ClientGone:
        deps.log("call: client gone")
    except Exception as exc:  # noqa: BLE001 -- a call must never crash the server
        deps.log(f"call: failed: {type(exc).__name__}: {exc}")
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": str(exc)})
    finally:
        await _cancel(turn)
        await _cancel(receiving)

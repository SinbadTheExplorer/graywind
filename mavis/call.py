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


# The only text a caller sees for an unexpected failure. AnswerError messages
# are deliberate copy and pass through; anything else stays in the server log.
GENERIC_ERROR = "Johnny's line dropped. Try again."


def _caller_message(exc: BaseException) -> str:
    return str(exc) if isinstance(exc, AnswerError) else GENERIC_ERROR


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
    # A call ends at max_seconds, or after idle_seconds with no utterance
    # (counted from the last utterance or the end of Johnny's last answer).
    max_seconds: float = 900.0
    idle_seconds: float = 120.0
    clock: Callable[[], float] = time.monotonic
    log: Callable[[str], None] = field(default=_stderr)
    # When Johnny placed the call (a "Johnny is calling" push), what he says
    # first, right after the greeting, as if the caller had asked it.
    opening: str | None = None


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
        await queue.put(("error", GENERIC_ERROR, None))
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
        if not isinstance(exc, AnswerError):
            deps.log(f"call: transcribe failed: {type(exc).__name__}: {exc}")
        await _send_json(ws, {"type": "error", "message": _caller_message(exc)})
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

    await _answer_turn(text, deps, ws, t0)
    return False


async def _answer_turn(text: str, deps: CallDeps, ws, t0: float) -> bool:
    """Answer `text` aloud: produce, deliver, back to listening."""
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


async def run_call(ws, deps: CallDeps) -> str:
    """Run one call on an accepted, authenticated WebSocket until it ends.

    Returns why it ended: "end", "dismissal", "closed", "gone", "time",
    "idle" or "failed" (for the audit log).
    """
    start = deps.clock()
    last_activity = start
    receiving = turn = None
    try:
        await _send_json(ws, {"type": "state", "state": "speaking"})
        greeting = deps.canned("greeting")
        if greeting:
            await _send_bytes(ws, greeting)
        await _send_json(ws, {"type": "state", "state": "listening"})
        deps.log(f"call: greeting sent in {int((deps.clock() - start) * 1000)} ms")
        if deps.opening:
            # He called: he speaks first. The loop below treats it as a turn,
            # so End and the time limits work while he talks.
            async def opening_turn():
                await _send_json(ws, {"type": "state", "state": "thinking"})
                return await _answer_turn(deps.opening, deps, ws, deps.clock())
            turn = asyncio.create_task(opening_turn())

        while True:
            now = deps.clock()
            if now - start >= deps.max_seconds:
                deps.log("call: ended, time limit")
                await _cancel(turn)
                turn = None
                await _send_json(ws, {"type": "bye", "reason": "time"})
                return "time"
            if turn is None and now - last_activity >= deps.idle_seconds:
                deps.log("call: ended, idle")
                await _send_json(ws, {"type": "bye", "reason": "idle"})
                return "idle"
            limit = deps.max_seconds - (now - start)
            if turn is None:
                limit = min(limit, deps.idle_seconds - (now - last_activity))

            if receiving is None:
                receiving = asyncio.create_task(ws.receive())
            waiting = {receiving} | ({turn} if turn else set())
            done, _ = await asyncio.wait(waiting, timeout=max(0.0, limit),
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done:
                continue    # a limit passed; the top of the loop ends the call

            if turn in done:
                finished, turn = turn, None
                last_activity = deps.clock()
                exc = finished.exception()
                if isinstance(exc, ClientGone):
                    raise exc
                if exc is not None:
                    deps.log(f"call: failed: {type(exc).__name__}: {exc}")
                    await _send_json(ws, {"type": "error", "message": _caller_message(exc)})
                    await _send_json(ws, {"type": "state", "state": "listening"})
                elif finished.result():
                    deps.log("call: ended by caller (dismissal)")
                    return "dismissal"

            if receiving in done:
                msg, receiving = receiving.result(), None
                if msg.get("type") == "websocket.disconnect":
                    deps.log("call: closed")
                    return "closed"
                if msg.get("bytes") is not None:
                    if turn is not None:
                        deps.log("call: utterance ignored, busy")
                    else:
                        last_activity = deps.clock()
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
                        return "end"
    except ClientGone:
        deps.log("call: client gone")
        return "gone"
    except Exception as exc:  # noqa: BLE001 -- a call must never crash the server
        deps.log(f"call: failed: {type(exc).__name__}: {exc}")
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": GENERIC_ERROR})
        return "failed"
    finally:
        await _cancel(turn)
        await _cancel(receiving)

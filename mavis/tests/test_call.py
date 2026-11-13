import asyncio
import json
import time

import pytest
import call


# ----------------------------------------------------------------------
# Fake websocket implementation
# ----------------------------------------------------------------------
class FakeWS:
    def __init__(self, *, raise_on_send=False):
        self._in = asyncio.Queue()
        self.sent = []  # ("json", obj) or ("bytes", b)
        self.raise_on_send = raise_on_send

    async def receive(self):
        return await self._in.get()

    async def send_json(self, obj):
        if self.raise_on_send:
            raise RuntimeError("send_json failure")
        self.sent.append(("json", obj))

    async def send_bytes(self, b):
        self.sent.append(("bytes", b))


# ----------------------------------------------------------------------
# Simple cutter implementation
# ----------------------------------------------------------------------
class SimpleCutter:
    def __init__(self):
        self.buf = ""

    def push(self, txt: str):
        self.buf += txt
        sentences = []
        while True:
            idx = self.buf.find(".")
            if idx == -1:
                break
            # include the dot
            sentence = self.buf[: idx + 1].strip()
            sentences.append(sentence)
            self.buf = self.buf[idx + 1 :]
        return sentences

    def flush(self):
        remainder = self.buf.strip()
        self.buf = ""
        return [remainder] if remainder else []


# ----------------------------------------------------------------------
# Helper to create dependency objects
# ----------------------------------------------------------------------
def make_deps(**over):
    # default canned
    canned_map = {"greeting": b"G", "filler": b"F", "dismissal": b"D"}

    async def default_transcribe(_wav: bytes) -> str:
        return ""

    async def default_answer(_text: str):
        if False:
            yield  # pragma: no cover

    def default_synth(sentence: str) -> bytes:
        return sentence.encode()

    def default_is_dismissal(_text: str) -> bool:
        return False

    def default_make_cutter():
        return SimpleCutter()

    deps = call.CallDeps(
        transcribe=over.get("transcribe", default_transcribe),
        answer=over.get("answer", default_answer),
        synth=over.get("synth", default_synth),
        canned=over.get(
            "canned", lambda moment: canned_map.get(moment, None)  # type: ignore[arg-type]
        ),
        is_dismissal=over.get("is_dismissal", default_is_dismissal),
        make_cutter=over.get("make_cutter", default_make_cutter),
        filler_after=over.get("filler_after", 2.0),
        max_seconds=over.get("max_seconds", 900.0),
        idle_seconds=over.get("idle_seconds", 120.0),
        clock=over.get("clock", time.monotonic),
        log=over.get("log", lambda *_: None),
    )
    return deps


# ----------------------------------------------------------------------
# Helper to read sent messages in order
# ----------------------------------------------------------------------
def messages(ws: FakeWS):
    return ws.sent


def said(text):
    async def transcribe(_wav):
        return text
    return transcribe


async def wait_for_sent(ws, item, timeout=1.0):
    end = time.monotonic() + timeout
    while item not in ws.sent:
        if time.monotonic() > end:
            raise AssertionError(f"never sent {item!r}; sent {ws.sent!r}")
        await asyncio.sleep(0.01)


TURN_DONE = ("json", {"type": "turn_done"})


async def one_turn(ws, deps, wav=b"audio"):
    """Run a call: one utterance, wait for the turn to finish, then hang up."""
    task = asyncio.create_task(call.run_call(ws, deps))
    ws._in.put_nowait({"type": "websocket.receive", "bytes": wav})
    await wait_for_sent(ws, TURN_DONE)
    ws._in.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(task, 2)
    return ws.sent


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------
GREETING = [
    ("json", {"type": "state", "state": "speaking"}),
    ("bytes", b"G"),
    ("json", {"type": "state", "state": "listening"}),
]


async def test_greeting_first():
    ws = FakeWS()
    ws._in.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(call.run_call(ws, make_deps()), timeout=2)

    assert messages(ws) == GREETING


async def test_normal_turn():
    async def answer(_text):
        yield "One."
        await asyncio.sleep(0)
        yield " Two."

    sent = await one_turn(FakeWS(), make_deps(transcribe=said("dummy"), answer=answer))

    assert sent == GREETING + [
        ("json", {"type": "state", "state": "thinking"}),
        ("json", {"type": "heard", "text": "dummy"}),
        ("json", {"type": "state", "state": "speaking"}),
        ("json", {"type": "caption", "text": "One."}),
        ("bytes", b"One."),
        ("json", {"type": "caption", "text": "Two."}),
        ("bytes", b"Two."),
        ("json", {"type": "turn_done"}),
        ("json", {"type": "state", "state": "listening"}),
    ]


async def test_empty_transcript_goes_back_to_listening():
    ws = FakeWS()
    task = asyncio.create_task(call.run_call(ws, make_deps(transcribe=said("   "))))
    ws._in.put_nowait({"type": "websocket.receive", "bytes": b"audio"})
    await wait_for_sent(ws, ("json", {"type": "state", "state": "thinking"}))
    await asyncio.sleep(0.05)
    ws._in.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(task, 2)

    assert messages(ws) == GREETING + [
        ("json", {"type": "state", "state": "thinking"}),
        ("json", {"type": "state", "state": "listening"}),
    ]


async def test_dismissal_ends_the_call_on_its_own():
    ws = FakeWS()
    ws._in.put_nowait({"type": "websocket.receive", "bytes": b"audio"})
    # No disconnect queued: the call must end by itself after "bye".
    deps = make_deps(transcribe=said("that's all"), is_dismissal=lambda _t: True)
    await asyncio.wait_for(call.run_call(ws, deps), timeout=2)

    assert messages(ws) == GREETING + [
        ("json", {"type": "state", "state": "thinking"}),
        ("json", {"type": "heard", "text": "that's all"}),
        ("json", {"type": "state", "state": "speaking"}),
        ("bytes", b"D"),
        ("json", {"type": "bye"}),
    ]


def _endless_answer(flag):
    async def answer(_):
        try:
            await asyncio.Event().wait()
            yield "never."
        finally:
            flag["ran"] = True
    return answer


async def test_end_button_mid_turn_cancels_the_answer():
    flag = {"ran": False}
    ws = FakeWS()
    deps = make_deps(transcribe=said("hello"), answer=_endless_answer(flag), filler_after=5)
    task = asyncio.create_task(call.run_call(ws, deps))
    ws._in.put_nowait({"type": "websocket.receive", "bytes": b"wav"})
    await wait_for_sent(ws, ("json", {"type": "heard", "text": "hello"}))
    ws._in.put_nowait({"type": "websocket.receive", "text": json.dumps({"type": "end"})})
    await asyncio.wait_for(task, 1)

    assert messages(ws)[-1] == ("json", {"type": "bye"})
    assert flag["ran"]


async def test_disconnect_mid_turn_cancels_the_answer():
    flag = {"ran": False}
    ws = FakeWS()
    deps = make_deps(transcribe=said("hello"), answer=_endless_answer(flag), filler_after=5)
    task = asyncio.create_task(call.run_call(ws, deps))
    ws._in.put_nowait({"type": "websocket.receive", "bytes": b"wav"})
    await wait_for_sent(ws, ("json", {"type": "heard", "text": "hello"}))
    ws._in.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(task, 1)

    assert flag["ran"]
    assert ("json", {"type": "bye"}) not in messages(ws)


async def test_slow_answer_gets_one_filler_first():
    async def answer(_):
        await asyncio.sleep(0.3)
        yield "One."

    sent = await one_turn(FakeWS(), make_deps(transcribe=said("hello"), answer=answer,
                                              filler_after=0.05))

    assert sent.count(("bytes", b"F")) == 1
    assert sent.index(("bytes", b"F")) < sent.index(("bytes", b"One."))


async def test_fast_answer_gets_no_filler():
    async def answer(_):
        yield "One."

    sent = await one_turn(FakeWS(), make_deps(transcribe=said("hello"), answer=answer))

    assert ("bytes", b"F") not in sent


async def test_answer_error_is_reported_and_call_continues():
    async def answer(_):
        raise call.AnswerError("boom")
        yield  # pragma: no cover

    sent = await one_turn(FakeWS(), make_deps(transcribe=said("hello"), answer=answer))

    assert ("json", {"type": "error", "message": "boom"}) in sent
    assert sent[-2:] == [("json", {"type": "turn_done"}),
                         ("json", {"type": "state", "state": "listening"})]


async def test_transcribe_failure_is_reported_and_call_continues():
    async def bad_transcribe(_):
        raise ValueError("bad transcription at /srv/secret/path")

    ws = FakeWS()
    task = asyncio.create_task(call.run_call(ws, make_deps(transcribe=bad_transcribe)))
    ws._in.put_nowait({"type": "websocket.receive", "bytes": b"wav"})
    # The internal detail stays in the log; the caller hears the generic line.
    await wait_for_sent(ws, ("json", {"type": "error", "message": call.GENERIC_ERROR}))
    await asyncio.sleep(0.02)
    ws._in.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(task, 2)

    assert messages(ws)[-1] == ("json", {"type": "state", "state": "listening"})


async def test_utterance_while_busy_is_ignored():
    count = 0

    async def count_transcribe(_):
        nonlocal count
        count += 1
        return "hello"

    async def slow_answer(_):
        yield "One."
        await asyncio.sleep(0.2)
        yield "Two."

    ws = FakeWS()
    deps = make_deps(transcribe=count_transcribe, answer=slow_answer, filler_after=5)
    task = asyncio.create_task(call.run_call(ws, deps))
    ws._in.put_nowait({"type": "websocket.receive", "bytes": b"first"})
    await wait_for_sent(ws, ("bytes", b"One."))
    ws._in.put_nowait({"type": "websocket.receive", "bytes": b"second"})
    await wait_for_sent(ws, TURN_DONE)
    ws._in.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(task, 2)

    assert count == 1
    assert ("bytes", b"Two.") in messages(ws)


async def test_one_failed_sentence_is_skipped_not_the_answer():
    async def answer(_):
        yield "One. "
        yield "Two. "
        yield "Three."

    def synth(sentence):
        if sentence == "Two.":
            raise RuntimeError("synth fail")
        return sentence.encode()

    sent = await one_turn(FakeWS(), make_deps(transcribe=said("hi"), answer=answer,
                                              synth=synth))
    audio = [b for kind, b in sent if kind == "bytes"]

    assert audio == [b"G", b"One.", b"Three."]


async def test_client_gone_does_not_raise():
    ws = FakeWS(raise_on_send=True)
    ws._in.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(call.run_call(ws, make_deps()), 2)


async def test_no_tasks_left_after_hang_up_mid_turn():
    flag = {"ran": False}
    before = set(asyncio.all_tasks())
    ws = FakeWS()
    deps = make_deps(transcribe=said("hello"), answer=_endless_answer(flag), filler_after=5)
    task = asyncio.create_task(call.run_call(ws, deps))
    ws._in.put_nowait({"type": "websocket.receive", "bytes": b"wav"})
    await wait_for_sent(ws, ("json", {"type": "heard", "text": "hello"}))
    ws._in.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(task, 1)
    await asyncio.sleep(0.02)

    leaked = {t for t in asyncio.all_tasks() if not t.done()} - before
    assert not leaked, f"leaked tasks: {leaked}"


async def test_internal_exception_text_never_reaches_the_caller():
    async def answer(_):
        raise RuntimeError("Traceback: /opt/mavis/providers.py key=gsk_123")
        yield  # pragma: no cover

    sent = await one_turn(FakeWS(), make_deps(transcribe=said("hello"), answer=answer))
    errors = [m for kind, m in sent if kind == "json" and m.get("type") == "error"]
    assert errors == [{"type": "error", "message": call.GENERIC_ERROR}]


async def test_answer_error_copy_passes_through_from_transcribe():
    async def capped(_):
        raise call.AnswerError("I'm tapped out for today, choom. Call me tomorrow.")

    ws = FakeWS()
    task = asyncio.create_task(call.run_call(ws, make_deps(transcribe=capped)))
    ws._in.put_nowait({"type": "websocket.receive", "bytes": b"wav"})
    await wait_for_sent(ws, ("json", {"type": "error",
                         "message": "I'm tapped out for today, choom. Call me tomorrow."}))
    ws._in.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(task, 2)


async def test_call_ends_after_idle_seconds():
    ws = FakeWS()
    reason = await asyncio.wait_for(
        call.run_call(ws, make_deps(idle_seconds=0.05)), timeout=2)
    assert reason == "idle"
    assert messages(ws)[-1] == ("json", {"type": "bye", "reason": "idle"})


async def test_utterances_keep_the_call_alive_past_idle():
    ws = FakeWS()
    task = asyncio.create_task(call.run_call(ws, make_deps(idle_seconds=0.15)))
    for _ in range(3):
        await asyncio.sleep(0.08)
        ws._in.put_nowait({"type": "websocket.receive", "bytes": b"wav"})
    assert not task.done()
    reason = await asyncio.wait_for(task, timeout=2)
    assert reason == "idle"


async def test_call_ends_at_max_seconds_even_mid_answer():
    flag = {"cancelled": False}
    ws = FakeWS()
    deps = make_deps(transcribe=said("hello"), answer=_endless_answer(flag),
                     max_seconds=0.2, idle_seconds=60)
    task = asyncio.create_task(call.run_call(ws, deps))
    ws._in.put_nowait({"type": "websocket.receive", "bytes": b"wav"})
    reason = await asyncio.wait_for(task, timeout=2)
    assert reason == "time"
    assert messages(ws)[-1] == ("json", {"type": "bye", "reason": "time"})


async def test_run_call_reports_why_it_ended():
    ws = FakeWS()
    ws._in.put_nowait({"type": "websocket.receive", "text": '{"type": "end"}'})
    assert await asyncio.wait_for(call.run_call(ws, make_deps()), 2) == "end"


# ----------------------------------------------------------------------
# Johnny placed the call: he speaks first
# ----------------------------------------------------------------------
async def test_owner_with_valid_event_hears_opening_first():
    asked, ordinary = [], []

    async def answer(text):
        ordinary.append(text)
        yield "Ordinary."

    async def answer_opening(text):
        asked.append(text)
        yield "AAPL closed."

    deps = make_deps(answer=answer)
    deps.opening, deps.answer_opening = "Why did you call?", answer_opening
    ws = FakeWS()
    task = asyncio.create_task(call.run_call(ws, deps))
    await wait_for_sent(ws, TURN_DONE)
    ws._in.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(task, 2)
    assert asked == ["Why did you call?"] and ordinary == []
    # The line isn't open until he has spoken: no "listening" before him.
    assert ws.sent[:3] == GREETING[:2] + [("json", {"type": "state", "state": "thinking"})]
    assert ("json", {"type": "caption", "text": "AAPL closed."}) in ws.sent
    assert ws.sent[-1] == ("json", {"type": "state", "state": "listening"})


async def test_no_opening_means_an_ordinary_call():
    ws = FakeWS()
    ws._in.put_nowait({"type": "websocket.disconnect"})
    await asyncio.wait_for(call.run_call(ws, make_deps()), timeout=2)
    assert messages(ws) == GREETING

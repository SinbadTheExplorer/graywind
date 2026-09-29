"""Runtime wiring around the caption.

The suite had no test that drove `Runtime` at all, so the caption's contract
-- `_answer` handing the exact answer text back for display -- shipped as the
kind of change this repo has been burned by before: correct in isolation, with
the call site free to drift.
"""
import asyncio
import os

import pytest

from avatar import app as app_mod


class StubTaskMgr:
    def add(self, *a, **k):
        pass


class StubBase:
    def __init__(self):
        self.taskMgr = StubTaskMgr()
        self.accepted = []

    def accept(self, key, fn):
        self.accepted.append(key)

    def userExit(self):
        pass


class CaptionScene:
    def __init__(self):
        self.captions = []

    def show_caption(self, text):
        self.captions.append(text)


def _runtime():
    return app_mod.Runtime(StubBase(), CaptionScene(), machine=object())


class FakeStream:
    def __init__(self, paths):
        self.paths = list(paths)
        self.cancelled = False
        self.workdir = "/nonexistent/mavis-test"

    def next(self, timeout=None):
        return self.paths.pop(0) if self.paths else None

    def cancel(self):
        self.cancelled = True


def test_answer_returns_the_first_chunk_the_stream_and_the_exact_text(monkeypatch):
    """The caption must be the answer itself, not a re-derivation of it."""
    runtime = _runtime()
    stream = FakeStream(["/tmp/fake/voice-0.wav", "/tmp/fake/voice-1.wav"])

    async def fake_ask(q):
        return "Gold bids when real yields fall, choom."

    monkeypatch.setattr(app_mod.brain, "ask", fake_ask)
    monkeypatch.setattr(runtime, "_voice", lambda text: stream)

    first, rest, text = asyncio.run(runtime._answer("what about gold"))

    assert first == "/tmp/fake/voice-0.wav"
    assert rest is stream and rest.paths == ["/tmp/fake/voice-1.wav"]
    assert text == "Gold bids when real yields fall, choom."


def test_answer_with_no_audio_is_a_failure_not_a_silent_answer(monkeypatch):
    runtime = _runtime()
    stream = FakeStream([])

    async def fake_ask(q):
        return "Something."

    monkeypatch.setattr(app_mod.brain, "ask", fake_ask)
    monkeypatch.setattr(runtime, "_voice", lambda text: stream)

    with pytest.raises(app_mod.brain.BrainError):
        asyncio.run(runtime._answer("anything"))
    assert stream.cancelled


def test_speak_plays_every_chunk_in_order(monkeypatch):
    runtime = _runtime()
    played = []
    monkeypatch.setattr(runtime, "say", played.append)
    runtime._speak("c0", FakeStream(["c1", "c2"]))
    assert played == ["c0", "c1", "c2"]


class FakeVoice:
    """Converts the first `good` chunks, then fails like a wedged worker."""

    def __init__(self, good):
        self.good = good
        self.calls = []
        self.last_gain = None
        self.last_error = None

    def convert(self, src, out, gain=None):
        self.calls.append(gain)
        if len(self.calls) > self.good:
            self.last_error = "voice worker did not answer within 120s"
            return False
        with open(out, "wb") as fh:
            fh.write(b"x")
        self.last_gain = gain or 5.0
        return True

    def cost_model(self):
        return 0.5, 0.3     # fast enough that the planner really chunks


class NoticeMachine:
    def __init__(self):
        self.degraded = []

    def note_degraded(self, reason):
        self.degraded.append(reason)


def _voiced(monkeypatch, voice, text):
    machine = NoticeMachine()
    runtime = app_mod.Runtime(StubBase(), CaptionScene(), machine=machine, voice=voice)
    monkeypatch.setattr(runtime, "on_render", lambda fn: fn())
    monkeypatch.setattr(app_mod.voice_client, "say_to_wav",
                        lambda t, path: open(path, "wb").write(b"s"))
    stream = runtime._voice(text)
    paths = []
    while (p := stream.next(timeout=5)) is not None:
        paths.append(os.path.basename(p))
    app_mod._discard(stream)
    return paths, machine


TEXT = ("Look, choom. " + "The Fed moves first and everyone else follows behind. " * 6)


def test_voice_chunks_share_one_gain(monkeypatch):
    voice = FakeVoice(good=99)
    paths, machine = _voiced(monkeypatch, voice, TEXT)
    assert len(paths) > 1 and all(p.startswith("voice-") for p in paths)
    assert voice.calls[0] is None and set(voice.calls[1:]) == {5.0}
    assert machine.degraded == []


def test_a_failing_voice_falls_back_to_the_scaffold_and_says_so(monkeypatch):
    voice = FakeVoice(good=1)
    paths, machine = _voiced(monkeypatch, voice, TEXT)
    assert paths[0].startswith("voice-")
    assert paths[1:] and all(p.startswith("scaffold-") for p in paths[1:])
    assert machine.degraded == ["voice worker did not answer within 120s"]


def test_answer_still_rejects_an_empty_answer(monkeypatch):
    runtime = _runtime()

    async def fake_ask(q):
        return ""

    monkeypatch.setattr(app_mod.brain, "ask", fake_ask)

    with pytest.raises(app_mod.brain.BrainError):
        asyncio.run(runtime._answer("anything"))


def test_on_render_gives_up_once_shutting_down():
    """Why the caption-clear in `finally` is wrapped: after Escape the render
    loop is gone, on_render raises, and cleanup behind it must still run."""
    runtime = _runtime()
    runtime._stopping.set()

    with pytest.raises(RuntimeError, match="shutting down"):
        runtime.on_render(lambda: None)


class FaceScene:
    def __init__(self):
        self.mouth, self.brows = [], []

    def idle(self, t):
        pass

    def set_mouth(self, v):
        self.mouth.append(v)

    def set_brows(self, v):
        self.brows.append(v)


class _Task:
    time = 0.0
    cont = "cont"


def test_tick_drives_the_brows_with_the_mouth_and_rests_them_after():
    """The brows ride the same playback clock as the mouth. Left raised after
    the answer, he would sit there looking surprised until the next one."""
    import numpy as np
    import time

    scene = FaceScene()
    runtime = app_mod.Runtime(StubBase(), scene, machine=object())
    runtime._mouth = (np.full(600, 0.4, dtype=np.float32),
                      np.full(600, 0.7, dtype=np.float32), time.monotonic())
    runtime._tick(_Task())
    assert scene.mouth[-1] == pytest.approx(0.4)
    assert scene.brows[-1] == pytest.approx(0.7)

    runtime._mouth = None
    runtime._tick(_Task())
    assert scene.mouth[-1] == 0.0
    assert scene.brows[-1] == 0.0

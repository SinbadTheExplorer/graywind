"""Runtime wiring around the caption.

The suite had no test that drove `Runtime` at all, so the caption's contract
-- `_answer` handing the exact answer text back for display -- shipped as the
kind of change this repo has been burned by before: correct in isolation, with
the call site free to drift.
"""
import asyncio

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


def test_answer_returns_the_wav_and_the_exact_text(monkeypatch):
    """The caption must be the answer itself, not a re-derivation of it."""
    runtime = _runtime()

    async def fake_ask(q):
        return "Gold bids when real yields fall, choom."

    monkeypatch.setattr(app_mod.brain, "ask", fake_ask)
    monkeypatch.setattr(runtime, "_voice", lambda text: "/tmp/fake/johnny.wav")

    wav, text = asyncio.run(runtime._answer("what about gold"))

    assert wav == "/tmp/fake/johnny.wav"
    assert text == "Gold bids when real yields fall, choom."


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

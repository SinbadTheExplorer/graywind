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


class PortalScene(CaptionScene):
    def __init__(self):
        super().__init__()
        from avatar import portal
        self.portal = portal.Screen()
        self.views = []
        self.notices = []

    def idle(self, t):
        pass

    def look_from(self, eye):
        self.views.append(eye)

    def show_notice(self, text):
        self.notices.append(text)

    def show_hud(self, text):
        pass


class StubTracker:
    def __init__(self, reading=(None, None), error=None):
        self.reading = reading
        self.error = error

    def latest(self):
        return self.reading


def test_portal_runtime_feeds_the_tracked_eye_to_the_lens():
    scene = PortalScene()
    tracker = StubTracker(((0.1, -0.5, 0.02), 1.0))
    rt = app_mod.Runtime(StubBase(), scene, machine=object(), tracker=tracker)
    assert "t" in rt.base.accepted
    rt._follow_eye()
    assert scene.views[-1] == (0.1, -0.5, 0.02)


def test_portal_runtime_says_why_tracking_is_off_once():
    scene = PortalScene()
    rt = app_mod.Runtime(StubBase(), scene, machine=object(),
                         tracker=StubTracker(error="head tracking off: no camera"))
    rt._follow_eye()
    rt._follow_eye()
    assert scene.notices == ["head tracking off: no camera"]
    assert scene.views[-1] == scene.portal.nominal_eye


def test_pausing_tracking_recentres_and_says_so():
    scene = PortalScene()
    tracker = StubTracker(((0.1, -0.5, 0.02), 1.0))
    rt = app_mod.Runtime(StubBase(), scene, machine=object(), tracker=tracker)
    rt._follow_eye()
    rt._toggle_tracking()
    assert scene.notices[-1] == "head tracking paused (T)"
    rt._toggle_tracking()
    assert scene.notices[-1] == ""


def test_overlay_runtime_has_no_tracking_key():
    rt = _runtime()
    assert "t" not in rt.base.accepted


def test_portal_requested_reads_the_env():
    assert app_mod.portal_requested({"MAVIS_PORTAL": "1"})
    assert not app_mod.portal_requested({"MAVIS_PORTAL": "0"})
    assert not app_mod.portal_requested({})


def test_hud_reports_what_the_tracker_sees():
    scene = PortalScene()
    scene.huds = []
    scene.show_hud = scene.huds.append      # instance attr shadows the stub
    tracker = StubTracker(((0.1, -0.5, 0.02), 1.0))
    tracker.fps = 29.6
    rt = app_mod.Runtime(StubBase(), scene, machine=object(), tracker=tracker)
    rt._follow_eye()
    assert scene.huds[-1].startswith("JOHNNY // LOCKED")
    assert "eye 0.50m" in scene.huds[-1] and "cam 30fps" in scene.huds[-1]
    assert "SEARCHING" in rt.hud_text(None, (0, -0.6, 0))
    rt._tracking = False
    assert "PAUSED" in rt.hud_text(None, (0, -0.6, 0))

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


class SettleScene:
    def __init__(self):
        self.notices = []

    def show_notice(self, text):
        self.notices.append(text)


def test_a_first_chunk_fault_survives_the_settle_that_follows_it(monkeypatch):
    """The settle runs right after chunk 0 is ready; it used to wipe the notice
    a failed chunk 0 had just raised, so he spoke in the wrong voice silently."""
    voice = FakeVoice(good=0)
    voice.degraded = False          # one failed call does not condemn the worker
    machine = NoticeMachine()
    scene = SettleScene()
    runtime = app_mod.Runtime(StubBase(), scene, machine=machine, voice=voice)
    monkeypatch.setattr(runtime, "on_render", lambda fn: fn())
    monkeypatch.setattr(app_mod.voice_client, "say_to_wav",
                        lambda t, path: open(path, "wb").write(b"s"))
    stream = runtime._voice("Short answer, choom.")
    assert stream.next(timeout=5).endswith("scaffold-0.wav")
    runtime._settle_notice()
    assert machine.degraded[-1] == "voice worker did not answer within 120s"
    assert "" not in scene.notices
    app_mod._discard(stream)


def test_without_a_fault_the_settle_clears_the_notice():
    scene = SettleScene()
    runtime = app_mod.Runtime(StubBase(), scene, machine=NoticeMachine(),
                              voice=FakeVoice(good=9))
    runtime.voice.degraded = False
    runtime._settle_notice()
    assert scene.notices == [""]


def _tone_wav(path, seconds):
    from scipy.io import wavfile
    import numpy as np
    wavfile.write(path, 22050, np.full(int(seconds * 22050), 0.1, dtype=np.float32))


def test_measure_plans_on_spoken_durations_and_reuses_the_first_piece(monkeypatch, tmp_path):
    """Two sentences of equal length, one spoken 4x slower (think "~1.9%"):
    the planner must see that, and chunk 0's scaffold must not be spoken twice."""
    spoken = []

    def fake_say(text, path):
        spoken.append(text)
        _tone_wav(path, 8.0 if "Slow" in text else 2.0)
    monkeypatch.setattr(app_mod.voice_client, "speaker_ready", lambda: True)
    monkeypatch.setattr(app_mod.voice_client, "say_to_wav", fake_say)
    seconds, scaffold = app_mod._measure("Fast one here. Slow one here.", str(tmp_path))
    assert seconds("Fast one here.") == 2.0
    assert seconds("Slow one here.") == 8.0
    assert spoken == ["Fast one here.", "Slow one here."]
    scaffold("Fast one here.", str(tmp_path / "scaffold-0.wav"))
    scaffold("Fast one here. Slow one here.", str(tmp_path / "scaffold-1.wav"))
    assert spoken[2:] == ["Fast one here. Slow one here."]     # only the merged one
    assert (tmp_path / "scaffold-0.wav").stat().st_size > 1000


def test_measure_uses_the_estimate_when_the_speaker_is_down(monkeypatch, tmp_path):
    monkeypatch.setattr(app_mod.voice_client, "speaker_ready", lambda: False)
    seconds, scaffold = app_mod._measure("Anything at all.", str(tmp_path))
    assert seconds is app_mod.chunks.spoken_seconds
    assert scaffold is app_mod.voice_client.say_to_wav


def test_measure_falls_back_when_measuring_fails(monkeypatch, tmp_path):
    def broken(text, path):
        raise OSError("helper died and say too")
    monkeypatch.setattr(app_mod.voice_client, "speaker_ready", lambda: True)
    monkeypatch.setattr(app_mod.voice_client, "say_to_wav", broken)
    seconds, _ = app_mod._measure("Anything at all.", str(tmp_path))
    assert seconds is app_mod.chunks.spoken_seconds


def test_voice_plans_with_the_measured_durations(monkeypatch):
    seen = {}
    real_plan = app_mod.chunks.plan

    def spy(text, **kwargs):
        seen["seconds"] = kwargs.get("seconds")
        return real_plan(text, **kwargs)
    monkeypatch.setattr(app_mod.chunks, "plan", spy)
    monkeypatch.setattr(app_mod.voice_client, "speaker_ready", lambda: True)
    monkeypatch.setattr(app_mod.voice_client, "say_to_wav",
                        lambda t, path: _tone_wav(path, 3.0))
    runtime = app_mod.Runtime(StubBase(), CaptionScene(), machine=NoticeMachine(),
                              voice=FakeVoice(good=99))
    monkeypatch.setattr(runtime, "on_render", lambda fn: fn())
    stream = runtime._voice("One sentence here. Another one here.")
    while stream.next(timeout=5) is not None:
        pass
    app_mod._discard(stream)
    assert seen["seconds"]("One sentence here.") == 3.0


def test_measure_stops_at_once_when_the_speaker_dies_mid_answer(monkeypatch, tmp_path):
    """The rest must not be measured at `say` speed (~1.2s a piece)."""
    ready = iter([True, True, False])
    spoken = []
    monkeypatch.setattr(app_mod.voice_client, "speaker_ready", lambda: next(ready, False))
    monkeypatch.setattr(app_mod.voice_client, "say_to_wav",
                        lambda t, path: (spoken.append(t), _tone_wav(path, 1.0)))
    seconds, _ = app_mod._measure("One. Two. Three. Four.", str(tmp_path))
    assert seconds is app_mod.chunks.spoken_seconds
    assert spoken == ["One."]

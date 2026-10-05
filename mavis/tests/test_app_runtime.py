"""Runtime wiring: the answer stream, the caption and the notices.

The caption's contract is that it shows the answer's own text, sentence by
sentence as he says it, never a transcription of his audio.
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


class NoticeMachine:
    def __init__(self):
        self.degraded = []

    def note_degraded(self, reason):
        self.degraded.append(reason)


class FakeSpeaker:
    """Speaks the first `good` sentences in voice, then falls back like a
    voice that has stopped answering."""

    name = "fake"

    def __init__(self, good=99):
        self.good = good
        self.said = []
        self.degraded = False
        self.last_error = None

    def synth(self, text, path):
        self.said.append(text)
        with open(path, "wb") as fh:
            fh.write(b"x")
        if len(self.said) > self.good:
            self.last_error = "kokoro failed: out of memory"
            return False
        return True


def _runtime(speaker=None, scene=None, machine=None):
    runtime = app_mod.Runtime(StubBase(), scene or CaptionScene(),
                              machine=machine or NoticeMachine(),
                              speaker=speaker or FakeSpeaker())
    runtime.on_render = lambda fn: fn()
    return runtime


def _answering(monkeypatch, sentences, fail=None):
    async def fake_sentences(question):
        for sentence in sentences:
            yield sentence
        if fail:
            raise fail
    monkeypatch.setattr(app_mod.brain, "sentences", fake_sentences)


async def _whole_answer(runtime, question="anything"):
    first, stream, feeder = await runtime._answer(question)
    items = [first]
    try:
        while (item := await asyncio.to_thread(stream.next, 5)) is not None:
            items.append(item)
    finally:
        await feeder
        app_mod._discard(stream)
    return items


def test_answer_hands_back_the_first_sentence_voiced_and_then_the_rest(monkeypatch):
    runtime = _runtime()
    _answering(monkeypatch, ["Gold bids when real yields fall.", "That is the trade, choom."])

    items = asyncio.run(_whole_answer(runtime))

    assert [text for _, text in items] == [
        "Gold bids when real yields fall.", "That is the trade, choom."]
    assert os.path.basename(items[0][0]) == "speech-0.wav"


def test_an_answer_with_no_sentences_is_a_failure_not_a_silent_answer(monkeypatch):
    runtime = _runtime()
    _answering(monkeypatch, [])

    with pytest.raises(app_mod.brain.BrainError, match="empty answer"):
        asyncio.run(runtime._answer("anything"))


def test_a_backend_failure_before_the_first_sentence_is_the_answers_failure(monkeypatch):
    runtime = _runtime()
    _answering(monkeypatch, [], fail=app_mod.brain.BrainError("MAVIS backend returned 401"))

    with pytest.raises(app_mod.brain.BrainError, match="401"):
        asyncio.run(runtime._answer("anything"))


def test_a_backend_failure_mid_answer_arrives_after_what_was_already_written(monkeypatch):
    runtime = _runtime()
    _answering(monkeypatch, ["One."], fail=app_mod.brain.BrainError("Groq error 503"))

    async def run():
        first, stream, feeder = await runtime._answer("anything")
        try:
            with pytest.raises(app_mod.brain.BrainError, match="503"):
                await asyncio.to_thread(stream.next, 5)
        finally:
            await feeder
            app_mod._discard(stream)
        return first

    assert asyncio.run(run())[1] == "One."


def test_an_unexpected_feeder_error_becomes_a_brain_error(monkeypatch):
    """Anything else would escape `_conversation`'s handler and put him to
    sleep mid-session instead of showing the failure and listening again."""
    runtime = _runtime()
    _answering(monkeypatch, [], fail=ValueError("boom"))

    with pytest.raises(app_mod.brain.BrainError, match="ValueError: boom"):
        asyncio.run(runtime._answer("anything"))


class FakeStream:
    def __init__(self, items):
        self.items = list(items)

    def next(self, timeout=None):
        return self.items.pop(0) if self.items else None


def test_speak_plays_every_sentence_in_order_and_captions_each_as_it_plays(monkeypatch):
    scene = CaptionScene()
    runtime = _runtime(scene=scene)
    events = []
    monkeypatch.setattr(scene, "show_caption", lambda text: events.append(("caption", text)))
    monkeypatch.setattr(runtime, "say", lambda path: events.append(("say", path)))

    runtime._speak(("c0.wav", "One."), FakeStream([("c1.wav", "Two.")]))

    assert events == [("caption", "One."), ("say", "c0.wav"),
                      ("caption", "Two."), ("say", "c1.wav")]


def test_a_sentence_that_falls_back_to_plain_speech_says_so_once(monkeypatch):
    machine = NoticeMachine()
    runtime = _runtime(speaker=FakeSpeaker(good=1), machine=machine)
    _answering(monkeypatch, ["One.", "Two.", "Three."])

    items = asyncio.run(_whole_answer(runtime))

    assert len(items) == 3                      # nothing went silent
    assert machine.degraded == ["kokoro failed: out of memory"]


def test_on_render_gives_up_once_shutting_down():
    """Why the caption-clear in `finally` is wrapped: after Escape the render
    loop is gone, on_render raises, and cleanup behind it must still run."""
    runtime = app_mod.Runtime(StubBase(), CaptionScene(), machine=object())
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


def test_a_first_sentence_fault_survives_the_settle_that_follows_it(monkeypatch):
    """The settle runs right after the first sentence is ready; it must not
    wipe the notice that sentence just raised, or he speaks in the wrong
    voice with nothing on screen to say why."""
    speaker = FakeSpeaker(good=0)
    machine, scene = NoticeMachine(), SettleScene()
    runtime = _runtime(speaker=speaker, scene=scene, machine=machine)
    _answering(monkeypatch, ["Short answer, choom."])

    async def run():
        first, stream, feeder = await runtime._answer("anything")
        runtime._settle_notice()
        await feeder
        app_mod._discard(stream)

    asyncio.run(run())
    assert machine.degraded[-1] == "kokoro failed: out of memory"
    assert "" not in scene.notices


def test_without_a_fault_the_settle_clears_the_notice():
    scene = SettleScene()
    runtime = _runtime(scene=scene)
    runtime._settle_notice()
    assert scene.notices == [""]


def test_a_voice_that_never_started_keeps_its_notice_up():
    speaker = FakeSpeaker()
    speaker.degraded, speaker.last_error = True, "voice model missing"
    machine, scene = NoticeMachine(), SettleScene()
    runtime = _runtime(speaker=speaker, scene=scene, machine=machine)
    runtime._settle_notice()
    assert machine.degraded == ["voice model missing"] and scene.notices == []


# -- one whole conversation ----------------------------------------------------

class ScriptedMachine(NoticeMachine):
    """Greets, answers one question with a filler on offer, then is dismissed."""

    def __init__(self):
        super().__init__()
        self.events = []

    def on_wake(self):
        return ("Awake.", "greeting.wav")

    def on_transcript(self, text):
        if text == "that's all":
            return ("dismiss", ("Later.", "bye.wav"))
        return ("ask", ("Hang on.", "filler.wav"))

    def on_answer_ready(self):
        self.events.append("answer_ready")

    def on_spoken(self):
        self.events.append("spoken")

    def on_failure(self, reason):
        self.events.append(f"failure: {reason}")

    def sleep(self):
        self.events.append("sleep")


class ConversationScene(CaptionScene, SettleScene):
    def __init__(self):
        CaptionScene.__init__(self)
        SettleScene.__init__(self)


def _converse(monkeypatch, sentences, delay=0.0, fail=None):
    import numpy as np
    machine, scene = ScriptedMachine(), ConversationScene()
    runtime = _runtime(scene=scene, machine=machine)
    played = []
    monkeypatch.setattr(runtime, "say", lambda path: played.append(os.path.basename(path)))
    heard = iter(["what about gold", "that's all"])
    monkeypatch.setattr(app_mod.capture, "record_utterance",
                        lambda: np.full(app_mod.capture.BLOCK, 0.5, dtype=np.float32))

    async def fake_transcribe(samples, rate):
        return next(heard)

    async def fake_sentences(question):
        await asyncio.sleep(delay)
        for sentence in sentences:
            yield sentence
        if fail:
            raise fail

    monkeypatch.setattr(app_mod.stt, "transcribe", fake_transcribe)
    monkeypatch.setattr(app_mod.brain, "sentences", fake_sentences)
    asyncio.run(runtime._conversation())
    return played, machine, scene


def test_a_fast_answer_is_not_held_up_by_the_filler_line(monkeypatch):
    played, machine, scene = _converse(monkeypatch, ["Gold bids.", "That is the trade."])
    assert played == ["greeting.wav", "speech-0.wav", "speech-1.wav", "bye.wav"]
    assert machine.events == ["answer_ready", "spoken", "sleep"]
    assert scene.captions == ["Gold bids.", "That is the trade.", ""]


def test_a_slow_answer_is_covered_by_the_filler_line(monkeypatch):
    monkeypatch.setattr(app_mod, "FILLER_AFTER_SECONDS", 0.05)
    played, machine, _ = _converse(monkeypatch, ["Gold bids."], delay=0.3)
    assert played == ["greeting.wav", "filler.wav", "speech-0.wav", "bye.wav"]
    assert machine.events == ["answer_ready", "spoken", "sleep"]


def test_a_failed_answer_is_shown_and_he_keeps_listening(monkeypatch):
    played, machine, _ = _converse(
        monkeypatch, [], fail=app_mod.brain.BrainError("MAVIS backend unreachable"))
    assert played == ["greeting.wav", "bye.wav"]
    assert machine.events == ["failure: MAVIS backend unreachable", "sleep"]


def test_an_answer_that_breaks_off_plays_what_it_had_then_reports(monkeypatch):
    played, machine, scene = _converse(
        monkeypatch, ["Gold bids."], fail=app_mod.brain.BrainError("Groq error 503"))
    assert played == ["greeting.wav", "speech-0.wav", "bye.wav"]
    assert machine.events == ["answer_ready", "failure: Groq error 503", "sleep"]
    assert scene.captions[-1] == ""             # the caption is cleared either way

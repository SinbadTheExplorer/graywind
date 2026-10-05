"""The voices behind his answers, and the fallback that keeps him audible."""
import httpx
import numpy as np
import pytest
from scipy.io import wavfile

from avatar import tts


class GoodVoice:
    name = "good"

    def __init__(self):
        self.started = False

    def start(self):
        self.started = True

    def synth(self, text, path):
        open(path, "w").write(f"good:{text}")


class DeadVoice:
    name = "dead"

    def start(self):
        raise tts.TTSError("model missing")

    def synth(self, text, path):
        raise AssertionError("a voice that never started must not be asked")


class FlakyVoice(GoodVoice):
    name = "flaky"

    def __init__(self, fail_on):
        super().__init__()
        self.fail_on = fail_on

    def synth(self, text, path):
        if text in self.fail_on:
            raise tts.TTSError("dropped the request")
        super().synth(text, path)


class Fallback:
    name = "say"

    def synth(self, text, path):
        open(path, "w").write(f"say:{text}")


def test_a_healthy_voice_speaks_and_nothing_is_degraded(tmp_path):
    speaker = tts.Speaker(GoodVoice(), Fallback())
    speaker.start()
    assert speaker.synth("Hello.", str(tmp_path / "a.wav")) is True
    assert (tmp_path / "a.wav").read_text() == "good:Hello."
    assert speaker.ready and not speaker.degraded and speaker.last_error is None


def test_a_voice_that_cannot_start_degrades_to_say_and_says_why(tmp_path):
    speaker = tts.Speaker(DeadVoice(), Fallback())
    speaker.start()
    assert speaker.degraded and speaker.last_error == "model missing"
    assert speaker.synth("Hello.", str(tmp_path / "a.wav")) is False
    assert (tmp_path / "a.wav").read_text() == "say:Hello."


def test_one_failed_sentence_falls_back_but_the_next_tries_the_voice_again(tmp_path):
    speaker = tts.Speaker(FlakyVoice(fail_on={"Two."}), Fallback())
    speaker.start()
    results = [speaker.synth(text, str(tmp_path / f"{i}.wav"))
               for i, text in enumerate(("One.", "Two.", "Three."))]
    assert results == [True, False, True]
    assert (tmp_path / "1.wav").read_text() == "say:Two."
    assert not speaker.degraded                  # cleared by the sentence that worked
    assert speaker.last_error == "dropped the request"


def test_blend_weights_are_normalised():
    assert tts.parse_blend("am_onyx") == [("am_onyx", 1.0)]
    assert tts.parse_blend("a:3, b:1") == [("a", 0.75), ("b", 0.25)]


@pytest.mark.parametrize("spec", ["", "a:zero", "a:0"])
def test_a_bad_blend_is_an_error_not_a_crash(spec):
    with pytest.raises(tts.TTSError):
        tts.parse_blend(spec)


def test_an_unknown_voice_name_degrades_to_say_instead_of_stopping_startup(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVIS_TTS", "nonsense")
    speaker = tts.Speaker(fallback=Fallback())
    speaker.start()
    assert speaker.degraded and "kokoro" in speaker.last_error
    assert speaker.synth("Hello.", str(tmp_path / "a.wav")) is False


def test_the_offline_generator_refuses_an_unknown_voice_name():
    with pytest.raises(tts.TTSError, match="kokoro"):
        tts.make_voice("nonsense", strict=True)


@pytest.mark.parametrize("raw", ["", "fast", "-1", "0"])
def test_a_bad_tuning_value_falls_back_instead_of_failing_import(monkeypatch, raw):
    monkeypatch.setenv("MAVIS_KOKORO_SPEED", raw)
    assert tts._number_from_env("MAVIS_KOKORO_SPEED", 1.0) == 1.0


def test_kokoro_without_its_model_fails_to_start_cleanly(tmp_path):
    voice = tts.KokoroVoice(model_dir=tmp_path)
    with pytest.raises(tts.TTSError, match="voice model missing"):
        voice.start()
    with pytest.raises(tts.TTSError):
        voice.synth("Hello.", str(tmp_path / "a.wav"))


def _elevenlabs(handler):
    voice = tts.ElevenLabsVoice(api_key="k", voice_id="v123",
                                client=httpx.Client(transport=httpx.MockTransport(handler)))
    voice.start()
    return voice


def test_elevenlabs_writes_the_pcm_it_gets_as_a_wav(tmp_path):
    pcm = (np.arange(2400) % 100).astype("<i2")

    def handler(request):
        assert request.url.path.endswith("/v123")
        assert request.headers["xi-api-key"] == "k"
        assert request.url.params["output_format"] == "pcm_24000"
        return httpx.Response(200, content=pcm.tobytes())

    path = str(tmp_path / "a.wav")
    _elevenlabs(handler).synth("Hello.", path)
    rate, data = wavfile.read(path)
    assert rate == 24000 and np.array_equal(data, pcm)


@pytest.mark.parametrize("response", [httpx.Response(401), httpx.Response(200, content=b"")])
def test_elevenlabs_failures_are_tts_errors(tmp_path, response):
    with pytest.raises(tts.TTSError):
        _elevenlabs(lambda request: response).synth("Hello.", str(tmp_path / "a.wav"))


def test_elevenlabs_without_credentials_does_not_start(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    with pytest.raises(tts.TTSError, match="ELEVENLABS"):
        tts.ElevenLabsVoice().start()

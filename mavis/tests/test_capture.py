"""When he decides the owner has stopped talking."""
import numpy as np
import pytest

from avatar import capture

BLOCK_SECONDS = capture.BLOCK / capture.SAMPLE_RATE


class Scripted:
    """A detector that answers from a script, one entry per block."""

    silence_seconds = 0.4

    def __init__(self, script):
        self.script = list(script)
        self.resets = 0

    def reset(self):
        self.resets += 1

    def is_speech(self, block):
        return self.script.pop(0) if self.script else False


def _blocks(n):
    return (np.full(capture.BLOCK, i, dtype=np.float32) for i in range(n))


def test_recording_stops_after_the_detectors_silence_following_speech():
    detect = Scripted([False, False, True, True, True])     # then silence
    out = capture.record_utterance(detect=detect, blocks=_blocks(200))
    needed = int(0.4 / BLOCK_SECONDS)
    assert len(out) == (5 + needed) * capture.BLOCK
    assert detect.resets == 1


def test_a_pause_shorter_than_the_wait_does_not_end_the_question():
    needed = int(0.4 / BLOCK_SECONDS)
    script = [True] + [False] * (needed - 1) + [True]
    out = capture.record_utterance(detect=Scripted(script), blocks=_blocks(200))
    assert len(out) == (len(script) + needed) * capture.BLOCK


def test_silence_alone_runs_to_the_time_limit():
    out = capture.record_utterance(seconds_max=1.0, detect=Scripted([]), blocks=_blocks(200))
    assert len(out) == int(1.0 / BLOCK_SECONDS) * capture.BLOCK


def test_the_wait_can_be_tuned_from_the_environment(monkeypatch):
    monkeypatch.setenv("MAVIS_ENDPOINT_SECONDS", "0.8")
    out = capture.record_utterance(detect=Scripted([True]), blocks=_blocks(200))
    assert len(out) == (1 + int(0.8 / BLOCK_SECONDS)) * capture.BLOCK


@pytest.mark.parametrize("raw", ["", "abc", "-1", "0"])
def test_a_bad_override_keeps_the_default(monkeypatch, raw):
    monkeypatch.setenv("MAVIS_ENDPOINT_SECONDS", raw)
    assert capture._silence_override(0.7) == 0.7


def test_loudness_detector_matches_the_old_threshold():
    detect = capture.RmsDetector()
    assert detect.silence_seconds == 1.2
    assert not detect.is_speech(np.full(capture.BLOCK, 0.005, dtype=np.float32))
    assert detect.is_speech(np.full(capture.BLOCK, 0.05, dtype=np.float32))


def test_without_the_model_the_session_falls_back_to_loudness(monkeypatch, tmp_path):
    monkeypatch.setattr(capture, "_detector", None)
    monkeypatch.setattr(capture, "VAD_MODEL", tmp_path / "missing.onnx")
    monkeypatch.setattr(capture.VadDetector.__init__, "__defaults__",
                        (tmp_path / "missing.onnx", capture.VAD_THRESHOLD))
    assert isinstance(capture.detector(), capture.RmsDetector)


@pytest.mark.skipif(not capture.VAD_MODEL.exists(), reason="VAD model not installed")
def test_the_vad_hears_nothing_in_silence_or_hiss_and_carries_partial_frames():
    detect = capture.VadDetector()
    for _ in range(20):
        assert not detect.is_speech(np.zeros(capture.BLOCK, dtype=np.float32))
    assert len(detect._carry) == (20 * capture.BLOCK) % capture.VAD_FRAME
    detect.reset()
    assert len(detect._carry) == 0
    rng = np.random.default_rng(0)
    for _ in range(20):
        assert not detect.is_speech(rng.normal(0, 0.003, capture.BLOCK).astype(np.float32))


@pytest.mark.skipif(not capture.VAD_MODEL.exists(), reason="VAD model not installed")
def test_the_vad_hears_speech_and_then_its_end(tmp_path):
    """A real spoken question, through the real model: recording must stop
    about VAD_SILENCE_SECONDS after the last word, not run to the limit."""
    import subprocess
    from scipy.io import wavfile
    path = str(tmp_path / "q.wav")
    try:
        subprocess.run(["say", "-o", path, "--data-format=LEI16@16000",
                        "What happens to gold when real yields fall?"], check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("macOS `say` not available")
    _rate, data = wavfile.read(path)
    speech = data.astype(np.float32) / 32768.0
    loud = np.nonzero(np.abs(speech) > 0.02)[0]
    speech = speech[: loud[-1] + 1]
    padded = np.concatenate([speech, np.zeros(4 * capture.SAMPLE_RATE, dtype=np.float32)])
    blocks = (padded[i:i + capture.BLOCK]
              for i in range(0, len(padded) - capture.BLOCK + 1, capture.BLOCK))
    out = capture.record_utterance(detect=capture.VadDetector(), blocks=blocks)
    waited = (len(out) - len(speech)) / capture.SAMPLE_RATE
    assert capture.VAD_SILENCE_SECONDS - 0.1 <= waited <= capture.VAD_SILENCE_SECONDS + 0.3

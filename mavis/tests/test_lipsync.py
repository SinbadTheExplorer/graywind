import numpy as np
import pytest

from avatar import lipsync


def _tone(seconds, sample_rate=22050, amplitude=1.0):
    t = np.linspace(0, seconds, int(seconds * sample_rate), endpoint=False)
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_envelope_has_one_value_per_frame():
    env = lipsync.envelope(_tone(1.0), 22050, fps=60)
    assert len(env) == 60


def test_envelope_is_normalised_to_unit_range():
    env = lipsync.envelope(_tone(1.0), 22050)
    assert env.max() == pytest.approx(1.0, abs=1e-6)
    assert env.min() >= 0.0


def test_silence_produces_a_closed_mouth():
    env = lipsync.envelope(np.zeros(22050, dtype=np.float32), 22050)
    assert env.max() == 0.0


def test_loud_section_scores_above_quiet_section():
    quiet = _tone(0.5, amplitude=0.1)
    loud = _tone(0.5, amplitude=1.0)
    env = lipsync.envelope(np.concatenate([quiet, loud]), 22050, fps=10)
    assert env[:5].mean() < env[5:].mean()


def test_envelope_handles_audio_shorter_than_one_frame():
    env = lipsync.envelope(_tone(0.001), 22050, fps=60)
    assert len(env) >= 1


def test_long_clip_does_not_drift_into_the_padding():
    """A frame at 22050Hz/60fps is 367.5 samples. Any fixed integer stride
    drifts against that -- floor(367) over-counts frames outright, round(368)
    accumulates half a sample per frame until a long answer's final frames sit
    entirely inside the zero padding and the mouth snaps shut early. Constant
    input must therefore hold a constant envelope all the way to the end."""
    env = lipsync.envelope(np.ones(22050 * 20, dtype=np.float32), 22050, fps=60)
    assert len(env) == 1200
    assert env[-1] == pytest.approx(1.0, abs=1e-6)
    assert env.min() == pytest.approx(1.0, abs=1e-6)


def test_amount_at_reads_the_matching_frame():
    env = np.array([0.0, 0.5, 1.0])
    assert lipsync.amount_at(env, 0.0, fps=10) == 0.0
    assert lipsync.amount_at(env, 0.1, fps=10) == 0.5
    assert lipsync.amount_at(env, 0.2, fps=10) == 1.0


def test_amount_at_closes_the_mouth_past_the_end():
    """When playback outruns the envelope the mouth must close, not hold
    open on the last value."""
    env = np.array([1.0, 1.0])
    assert lipsync.amount_at(env, 99.0, fps=10) == 0.0


def test_amount_at_on_empty_envelope_is_closed():
    assert lipsync.amount_at(np.array([]), 0.0) == 0.0


@pytest.mark.parametrize("n", [0, 1, 7, 60, 1000])
def test_emphasis_keeps_the_envelope_length(n):
    env = np.random.default_rng(n).random(n).astype(np.float32)
    assert lipsync.emphasis(env).shape == env.shape


def test_emphasis_is_silent_on_silence():
    assert not lipsync.emphasis(np.zeros(123, dtype=np.float32)).any()


def test_steady_speech_never_raises_the_brows():
    assert lipsync.emphasis(np.full(600, 0.5, dtype=np.float32)).max() < 0.05


def test_a_burst_raises_the_brows_and_they_linger_then_settle():
    fps = 60
    env = np.full(6 * fps, 0.3, dtype=np.float32)
    start, length = (6 * fps - fps // 2) // 2, fps // 2
    env[start:start + length] = 1.0
    out = lipsync.emphasis(env, fps=fps)
    assert out[:fps].max() < 0.05
    assert out[start:start + int(0.6 * fps)].max() > 0.5
    end = start + length - 1
    assert out[end + fps] < out[end]


def test_emphasis_stays_in_range():
    out = lipsync.emphasis(np.random.default_rng(0).random(600).astype(np.float32))
    assert out.min() >= 0.0 and out.max() <= 1.0

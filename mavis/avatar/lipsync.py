"""Amplitude-driven mouth movement.

This model carries only two blendshapes (mouthOpen, mouthSmile) and no
visemes, so true phoneme-accurate lip-sync is not available at any price.
An RMS envelope of the finished audio is what the rig can actually
express.

Working from *finished* audio is also what keeps the 8GB M2 viable: the
envelope is computed once after voice conversion completes, so nothing
neural is running while the renderer animates.
"""
import numpy as np


def envelope(samples: np.ndarray, sample_rate: int, fps: int = 60) -> np.ndarray:
    """RMS energy per animation frame, normalised to 0..1.

    Returns at least one frame even for very short input.
    """
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        return np.zeros(1, dtype=np.float32)

    # Frame count comes from the clip's duration, and frame boundaries are
    # computed at fractional sample positions rather than by a fixed integer
    # stride. The production rate is 22050Hz at 60fps, where a frame is 367.5
    # samples: flooring to 367 reports 61 frames for one second of audio, and
    # rounding to 368 drifts half a sample per frame, so a 20s answer ends with
    # its last frames sitting entirely in the zero padding. Both show up the
    # same way -- the mouth twitching or snapping shut before the audio ends.
    per_frame = sample_rate / fps
    frame_count = max(1, round(samples.size / per_frame))
    frame_count = min(frame_count, samples.size)

    edges = np.rint(np.arange(frame_count + 1) * per_frame).astype(np.int64)
    padded = np.zeros(int(edges[-1]), dtype=np.float32)
    real = min(padded.size, samples.size)
    padded[:real] = samples[:real]

    counts = np.maximum(np.diff(edges), 1)
    rms = np.sqrt(np.add.reduceat(np.square(padded), edges[:-1]) / counts)
    peak = rms.max()
    if peak <= 0.0:
        return np.zeros(frame_count, dtype=np.float32)
    return (rms / peak).astype(np.float32)


def amount_at(env: np.ndarray, elapsed: float, fps: int = 60) -> float:
    """Envelope value for a playback position, 0.0 outside the clip."""
    if len(env) == 0 or elapsed < 0:
        return 0.0
    index = int(elapsed * fps)
    if index >= len(env):
        return 0.0
    return float(env[index])


def emphasis(env: np.ndarray, fps: int = 60, fast: float = 0.25, slow: float = 2.0,
             lift: float = 1.7, span: float = 0.25, rise: float = 0.12,
             fall: float = 0.35) -> np.ndarray:
    """Brow-raise track, 0..1 per frame, from the same envelope as the mouth.

    Fires when he gets louder than his own recent average, not on every
    syllable -- brows that track loudness directly leave him looking
    permanently surprised. Rises fast and falls slowly, the way a raised brow
    lingers a beat after the word. First drafted by the `delegate` model.

    `lift` and `fall` were tuned on his real recorded lines (2026-09-28): at
    the drafted 1.15/0.5 the brows were up 48% of the time, 44 raises a
    minute, because pauses drag the recent average down and everything after
    one reads as emphasis. At 1.7/0.35: up 12%, about 21 a minute.
    """
    env = np.asarray(env, dtype=np.float32)
    if env.size == 0:
        return env

    def average(x, n):
        # Edge-padded centred mean; the output length is exact for any n,
        # including windows longer than the clip.
        n = max(1, n)
        head = n // 2
        padded = np.pad(x, (head, n - 1 - head), mode="edge")
        return np.convolve(padded, np.ones(n) / n, mode="valid")

    near = average(env, round(fast * fps))
    recent = average(env, round(slow * fps))
    raw = np.clip((near - lift * recent) / span, 0.0, 1.0)

    up = 1.0 - np.exp(-1.0 / (fps * rise))
    down = 1.0 - np.exp(-1.0 / (fps * fall))
    out = np.empty(raw.size, dtype=np.float32)
    y = 0.0
    for i, r in enumerate(raw):
        y += (r - y) * (up if r > y else down)
        out[i] = y
    return np.clip(out, 0.0, 1.0)

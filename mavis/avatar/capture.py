"""Record one spoken utterance from the default microphone.

How long he waits after the owner stops talking is paid on every single
question, before anything else can start. With only a loudness threshold to
go on that wait had to be 1.2s: quiet word endings and breaths fall under the
threshold, so anything shorter cut questions off. A voice-activity model
(Silero, ~2MB, on the CPU) tells speech from quiet far better, which is what
lets the wait drop to `VAD_SILENCE_SECONDS`. Without the model file the old
threshold and the old 1.2s are used, unchanged.
"""
import os
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
BLOCK = 1280
SILENCE_RMS = 0.012

RMS_SILENCE_SECONDS = 1.2
# Override to tune against a real voice: export MAVIS_ENDPOINT_SECONDS=0.9
VAD_SILENCE_SECONDS = 0.7
VAD_MODEL = Path(os.environ.get("MAVIS_MODEL_DIR", Path.home() / ".mavis" / "models")
                 ) / "silero_vad.onnx"
VAD_FRAME = 512             # the frame Silero was trained on at 16kHz
VAD_THRESHOLD = 0.5


class RmsDetector:
    """Loudness only. The fallback, and the behaviour before 2026-10-01."""

    silence_seconds = RMS_SILENCE_SECONDS

    def is_speech(self, block: np.ndarray) -> bool:
        return float(np.sqrt(np.mean(np.square(block)))) >= SILENCE_RMS


class VadDetector:
    """Silero VAD over a stream of capture blocks."""

    silence_seconds = VAD_SILENCE_SECONDS

    def __init__(self, model_path=VAD_MODEL, threshold=VAD_THRESHOLD):
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.inter_op_num_threads = options.intra_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        self._rate = np.array(SAMPLE_RATE, dtype=np.int64)
        self.threshold = threshold
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)
        self._carry = np.zeros(0, dtype=np.float32)

    def is_speech(self, block: np.ndarray) -> bool:
        """True if any model frame completed by this block holds speech.

        Capture blocks are 1280 samples and the model wants 512, so the
        remainder is carried into the next call rather than dropped.
        """
        samples = np.concatenate([self._carry, block.astype(np.float32)])
        usable = len(samples) // VAD_FRAME * VAD_FRAME
        self._carry = samples[usable:]
        heard = False
        for start in range(0, usable, VAD_FRAME):
            out, self._h, self._c = self._session.run(None, {
                "input": samples[None, start:start + VAD_FRAME],
                "sr": self._rate, "h": self._h, "c": self._c})
            heard = heard or float(out[0][0]) >= self.threshold
        return heard


def _silence_override(default: float) -> float:
    try:
        value = float(os.environ.get("MAVIS_ENDPOINT_SECONDS", ""))
    except ValueError:
        return default
    return value if value > 0 else default


_detector = None


def detector():
    """The session's detector: the VAD if its model loads, else loudness."""
    global _detector
    if _detector is None:
        try:
            _detector = VadDetector()
        except Exception:  # noqa: BLE001 - no model, no onnxruntime: fall back
            _detector = RmsDetector()
    return _detector


def _mic_blocks():
    import sounddevice as sd
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=BLOCK) as stream:
        while True:
            block, _overflowed = stream.read(BLOCK)
            yield block[:, 0].copy()


def record_utterance(seconds_max: float = 12.0, silence_seconds: float = None,
                     *, detect=None, blocks=None) -> np.ndarray:
    """Record until the speaker stops, or seconds_max, whichever first.

    Returns float32 samples in -1..1 at SAMPLE_RATE. `detect` and `blocks`
    exist for tests; by default it is the session detector on the microphone.
    """
    detect = detect or detector()
    if hasattr(detect, "reset"):
        detect.reset()
    if silence_seconds is None:
        silence_seconds = _silence_override(detect.silence_seconds)
    needed_silent = max(1, int(silence_seconds * SAMPLE_RATE / BLOCK))
    max_blocks = int(seconds_max * SAMPLE_RATE / BLOCK)

    collected = []
    silent_blocks = 0
    heard_speech = False
    source = blocks if blocks is not None else _mic_blocks()
    try:
        for _, mono in zip(range(max_blocks), source):
            collected.append(mono)
            if detect.is_speech(mono):
                heard_speech = True
                silent_blocks = 0
            else:
                silent_blocks += 1
                if heard_speech and silent_blocks >= needed_silent:
                    break
    finally:
        if blocks is None:
            source.close()      # releases the microphone

    if not collected:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(collected)

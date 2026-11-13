"""Text straight to speech, fast enough to answer in.

This replaces the `say` -> ChatterboxVC path. Voice conversion into the
character's voice ran at ~1.5x realtime on this 8GB M2, so every answer was a
wait however it was chunked; the owner traded the voice for speed on
2026-10-01. A voice here turns one sentence into a wav in about a second.

Which voice is `MAVIS_TTS`:
    kokoro      local, free, the default. ~0.4x realtime on CPU (measured
                2026-10-01: 81 chars -> 4.9s of audio in 1.2s).
    elevenlabs  cloud. Needs ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID.
    say         macOS `say`. Mac only.

A failing voice degrades rather than going silent: a cloud voice falls back
to Kokoro, and on a Mac anything falls back to `say` last. The server is
Linux, where `say` does not exist. `Speaker.degraded` / `last_error` let the
UI show it -- the same rule the old voice path kept.
"""
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
from scipy.io import wavfile

MODEL_DIR = Path(os.environ.get("MAVIS_MODEL_DIR", Path.home() / ".mavis" / "models"))
KOKORO_MODEL = "kokoro-v1.0.onnx"
KOKORO_VOICES = "voices-v1.0.bin"
# A blend, not one stock voice: onyx is the low one, fenrir the rough one.
# Override with a single name ("am_onyx") or another "name:weight,..." blend.
DEFAULT_KOKORO_VOICE = "am_onyx:0.6,am_fenrir:0.4"
KOKORO_VOICE = os.environ.get("MAVIS_KOKORO_VOICE") or DEFAULT_KOKORO_VOICE


def _number_from_env(name: str, default, kind=float):
    """A tuning knob that falls back rather than refusing to import.

    Same rule as `brain._budget_from_env`: a mistyped or empty value in the
    LaunchAgent's env file must not stop the avatar from starting.
    """
    try:
        value = kind(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


KOKORO_SPEED = _number_from_env("MAVIS_KOKORO_SPEED", 1.0)
# onnxruntime takes every core by default, and for the second it spends on a
# sentence Panda3D gets none: his animation would hitch each time he starts a
# sentence. Half the cores costs little (measured below) and leaves him moving.
KOKORO_THREADS = _number_from_env("MAVIS_KOKORO_THREADS", 4, int)

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}"
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")
ELEVENLABS_RATE = 24000
ELEVENLABS_TIMEOUT = 15.0

SAY_VOICE = "Tom"


class TTSError(RuntimeError):
    pass


def say_to_wav(text: str, path: str) -> None:
    """macOS `say`: the voice of last resort. Float32 at 22050Hz."""
    subprocess.run(
        ["say", "-v", SAY_VOICE, "-o", path, "--data-format=LEF32@22050", text],
        check=True,
    )


class SayVoice:
    name = "say"

    def start(self) -> None:
        if sys.platform != "darwin" or not shutil.which("say"):
            raise TTSError("`say` exists only on a Mac")

    def synth(self, text: str, path: str) -> None:
        try:
            say_to_wav(text, path)
        except (OSError, subprocess.SubprocessError) as exc:
            raise TTSError(f"say failed: {exc}") from exc


def parse_blend(spec: str):
    """[(name, weight), ...] from "a" or "a:0.6,b:0.4". Weights sum to 1."""
    parts = []
    for item in spec.split(","):
        name, _, weight = item.strip().partition(":")
        if not name:
            continue
        try:
            parts.append((name, float(weight) if weight else 1.0))
        except ValueError as exc:
            raise TTSError(f"bad voice weight in {spec!r}") from exc
    total = sum(weight for _, weight in parts)
    if not parts or total <= 0:
        raise TTSError(f"no voice named in {spec!r}")
    return [(name, weight / total) for name, weight in parts]


class KokoroVoice:
    """Kokoro-82M through onnxruntime, on the CPU.

    The CoreML provider was measured slower here (2026-10-01), and the int8
    model half as fast again, so it is the plain model on plain CPU.
    """

    name = "kokoro"

    def __init__(self, voice=KOKORO_VOICE, speed=KOKORO_SPEED, model_dir=MODEL_DIR,
                 threads=KOKORO_THREADS):
        self.voice_spec = voice
        self.speed = speed
        self.threads = threads
        self.model_dir = Path(model_dir)
        self._kokoro = None
        self._style = None
        self._espeak = None
        # onnxruntime sessions are thread-safe; the espeak backend is not.
        self._lock = threading.Lock()

    def start(self) -> None:
        model = self.model_dir / KOKORO_MODEL
        voices = self.model_dir / KOKORO_VOICES
        for needed in (model, voices):
            if not needed.exists():
                raise TTSError(f"voice model missing at {needed}")
        try:
            import onnxruntime as ort
            from kokoro_onnx import Kokoro
            from phonemizer.backend import EspeakBackend
            options = ort.SessionOptions()
            options.intra_op_num_threads = self.threads
            session = ort.InferenceSession(str(model), sess_options=options,
                                           providers=["CPUExecutionProvider"])
            self._kokoro = Kokoro.from_session(session, str(voices))
            # kokoro_onnx calls phonemizer.phonemize(), which builds a fresh
            # espeak backend on every call: a flat 0.6s per sentence, half of
            # time-to-first-word. One backend kept for the session costs ~0.
            self._espeak = EspeakBackend("en-us", preserve_punctuation=True,
                                         with_stress=True)
            self._style = sum(self._kokoro.get_voice_style(name) * weight
                              for name, weight in parse_blend(self.voice_spec))
            self.synth_samples("Ready.")    # first run compiles the graph
        except TTSError:
            raise
        except Exception as exc:  # noqa: BLE001 - any load failure degrades
            raise TTSError(f"kokoro failed to load: {exc}") from exc

    def _phonemes(self, text: str) -> str:
        raw = self._espeak.phonemize([text.strip()])[0]
        vocab = self._kokoro.tokenizer.vocab
        return "".join(p for p in raw if p in vocab).strip()

    def synth_samples(self, text: str):
        if self._kokoro is None:
            raise TTSError("kokoro is not loaded")
        with self._lock:
            phonemes = self._phonemes(text)
            if not phonemes:
                raise TTSError("nothing speakable in the text")
            samples, rate = self._kokoro.create(
                phonemes, voice=self._style, speed=self.speed, is_phonemes=True)
        return np.asarray(samples, dtype=np.float32), rate

    def synth(self, text: str, path: str) -> None:
        try:
            samples, rate = self.synth_samples(text)
        except TTSError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TTSError(f"kokoro failed: {exc}") from exc
        wavfile.write(path, rate, samples)


class ElevenLabsVoice:
    """ElevenLabs over HTTP, raw PCM so nothing needs decoding.

    The voice must be a designed or library voice. Their prohibited-use
    policy forbids replicating a person's voice without consent or legal
    right (read 2026-10-01).
    """

    name = "elevenlabs"

    def __init__(self, api_key=None, voice_id=None, client=None):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        self.voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID")
        self._client = client

    def start(self) -> None:
        if not self.api_key or not self.voice_id:
            raise TTSError("ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID must be set")
        if self._client is None:
            import httpx
            # Kept open: a fresh TLS handshake per sentence is ~0.2s.
            self._client = httpx.Client(timeout=ELEVENLABS_TIMEOUT)

    def synth(self, text: str, path: str) -> None:
        import httpx
        if self._client is None:
            raise TTSError("elevenlabs is not started")
        try:
            resp = self._client.post(
                ELEVENLABS_URL.format(voice=self.voice_id),
                params={"output_format": f"pcm_{ELEVENLABS_RATE}"},
                headers={"xi-api-key": self.api_key},
                json={"text": text, "model_id": ELEVENLABS_MODEL},
            )
        except httpx.RequestError as exc:
            raise TTSError(f"elevenlabs unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise TTSError(f"elevenlabs returned {resp.status_code}")
        pcm = np.frombuffer(resp.content[: len(resp.content) // 2 * 2], dtype="<i2")
        if pcm.size == 0:
            raise TTSError("elevenlabs returned no audio")
        wavfile.write(path, ELEVENLABS_RATE, pcm)


VOICES = {"kokoro": KokoroVoice, "elevenlabs": ElevenLabsVoice, "say": SayVoice}


def default_fallbacks(primary_name: str) -> list:
    """The voices behind `primary_name`, in the order they are tried.

    Kokoro is local and free, so it backs a cloud voice. `say` is last; off
    a Mac it refuses to start and is skipped.
    """
    fallbacks = []
    if primary_name not in ("kokoro", "say"):
        fallbacks.append(KokoroVoice())     # cheap to build; loads on first use
    fallbacks.append(SayVoice())
    return fallbacks


class Speaker:
    """The chosen voice, with fallback voices behind it.

    A voice that fails to start, or fails on a sentence, hands that sentence
    to the first fallback that can speak it and marks the speaker degraded.
    A failed sentence is not retried in the chosen voice, but the next one
    is: a cloud voice drops a request now and then, and one drop should not
    cost the rest of the session. Only when every voice fails does `synth`
    raise; the call skips that sentence.

    Fallbacks start the first time they are needed, not in `start()`:
    loading Kokoro takes seconds and real memory, wasted while a cloud voice
    is healthy. `last_error` is always the chosen voice's error.
    """

    def __init__(self, voice=None, fallback=None):
        self.voice = voice if voice is not None else make_voice()
        # None -> the defaults; one voice or a list/tuple of them otherwise.
        if fallback is None:
            self.fallbacks = default_fallbacks(self.voice.name)
        elif isinstance(fallback, (list, tuple)):
            self.fallbacks = list(fallback)
        else:
            self.fallbacks = [fallback]
        self._started = {}              # fallback index -> True / False (won't start)
        self._start_lock = threading.Lock()
        self.ready = False
        self.degraded = False
        self.last_error = None

    @property
    def name(self) -> str:
        return self.voice.name

    def start(self) -> None:
        """Start the chosen voice. Fallbacks wait until they are needed."""
        self.ready = False
        self._started = {}
        try:
            self.voice.start()
        except TTSError as exc:
            self.degraded, self.last_error = True, str(exc)
            return
        self.ready = True

    def _fallback_ready(self, i: int) -> bool:
        with self._start_lock:         # two calls may need it at once
            if i not in self._started:
                try:
                    self.fallbacks[i].start()
                    self._started[i] = True
                except TTSError:
                    self._started[i] = False
            return self._started[i]

    def synth(self, text: str, path: str) -> bool:
        """Write `text` as a wav at `path`. True if in the chosen voice,
        False if a fallback spoke it. Raises TTSError if no voice could."""
        if self.ready:
            try:
                self.voice.synth(text, path)
                self.degraded = False
                return True
            except TTSError as exc:
                self.degraded, self.last_error = True, str(exc)
        fallback_errors = []
        for i, fb in enumerate(self.fallbacks):
            if not self._fallback_ready(i):
                continue
            try:
                fb.synth(text, path)
                return False
            except TTSError as exc:
                fallback_errors.append(f"{fb.name}: {exc}")
        detail = "; ".join(fallback_errors) or "no fallback voice available"
        raise TTSError(f"no voice could speak ({self.last_error}; {detail})")


class UnknownVoice(SayVoice):
    """A MAVIS_TTS that names no voice: he starts degraded and says why,
    speaking in `say` on a Mac (on Linux, nothing is behind it)."""

    def __init__(self, name):
        self.name = "say"
        self._reason = f"unknown MAVIS_TTS {name!r}; one of {sorted(VOICES)}"

    def start(self) -> None:
        raise TTSError(self._reason)


def make_voice(name=None, strict=False):
    """The voice `MAVIS_TTS` names. An unknown name is an error only when
    `strict` (the offline generator); the runtime gets a voice that degrades."""
    name = (name or os.environ.get("MAVIS_TTS") or "kokoro").strip().lower()
    if name in VOICES:
        return VOICES[name]()
    if strict:
        raise TTSError(f"unknown MAVIS_TTS {name!r}; one of {sorted(VOICES)}")
    return UnknownVoice(name)

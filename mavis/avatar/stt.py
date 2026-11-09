"""Transcribe an utterance with Groq's Whisper endpoint."""
import io
import os
import wave

import httpx
import numpy as np

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_STT_MODEL = "whisper-large-v3-turbo"
# Whisper spells unfamiliar names by ear, and a misspelt name misses the
# grounding lookup entirely: "Graywind" heard as "Greywind" got "I don't have
# that information" for the watchlist that was sitting in the corpus
# (2026-10-01). The prompt is Whisper's vocabulary hint, not an instruction.
GROQ_STT_PROMPT = ("Johnny, Graywind, watchlist, macro gate, VIX gate, tier pools, "
                   "drawdown breaker, deflated Sharpe, Bullion, the Fed, choom.")


class STTError(RuntimeError):
    pass


_client = None


def _shared_client() -> httpx.AsyncClient:
    """One client for the session. A new one per question paid a fresh TLS
    handshake with Groq every time, inside time-to-first-word."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


def _to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        fh.writeframes(pcm.tobytes())
    return buf.getvalue()


async def transcribe_wav(wav: bytes,
                         *, client: httpx.AsyncClient | None = None) -> str:
    """Transcribe a WAV file's bytes as they are (the call page sends WAV)."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise STTError("GROQ_API_KEY not set")
    if not wav:
        return ""
    return await _post(wav, api_key, client or _shared_client())


async def transcribe(samples: np.ndarray, sample_rate: int = 16000,
                     *, client: httpx.AsyncClient | None = None) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise STTError("GROQ_API_KEY not set")
    if samples.size == 0:
        return ""

    return await _post(_to_wav_bytes(samples, sample_rate), api_key,
                       client or _shared_client())


async def _post(wav: bytes, api_key: str, client: httpx.AsyncClient) -> str:
    try:
        resp = await client.post(
            GROQ_STT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": ("utterance.wav", wav, "audio/wav")},
            data={"model": GROQ_STT_MODEL, "prompt": GROQ_STT_PROMPT},
        )
    except httpx.RequestError as exc:
        raise STTError(f"speech-to-text unreachable: {exc}") from exc

    if resp.status_code != 200:
        raise STTError(f"speech-to-text failed ({resp.status_code})")
    return resp.json().get("text", "").strip()

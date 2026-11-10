"""The /call WebSocket: a phone-style call from the browser.

call.py runs the call itself; this module is the door (the key check, the
rate limit) and the real parts plugged into it: Groq speech-to-text, the
same answer stream as /ask/stream, and Johnny's Kokoro voice.

Browsers cannot set headers on a WebSocket, so the key arrives as the first
message rather than in the URL, where it would land in logs and history.
"""
import asyncio
import contextlib
import functools
import os
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

import auth
import call
from rate_limit import check_rate_limit
from avatar import brain as avatar_brain
from avatar import canned as avatar_canned
from avatar import dismiss as avatar_dismiss
from avatar import speech as avatar_speech
from avatar import stt as avatar_stt
from avatar import tts as avatar_tts

router = APIRouter()

PAGE = Path(__file__).resolve().parent / "web" / "call.html"
# Built from the local-only Keanu port (see assets/avatar/ATTRIBUTION.md):
# gitignored and CD Projekt Red's property, so it is served only to a caller
# holding the key, never as a public file.
MODEL = Path(os.environ.get(
    "MAVIS_CALL_MODEL",
    Path(__file__).resolve().parent / "assets" / "avatar" / "keanu-web.glb"))


@router.get("/johnny", include_in_schema=False)
def call_page():
    return FileResponse(PAGE, media_type="text/html",
                        headers={"Cache-Control": "no-cache"})


@router.get("/johnny/model.glb", include_in_schema=False)
def call_model(_rec: auth.KeyRecord = Depends(auth.require_api_key)):
    if not MODEL.exists():
        raise HTTPException(404, f"call model missing at {MODEL}")
    # no-cache: the browser keeps it but asks again (with the key) every
    # time, so a rebuilt model or a changed key is never served stale.
    # Unchanged, the answer is a 304 with no body.
    return FileResponse(MODEL, media_type="model/gltf-binary",
                        headers={"Cache-Control": "private, no-cache"})


@router.get("/johnny/check", include_in_schema=False)
def call_check(_rec: auth.KeyRecord = Depends(auth.require_api_key)):
    """Lets the page test a key before saving it."""
    return {"ok": True}


VENDOR = Path(__file__).resolve().parent / "web" / "vendor"

HELLO_TIMEOUT = 5.0
# Distinct codes so the page clears its saved key only for a wrong key,
# never for a slow or garbled hello.
CLOSE_NO_HELLO = 4400
CLOSE_WRONG_KEY = 4401
CALL_MAX_CHARS = avatar_brain.MAX_ANSWER_CHARS

_voice_lock = threading.Lock()
_speaker = None
_canned_voice = None


def _call_voice():
    """The voice and its canned lines, loaded once (Kokoro takes seconds)."""
    global _speaker, _canned_voice
    with _voice_lock:
        if _speaker is None:
            speaker = avatar_tts.Speaker()
            speaker.start()
            _canned_voice = avatar_canned.CannedVoice(
                avatar_canned.asset_dir(speaker.name))
            _speaker = speaker
    return _speaker, _canned_voice


def warm_up_in_background() -> None:
    """Opt-in (MAVIS_CALL_WARM=1): load the voice at server start so the
    first call picks up fast. Off by default, so a server that never takes
    calls does not hold a second Kokoro next to the desktop avatar's."""
    if os.environ.get("MAVIS_CALL_WARM") == "1":
        threading.Thread(target=_call_voice, name="call-voice-warmup",
                         daemon=True).start()


async def _call_transcribe(rec: auth.KeyRecord, wav: bytes) -> str:
    # Counted here, before the paid STT request, so every utterance -- even
    # one that turns out empty or a goodbye -- uses a slot.
    if not auth.still_valid(rec):
        raise call.AnswerError("This key was revoked.")
    try:
        check_rate_limit(rec.id, rec.per_minute)
    except HTTPException as exc:
        raise call.AnswerError(exc.detail) from exc
    return await avatar_stt.transcribe_wav(wav)


def _call_synth(sentence: str) -> bytes:
    speaker, _ = _call_voice()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "line.wav"
        speaker.synth(sentence, str(path))
        return path.read_bytes()


@functools.lru_cache(maxsize=64)
def _read_line(path: str) -> bytes | None:
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def _call_canned(moment: str) -> bytes | None:
    canned_voice = _canned_voice    # loaded before run_call starts
    found = canned_voice.path_for(moment) if canned_voice else None
    return _read_line(found[1]) if found else None


def _call_deps(rec: auth.KeyRecord) -> call.CallDeps:
    from app import _answer_events    # app imports this module

    async def transcribe(wav: bytes) -> str:
        return await _call_transcribe(rec, wav)

    async def answer(question: str):
        async for event in _answer_events(question, CALL_MAX_CHARS):
            if "error" in event:
                raise call.AnswerError(event["error"])
            if "delta" in event:
                yield event["delta"]

    return call.CallDeps(
        transcribe=transcribe,
        answer=answer,
        synth=_call_synth,
        canned=_call_canned,
        is_dismissal=avatar_dismiss.is_dismissal,
        make_cutter=avatar_speech.SentenceCutter,
    )


async def _refuse(ws: WebSocket, message: str | None, code: int) -> None:
    with contextlib.suppress(Exception):    # the browser may already be gone
        if message:
            await ws.send_json({"type": "error", "message": message})
        await ws.close(code=code)


@router.websocket("/call")
async def call_ws(ws: WebSocket):
    """One call. The first message must be {"type": "hello", "key": "..."}."""
    await ws.accept()
    try:
        hello = await asyncio.wait_for(ws.receive_json(), HELLO_TIMEOUT)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, KeyError):
        await _refuse(ws, None, CLOSE_NO_HELLO)
        return
    if not auth.configured():
        await _refuse(ws, "no keys configured on the server", 1011)
        return
    key = hello.get("key") if isinstance(hello, dict) else None
    rec = auth.lookup(key)
    if rec is None:
        await _refuse(ws, "wrong or missing key", CLOSE_WRONG_KEY)
        return
    # Instant once warmed; otherwise the first call waits for Kokoro here,
    # off the event loop.
    await asyncio.to_thread(_call_voice)
    await call.run_call(ws, _call_deps(rec))
    with contextlib.suppress(Exception):    # the browser may already be gone
        await ws.close()

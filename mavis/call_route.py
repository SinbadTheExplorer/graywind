"""The /call WebSocket: a phone-style call from the browser.

call.py runs the call itself; this module is the door (the key check, the
rate limit) and the real parts plugged into it: Groq speech-to-text, the
same answer stream as /ask/stream, and Johnny's Kokoro voice.

Browsers cannot set headers on a WebSocket, so the key arrives as the first
message rather than in the URL, where it would land in logs and history.
"""
import asyncio
import base64
import hashlib
import re
import contextlib
import functools
import os
import sys
import tempfile
import time
from urllib.parse import urlsplit
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response

import alerts
import auth
import call
import guards
import usage
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
def _audit(event: str, key_id, **fields) -> None:
    """Audit, but never let a broken log file break a call or a refund."""
    try:
        usage.audit(event, key_id, **fields)
    except Exception as exc:  # noqa: BLE001
        print(f"call: audit {event} failed: {exc!r}", file=sys.stderr)


# Extra page origins allowed to open a call, comma-separated, for a proxy
# that rewrites Host (normally the Host check below is enough).
ALLOWED_ORIGINS = {o.strip().lower() for o in
                   os.environ.get("MAVIS_ALLOWED_ORIGINS", "").split(",") if o.strip()}

# What a guest sees instead: a model the owner has the rights to share.
# Unset (today), guests get the orb.
PUBLIC_MODEL = os.environ.get("MAVIS_PUBLIC_MODEL")


WEB = PAGE.parent


_IMPORTMAP = re.compile(r"<script type=\"importmap\">(.*?)</script>", re.S)
_SAFE_HOST = re.compile(r"[A-Za-z0-9.-]+(:[0-9]{1,5})?")


def _importmap_hash(html: str) -> str | None:
    """CSP hash of the page's one inline block, the import map, or None.

    three.js's add-ons import 'three' by bare name, which only an import map
    can resolve, and browsers don't load import maps from files. Allowing
    exactly this block by its hash keeps every other inline script blocked.
    """
    blocks = _IMPORTMAP.findall(html)
    if len(blocks) != 1:
        return None
    digest = hashlib.sha256(blocks[0].encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode() + "'"


def page_csp(html: str, host: str | None) -> str:
    """The call page's CSP, built from the exact bytes being served, so the
    import map's hash always matches the page the browser gets.

    'wasm-unsafe-eval' lets the model decoder (meshopt) run WebAssembly; it
    does not allow JavaScript eval (Safari 16+ / iOS 16+). The call's own
    wss:// address is named outright, because older WebKit doesn't count a
    WebSocket as 'self'.
    """
    importmap = _importmap_hash(html)
    if importmap is None:    # fail closed: the page breaks, nothing else runs
        print("call: call.html must have exactly one import map", file=sys.stderr)
    connect = ["'self'", "blob:"]
    if host and _SAFE_HOST.fullmatch(host):
        connect += [f"wss://{host}", f"ws://{host}"]
    return ("default-src 'self'; "
            f"script-src 'self' 'wasm-unsafe-eval'{' ' + importmap if importmap else ''}; "
            f"connect-src {' '.join(connect)}; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")


SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"microphone=(self), camera=(), geolocation=()"),
    (b"x-frame-options", b"DENY"),
]


class SecurityHeaders:
    """Plain ASGI middleware: adds the basic headers to every HTTP response
    without re-streaming the body (so /ask/stream is untouched)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _ in message.get("headers", [])}
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [
                    (k, v) for k, v in SECURITY_HEADERS if k not in names]
            await send(message)

        await self.app(scope, receive, send_with_headers)


@router.get("/johnny", include_in_schema=False)
def call_page(request: Request):
    html = PAGE.read_text(encoding="utf-8")
    return Response(html, media_type="text/html", headers={
        "Cache-Control": "no-cache",
        "Content-Security-Policy": page_csp(html, request.headers.get("host")),
    })


# The page's own scripts. Only these names are served from web/.
PAGE_SCRIPTS = {"call.js", "worklet.js"}


@router.get("/johnny/{name}.js", include_in_schema=False)
def call_script(name: str):
    if f"{name}.js" not in PAGE_SCRIPTS:
        raise HTTPException(404)
    return FileResponse(WEB / f"{name}.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})




@router.get("/johnny/model.glb", include_in_schema=False)
def call_model(rec: auth.KeyRecord = Depends(auth.require_api_key)):
    if rec.scope != "owner":
        public = Path(PUBLIC_MODEL) if PUBLIC_MODEL else None
        # Never Keanu for a guest, even if the public path points at him.
        if public is not None and public.resolve() == MODEL.resolve():
            raise HTTPException(403, "no model for this key")   # never Keanu
        if public is None or not public.is_file():
            raise HTTPException(404, "no model")   # the page shows the orb
        return FileResponse(public, media_type="model/gltf-binary",
                            headers={"Cache-Control": "private, no-cache"})
    if not MODEL.exists():
        raise HTTPException(404, "call model missing")
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
CLOSE_BAD_ORIGIN = 4403
CLOSE_LOCKED = 4423
CLOSE_BUSY = 4429
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
    """Every check that costs nothing runs before the paid STT request."""
    if not auth.still_valid(rec):
        raise call.AnswerError("This key was revoked.")
    # First, so even junk messages use a slot: a flood of bad frames is
    # throttled like any other.
    try:
        check_rate_limit(rec.id, rec.per_minute)
    except HTTPException as exc:
        raise call.AnswerError(exc.detail) from exc
    try:
        wav, seconds = guards.normalize_wav(wav)
    except guards.TooLong as exc:
        await asyncio.to_thread(_audit, "bad_audio", rec.id, reason="too long")
        raise call.AnswerError("Too long for me, choom. Keep it under "
                               f"{int(guards.MAX_UTTERANCE_SECONDS)} seconds.") from exc
    except guards.BadAudio as exc:
        await asyncio.to_thread(_audit, "bad_audio", rec.id, reason=str(exc))
        raise call.AnswerError(guards.GENERIC_ERROR) from exc
    try:
        await asyncio.to_thread(usage.charge, rec, "stt_seconds", seconds)
    except usage.CapExceeded as exc:
        await asyncio.to_thread(_audit, "cap_hit", rec.id,
                                kind="stt_seconds", which=exc.which)
        alerts.cap_alert("stt_seconds", exc.which, rec.id)
        raise call.AnswerError(guards.TAPPED_OUT) from exc
    except Exception as exc:  # usage store down: refuse, never spend uncounted
        print(f"call: usage charge failed: {exc!r}", file=sys.stderr)
        raise call.AnswerError(guards.GENERIC_ERROR) from exc
    try:
        await asyncio.to_thread(_audit, "utterance", rec.id, seconds=round(seconds, 2))
        return await avatar_stt.transcribe_wav(wav)
    except Exception:
        with contextlib.suppress(Exception):    # nothing was transcribed: give it back
            await asyncio.to_thread(usage.refund, rec, "stt_seconds", seconds)
        raise


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
        async for event in _answer_events(question, CALL_MAX_CHARS, rec):
            if "error" in event:
                raise call.AnswerError(event["error"])
            if "delta" in event:
                yield event["delta"]

    return call.CallDeps(
        max_seconds=guards.env_number("MAVIS_CALL_MAX_SECONDS", 900, minimum=10),
        idle_seconds=guards.env_number("MAVIS_CALL_IDLE_SECONDS", 120, minimum=10),
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


def _origin_ok(ws: WebSocket) -> bool:
    """A browser always sends Origin; it must be this server's own page.

    Clients that send no Origin (scripts, the test client) are let through:
    the key is the real lock, and this only stops another website's page
    from opening a call in a visitor's browser.
    """
    origin = ws.headers.get("origin")
    if not origin:
        return True
    if origin.strip().lower().rstrip("/") in ALLOWED_ORIGINS:
        return True
    host = urlsplit(origin).netloc.lower()
    allowed = {ws.headers.get("host", "").strip().lower()}
    allowed |= {h.strip().lower() for h in ws.headers.get("x-forwarded-host", "").split(",")}
    allowed.discard("")
    return host in allowed


@router.websocket("/call")
async def call_ws(ws: WebSocket):
    """One call. The first message must be {"type": "hello", "key": "..."}."""
    origin_ok = _origin_ok(ws)
    # Accept first, then close: a close before accept reaches a browser as a
    # bare 1006 with no reason, and the page couldn't say why.
    await ws.accept()
    if not origin_ok:
        _audit("bad_origin", None, reason=ws.headers.get("origin", ""))
        await _refuse(ws, "This page can't call Johnny.", CLOSE_BAD_ORIGIN)
        return
    try:
        hello = await asyncio.wait_for(ws.receive_json(), HELLO_TIMEOUT)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, KeyError):
        await _refuse(ws, None, CLOSE_NO_HELLO)
        return
    ident = guards.identity(ws)
    key = hello.get("key") if isinstance(hello, dict) else None
    rec, reason = auth.authenticate(key, ident)
    if reason == "locked":
        await _refuse(ws, auth.LOCKED_OUT, CLOSE_LOCKED)
        return
    if reason == "unconfigured":
        await _refuse(ws, "no keys configured on the server", 1011)
        return
    if reason == "wrong":
        if key:
            await asyncio.to_thread(auth.note_failure, ident)
        await _refuse(ws, "wrong or missing key", CLOSE_WRONG_KEY)
        return
    if not guards.SLOTS.acquire(rec.id, owner=rec.scope == "owner"):
        _audit("call_busy", rec.id)
        await _refuse(ws, "Johnny's on another call.", CLOSE_BUSY)
        return
    started = time.monotonic()
    reason = "failed"
    try:
        _audit("call_start", rec.id, scope=rec.scope)
        # Instant once warmed; otherwise the first call waits for Kokoro here,
        # off the event loop.
        await asyncio.to_thread(_call_voice)
        reason = await call.run_call(ws, _call_deps(rec))
    finally:
        guards.SLOTS.release(rec.id)
        _audit("call_end", rec.id, reason=reason,
                    seconds=round(time.monotonic() - started, 1))
    with contextlib.suppress(Exception):    # the browser may already be gone
        await ws.close()

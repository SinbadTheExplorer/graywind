"""Input guards: what a caller may send before any paid work starts."""
import os
import struct

MAX_UTTERANCE_SECONDS = float(os.environ.get("MAVIS_MAX_UTTERANCE_SECONDS", "30"))
GENERIC_ERROR = "Johnny's line dropped. Try again."
TAPPED_OUT = "I'm tapped out for today, choom. Call me tomorrow."


class BadAudio(ValueError):
    """Raised when a WAV file does not meet the required constraints."""


class TooLong(BadAudio):
    """A valid recording, just longer than MAX_UTTERANCE_SECONDS."""


def _header(n_bytes: int) -> bytes:
    """A canonical 44-byte header for 16 kHz mono 16-bit PCM."""
    return (b"RIFF" + struct.pack("<I", 36 + n_bytes) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
            + b"data" + struct.pack("<I", n_bytes))


def wav_seconds(data: bytes, max_seconds: float | None = None) -> float:
    """Seconds of audio in a WAV the caller sent (see normalize_wav)."""
    return normalize_wav(data, max_seconds)[1]


def normalize_wav(data: bytes, max_seconds: float | None = None) -> tuple[bytes, float]:
    """Check a caller's WAV and rebuild it, returning (clean_wav, seconds).

    The clean copy holds exactly the audio that was measured: the data
    chunk's declared size, or what actually arrived if less did. Bytes
    after it -- metadata chunks, or extra audio behind a header that lies
    small -- never reach the paid speech-to-text, so what is billed is what
    was measured. Raises BadAudio for anything but 16 kHz mono 16-bit PCM.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise BadAudio("not 16 kHz mono 16-bit WAV")
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise BadAudio("not 16 kHz mono 16-bit WAV")

    offset = 12
    fmt_found = False
    data_found = False
    audio_bytes = 0
    audio_start = 0

    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        offset += 8

        # Guard against chunk claiming more bytes than exist
        payload_end = offset + chunk_size
        if payload_end > len(data):
            # Truncate the payload to the actual remaining bytes
            payload_end = len(data)

        if chunk_id == b"fmt ":
            if fmt_found:
                # ignore duplicate fmt chunks
                pass
            else:
                if chunk_size < 16 or offset + 16 > len(data):
                    raise BadAudio("not 16 kHz mono 16-bit WAV")
                (
                    audio_format,
                    channels,
                    sample_rate,
                    _byte_rate,
                    _block_align,
                    bits_per_sample,
                ) = struct.unpack_from("<HHIIHH", data, offset)
                if (
                    audio_format != 1
                    or channels != 1
                    or sample_rate != 16000
                    or bits_per_sample != 16
                ):
                    raise BadAudio("not 16 kHz mono 16-bit WAV")
                fmt_found = True

        elif chunk_id == b"data":
            if not fmt_found:
                raise BadAudio("not 16 kHz mono 16-bit WAV")
            audio_start = offset
            audio_bytes = min(chunk_size, len(data) - offset)
            audio_bytes -= audio_bytes % 2    # whole 16-bit samples only
            data_found = True
            break

        # Move to next chunk, accounting for padding byte if size is odd
        offset = payload_end
        if chunk_size % 2 == 1:
            offset += 1

    if not fmt_found:
        raise BadAudio("not 16 kHz mono 16-bit WAV")
    if not data_found:
        raise BadAudio("no data chunk")
    if audio_bytes == 0:
        raise BadAudio("zero length audio")

    seconds = audio_bytes / 32000.0  # 16kHz mono 16‑bit → 32 000 bytes per second
    limit = max_seconds if max_seconds is not None else MAX_UTTERANCE_SECONDS
    if seconds > limit:
        raise TooLong("utterance too long")
    return _header(audio_bytes) + data[audio_start:audio_start + audio_bytes], seconds



def env_number(name: str, default: float, minimum: float = 0) -> float:
    """A number from the environment; a bad value falls back loudly, never crashes."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not (value == value) or value in (float("inf"), float("-inf")) or value < minimum:
        import sys
        print(f"guards: bad {name}={raw!r}, using {default}", file=sys.stderr)
        return default
    return value


class CallSlots:
    """How many calls may run at once: in total, and per key.

    Kokoro is CPU-heavy, and a small server freezes under a few parallel
    calls, so the extra ones are turned away instead.
    """

    def __init__(self, max_total: int, max_per_key: int = 1):
        import threading
        self.max_total, self.max_per_key = max_total, max_per_key
        self._active: dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire(self, key_id: str, owner: bool = False) -> bool:
        """The owner is never turned away for lack of room: guests can't lock
        him out of his own server. Everyone gets one call per key."""
        with self._lock:
            if not owner and sum(self._active.values()) >= self.max_total:
                return False
            if self._active.get(key_id, 0) >= self.max_per_key:
                return False
            self._active[key_id] = self._active.get(key_id, 0) + 1
            return True

    def release(self, key_id: str) -> None:
        with self._lock:
            left = self._active.get(key_id, 0) - 1
            if left > 0:
                self._active[key_id] = left
            else:
                self._active.pop(key_id, None)


SLOTS = CallSlots(max_total=int(env_number("MAVIS_MAX_CALLS", 2, minimum=1)))


# --- Failed-key lockout -----------------------------------------------------

_IDENT_CHARS = 120


def _is_loopback(host: str | None) -> bool:
    import ipaddress
    try:
        addr = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_loopback


def identity(conn) -> str:
    """Who is knocking, for counting wrong keys. `conn` is a Request or a
    WebSocket (or None).

    Behind `tailscale serve` every request comes from localhost, so the
    address can't tell callers apart; the Tailscale login can. The login
    header is trusted only from the local proxy (a loopback address), so a
    direct caller can't pick a name to dodge the count or frame someone.
    """
    if conn is None:
        return "ip:unknown"
    host = conn.client.host if conn.client else None
    login = (conn.headers.get("tailscale-user-login") or "").strip()
    if login and _is_loopback(host):
        return "ts:" + login[:_IDENT_CHARS]
    return "ip:" + (host or "unknown")[:_IDENT_CHARS]


class Lockout:
    """`max_failures` wrong keys within `window` seconds locks an identity
    out for `lock_seconds`. A right key does not reset the count, so a
    guest can't mix in their own key to keep guessing."""

    MAX_TRACKED = 10_000    # identities held at once; old ones are dropped

    def __init__(self, max_failures: int = 5, window: float = 600,
                 lock_seconds: float = 600, clock=None):
        import threading
        import time
        self.max_failures, self.window, self.lock_seconds = max_failures, window, lock_seconds
        self._clock = clock or time.monotonic
        self._fails: dict[str, list[float]] = {}
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    def locked(self, ident: str) -> bool:
        with self._lock:
            until = self._until.get(ident)
            if until is None:
                return False
            if self._clock() >= until:
                del self._until[ident]
                return False
            return True

    def fail(self, ident: str) -> bool:
        """Count one wrong key. True only when this one starts a lock."""
        with self._lock:
            now = self._clock()
            if self._until.get(ident, 0) > now:
                return False    # already locked
            recent = [t for t in self._fails.pop(ident, []) if now - t < self.window]
            recent.append(now)
            if len(recent) >= self.max_failures:
                self._until[ident] = now + self.lock_seconds
                locked = True
            else:
                # Popped and re-added, so the dict stays oldest-failure-first
                # and an identity still guessing is the last to be dropped.
                self._fails[ident] = recent
                locked = False
            if len(self._fails) + len(self._until) > self.MAX_TRACKED:
                self._prune(now)
            return locked

    def _prune(self, now: float) -> None:
        self._fails = {i: ts for i, ts in self._fails.items() if now - ts[-1] < self.window}
        self._until = {i: u for i, u in self._until.items() if u > now}
        while self._fails and len(self._fails) + len(self._until) > self.MAX_TRACKED:
            self._fails.pop(next(iter(self._fails)))    # a flood of fresh names

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()
            self._until.clear()


LOCKOUT = Lockout(
    max_failures=int(env_number("MAVIS_LOCKOUT_FAILURES", 5, minimum=1)),
    window=env_number("MAVIS_LOCKOUT_WINDOW_SECONDS", 600, minimum=1),
    lock_seconds=env_number("MAVIS_LOCKOUT_SECONDS", 600, minimum=1),
)

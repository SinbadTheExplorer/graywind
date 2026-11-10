"""Per-person keys: who is calling, and what they may see.

Each key has a scope. "owner" sees everything, including Graywind's own data
and the Keanu model. "guest" sees Bullion and the news only. The file holds
SHA-256 hashes, never the keys, so a copy of it lets nobody in.

The env key MAVIS_API_KEY is not in this file: auth.py treats it as the
owner's key, so the desktop avatar and existing setups keep working.

    python keys.py add <id> <owner|guest>    prints the new key once
    python keys.py revoke <id>
    python keys.py list
"""
import contextlib
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

SCOPES = ("owner", "guest")
# Reserved for the env key (see auth.py). A file record may never take it,
# or it would share the owner's rate limit, caps and audit trail.
OWNER_ENV_ID = "owner-env"
DEFAULTS = {
    "owner": dict(per_minute=20, per_day_llm=300, per_day_stt_seconds=1800),
    "guest": dict(per_minute=10, per_day_llm=50, per_day_stt_seconds=300),
}


@dataclass(frozen=True)
class KeyRecord:
    id: str
    scope: str
    per_minute: int
    per_day_llm: int
    per_day_stt_seconds: int
    revoked: bool = False


def store_path() -> Path:
    return Path(os.environ.get("MAVIS_KEYS_FILE", "~/.mavis/keys.json")).expanduser()


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()


_lock = threading.Lock()
_cache: dict = {"stamp": None, "path": None, "entries": []}


def _stamp(path: Path):
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    # A rename-replace gives a new inode, so a write is seen even within
    # the filesystem's timestamp resolution.
    return (st.st_ino, st.st_mtime_ns, st.st_size)


_warned: set = set()


def _valid(entry) -> bool:
    try:
        return (isinstance(entry, dict) and isinstance(entry["hash"], str)
                and entry["id"] != OWNER_ENV_ID and entry["scope"] in SCOPES
                and all(isinstance(entry[k], int)
                        for k in ("per_minute", "per_day_llm", "per_day_stt_seconds")))
    except (KeyError, TypeError):
        return False


def _entries() -> list[dict]:
    """The file's valid records ({"hash": ..., **KeyRecord fields}), re-read on change.

    A damaged file fails closed for file keys only: none of them work, but
    the env owner key (auth.py) is unaffected, so the owner is never locked
    out by a typo in keys.json.
    """
    path = store_path()
    stamp = _stamp(path)
    with _lock:
        if stamp == _cache["stamp"] and path == _cache["path"]:
            return _cache["entries"]
        entries = []
        if stamp is not None:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))["keys"]
                entries = [e for e in raw if _valid(e)]
                if len(entries) != len(raw):
                    _warn(path, f"{len(raw) - len(entries)} malformed record(s) ignored")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                _warn(path, f"unreadable ({type(exc).__name__}); no file keys accepted")
                entries = []
        _cache.update(stamp=stamp, path=path, entries=entries)
        return entries


def _warn(path: Path, msg: str) -> None:
    if (path, msg) not in _warned:
        _warned.add((path, msg))
        print(f"keys: {path}: {msg}", file=sys.stderr)


@contextlib.contextmanager
def _writing():
    """Serialise add/revoke across processes, so no update is lost."""
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(path.with_name(path.name + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with _lock:
                _cache["stamp"] = None    # read the latest, not a cached copy
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _write(entries: list[dict]) -> None:
    path = store_path()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".keys-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"keys": entries}, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    with _lock:
        _cache["stamp"] = None    # force a re-read


def _record(entry: dict) -> KeyRecord:
    return KeyRecord(id=entry["id"], scope=entry["scope"],
                     per_minute=entry["per_minute"], per_day_llm=entry["per_day_llm"],
                     per_day_stt_seconds=entry["per_day_stt_seconds"],
                     revoked=bool(entry.get("revoked", False)))


def add(key_id: str, scope: str) -> str:
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}; use one of {SCOPES}")
    if not key_id or not key_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("key id must be letters, digits, - or _")
    with _writing():
        entries = list(_entries())
        if key_id == OWNER_ENV_ID or any(e["id"] == key_id for e in entries):
            raise ValueError(f"key id {key_id!r} already exists or is reserved")
        key = secrets.token_urlsafe(32)
        rec = KeyRecord(id=key_id, scope=scope, **DEFAULTS[scope])
        entries.append({"hash": _hash(key), **asdict(rec)})
        _write(entries)
    return key


def revoke(key_id: str) -> None:
    with _writing():
        entries = [dict(e) for e in _entries()]
        for e in entries:
            if e["id"] == key_id:
                e["revoked"] = True
                _write(entries)
                return
    raise KeyError(key_id)


def is_active(key_id: str) -> bool:
    """True if this file key still exists and is not revoked (a mid-call check)."""
    return any(e["id"] == key_id and not e.get("revoked") for e in _entries())


def list_records() -> list[KeyRecord]:
    return [_record(e) for e in _entries()]


def has_records() -> bool:
    return bool(_entries())


def lookup_file(candidate) -> KeyRecord | None:
    """The record for this key, or None if unknown or revoked."""
    if not isinstance(candidate, str) or not candidate:
        return None
    digest = _hash(candidate)
    found = None
    for e in _entries():    # no early exit: same work for every candidate
        if hmac.compare_digest(digest, e["hash"]):
            found = e
    if found is None or found.get("revoked"):
        return None
    return _record(found)


def _main(argv: list[str]) -> int:
    if argv[:1] == ["add"] and len(argv) == 3:
        key = add(argv[1], argv[2])
        print(f"New {argv[2]} key for {argv[1]} (shown once, store it now):\n{key}")
    elif argv[:1] == ["revoke"] and len(argv) == 2:
        revoke(argv[1])
        print(f"revoked {argv[1]}")
    elif argv == ["list"]:
        for r in list_records():
            state = "REVOKED" if r.revoked else "active"
            print(f"{r.id:20} {r.scope:6} {state:8} {r.per_minute}/min "
                  f"{r.per_day_llm} answers/day {r.per_day_stt_seconds}s audio/day")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))

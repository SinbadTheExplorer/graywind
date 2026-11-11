import hmac
import os
import sys

from fastapi import Header, HTTPException, Request

import alerts
import guards
import keys
import rate_limit
import usage
from keys import OWNER_ENV_ID, KeyRecord

# The owner's original key. It stays valid as an owner key (id "owner-env")
# beside the per-person keys in keys.json, so the desktop avatar, the MCP
# wrapper and existing setups keep working unchanged.
MAVIS_API_KEY = os.environ.get("MAVIS_API_KEY")


def configured() -> bool:
    """True if any key can be valid: the env key, or a keys.json record."""
    return bool(MAVIS_API_KEY) or keys.has_records()


def lookup(candidate) -> KeyRecord | None:
    """Who holds this key, or None for an unknown or revoked one."""
    if not isinstance(candidate, str) or not candidate:
        return None
    # Assumes ASCII secrets (base64/hex style); Starlette decodes headers as
    # latin-1, which matches UTF-8 for ASCII. A non-ASCII candidate simply
    # fails to match.
    env_match = bool(MAVIS_API_KEY) and hmac.compare_digest(
        candidate.encode("utf-8", "surrogatepass"), MAVIS_API_KEY.encode())
    file_rec = keys.lookup_file(candidate)    # always run: same work either way
    if env_match:
        # The env key keeps honouring MAVIS_RATE_LIMIT_PER_MINUTE, as before.
        limits = {**keys.DEFAULTS["owner"], "per_minute": rate_limit.MAX_REQUESTS_PER_WINDOW}
        return KeyRecord(OWNER_ENV_ID, "owner", **limits)
    return file_rec


def still_valid(rec: KeyRecord) -> bool:
    """Re-checked on every utterance, so a revoke ends an open call."""
    if rec.id == OWNER_ENV_ID:
        return bool(MAVIS_API_KEY)
    return keys.is_active(rec.id)


LOCKED_OUT = "Too many wrong keys. Try again in 10 minutes."


class Refused(Exception):
    """Why a key was turned away: "locked", "wrong" or "unconfigured"."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _audit(event: str, **fields) -> None:
    try:
        usage.audit(event, None, **fields)
    except Exception as exc:  # noqa: BLE001
        print(f"auth: audit {event} failed: {exc!r}", file=sys.stderr)


def note_failure(ident: str) -> None:
    """Count a wrong key; log it, and alert the owner when it locks someone out.

    Blocking (audit file writes; the alert itself returns at once): async
    callers run it in a thread.
    """
    _audit("auth_fail", ident=ident)
    if guards.LOCKOUT.fail(ident):
        _audit("lockout", ident=ident)
        try:
            alerts.notify("Johnny lockout",
                          "Someone was locked out after too many wrong keys. "
                          "Details in audit.log.", dedupe=f"lockout:{ident}")
        except Exception as exc:  # noqa: BLE001
            print(f"auth: alert failed: {exc!r}", file=sys.stderr)


def authenticate(candidate, ident: str) -> tuple[KeyRecord | None, str | None]:
    """The one door every key goes through: (record, None), or (None, reason)
    where reason is "locked", "wrong" or "unconfigured". The caller must run
    note_failure(ident) when reason is "wrong" and a key was sent.

    A locked caller is turned away even with a right key -- except the
    owner's: the keys are far too long to guess, so letting the owner's key
    through teaches a guesser nothing, and a guest's typos sharing the
    owner's address can't lock the owner out of his own server.
    """
    locked = guards.LOCKOUT.locked(ident)
    rec = lookup(candidate)
    if locked and (rec is None or rec.scope != "owner"):
        return None, "locked"
    if rec is None:
        return None, "wrong" if configured() else "unconfigured"
    return rec, None


def require_api_key(x_api_key: str = Header(default=None),
                    request: Request = None) -> KeyRecord:
    ident = guards.identity(request)
    rec, reason = authenticate(x_api_key, ident)
    if reason == "locked":
        raise HTTPException(429, LOCKED_OUT)
    if reason == "unconfigured":
        raise HTTPException(500, "no keys configured on the server")
    if reason == "wrong":
        if x_api_key:    # a missing key guesses nothing; a wrong one counts
            note_failure(ident)
        raise HTTPException(401, "invalid or missing X-API-Key header")
    return rec

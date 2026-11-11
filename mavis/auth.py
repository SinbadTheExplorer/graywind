import dataclasses
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

# Tailscale logins that are the owner, comma-separated (the server's env).
# A request relayed by `tailscale serve` carries the caller's login, and
# serve overwrites any login a caller tries to forge (checked on the VPS
# 2026-11-11), so these callers need no key at all.
#
# Off unless MAVIS_TAILSCALE_SIGNIN=1. Turn it on only where `tailscale
# serve` is the sole thing that can reach the API's port: any process that
# can connect to 127.0.0.1:8000 could claim a login. On the VPS the other
# services are blocked from localhost (IPAddressDeny), and only root can
# log in; on a laptop full of other programs, leave it off.
SIGNIN = os.environ.get("MAVIS_TAILSCALE_SIGNIN") == "1"
OWNER_LOGINS = {keys.login_key(l) for l in
                os.environ.get("MAVIS_OWNER_LOGINS", "").split(",") if l.strip()}


def configured() -> bool:
    """True if anyone can get in: the env key, an owner login, or a keys.json record."""
    return bool(MAVIS_API_KEY) or (SIGNIN and bool(OWNER_LOGINS)) or keys.has_records()


def _owner_record() -> KeyRecord:
    # The env key keeps honouring MAVIS_RATE_LIMIT_PER_MINUTE, as before.
    limits = {**keys.DEFAULTS["owner"], "per_minute": rate_limit.MAX_REQUESTS_PER_WINDOW}
    return KeyRecord(OWNER_ENV_ID, "owner", **limits)


def login_of(ident: str) -> str | None:
    """The Tailscale login in an identity from guards.identity(), if any.
    identity() only reports one for a request relayed by local serve."""
    return keys.login_key(ident[3:]) or None if ident.startswith("ts:") else None


def lookup_login(login: str | None) -> KeyRecord | None:
    """Who this Tailscale login is: the owner, a linked guest, or None.
    Always None unless sign-in by login is switched on (SIGNIN)."""
    login = keys.login_key(login)
    if not SIGNIN or not login:
        return None
    if login in OWNER_LOGINS:
        rec = _owner_record()
    else:
        rec = keys.lookup_file_login(login)
    return dataclasses.replace(rec, via_login=login) if rec else None


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
        return _owner_record()
    return file_rec


def still_valid(rec: KeyRecord) -> bool:
    """Re-checked on every utterance, so a revoke ends an open call."""
    if rec.via_login:    # got in by login: that login must still map to this key
        current = lookup_login(rec.via_login)
        return current is not None and current.id == rec.id
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
    """The one door every caller goes through -- by key, or with no key by
    Tailscale login: (record, None), or (None, reason)
    where reason is "locked", "wrong" or "unconfigured". The caller must run
    note_failure(ident) when reason is "wrong" and a key was sent.

    A locked caller is turned away even with a right key -- except the
    owner's: the keys are far too long to guess, so letting the owner's key
    through teaches a guesser nothing, and a guest's typos sharing the
    owner's address can't lock the owner out of his own server.
    """
    locked = guards.LOCKOUT.locked(ident)
    # No key sent: a recognised Tailscale login is enough. A key, when sent,
    # always decides, so a wrong key is still counted as one.
    rec = lookup(candidate) if candidate else lookup_login(login_of(ident))
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

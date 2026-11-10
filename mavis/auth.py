import hmac
import os

from fastapi import Header, HTTPException

import keys
import rate_limit
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


def require_api_key(x_api_key: str = Header(default=None)) -> KeyRecord:
    rec = lookup(x_api_key)
    if rec is None:
        if not configured():
            raise HTTPException(500, "no keys configured on the server")
        raise HTTPException(401, "invalid or missing X-API-Key header")
    return rec

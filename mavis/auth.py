import hmac
import os

from fastapi import Header, HTTPException

MAVIS_API_KEY = os.environ.get("MAVIS_API_KEY")


def key_matches(candidate) -> bool:
    """True if `candidate` is the configured key. False when none is set."""
    if not MAVIS_API_KEY or not isinstance(candidate, str):
        return False
    return hmac.compare_digest(candidate.encode(), MAVIS_API_KEY.encode())


def require_api_key(x_api_key: str = Header(default=None)):
    # Assumes MAVIS_API_KEY is an ASCII secret (base64/hex/UUID-style, as
    # API keys conventionally are) -- for ASCII input, UTF-8 and Starlette's
    # latin-1 header-decoding produce identical bytes, so this comparison
    # is correct. A non-ASCII secret would need matching encodings on both
    # sides, which isn't a supported configuration here.
    if not MAVIS_API_KEY:
        raise HTTPException(500, "MAVIS_API_KEY not set on the server")
    if not key_matches(x_api_key):
        raise HTTPException(401, "invalid or missing X-API-Key header")
    return x_api_key

import os
import time
from collections import defaultdict

from fastapi import HTTPException

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = int(os.environ.get("MAVIS_RATE_LIMIT_PER_MINUTE", "20"))

_request_log = defaultdict(list)


def check_rate_limit(key, limit: int | None = None):
    """Fixed-window limiter: at most MAX_REQUESTS_PER_WINDOW calls per key
    per WINDOW_SECONDS. In-memory and per-process -- fine for a single-VPS
    FastAPI instance, not for multiple workers/instances.

    `key` is a key *id* (KeyRecord.id), never the key itself, and `limit`
    is that key's own per-minute allowance (default: the env setting).
    """
    now = time.monotonic()
    window_start = now - WINDOW_SECONDS

    recent = [t for t in _request_log[key] if t > window_start]
    if len(recent) >= (MAX_REQUESTS_PER_WINDOW if limit is None else limit):
        raise HTTPException(429, "rate limit exceeded, try again shortly")

    recent.append(now)
    _request_log[key] = recent

# push.py
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional

import httpx

import alerts
import jsonfile

# ---------------------------------------------------------------------------


class PushError(RuntimeError):
    """Raised when a push cannot be delivered."""


MAX_CALLS_PER_DAY = 3
TIMEOUT = 10
CT = ZoneInfo("America/Chicago")

# ---------------------------------------------------------------------------


def _log_path() -> Path:
    """
    Return the path of the push‑log file.

    The environment variable ``MAVIS_PUSH_FILE`` is consulted *at call time*.
    If the variable is not set, ``/var/lib/mavis/pushes.json`` is used.
    """
    env_path = os.getenv("MAVIS_PUSH_FILE", "/var/lib/mavis/pushes.json")
    return Path(env_path)


def _sent_utc(entry) -> Optional[datetime]:
    """The entry's send time in UTC, or None for a malformed entry."""
    try:
        sent = datetime.fromisoformat(entry["sent"])
    except (TypeError, KeyError, ValueError):
        return None
    return sent.replace(tzinfo=timezone.utc) if sent.tzinfo is None else sent.astimezone(timezone.utc)


def _load_log() -> Dict[str, Dict[str, Any]]:
    """The dedupe log; malformed entries are dropped, never fatal."""
    data = jsonfile.read(_log_path(), {})
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict) and _sent_utc(v)}


def _save_log(log: Dict[str, Dict[str, Any]], now: datetime) -> None:
    cutoff = now - timedelta(days=7)
    jsonfile.write_atomic(_log_path(), {k: v for k, v in log.items() if _sent_utc(v) >= cutoff})


# ---------------------------------------------------------------------------


def send(
    title: str,
    message: str,
    *,
    dedupe: str,
    call_url: Optional[str] = None,
    client: Optional[httpx.Client] = None,
    now: Optional[datetime] = None,
) -> bool:
    """
    Send a push notification via ntfy.

    Returns ``True`` if the notification was sent, ``False`` if sending is
    disabled (no topic) or the *dedupe* key was used in the last 7 days.

    Raises ``PushError`` on network/HTTP failures.
    """
    now = now or datetime.now(timezone.utc)

    topic = alerts._topic()
    if topic is None:
        return False

    # Held through the send: two jobs at once must not both send (or both
    # miss the other's record).
    with jsonfile.locked(_log_path()):
        return _send_locked(title, message, dedupe, call_url, client, now, topic)


def _send_locked(title, message, dedupe, call_url, client, now, topic) -> bool:
    log = _load_log()
    if dedupe in log:
        return False

    # Build headers – title must be ASCII with replacement for non‑ASCII.
    ascii_title = title.encode("ascii", "replace").decode("ascii")
    headers = {
        "Title": ascii_title,
        "Tags": "telephone_receiver" if call_url else "robot",
    }
    if call_url:
        headers["Priority"] = "5"
        headers["Click"] = call_url

    url = f"{alerts._server()}/{topic}"
    post_kwargs = {
        "url": url,
        "content": message.encode("utf-8"),
        "headers": headers,
        "timeout": TIMEOUT,
    }

    try:
        if client is not None:
            resp = client.post(**post_kwargs)
        else:
            resp = httpx.post(**post_kwargs)
    except Exception as exc:  # pragma: no cover – exercised via tests
        raise PushError("failed to deliver push notification") from exc

    if resp.status_code >= 300:
        raise PushError(f"push request returned HTTP {resp.status_code}")

    # Record the successful push.
    log[dedupe] = {"sent": now.astimezone(timezone.utc).isoformat(), "call": bool(call_url)}
    try:
        _save_log(log, now)
    except OSError as exc:
        # The phone already got it: raising would make the job retry and
        # send it again. Say so in the log instead.
        print(f"push: sent but not recorded ({type(exc).__name__})", file=sys.stderr)
    return True


def calls_today(now: Optional[datetime] = None) -> int:
    """
    Count how many *call* pushes have been sent today (America/Chicago day).
    """
    now = now or datetime.now(timezone.utc)
    ct_today = now.astimezone(CT).date()

    log = _load_log()
    count = 0
    for entry in log.values():
        if not entry.get("call"):
            continue
        if _sent_utc(entry).astimezone(CT).date() == ct_today:
            count += 1
    return count

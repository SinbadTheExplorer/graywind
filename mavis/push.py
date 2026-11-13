# push.py
import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Dict, Optional

import httpx

import alerts

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


def _load_log() -> Dict[str, Dict[str, Any]]:
    """
    Load the JSON log.  If the file cannot be read or is malformed, return an
    empty dict.
    """
    p = _log_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _sent_utc(entry: Dict[str, Any]) -> datetime:
    sent = datetime.fromisoformat(entry["sent"])
    return sent.replace(tzinfo=timezone.utc) if sent.tzinfo is None else sent.astimezone(timezone.utc)


def _prune_log(log: Dict[str, Dict[str, Any]], now: datetime) -> None:
    """
    Remove entries older than 7 days (based on the stored UTC ``sent`` time).
    The function mutates ``log`` in‑place.
    """
    cutoff = now - timedelta(days=7)
    to_del = [
        k
        for k, v in log.items()
        if _sent_utc(v) < cutoff
    ]
    for k in to_del:
        del log[k]


def _save_log(log: Dict[str, Dict[str, Any]], now: datetime) -> None:
    """
    Write *log* atomically to the file returned by ``_log_path``.
    Parent directories are created if necessary.
    """
    _prune_log(log, now)

    p = _log_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temporary file in the same directory.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=str(p.parent),
        prefix=".pushlog.",
    ) as tf:
        json.dump(log, tf, ensure_ascii=False, indent=2)
        temp_name = tf.name

    # Replace atomically.
    os.replace(temp_name, p)


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
    disabled (no topic) or the *dedupe* key was already used today.

    Raises ``PushError`` on network/HTTP failures.
    """
    now = now or datetime.now(timezone.utc)

    topic = alerts._topic()
    if topic is None:
        return False

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
    _save_log(log, now)
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

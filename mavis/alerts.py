"""Phone alerts for the owner, through ntfy (https://ntfy.sh).

Set MAVIS_NTFY_TOPIC in the server's env file to turn alerts on; unset,
nothing is sent. Anyone who knows the topic can read it, so an alert says
what happened but never who: no key ids, logins or addresses. Those stay in
audit.log on the server.

Each kind of alert goes out at most once per UTC day, and at most
MAX_PER_DAY alerts go out in a day in all, so an attacker rotating
addresses can't flood the phone. A day's alert is marked sent only after
ntfy accepts it, so an outage never silences it for the rest of the day.
"""
import os
import re
import sys
import threading

import httpx

import usage

TIMEOUT_SECONDS = 5
MAX_PER_DAY = 10
_TOPIC_OK = re.compile(r"[A-Za-z0-9_-]{1,64}")

_lock = threading.Lock()
_claimed: set = set()    # (day, dedupe) sent or being sent by this process
_warned: set = set()


def _topic() -> str | None:
    topic = os.environ.get("MAVIS_NTFY_TOPIC", "").strip()
    if not topic:
        return None
    if not _TOPIC_OK.fullmatch(topic):
        if topic not in _warned:
            _warned.add(topic)
            print("alerts: MAVIS_NTFY_TOPIC must be letters, digits, - or _; "
                  "alerts are off", file=sys.stderr)
        return None
    return topic


def _server() -> str:
    return os.environ.get("MAVIS_NTFY_SERVER", "https://ntfy.sh").rstrip("/")


def _deliver(topic: str, title: str, message: str, key: tuple) -> None:
    """Runs in a background thread. Never raises."""
    day, dedupe = key
    sent = False
    try:
        if usage.alert_sent_today(dedupe) or usage.alerts_sent_today() >= MAX_PER_DAY:
            sent = True    # nothing to do; keep the claim so we stop asking
            return
        resp = httpx.post(f"{_server()}/{topic}", content=message.encode("utf-8"),
                          headers={"Title": title.encode("ascii", "replace").decode(),
                                   "Tags": "warning"},
                          timeout=TIMEOUT_SECONDS)
        if resp.status_code >= 300:
            print(f"alerts: ntfy answered {resp.status_code}", file=sys.stderr)
            return
        usage.record_alert(dedupe)
        sent = True
    except Exception as exc:  # noqa: BLE001 -- an alert must never break anything
        print(f"alerts: not sent: {type(exc).__name__}", file=sys.stderr)
    finally:
        if not sent:
            with _lock:
                _claimed.discard(key)    # let the next event try again


def _spawn(target, *args) -> None:
    threading.Thread(target=target, args=args, daemon=True).start()


def notify(title: str, message: str, dedupe: str) -> None:
    """Send an alert at most once per `dedupe` key per UTC day.

    Returns at once (the send happens in a thread), so async code may call
    it directly. Repeats of an alert already sent cost only a set lookup.
    A no-op without a valid topic. Never raises.
    """
    try:
        topic = _topic()
        if not topic:
            return
        key = (usage._today(), str(dedupe))
        with _lock:
            if key in _claimed:
                return
            _claimed.add(key)
            if len(_claimed) > 1000:    # yesterday's claims are dead weight
                _claimed.intersection_update({k for k in _claimed if k[0] == key[0]})
        _spawn(_deliver, topic, title, message, key)
    except Exception as exc:  # noqa: BLE001
        print(f"alerts: not sent: {type(exc).__name__}", file=sys.stderr)


def cap_alert(kind: str, which: str, key_id: str | None = None) -> None:
    """Tell the owner a daily cap was hit (once a day per cap, per key).

    The key id only separates the alerts; it is never in the message.
    """
    what = "answers" if kind == "llm" else "listening time"
    whose = "Everyone's" if which == "global" else "A key's"
    dedupe = f"cap:{which}:{kind}" + (f":{key_id}" if which == "key" else "")
    notify("Johnny cap hit", f"{whose} daily {what} cap is used up.", dedupe=dedupe)

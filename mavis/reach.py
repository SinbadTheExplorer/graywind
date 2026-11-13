# reach.py
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

import jsonfile
import push
import events

CT = ZoneInfo('America/Chicago')

DEFAULT_SCHEDULE = {
    'busy': [
        {'days': ['Mon', 'Wed'], 'start': '08:40', 'end': '12:00'},
        {'days': ['Mon', 'Wed'], 'start': '14:30', 'end': '16:00'},
    ],
    'quiet': {'start': '22:00', 'end': '07:00'},
}


def schedule_path() -> str:
    """Path to the schedule JSON file (read at call time)."""
    return os.getenv('MAVIS_SCHEDULE_FILE', '/var/lib/mavis/schedule.json')


def load_schedule() -> dict:
    """Load the schedule file, falling back to DEFAULT_SCHEDULE on any problem."""
    path = schedule_path()
    try:
        data = jsonfile.read(path, default=None)
        if (
            isinstance(data, dict)
            and isinstance(data.get('busy'), list)
            and isinstance(data.get('quiet'), dict)
        ):
            return data
    except Exception:          # pragma: no cover – defensive
        pass
    return DEFAULT_SCHEDULE


def public_url() -> str:
    """Base URL for the public Johnny endpoint."""
    return os.getenv('MAVIS_PUBLIC_URL', 'https://johnny.tail4beff0.ts.net').rstrip('/')


def _parse_hm(s: str) -> time:
    """Parse an HH:MM string into a time object."""
    h, m = map(int, s.split(':'))
    return time(hour=h, minute=m)


def is_busy(now: datetime, sched: dict | None = None) -> bool:
    """True if `now` (any tz) falls inside a busy window."""
    now_ct = now.astimezone(CT)
    day_name = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[now_ct.weekday()]   # not locale-dependent
    t = now_ct.time()
    sched = sched or load_schedule()
    for entry in sched.get('busy', []):
        if day_name not in entry.get('days', []):
            continue
        try:
            start, end = _parse_hm(entry['start']), _parse_hm(entry['end'])
        except (KeyError, TypeError, ValueError, AttributeError):
            continue    # a typo in schedule.json must never stop an alert
        if start <= t < end:
            return True
    return False


def is_quiet(now: datetime, sched: dict | None = None) -> bool:
    """True if `now` falls inside the quiet window (may wrap midnight)."""
    now_ct = now.astimezone(CT)
    t = now_ct.time()
    sched = sched or load_schedule()
    quiet = sched.get('quiet', {})
    try:
        start = _parse_hm(quiet.get('start', '22:00'))
        end = _parse_hm(quiet.get('end', '07:00'))
    except (TypeError, ValueError, AttributeError):
        start, end = time(22, 0), time(7, 0)

    if start <= end:                     # simple case, e.g. 02:00‑05:00
        return start <= t < end
    # wrapped case, e.g. 22:00‑07:00
    return t >= start or t < end


def deliver(event: dict, now: datetime | None = None, *, send=None, calls_today=None,
            decide_at: datetime | None = None) -> str:
    """
    Send the appropriate notification for *event* and record the delivery method.

    Returns the delivery method used: 'call' or 'text'.
    """
    now = now or datetime.now(tz=CT)
    send = send or push.send          # looked up at call time, so tests can patch push
    calls_today = calls_today or push.calls_today
    sched = load_schedule()
    urgent = event.get('urgency') == 'urgent'
    # decide_at: a test event asks "what would happen at 9:00 on Wednesday"
    # without writing fake times into the real logs.
    when = decide_at or now
    already_busy = is_busy(when, sched)
    already_quiet = is_quiet(when, sched)

    # decide whether we can place a call
    if urgent and not already_busy and not already_quiet and calls_today(now) < push.MAX_CALLS_PER_DAY:
        # phone call
        title = 'Johnny is calling'
        body = f"{event['text']} Tap to answer."
        dedupe = f"event:{event['id']}"
        call_url = f"{public_url()}/johnny?event={event['id']}"
        send(title, body, dedupe=dedupe, call_url=call_url, now=now)
        delivery = 'call'
    else:
        # plain text notification (also used for non‑urgent events)
        title = 'Johnny'
        # lower‑case the first character of the text (preserve rest)
        txt = event['text']
        body = f"Hey choom, {txt[0].lower()}{txt[1:]}" if txt else "Hey choom"
        dedupe = f"event:{event['id']}"
        send(title, body, dedupe=dedupe, now=now)
        delivery = 'text'

    # record the delivery method
    events.mark([event['id']], delivery)
    return delivery

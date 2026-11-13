# events.py
import os
import secrets
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import jsonfile
import push

CT = ZoneInfo('America/Chicago')


def _events_path() -> Path:
    """Path to the events JSON file (read at call time)."""
    return Path(os.getenv('MAVIS_EVENTS_FILE', '/var/lib/mavis/events.json'))


def _load_events(path: Path) -> dict:
    """Load the JSON file, tolerating malformed content."""
    try:
        data = jsonfile.read(path, default={'events': []})
        if not isinstance(data, dict) or 'events' not in data or not isinstance(data['events'], list):
            return {'events': []}
        return data
    except Exception:          # pragma: no cover – defensive
        return {'events': []}


def events_path() -> Path:
    """Public accessor used by the tests."""
    return _events_path()


def _created(ev) -> datetime | None:
    try:
        created = datetime.fromisoformat(ev['created'])
    except (TypeError, KeyError, ValueError):
        return None
    return created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created


def add(kind: str, urgency: str, text: str, *, key: str, now: datetime | None = None) -> dict | None:
    """Append a new event unless an event with the same key already exists for the same CT date."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(CT).date()
    path = _events_path()
    with jsonfile.locked(path):
        data = _load_events(path)

        # duplicate‑key check (same CT calendar day)
        for ev in data['events']:
            if ev.get('key') == key:
                try:
                    created = datetime.fromisoformat(ev['created']).astimezone(CT)
                except Exception:      # pragma: no cover – malformed entry
                    continue
                if created.date() == today:
                    return None

        event = {
            'id': secrets.token_hex(6),
            'kind': kind,
            'urgency': urgency,
            'text': text,
            'key': key,
            'created': now.astimezone(timezone.utc).isoformat(),
            'delivery': None,
        }
        data['events'].append(event)

        # keep only the last 14 days (UTC comparison)
        cutoff = now - timedelta(days=14)
        data['events'] = [ev for ev in data['events'] if _created(ev) and _created(ev) >= cutoff]

        jsonfile.write_atomic(path, data)
    return event


def get(event_id: str) -> dict | None:
    """Return the event with the given id, or None."""
    path = _events_path()
    data = _load_events(path)
    for ev in data['events']:
        if ev.get('id') == event_id:
            return ev
    return None


def pending_info() -> list[dict]:
    """All info‑urgency events that have not yet been delivered, oldest first."""
    path = _events_path()
    data = _load_events(path)
    pending = [
        ev for ev in data['events']
        if ev.get('urgency') == 'info' and ev.get('delivery') is None
    ]
    pending.sort(key=lambda e: e['created'])
    return pending


def mark(ids: list[str], delivery: str) -> None:
    """Record how the given events were delivered."""
    path = _events_path()
    with jsonfile.locked(path):
        data = _load_events(path)
        for ev in data['events']:
            if ev.get('id') in ids:
                ev['delivery'] = delivery
        jsonfile.write_atomic(path, data)

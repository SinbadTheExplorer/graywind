# tests/test_reach.py
import os
import json
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

import reach
import events
import push


CT = ZoneInfo('America/Chicago')


@pytest.fixture(autouse=True)
def reset_env(monkeypatch, tmp_path):
    # default schedule file location
    monkeypatch.setenv('MAVIS_SCHEDULE_FILE', str(tmp_path / 'schedule.json'))
    monkeypatch.setenv('MAVIS_PUBLIC_URL', 'https://example.com')
    # ensure a fresh events file for the reach module (it uses events.mark)
    monkeypatch.setenv('MAVIS_EVENTS_FILE', str(tmp_path / 'events.json'))
    yield


def fake_send_capture():
    """Factory returning a callable that records its calls."""
    calls = []

    def send(title, body, *, dedupe, call_url=None, now=None):
        calls.append({
            'title': title,
            'body': body,
            'dedupe': dedupe,
            'call_url': call_url,
            'now': now,
        })
        return True

    send.calls = calls
    return send


def fake_calls_today_factory(limit):
    """Factory returning a callable that pretends a certain number of calls already made."""
    def calls_today(_now=None):
        return limit
    return calls_today


def test_wednesday_1500_is_busy_and_tuesday_1500_is_not():
    wed = datetime(2023, 4, 5, 15, 0, tzinfo=CT)   # Wed
    tue = datetime(2023, 4, 4, 15, 0, tzinfo=CT)   # Tue
    sched = reach.load_schedule()
    assert reach.is_busy(wed, sched) is True
    assert reach.is_busy(tue, sched) is False


def test_quiet_hours_wrap_midnight():
    # 23:30 should be quiet, 06:30 should be quiet, 12:00 not quiet
    night = datetime(2023, 4, 5, 23, 30, tzinfo=CT)
    early = datetime(2023, 4, 6, 6, 30, tzinfo=CT)
    midday = datetime(2023, 4, 5, 12, 0, tzinfo=CT)
    assert reach.is_quiet(night) is True
    assert reach.is_quiet(early) is True
    assert reach.is_quiet(midday) is False


def test_busy_window_texts(monkeypatch):
    send = fake_send_capture()
    monkeypatch.setattr(reach, 'push', push)  # keep original push module for constants
    # make calls_today return 0 so call would be possible if not busy
    monkeypatch.setattr(reach, 'push', push)
    ev = {
        'id': '123',
        'urgency': 'urgent',
        'text': 'Price surge!',
    }
    now = datetime(2023, 4, 5, 15, 0, tzinfo=CT)   # Wed busy window
    delivery = reach.deliver(ev, now, send=send, calls_today=lambda *_: 0)
    assert delivery == 'text'
    assert send.calls[0]['title'] == 'Johnny'
    assert 'Hey choom' in send.calls[0]['body']
    # ensure the event got marked as text
    assert MARKS[-1] == (['123'], 'text')


def test_quiet_hours_text(monkeypatch):
    send = fake_send_capture()
    ev = {
        'id': 'q1',
        'urgency': 'urgent',
        'text': 'Quiet test',
    }
    now = datetime(2023, 4, 5, 23, 30, tzinfo=CT)   # quiet time
    delivery = reach.deliver(ev, now, send=send, calls_today=lambda *_: 0)
    assert delivery == 'text'
    assert send.calls[0]['title'] == 'Johnny'
    assert MARKS[-1] == (['q1'], 'text')


def test_free_time_calls_with_event_url(monkeypatch):
    send = fake_send_capture()
    ev = {
        'id': 'call1',
        'urgency': 'urgent',
        'text': 'Call me now',
    }
    now = datetime(2023, 4, 4, 10, 0, tzinfo=CT)   # Tue, not busy, not quiet
    delivery = reach.deliver(ev, now, send=send, calls_today=lambda *_: 0)
    assert delivery == 'call'
    assert send.calls[0]['title'] == 'Johnny is calling'
    assert 'Tap to answer.' in send.calls[0]['body']
    assert send.calls[0]['call_url'] == 'https://example.com/johnny?event=call1'
    assert MARKS[-1] == (['call1'], 'call')


def test_fourth_call_of_the_day_becomes_text(monkeypatch):
    send = fake_send_capture()
    ev = {
        'id': 'call2',
        'urgency': 'urgent',
        'text': 'Too many calls',
    }
    now = datetime(2023, 4, 4, 10, 0, tzinfo=CT)
    # simulate that MAX_CALLS_PER_DAY have already been used
    monkeypatch.setattr(push, 'MAX_CALLS_PER_DAY', 3)
    delivery = reach.deliver(ev, now, send=send, calls_today=lambda *_: 3)
    assert delivery == 'text'
    assert send.calls[0]['title'] == 'Johnny'
    assert MARKS[-1] == (['call2'], 'text')


def test_info_event_is_texted_if_delivered_directly(monkeypatch):
    send = fake_send_capture()
    ev = {
        'id': 'info1',
        'urgency': 'info',
        'text': 'Just FYI',
    }
    now = datetime(2023, 4, 4, 10, 0, tzinfo=CT)
    delivery = reach.deliver(ev, now, send=send, calls_today=lambda *_: 0)
    assert delivery == 'text'
    assert send.calls[0]['title'] == 'Johnny'
    assert MARKS[-1] == (['info1'], 'text')


def test_schedule_file_overrides_default(monkeypatch, tmp_path):
    # write a custom schedule with a busy window on Tuesdays 09‑10
    custom = {
        'busy': [{'days': ['Tue'], 'start': '09:00', 'end': '10:00'}],
        'quiet': {'start': '23:00', 'end': '06:00'},
    }
    path = tmp_path / 'schedule.json'
    path.write_text(json.dumps(custom))
    monkeypatch.setenv('MAVIS_SCHEDULE_FILE', str(path))
    sched = reach.load_schedule()
    assert sched == custom
    # now verify is_busy for Tuesday 09:30
    t = datetime(2023, 4, 4, 9, 30, tzinfo=CT)
    assert reach.is_busy(t, sched) is True
    # and not busy at other times
    assert reach.is_busy(datetime(2023, 4, 4, 11, 0, tzinfo=CT), sched) is False


def test_bad_schedule_file_uses_default(monkeypatch, tmp_path):
    # write malformed JSON
    path = tmp_path / 'schedule.json'
    path.write_text('not json')
    monkeypatch.setenv('MAVIS_SCHEDULE_FILE', str(path))
    sched = reach.load_schedule()
    assert sched == reach.DEFAULT_SCHEDULE
    # also test missing keys
    path.write_text(json.dumps({'busy': []}))
    sched2 = reach.load_schedule()
    assert sched2 == reach.DEFAULT_SCHEDULE


MARKS = []


@pytest.fixture(autouse=True)
def _capture_marks(monkeypatch):
    MARKS.clear()
    monkeypatch.setattr(reach.events, "mark", lambda ids, delivery: MARKS.append((list(ids), delivery)))


def test_a_typo_in_the_schedule_never_stops_an_alert(monkeypatch, tmp_path):
    import json, os
    from pathlib import Path
    Path(os.environ["MAVIS_SCHEDULE_FILE"]).write_text(json.dumps(
        {"busy": [{"days": ["Wed"], "start": "8h40", "end": "12:00"}], "quiet": {"start": "late"}}))
    sched = reach.load_schedule()
    now = datetime(2026, 11, 11, 9, 0, tzinfo=CT)
    assert reach.is_busy(now, sched) is False and reach.is_quiet(now, sched) is False

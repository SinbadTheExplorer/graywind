# tests/test_events.py
import os
import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import pytest

import events


CT = ZoneInfo('America/Chicago')


@pytest.fixture(autouse=True)
def reset_env(monkeypatch, tmp_path):
    # ensure a clean env for each test
    monkeypatch.setenv('MAVIS_EVENTS_FILE', str(tmp_path / 'events.json'))
    yield


def test_add_and_get():
    ev = events.add('trade', 'urgent', 'Buy BTC', key='alpha')
    assert ev is not None
    fetched = events.get(ev['id'])
    assert fetched == ev
    assert fetched['kind'] == 'trade'
    assert fetched['urgency'] == 'urgent'
    assert fetched['key'] == 'alpha'


def test_same_key_same_day_is_ignored():
    now = datetime(2023, 4, 1, 12, 0, tzinfo=CT)
    ev1 = events.add('trade', 'info', 'first', key='dup', now=now)
    assert ev1 is not None
    ev2 = events.add('trade', 'info', 'second', key='dup', now=now)
    assert ev2 is None
    # only one event stored
    pending = events.pending_info()
    assert len(pending) == 1
    assert pending[0]['key'] == 'dup'


def test_same_key_next_day_is_new():
    day1 = datetime(2023, 4, 1, 9, 0, tzinfo=CT)
    day2 = day1 + timedelta(days=1)
    ev1 = events.add('trade', 'info', 'day1', key='same', now=day1)
    ev2 = events.add('trade', 'info', 'day2', key='same', now=day2)
    assert ev1 is not None
    assert ev2 is not None
    assert ev1['id'] != ev2['id']


def test_pending_info_and_mark():
    ev1 = events.add('trade', 'info', 'msg1', key='k1')
    ev2 = events.add('trade', 'info', 'msg2', key='k2')
    pending = events.pending_info()
    # order should be oldest first
    assert [e['id'] for e in pending] == [ev1['id'], ev2['id']]
    events.mark([ev1['id']], 'text')
    pending2 = events.pending_info()
    assert len(pending2) == 1
    assert pending2[0]['id'] == ev2['id']


def test_malformed_file_is_empty(monkeypatch, tmp_path):
    # write garbage to the file
    path = tmp_path / 'events.json'
    path.write_text('not json')
    # ensure the module reads it as empty
    assert events.get('whatever') is None
    assert events.pending_info() == []


def test_cleanup_old_events(monkeypatch, tmp_path):
    # create an old event (>14 days) and a recent one
    old = datetime.now(timezone.utc) - timedelta(days=20)
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    data = {
        'events': [
            {
                'id': 'oldid',
                'kind': 'trade',
                'urgency': 'info',
                'text': 'old',
                'key': 'old',
                'created': old.isoformat(),
                'delivery': None,
            },
            {
                'id': 'newid',
                'kind': 'trade',
                'urgency': 'info',
                'text': 'new',
                'key': 'new',
                'created': recent.isoformat(),
                'delivery': None,
            },
        ]
    }
    path = tmp_path / 'events.json'
    path.write_text(json.dumps(data))
    # Adding a fresh event forces a rewrite
    events.add('trade', 'info', 'fresh', key='fresh')
    loaded = events.pending_info()
    ids = [e['id'] for e in loaded]
    assert 'oldid' not in ids
    assert 'newid' in ids
    assert 'fresh' in [e['text'] for e in loaded]

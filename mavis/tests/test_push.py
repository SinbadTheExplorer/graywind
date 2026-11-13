# tests/test_push.py
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List

import httpx
import pytest

import push
import alerts


# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code


class FakeClient:
    """
    Very small httpx‑compatible client that records calls.
    """

    def __init__(self, response: httpx.Response | FakeResponse):
        self.response = response
        self.posts: List[dict] = []

    def post(self, **kwargs):
        self.posts.append(kwargs)
        return self.response


# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Make sure each test starts with a clean environment."""
    # Ensure the push‑log points to a temporary location.
    monkeypatch.setenv("MAVIS_PUSH_FILE", str(tmp_path / "pushes.json"))
    # Remove any topic – individual tests will set it when needed.
    monkeypatch.delenv("MAVIS_NTFY_TOPIC", raising=False)
    yield
    # Clean up the temporary file if it exists.
    push_path = Path(os.getenv("MAVIS_PUSH_FILE"))
    if push_path.exists():
        push_path.unlink()


# ---------------------------------------------------------------------------


def test_sends_once_per_dedupe(monkeypatch):
    monkeypatch.setenv("MAVIS_NTFY_TOPIC", "testtopic")
    client = FakeClient(FakeResponse(200))

    # first call – should succeed
    ok = push.send(
        title="Hello",
        message="World",
        dedupe="abc123",
        client=client,
    )
    assert ok is True
    assert len(client.posts) == 1

    # second call with same dedupe – should be ignored
    ok2 = push.send(
        title="Hello again",
        message="World again",
        dedupe="abc123",
        client=client,
    )
    assert ok2 is False
    assert len(client.posts) == 1  # no extra POST


def test_failed_send_raises_and_is_not_recorded(monkeypatch):
    monkeypatch.setenv("MAVIS_NTFY_TOPIC", "testtopic")
    # 1) HTTP 500 response
    client_500 = FakeClient(FakeResponse(500))
    with pytest.raises(push.PushError):
        push.send(
            title="Fail",
            message="Boom",
            dedupe="fail1",
            client=client_500,
        )
    # log must be empty
    log_path = Path(os.getenv("MAVIS_PUSH_FILE"))
    assert not log_path.exists()

    # 2) Client raises an exception
    class RaisingClient:
        def post(self, **kwargs):
            raise RuntimeError("network down")

    with pytest.raises(push.PushError):
        push.send(
            title="Fail",
            message="Boom",
            dedupe="fail2",
            client=RaisingClient(),
        )
    # still empty
    assert not log_path.exists()


def test_no_topic_sends_nothing(monkeypatch):
    # Ensure no topic is set
    client = FakeClient(FakeResponse(200))
    result = push.send(
        title="NoTopic",
        message="Nothing",
        dedupe="no-topic",
        client=client,
    )
    assert result is False
    assert len(client.posts) == 0


def test_call_push_sets_priority_and_click(monkeypatch):
    monkeypatch.setenv("MAVIS_NTFY_TOPIC", "calltopic")
    client = FakeClient(FakeResponse(200))
    call_url = "https://example.com/call"

    ok = push.send(
        title="Call me",
        message="Ring ring",
        dedupe="call1",
        call_url=call_url,
        client=client,
    )
    assert ok is True
    assert len(client.posts) == 1
    hdrs = client.posts[0]["headers"]
    assert hdrs["Tags"] == "telephone_receiver"
    assert hdrs["Priority"] == "5"
    assert hdrs["Click"] == call_url


def test_title_is_ascii_safe(monkeypatch):
    monkeypatch.setenv("MAVIS_NTFY_TOPIC", "asciitest")
    client = FakeClient(FakeResponse(200))
    title = "Johnny’s brief"  # curly apostrophe (U+2019)
    push.send(
        title=title,
        message="content",
        dedupe="ascii1",
        client=client,
    )
    sent_title = client.posts[0]["headers"]["Title"]
    assert sent_title == "Johnny?s brief"  # non‑ASCII replaced with ?


def test_calls_today_counts_ct_day_only(monkeypatch, tmp_path):
    # Prepare a log entry that is a call sent at 2026‑11‑13T05:00Z
    sent_utc = datetime(2026, 11, 13, 5, 0, tzinfo=timezone.utc)
    log = {
        "oldcall": {
            "sent": sent_utc.isoformat(),
            "call": True,
        }
    }
    log_path = Path(os.getenv("MAVIS_PUSH_FILE"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log), encoding="utf-8")

    # Now ask for counts on a UTC time that maps to 2026‑11‑13 CT.
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    # In CT this is 2026‑11‑13 06:00‑06 = 2026‑11‑13 06:00? actually CT = UTC‑6, so 06:00 CT,
    # date = 2026‑11‑13, different from the log entry which is 2026‑11‑12 CT.
    assert push.calls_today(now=now) == 0

    # Add another entry that falls on the same CT day.
    same_day_utc = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)  # 06:00 CT
    log["todaycall"] = {"sent": same_day_utc.isoformat(), "call": True}
    log_path.write_text(json.dumps(log), encoding="utf-8")
    assert push.calls_today(now=now) == 1


def test_old_entries_are_pruned(monkeypatch, tmp_path):
    monkeypatch.setenv("MAVIS_NTFY_TOPIC", "prunetest")
    client = FakeClient(FakeResponse(200))

    now = datetime.now(timezone.utc)

    old_time = now - timedelta(days=8)
    recent_time = now - timedelta(days=1)

    # Create a pre‑existing log with one old and one recent entry.
    prelog = {
        "old": {"sent": old_time.isoformat(), "call": False},
        "recent": {"sent": recent_time.isoformat(), "call": False},
    }
    push_path = Path(os.getenv("MAVIS_PUSH_FILE"))
    push_path.parent.mkdir(parents=True, exist_ok=True)
    push_path.write_text(json.dumps(prelog), encoding="utf-8")

    # Send a new push – this triggers a write that should prune the 8‑day‑old entry.
    push.send(
        title="New",
        message="msg",
        dedupe="newone",
        client=client,
        now=now,
    )

    final_log = json.loads(push_path.read_text(encoding="utf-8"))
    # Old entry must be gone, recent and new one must be present.
    assert "old" not in final_log
    assert "recent" in final_log
    assert "newone" in final_log

"""ntfy alerts: once a day per kind, never in the way, never naming anyone."""
import httpx
import pytest

import alerts


class _Resp:
    status_code = 200


@pytest.fixture(autouse=True)
def _fresh_claims():
    alerts._claimed.clear()
    yield
    alerts._claimed.clear()


@pytest.fixture
def posts(monkeypatch):
    sent = []

    def fake_post(url, content=None, headers=None, timeout=None):
        sent.append({"url": url, "body": content.decode(), "headers": headers,
                     "timeout": timeout})
        return _Resp()

    monkeypatch.setattr(alerts.httpx, "post", fake_post)
    monkeypatch.setattr(alerts, "_spawn", lambda target, *args: target(*args))  # inline
    monkeypatch.setenv("MAVIS_NTFY_TOPIC", "test-topic")
    return sent


def test_notify_posts_once_per_day_per_dedupe(posts):
    alerts.notify("Johnny lockout", "msg", dedupe="lockout:ip:1")
    alerts.notify("Johnny lockout", "msg", dedupe="lockout:ip:1")
    alerts.notify("Johnny lockout", "msg", dedupe="lockout:ip:2")
    assert len(posts) == 2
    assert posts[0]["url"] == "https://ntfy.sh/test-topic"
    assert posts[0]["headers"]["Title"] == "Johnny lockout"
    assert posts[0]["timeout"] == 5


def test_dedupe_resets_on_a_new_day(posts, monkeypatch):
    import usage
    alerts.notify("t", "m", dedupe="cap:key:llm")
    monkeypatch.setattr(usage, "_today", lambda: "2099-01-01")
    alerts.notify("t", "m", dedupe="cap:key:llm")
    assert len(posts) == 2


def test_notify_noop_without_topic(posts, monkeypatch):
    monkeypatch.delenv("MAVIS_NTFY_TOPIC")
    alerts.notify("t", "m", dedupe="x")
    assert posts == []


def test_notify_swallows_network_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(alerts.httpx, "post", boom)
    monkeypatch.setattr(alerts, "_spawn", lambda target, *args: target(*args))
    monkeypatch.setenv("MAVIS_NTFY_TOPIC", "test-topic")
    alerts.notify("t", "m", dedupe="y")    # must not raise


def test_notify_swallows_broken_usage_db(posts, monkeypatch):
    import usage
    def broken(_):
        raise OSError("disk full")
    monkeypatch.setattr(usage, "alert_sent_today", broken)
    alerts.notify("t", "m", dedupe="z")
    assert posts == []


def test_notify_returns_without_waiting_for_the_network(monkeypatch):
    started = []
    monkeypatch.setenv("MAVIS_NTFY_TOPIC", "test-topic")
    monkeypatch.setattr(alerts, "_spawn", lambda target, *args: started.append(target))
    alerts.notify("t", "m", dedupe="w")
    assert started == [alerts._deliver]


def test_cap_alert_says_what_not_who(posts):
    alerts.cap_alert("llm", "global")
    alerts.cap_alert("stt_seconds", "key", "owner-env")
    alerts.cap_alert("stt_seconds", "key", "friend")
    bodies = [p["body"] for p in posts]
    assert bodies == ["Everyone's daily answers cap is used up.",
                      "A key's daily listening time cap is used up.",
                      "A key's daily listening time cap is used up."]
    assert not any("friend" in p["body"] or "friend" in p["url"] for p in posts)


def test_cap_hit_on_ask_sends_an_alert(monkeypatch):
    from fastapi.testclient import TestClient
    import app as app_module
    import auth
    import usage
    sent = []
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    monkeypatch.setattr(alerts, "notify", lambda t, m, dedupe: sent.append(dedupe))
    monkeypatch.setattr(usage, "GLOBAL_DAILY_LLM", 0)
    resp = TestClient(app_module.app).post("/ask", json={"query": "hi"},
                                           headers={"X-API-Key": "secret123"})
    assert resp.status_code == 429
    assert sent == ["cap:global:llm"]


def test_failed_send_is_retried_by_the_next_event(posts, monkeypatch):
    real = alerts.httpx.post
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("ntfy down")
        return real(*a, **k)
    monkeypatch.setattr(alerts.httpx, "post", flaky)
    alerts.notify("t", "m", dedupe="cap:global:llm")
    alerts.notify("t", "m", dedupe="cap:global:llm")
    assert len(posts) == 1    # the second event got through


def test_daily_ceiling_stops_a_flood(posts):
    for i in range(50):
        alerts.notify("Johnny lockout", "m", dedupe=f"lockout:ip:{i}")
    assert len(posts) == alerts.MAX_PER_DAY


def test_repeats_do_not_touch_the_db(posts, monkeypatch):
    import usage
    alerts.notify("t", "m", dedupe="once")
    monkeypatch.setattr(usage, "alert_sent_today",
                        lambda d: (_ for _ in ()).throw(AssertionError("db hit")))
    alerts.notify("t", "m", dedupe="once")


@pytest.mark.parametrize("bad", ["a/b", "x?y=1", "https://ntfy.sh/t", "a b"])
def test_bad_topic_turns_alerts_off(posts, monkeypatch, bad):
    monkeypatch.setenv("MAVIS_NTFY_TOPIC", bad)
    alerts.notify("t", "m", dedupe="q")
    assert posts == []


def test_old_alert_rows_are_pruned(posts, monkeypatch):
    import sqlite3, usage
    monkeypatch.setattr(usage, "_today", lambda: "2000-01-01")
    alerts.notify("t", "m", dedupe="old")
    monkeypatch.setattr(usage, "_today", lambda: "2000-01-02")
    alerts.notify("t", "m", dedupe="new")
    rows = sqlite3.connect(usage.db_path()).execute("SELECT day FROM alerts").fetchall()
    assert rows == [("2000-01-02",)]


def test_cap_hit_still_429_when_audit_is_broken(monkeypatch):
    from fastapi.testclient import TestClient
    import app as app_module
    import auth
    import usage
    sent = []
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    monkeypatch.setattr(alerts, "notify", lambda t, m, dedupe: sent.append(dedupe))
    monkeypatch.setattr(usage, "GLOBAL_DAILY_LLM", 0)
    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(usage, "audit", broken)
    resp = TestClient(app_module.app).post("/ask", json={"query": "hi"},
                                           headers={"X-API-Key": "secret123"})
    assert resp.status_code == 429 and sent == ["cap:global:llm"]

"""The timer entry points: dispatch, exit codes, the news failure page."""
from datetime import datetime
from zoneinfo import ZoneInfo

import jobs

CT = ZoneInfo("America/Chicago")


def test_cli_dispatches_each_subcommand(monkeypatch):
    seen = []
    monkeypatch.setattr(jobs, "news_job", lambda: seen.append("news"))
    monkeypatch.setattr(jobs.watch, "run", lambda: seen.append("watch"))
    monkeypatch.setattr(jobs, "brief_job", lambda kind: seen.append(f"brief:{kind}") or "ok")
    monkeypatch.setattr(jobs, "test_event", lambda at, text: seen.append("test") or "text")
    for argv in (["news"], ["watch"], ["brief", "close"], ["brief", "night"], ["test-event"]):
        assert jobs.main(argv) == 0
    assert seen == ["news", "watch", "brief:close", "brief:night", "test"]


def test_a_failing_job_exits_1(monkeypatch):
    def boom():
        raise RuntimeError("no")
    monkeypatch.setattr(jobs.watch, "run", boom)
    assert jobs.main(["watch"]) == 1


def test_news_failure_counter_pages_at_two(monkeypatch):
    pages = []
    monkeypatch.setattr(jobs, "_symbols", lambda now: [])

    def down(symbols, now=None):
        raise jobs.newsdesk.NewsError("all sources failed")

    monkeypatch.setattr(jobs.newsdesk, "run", down)
    monkeypatch.setattr(jobs.push, "send", lambda *a, **k: pages.append(k["dedupe"]) or True)
    now = datetime(2026, 11, 12, 10, 0, tzinfo=CT)
    for _ in range(3):
        try:
            jobs.news_job(now)
        except jobs.newsdesk.NewsError:
            pass
    assert pages == ["newsfail:2026-11-12"]


def test_a_good_news_run_resets_the_counter(monkeypatch):
    monkeypatch.setattr(jobs, "_symbols", lambda now: [])
    failures = jobs.newsdesk.news_path().with_name("news.failures")
    jobs.jsonfile.write_atomic(failures, 1)
    monkeypatch.setattr(jobs.newsdesk, "run", lambda symbols, now=None: {})
    jobs.news_job(datetime(2026, 11, 12, 10, 0, tzinfo=CT))
    assert not failures.exists()


def test_brief_marks_folded_events_delivered(monkeypatch):
    ev = jobs.events.add("closed", "info", "AAPL position closed in the 100k account.", key="k")
    seen = {}
    monkeypatch.setattr(jobs.briefing, "run",
                        lambda kind, now=None, info_events=None: seen.setdefault("info", info_events) and "ok")
    jobs.brief_job("night")
    assert [e["id"] for e in seen["info"]] == [ev["id"]]
    assert jobs.events.pending_info() == []


def test_test_event_during_class_is_a_text(monkeypatch):
    sent = []
    monkeypatch.setattr(jobs.reach.push, "send", lambda *a, **k: sent.append(k) or True)
    monkeypatch.setattr(jobs.reach.push, "calls_today", lambda now=None: 0)
    wed_class = datetime(2026, 11, 11, 9, 0, tzinfo=CT)
    tue_free = datetime(2026, 11, 10, 17, 0, tzinfo=CT)
    assert jobs.test_event(wed_class) == "text"
    assert jobs.test_event(tue_free) == "call"
    assert "call_url" not in sent[0] or sent[0]["call_url"] is None
    assert "/johnny?event=" in sent[1]["call_url"]


def test_systemd_instance_name_for_briefs(monkeypatch):
    seen = []
    monkeypatch.setattr(jobs, "brief_job", lambda kind: seen.append(kind) or "ok")
    assert jobs.main(["brief-night"]) == 0 and seen == ["night"]

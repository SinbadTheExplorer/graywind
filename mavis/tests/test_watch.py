"""Johnny's watcher: what counts as urgent, and that nothing is lost or repeated."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import events
import watch

CT = ZoneInfo("America/Chicago")
THU_10AM = datetime(2026, 11, 12, 10, 0, tzinfo=CT)


def snap(*, equity=99584.21, prev=100240.06, day="2026-11-12", positions=("AAPL",),
         last_decision=None, missing=(), ok=True):
    acct = {"equity": equity, "prev_equity": prev, "equity_day": day,
            "positions": [{"symbol": s, "entry": 1.0, "shares": 1.0, "stop": None, "target": None}
                          for s in positions],
            "buys_today": [], "blocked_today": 0, "decisions_today": 5, "missing": list(missing)}
    return {"ok": ok, "accounts": {"100k": acct}, "pending": [], "watchlist": [],
            "last_decision": last_decision or THU_10AM - timedelta(minutes=10)}


def fresh_news(now):
    return {"generated_at": (now - timedelta(minutes=5)).isoformat(), "items": []}


class Deliveries(list):
    def __call__(self, event, now):
        self.append(event)
        events.mark([event["id"]], "text")
        return "text"


def run(now, deliver=None, **kw):
    kw.setdefault("snap", snap())
    kw.setdefault("news", fresh_news(now))
    return watch.run(now, deliver=deliver if deliver is not None else Deliveries(), **kw)


def test_first_run_only_saves_baseline():
    out = Deliveries()
    assert run(THU_10AM, out, snap=snap(equity=50000.0, prev=100000.0)) == []
    assert out == []


def test_one_percent_drop_is_urgent_once_a_day():
    run(THU_10AM)
    out = Deliveries()
    s = snap(equity=98000.0, prev=100000.0)
    run(THU_10AM, out, snap=s)
    run(THU_10AM + timedelta(minutes=15), out, snap=s)
    assert [e["kind"] for e in out] == ["drop"]
    assert out[0]["text"] == "100k account is down 2.0% today ($2,000), now $98,000."


def test_small_drop_is_not_urgent():
    run(THU_10AM)
    out = Deliveries()
    run(THU_10AM, out)          # -0.65%
    assert out == []


def test_silent_graywind_only_in_market_hours():
    two_hours_ago = THU_10AM - timedelta(hours=2)
    run(THU_10AM)
    out = Deliveries()
    run(THU_10AM, out, snap=snap(last_decision=two_hours_ago))
    assert [e["kind"] for e in out] == ["silent"]

    after_close = datetime(2026, 11, 12, 16, 0, tzinfo=CT)
    thanksgiving = datetime(2026, 11, 26, 10, 0, tzinfo=CT)
    for when in (after_close, thanksgiving):
        later = Deliveries()
        run(when, later, snap=snap(last_decision=when - timedelta(hours=5)))
        assert later == []


def test_early_close_day():
    assert watch.market_open_now(datetime(2026, 11, 27, 11, 0, tzinfo=CT))
    assert not watch.market_open_now(datetime(2026, 11, 27, 13, 0, tzinfo=CT))


def test_stale_news_is_urgent_once_a_day():
    run(THU_10AM)
    out = Deliveries()
    old = {"generated_at": (THU_10AM - timedelta(hours=3)).isoformat(), "items": []}
    run(THU_10AM, out, news=old)
    run(THU_10AM + timedelta(minutes=15), out, news=old)
    assert [e["kind"] for e in out] == ["news_stale"]


def test_closed_position_is_info_not_delivered():
    run(THU_10AM)
    out = Deliveries()
    new = run(THU_10AM + timedelta(minutes=15), out, snap=snap(positions=()))
    assert out == []
    assert [e["text"] for e in new] == ["AAPL position closed in the 100k account."]
    assert [e["kind"] for e in events.pending_info()] == ["closed"]


def test_unreadable_positions_file_is_not_a_close():
    run(THU_10AM)
    new = run(THU_10AM + timedelta(minutes=15), snap=snap(positions=(), missing=("positions.csv",)))
    assert new == []


def test_a_failed_delivery_is_retried_on_the_next_run():
    run(THU_10AM)

    def broken(event, now):
        raise RuntimeError("ntfy down")

    s = snap(equity=98000.0, prev=100000.0)
    with pytest.raises(RuntimeError):
        run(THU_10AM, broken, snap=s)
    out = Deliveries()
    run(THU_10AM + timedelta(minutes=15), out, snap=s)
    assert [e["kind"] for e in out] == ["drop"]
    again = Deliveries()
    run(THU_10AM + timedelta(minutes=30), again, snap=s)
    assert again == []


def test_delivery_failure_still_saves_baseline():
    run(THU_10AM)

    def broken(event, now):
        raise RuntimeError("ntfy down")

    with pytest.raises(RuntimeError):
        run(THU_10AM, broken, snap=snap(equity=98000.0, prev=100000.0, positions=()))
    # The close was seen once; the next run doesn't report it again.
    assert run(THU_10AM + timedelta(minutes=15), snap=snap(positions=())) == []

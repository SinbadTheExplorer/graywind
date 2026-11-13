# tests/test_briefing.py
import asyncio
import re
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, Mock

import pytest

import briefing


CT = ZoneInfo("America/Chicago")
FIXED_NOW = datetime(2026, 11, 12, 15, 15, tzinfo=CT)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def dummy_snap(
    *,
    ok=True,
    decisions_total=0,
    equity_day=FIXED_NOW.date().isoformat(),
    equity=99_584.21,
    prev_equity=100_240.06,
    positions=None,
    buys_today=None,
    pending=None,
    watchlist=None,
):
    snap = {
        "ok": ok,
        "accounts": {
            "100k": {
                "equity": equity,
                "prev_equity": prev_equity,
                "equity_day": equity_day,
                "positions": positions or [],
                "buys_today": buys_today or [],
                "decisions_today": decisions_total,
            }
        },
        "watchlist": watchlist or [],
        "pending": pending or [],
    }
    return snap


# --------------------------------------------------------------------------- #
# 1. Formatting
# --------------------------------------------------------------------------- #
def test_money_and_pct_formatting():
    assert briefing.fmt_money(99_584.21) == "$99,584"
    assert briefing.fmt_price(348.07) == "$348.07"
    assert briefing.fmt_pct(-0.73) == "0.7%"


# --------------------------------------------------------------------------- #
# 2. Guard
# --------------------------------------------------------------------------- #
def test_guard_rejects_invented_number():
    facts = ["Balance is $99,584.", "Change was 0.7%."]
    txt = "Balance is $100,000."
    assert not briefing.guard_ok(txt, facts)


def test_guard_ignores_commas_and_accepts_reworded():
    facts = ["Balance is $99,584.", "Change was 0.7%."]
    txt = "Balance is $99584 and change is 0.7 percent."
    assert briefing.guard_ok(txt, facts)


def test_guard_rejects_four_sentences():
    facts = ["A.", "B.", "C.", "D."]
    txt = "One. Two. Three. Four."
    assert not briefing.guard_ok(txt, facts)


# --------------------------------------------------------------------------- #
# 3. Template fallback
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_template_used_when_model_fails(monkeypatch):
    # ask raises
    async def bad_ask(_):
        raise RuntimeError("boom")

    facts_list = ["Fact one.", "Fact two."]
    out = await briefing.compose("close", facts_list, ask=bad_ask)
    assert out == briefing.template("close", facts_list)


@pytest.mark.asyncio
async def test_template_used_when_guard_fails(monkeypatch):
    async def good_ask(_):
        return "You made $12,000 today, choom."

    facts_list = ["Balance is $99,584."]
    out = await briefing.compose("close", facts_list, ask=good_ask)
    # guard will reject because number $99,584 not present
    assert out == briefing.template("close", facts_list)


# --------------------------------------------------------------------------- #
# 4. Facts generation – quiet day
# --------------------------------------------------------------------------- #
def test_quiet_day_when_no_decisions_today(monkeypatch):
    snap = dummy_snap(decisions_total=0)
    f = briefing.facts("close", snap, None, [], FIXED_NOW)
    assert "Quiet day: Graywind made no decisions today." in f


def test_missing_state_says_data_unavailable():
    f = briefing.facts("close", None, None, [], FIXED_NOW)
    assert f == ["Graywind's data is unavailable right now."]


def test_no_update_for_today_when_equity_day_is_old():
    snap = dummy_snap(equity_day="2026-11-10")
    f = briefing.facts("close", snap, None, [], FIXED_NOW)
    # should contain the "no update for today" line
    assert any("no update for today" in s for s in f)


def test_nothing_needs_you_only_when_no_pending():
    snap = dummy_snap(pending=[])
    f = briefing.facts("close", snap, None, [], FIXED_NOW)
    assert "Nothing needs you." in f
    # make sure it's the only pending‑related fact
    assert sum("Waiting on you:" in s for s in f) == 0


# --------------------------------------------------------------------------- #
# 5. Night‑only news handling
# --------------------------------------------------------------------------- #
def test_night_brief_includes_symbol_news_first():
    snap = dummy_snap(
        positions=[{"symbol": "AAPL", "entry": 100, "stop": 95, "target": 110}],
        watchlist=["TSLA"],
    )
    news = {
        "items": [
            {
                "title": "AAPL rockets",
                "source": "Reuters",
                "symbols": ["AAPL"],
            },
            {
                "title": "TSLA slides",
                "source": "Bloomberg",
                "symbols": ["TSLA"],
            },
            {
                "title": "General market news",
                "source": "CNBC",
                "symbols": [],
            },
        ]
    }
    f = briefing.facts("night", snap, news, [], FIXED_NOW)
    # first news should be about AAPL (symbol intersect)
    assert any('News on AAPL' in s for s in f)
    # then a generic market headline
    assert any(s.startswith('Market:') for s in f)


def test_night_brief_news_unavailable():
    snap = dummy_snap()
    f = briefing.facts("night", snap, None, [], FIXED_NOW)
    assert "News feed unavailable." in f


# --------------------------------------------------------------------------- #
# 6. run() integration
# --------------------------------------------------------------------------- #
def test_run_sends_with_dedupe_key(monkeypatch):
    fake_send = Mock(return_value=True)
    fake_ask = AsyncMock(return_value="Close wrap: Fact.")
    fake_snap = dummy_snap(decisions_total=1)
    fake_news = {"items": []}
    # monkeypatch internal helpers
    monkeypatch.setattr(briefing, "graywind_state", Mock())
    monkeypatch.setattr(briefing, "newsdesk", Mock())
    monkeypatch.setattr(briefing, "push", Mock())
    # make snapshot and news return our fakes
    briefing.graywind_state.snapshot.return_value = fake_snap
    briefing.graywind_state.repo_path.return_value = "unused"
    briefing.newsdesk.load.return_value = fake_news
    briefing.push.send = fake_send

    out = briefing.run("close", now=FIXED_NOW, ask=fake_ask, send=fake_send, snap=fake_snap, news=fake_news)

    # ensure send called with proper dedupe key
    expected_key = f"brief:close:{FIXED_NOW.date().isoformat()}"
    fake_send.assert_called_once()
    args, kwargs = fake_send.call_args
    assert kwargs["dedupe"] == expected_key
    # output should be the LLM text (guard passes)
    assert out == "Close wrap: Fact."


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    monkeypatch.setattr(briefing, "RETRY_AFTER_SECONDS", 0)


@pytest.mark.asyncio
async def test_one_retry_after_a_failure():
    calls = []

    async def flaky(_):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("429")
        return "Up $31, choom. Nothing needs you."

    facts_list = ["100k account: $99,645, flat today.", "Up $31.", "Nothing needs you."]
    assert await briefing.compose("close", facts_list, ask=flaky) == "Up $31, choom. Nothing needs you."
    assert len(calls) == 2


def test_pending_proposals_are_merged():
    now = datetime(2026, 11, 12, 15, 15, tzinfo=briefing.CT)
    snap = {"ok": True, "watchlist": [], "accounts": {"100k": {"equity": None, "prev_equity": None,
            "equity_day": None, "positions": [], "buys_today": [], "decisions_today": 3}},
            "pending": [{"symbol": "SPY", "issue": "126", "side": "buy"},
                        {"symbol": "SPY", "issue": "127", "side": "buy"}]}
    f = briefing.facts("close", snap, None, [], now)
    assert "Waiting on you: SPY buy 2 proposals (#126, #127)." in f

# tests/test_graywind_state.py
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import graywind_state as gs


# ----------------------------------------------------------------------
# Utility helpers for tests
# ----------------------------------------------------------------------
def write_csv(path: Path, header: list, rows: list):
    """Write a CSV file with given header and rows (list of tuples)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)


@pytest.fixture
def repo(tmp_path: Path):
    """Create a fake graywind repo with the two account folders."""
    # populate the folder structure but leave files empty; each test will fill as needed
    for _, sub_path in gs.ACCOUNTS:
        (tmp_path / sub_path).mkdir(parents=True, exist_ok=True)
    return tmp_path


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------
def test_day_change_uses_last_two_rows(repo):
    # equity_history with two rows
    equity_path = repo / "state" / "equity_history.csv"
    write_csv(
        equity_path,
        ["day", "equity"],
        [
            ["2026-10-14", "101000.00"],
            ["2026-10-15", "102000.00"],
        ],
    )
    now = datetime(2026, 10, 15, 12, 0, tzinfo=gs.CT)
    snap = gs.snapshot(repo, now)

    acct = snap["accounts"]["100k"]
    assert acct["equity"] == 102000.0
    assert acct["prev_equity"] == 101000.0
    assert acct["equity_day"] == "2026-10-15"


def test_no_row_for_today_means_equity_day_is_not_today(repo):
    equity_path = repo / "state" / "equity_history.csv"
    write_csv(
        equity_path,
        ["day", "equity"],
        [
            ["2026-10-13", "99000.00"],
        ],
    )
    now = datetime(2026, 10, 14, 12, 0, tzinfo=gs.CT)
    snap = gs.snapshot(repo, now)

    acct = snap["accounts"]["100k"]
    # equity_day should be the day of the last row, not today
    assert acct["equity_day"] == "2026-10-13"
    # still have equity value
    assert acct["equity"] == 99000.0


def test_missing_file_gives_none_not_crash(tmp_path):
    # Do not create any account folders – everything missing
    now = datetime(2026, 11, 12, 12, 0, tzinfo=gs.CT)
    snap = gs.snapshot(tmp_path, now)

    # Both accounts should be present with missing entries
    for name in ("100k", "small"):
        acct = snap["accounts"][name]
        assert set(acct["missing"]) == set(gs.EXPECTED_FILES)
        assert acct["equity"] is None
        assert acct["positions"] == []
    # No data at all -> ok should be False
    assert snap["ok"] is False
    # last_decision is None and watchlist empty
    assert snap["last_decision"] is None
    assert snap["watchlist"] == []


def test_decision_counts_are_per_ct_day(repo):
    # Decision log with two rows: one that falls on CT today, one that does not
    decision_path = repo / "state" / "decision_log.csv"
    write_csv(
        decision_path,
        ["timestamp", "symbol", "action", "reason", "rsi", "sma_fast", "sma_slow"],
        [
            # 2026-11-12 23:30 UTC => 2026-11-12 17:30 CT (same day)
            ["2026-11-12T23:30:00+00:00", "AAPL", "buy", "", "30", "2.5", "3.0"],
            # 2026-11-13 07:00 UTC => 2026-11-13 01:00 CT (next day)
            ["2026-11-13T07:00:00+00:00", "MSFT", "hold", "", "40", "2.6", "3.1"],
        ],
    )
    # now is 2026-11-12 20:00 CT
    now = datetime(2026, 11, 12, 20, 0, tzinfo=gs.CT)
    snap = gs.snapshot(repo, now)

    acct = snap["accounts"]["100k"]
    assert acct["decisions_today"] == 1
    assert acct["buys_today"] == ["AAPL"]
    assert acct["blocked_today"] == 0


def test_pending_dedupes_issue_across_accounts(tmp_path):
    # Account 100k pending
    p1 = tmp_path / "state" / "pending_trades.csv"
    write_csv(
        p1,
        ["symbol", "issue_number", "side", "qty", "price_at_proposal", "stop_price", "target_price", "tier", "proposed_date"],
        [
            ["SPY", "123", "buy", "100", "400", "", "", "1", "2026-11-12"],
        ],
    )
    # Account small pending with same issue number
    p2 = tmp_path / "state/small" / "pending_trades.csv"
    write_csv(
        p2,
        ["symbol", "issue_number", "side", "qty", "price_at_proposal", "stop_price", "target_price", "tier", "proposed_date"],
        [
            ["SPY", "123", "sell", "50", "405", "", "", "1", "2026-11-12"],
        ],
    )
    now = datetime(2026, 11, 12, 12, 0, tzinfo=gs.CT)
    snap = gs.snapshot(tmp_path, now)

    # Only one pending entry should survive (the first account's)
    assert len(snap["pending"]) == 1
    assert snap["pending"][0]["issue"] == "123"
    assert snap["pending"][0]["side"] == "buy"


def test_last_decision_is_newest_across_accounts(tmp_path):
    # Account 100k: older decision
    d1 = tmp_path / "state" / "decision_log.csv"
    write_csv(
        d1,
        ["timestamp", "symbol", "action", "reason"],
        [
            ["2026-11-10T12:00:00+00:00", "AAPL", "buy", ""],
        ],
    )
    # Account small: newer decision
    d2 = tmp_path / "state/small" / "decision_log.csv"
    write_csv(
        d2,
        ["timestamp", "symbol", "action", "reason"],
        [
            ["2026-11-12T15:00:00+00:00", "MSFT", "buy", ""],
        ],
    )
    now = datetime(2026, 11, 12, 12, 0, tzinfo=gs.CT)
    snap = gs.snapshot(tmp_path, now)

    assert snap["last_decision"] == datetime.fromisoformat("2026-11-12T15:00:00+00:00")


def test_watchlist_last_7_days(repo):
    decision_path = repo / "state" / "decision_log.csv"
    today = datetime(2026, 11, 12, 12, 0, tzinfo=gs.CT).date()
    rows = []
    # create symbols for the last 8 days
    for i in range(8):
        day = today - timedelta(days=i)
        ts = datetime.combine(day, datetime.min.time()).replace(tzinfo=gs.CT).astimezone(timezone.utc)
        rows.append([ts.isoformat(), f"SYM{i}", "hold", ""])
    write_csv(
        decision_path,
        ["timestamp", "symbol", "action", "reason"],
        rows,
    )
    now = datetime(2026, 11, 12, 12, 0, tzinfo=gs.CT)
    snap = gs.snapshot(repo, now)

    # watchlist should contain SYM0 .. SYM6 (last 7 days), sorted
    expected = sorted([f"SYM{i}" for i in range(7)])
    assert snap["watchlist"] == expected

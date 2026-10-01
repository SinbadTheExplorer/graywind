# Graywind Dashboard Implementation Plan

> **Superseded 2026-08-15, same day:** this plan's two-repo architecture (Tasks 4-7 involve
> `graywind-dashboard` as a separate repo, a PAT, cross-repo pushes) was reversed to a single
> repo before Task 7's GitHub setup ever ran. This file is kept as a point-in-time historical
> record — for what's actually true today, read the "Revision" section at the top of
> `docs/superpowers/specs/2026-08-15-graywind-dashboard-design.md` instead.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Graywind trading bot a public-but-unlisted dashboard (equity curve, trade log, current status) driven by a GitHub Actions cron, mirroring Bullion's cron-commits-data/static-page-reads-it pattern but split across two private repos with CSV instead of JSON.

**Architecture:** `graywind`'s existing `live_loop.py` cycle gains two new outputs each run: its own CSV-based operational state (replacing `live_state.json`) committed to itself, and an incremental "cycle export" (one new equity point, any new trades, a refreshed per-symbol status) written to a local scratch directory. A new `merge_dashboard_export.py` script folds that scratch export into a fresh clone of the separate `graywind-dashboard` repo (appending history, overwriting status) and pushes it. A static `index.html` in `graywind-dashboard`, served by GitHub Pages, reads the three committed CSVs client-side with vanilla JS + D3.

**Tech Stack:** Python 3 (stdlib `csv`, existing `pandas`/`alpaca-py` stack), pytest, GitHub Actions, vanilla JS + D3 v7 (no build step), GitHub Pages.

## Global Constraints

- No JSON anywhere in this feature's data files — both `graywind`'s internal operational state and `graywind-dashboard`'s display data are CSV. (Spec: "Data Format — CSV everywhere, no JSON")
- `graywind` stays private; `graywind-dashboard` stays private too, unlisted-URL access model, no auth layer. (Spec: "Repo Structure", "Privacy model")
- Cron cadence: every 15 minutes, 9:30am–4:00pm ET, Monday–Friday. (Spec: "Execution Model")
- `graywind`'s own state commit must succeed/fail independently of the cross-repo dashboard push — a dashboard push failure must never lose or block the bot's own operational continuity. (Spec: "Error Handling")
- No change to `graywind_strategy/`'s actual decision/strategy logic — this feature only touches state persistence and adds export/observability plumbing in `live_loop.py`. (Spec: "Explicitly Out of Scope")
- Reuse Bullion's failure-alert-issue GitHub Actions pattern (`.github/workflows/daily-data.yml` in the claudekit/Bullion repo) rather than inventing a new alerting mechanism. (Spec: "Error Handling")
- `pytest tests/ -q` must keep working bare from the repo root (existing `conftest.py` already enables this — don't break it).

---

## File Structure

**`graywind` repo (existing, this repo):**
- Modify: `graywind_strategy/state_store.py` — JSON → CSV, same `load_state()`/`save_state()` external contract
- Modify: `tests/test_state_store.py` — full rewrite for CSV
- Modify: `.gitignore` — un-ignore `state/`, ignore new `dashboard_export/`
- Create: `graywind_strategy/dashboard_export.py` — pure writer for the local per-cycle export directory
- Create: `tests/test_dashboard_export.py`
- Modify: `live_loop.py` — thread optional export-collection params through `process_symbol()`/`main()`
- Modify: `tests/test_live_loop.py` — new cases + 3 existing `main()`-level tests gain a new patch
- Create: `merge_dashboard_export.py` — merges a cycle export into a dashboard repo checkout
- Create: `tests/test_merge_dashboard_export.py` — includes the two-run round-trip simulation
- Create: `.github/workflows/live-trading.yml`

**`graywind-dashboard` repo (new, sibling local repo at `~/Projects/graywind-dashboard`):**
- Create: `data/equity_curve.csv`, `data/trade_log.csv`, `data/status.csv` (headers only, seed content)
- Create: `index.html` — the dashboard itself
- Create: `_config.yml` — Jekyll-exclude safeguard (Bullion precedent)
- Create: `README.md`

---

### Task 1: Migrate `state_store.py` from JSON to CSV

**Files:**
- Modify: `graywind_strategy/state_store.py`
- Modify: `tests/test_state_store.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `load_state(state_dir=DEFAULT_STATE_DIR) -> dict` with keys `day_trade_dates` (list[str]), `day` (str|None), `starting_equity` (float|None), `open_positions` (dict[str, dict]) — same shape `live_loop.py` and `backtester.py`-style code already expect.
- Produces: `save_state(state: dict, state_dir=DEFAULT_STATE_DIR) -> None`.
- `live_loop.py` calls both with no explicit path/dir argument (uses the default), so this task alone does not require changing `live_loop.py`.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_state_store.py`:

```python
import csv
import os

from graywind_strategy.state_store import load_state, save_state


def test_load_state_returns_empty_defaults_when_no_files_exist(tmp_path):
    state = load_state(state_dir=str(tmp_path / "nonexistent"))
    assert state == {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}


def test_save_then_load_round_trips_operational_fields(tmp_path):
    state_dir = str(tmp_path)
    save_state(
        {
            "day_trade_dates": ["2024-01-08", "2024-01-09"],
            "day": "2024-01-09",
            "starting_equity": 10000.0,
            "open_positions": {},
        },
        state_dir=state_dir,
    )
    state = load_state(state_dir=state_dir)
    assert state["day_trade_dates"] == ["2024-01-08", "2024-01-09"]
    assert state["day"] == "2024-01-09"
    assert state["starting_equity"] == 10000.0


def test_save_then_load_round_trips_open_positions(tmp_path):
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["open_positions"]["AAPL"] == {
        "entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08",
    }


def test_save_then_load_round_trips_multiple_open_positions(tmp_path):
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {
            "AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"},
            "SPY": {"entry_price": 400.0, "shares": 5, "stop": 392.0, "target": 410.0, "opened_date": "2024-01-08"},
        },
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert set(state["open_positions"].keys()) == {"AAPL", "SPY"}
    assert state["open_positions"]["SPY"]["shares"] == 5


def test_save_then_load_round_trips_empty_open_positions(tmp_path):
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": ["2024-01-08"], "day": "2024-01-08", "starting_equity": 9500.0,
        "open_positions": {},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["open_positions"] == {}


def test_save_then_load_round_trips_empty_day_trade_dates(tmp_path):
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 9500.0,
        "open_positions": {},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["day_trade_dates"] == []


def test_save_then_load_round_trips_none_day_and_starting_equity(tmp_path):
    # main()'s very first-ever cycle (no prior state) passes day=None,
    # starting_equity=None through save_state before any account read has
    # succeeded -- must round-trip back to None, not "" or 0.0.
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": None, "starting_equity": None,
        "open_positions": {},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["day"] is None
    assert state["starting_equity"] is None


def test_save_writes_two_separate_csv_files(tmp_path):
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": ["2024-01-08"], "day": "2024-01-08", "starting_equity": 9500.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, state_dir=state_dir)
    assert os.path.exists(os.path.join(state_dir, "operational.csv"))
    assert os.path.exists(os.path.join(state_dir, "positions.csv"))
    with open(os.path.join(state_dir, "positions.csv"), newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows == [{"symbol": "AAPL", "entry_price": "150.0", "shares": "10", "stop": "147.0", "target": "154.5", "opened_date": "2024-01-08"}]


def test_save_overwrites_previous_positions_rather_than_appending(tmp_path):
    # positions.csv reflects CURRENT holdings, not history -- a position
    # closed since the last save must disappear from the file, not linger
    # as a stale row alongside the new state.
    state_dir = str(tmp_path)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {"AAPL": {"entry_price": 150.0, "shares": 10, "stop": 147.0, "target": 154.5, "opened_date": "2024-01-08"}},
    }, state_dir=state_dir)
    save_state({
        "day_trade_dates": [], "day": "2024-01-08", "starting_equity": 10000.0,
        "open_positions": {},
    }, state_dir=state_dir)
    state = load_state(state_dir=state_dir)
    assert state["open_positions"] == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_state_store.py -v`
Expected: FAIL (old JSON-based `load_state`/`save_state` don't accept `state_dir=`, and don't write `operational.csv`/`positions.csv`)

- [ ] **Step 3: Rewrite `state_store.py` for CSV**

Replace the full contents of `graywind_strategy/state_store.py`:

```python
"""Persists PDT-throttle, drawdown-breaker, and open-position state as two
CSV files in a directory between live_loop.py invocations, since each run
is a fresh process (a cron-invoked script, not a long-running one).

Two files instead of one nested blob because the two halves have different
overwrite semantics once this state also feeds the dashboard export
(dashboard_export.py): positions.csv is a snapshot of CURRENT holdings
(fully overwritten every save), and so is operational.csv (a single scalar
row) -- neither accumulates history, unlike the dashboard's own
equity_curve.csv/trade_log.csv.
"""
import csv
import os

DEFAULT_STATE_DIR = "state"
OPERATIONAL_FILENAME = "operational.csv"
POSITIONS_FILENAME = "positions.csv"
OPERATIONAL_FIELDS = ["day", "starting_equity", "day_trade_dates"]
POSITIONS_FIELDS = ["symbol", "entry_price", "shares", "stop", "target", "opened_date"]


def load_state(state_dir=DEFAULT_STATE_DIR):
    state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

    operational_path = os.path.join(state_dir, OPERATIONAL_FILENAME)
    if os.path.exists(operational_path):
        with open(operational_path, newline="") as f:
            row = next(csv.DictReader(f), None)
        if row is not None:
            state["day"] = row["day"] or None
            state["starting_equity"] = float(row["starting_equity"]) if row["starting_equity"] else None
            state["day_trade_dates"] = row["day_trade_dates"].split(";") if row["day_trade_dates"] else []

    positions_path = os.path.join(state_dir, POSITIONS_FILENAME)
    if os.path.exists(positions_path):
        with open(positions_path, newline="") as f:
            for row in csv.DictReader(f):
                state["open_positions"][row["symbol"]] = {
                    "entry_price": float(row["entry_price"]),
                    "shares": int(row["shares"]),
                    "stop": float(row["stop"]),
                    "target": float(row["target"]),
                    "opened_date": row["opened_date"],
                }

    return state


def save_state(state, state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)

    with open(os.path.join(state_dir, OPERATIONAL_FILENAME), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OPERATIONAL_FIELDS)
        writer.writeheader()
        writer.writerow({
            "day": state["day"] or "",
            "starting_equity": state["starting_equity"] if state["starting_equity"] is not None else "",
            "day_trade_dates": ";".join(state["day_trade_dates"]),
        })

    with open(os.path.join(state_dir, POSITIONS_FILENAME), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=POSITIONS_FIELDS)
        writer.writeheader()
        for symbol, position in state["open_positions"].items():
            writer.writerow({"symbol": symbol, **position})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_state_store.py -v`
Expected: PASS (all 9 cases)

- [ ] **Step 5: Un-gitignore `state/`**

In `.gitignore`, delete the `state/` line entirely (the whole point of this migration is that `state/*.csv` must now be tracked and committed by the GitHub Actions workflow — see Task 6).

- [ ] **Step 6: Run the full test suite to confirm nothing else broke**

Run: `pytest tests/ -q`
Expected: PASS (this task doesn't touch `live_loop.py`, so `test_live_loop.py` should be unaffected)

- [ ] **Step 7: Commit**

```bash
git add graywind_strategy/state_store.py tests/test_state_store.py .gitignore
git commit -m "Migrate state_store.py from JSON to two CSV files"
```

---

### Task 2: Add `dashboard_export.py` — per-cycle export writer

**Files:**
- Create: `graywind_strategy/dashboard_export.py`
- Create: `tests/test_dashboard_export.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure new module).
- Produces: `write_cycle_export(export_dir, timestamp, symbols, equity, today_pnl, symbol_statuses, cycle_trades) -> None`, writing three files into `export_dir`: `new_equity_point.csv`, `new_trades.csv`, `status.csv`. `symbol_statuses` is `dict[str, dict]`, each value having keys `position_open` (bool|None), `shares` (int|None), `entry_price` (float|None), `current_price` (float|None), `action` (str), `reason` (str). `cycle_trades` is `list[dict]`, each with keys `timestamp`, `symbol`, `side`, `qty`, `price`, `reason`. Task 3 (`live_loop.py`) and Task 4 (`merge_dashboard_export.py`) both rely on these exact filenames/columns.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard_export.py`:

```python
import csv
import os

from graywind_strategy.dashboard_export import write_cycle_export


def _read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_writes_new_equity_point_with_timestamp_and_equity(tmp_path):
    export_dir = str(tmp_path)
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL"],
        equity=10500.0, today_pnl=500.0, symbol_statuses={}, cycle_trades=[],
    )
    rows = _read_csv(os.path.join(export_dir, "new_equity_point.csv"))
    assert rows == [{"timestamp": "2026-08-15T10:00:00-04:00", "equity": "10500.0"}]


def test_writes_blank_equity_when_cycle_had_no_confirmed_equity_reading(tmp_path):
    # main()'s get_account() failure path -- equity/today_pnl are None, but
    # the file must still exist with a row (a failed cycle is still a
    # recorded event, not a silent gap in the dashboard).
    export_dir = str(tmp_path)
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL"],
        equity=None, today_pnl=None, symbol_statuses={}, cycle_trades=[],
    )
    rows = _read_csv(os.path.join(export_dir, "new_equity_point.csv"))
    assert rows == [{"timestamp": "2026-08-15T10:00:00-04:00", "equity": ""}]


def test_writes_one_trade_row_per_cycle_trade(tmp_path):
    export_dir = str(tmp_path)
    trades = [
        {"timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 150.0, "reason": "signal=buy"},
        {"timestamp": "2026-08-15T10:00:00-04:00", "symbol": "SPY", "side": "sell", "qty": 5, "price": 410.0, "reason": "stop/target exit"},
    ]
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL", "SPY"],
        equity=10500.0, today_pnl=500.0, symbol_statuses={}, cycle_trades=trades,
    )
    rows = _read_csv(os.path.join(export_dir, "new_trades.csv"))
    assert len(rows) == 2
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["side"] == "buy"
    assert rows[1]["symbol"] == "SPY"
    assert rows[1]["side"] == "sell"


def test_writes_empty_trades_file_with_header_when_no_trades_this_cycle(tmp_path):
    export_dir = str(tmp_path)
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL"],
        equity=10500.0, today_pnl=500.0, symbol_statuses={}, cycle_trades=[],
    )
    rows = _read_csv(os.path.join(export_dir, "new_trades.csv"))
    assert rows == []


def test_status_has_one_row_per_requested_symbol(tmp_path):
    export_dir = str(tmp_path)
    statuses = {
        "AAPL": {"position_open": True, "shares": 10, "entry_price": 150.0, "current_price": 152.0, "action": "hold", "reason": "already holding 10 shares"},
    }
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL", "SPY"],
        equity=10500.0, today_pnl=500.0, symbol_statuses=statuses, cycle_trades=[],
    )
    rows = _read_csv(os.path.join(export_dir, "status.csv"))
    assert len(rows) == 2
    by_symbol = {r["symbol"]: r for r in rows}
    assert by_symbol["AAPL"]["action"] == "hold"
    assert by_symbol["AAPL"]["shares"] == "10"


def test_status_defaults_unevaluated_symbol_to_unknown_action(tmp_path):
    # A cycle that failed before the per-symbol loop ran (e.g. get_account()
    # raised) leaves symbol_statuses empty -- every watchlist symbol must
    # still get a row, not silently vanish from the dashboard for that cycle.
    export_dir = str(tmp_path)
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL", "SPY"],
        equity=None, today_pnl=None, symbol_statuses={}, cycle_trades=[],
    )
    rows = _read_csv(os.path.join(export_dir, "status.csv"))
    assert len(rows) == 2
    assert all(r["action"] == "unknown" for r in rows)
    assert all(r["reason"] == "cycle did not evaluate this symbol" for r in rows)


def test_status_rows_carry_account_level_fields(tmp_path):
    export_dir = str(tmp_path)
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL"],
        equity=10500.0, today_pnl=500.0, symbol_statuses={}, cycle_trades=[],
    )
    rows = _read_csv(os.path.join(export_dir, "status.csv"))
    assert rows[0]["last_cycle_timestamp"] == "2026-08-15T10:00:00-04:00"
    assert rows[0]["account_equity"] == "10500.0"
    assert rows[0]["today_pnl"] == "500.0"


def test_export_dir_is_created_if_missing(tmp_path):
    export_dir = str(tmp_path / "nested" / "export")
    write_cycle_export(
        export_dir=export_dir, timestamp="2026-08-15T10:00:00-04:00", symbols=["AAPL"],
        equity=10500.0, today_pnl=500.0, symbol_statuses={}, cycle_trades=[],
    )
    assert os.path.exists(os.path.join(export_dir, "status.csv"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_dashboard_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'graywind_strategy.dashboard_export'`

- [ ] **Step 3: Write `dashboard_export.py`**

Create `graywind_strategy/dashboard_export.py`:

```python
"""Writes one cycle's dashboard update -- a new equity point, any new
trades, and a refreshed per-symbol status -- to a local scratch directory.
This module knows nothing about the graywind-dashboard repo; it only
writes files. merge_dashboard_export.py folds this directory's contents
into a checkout of that repo (see that module for the append-vs-overwrite
distinction between equity_curve.csv/trade_log.csv and status.csv).
"""
import csv
import os

EQUITY_POINT_FIELDS = ["timestamp", "equity"]
TRADE_FIELDS = ["timestamp", "symbol", "side", "qty", "price", "reason"]
STATUS_FIELDS = [
    "last_cycle_timestamp", "account_equity", "today_pnl", "symbol",
    "position_open", "shares", "entry_price", "current_price", "action", "reason",
]

_UNEVALUATED_STATUS = {
    "position_open": "", "shares": "", "entry_price": "", "current_price": "",
    "action": "unknown", "reason": "cycle did not evaluate this symbol",
}


def _fmt(value):
    return "" if value is None else str(value)


def write_cycle_export(export_dir, timestamp, symbols, equity, today_pnl, symbol_statuses, cycle_trades):
    os.makedirs(export_dir, exist_ok=True)

    with open(os.path.join(export_dir, "new_equity_point.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EQUITY_POINT_FIELDS)
        writer.writeheader()
        writer.writerow({"timestamp": timestamp, "equity": _fmt(equity)})

    with open(os.path.join(export_dir, "new_trades.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        writer.writeheader()
        for trade in cycle_trades:
            writer.writerow({field: trade[field] for field in TRADE_FIELDS})

    with open(os.path.join(export_dir, "status.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=STATUS_FIELDS)
        writer.writeheader()
        for symbol in symbols:
            status = symbol_statuses.get(symbol, _UNEVALUATED_STATUS)
            writer.writerow({
                "last_cycle_timestamp": timestamp,
                "account_equity": _fmt(equity),
                "today_pnl": _fmt(today_pnl),
                "symbol": symbol,
                "position_open": _fmt(status["position_open"]),
                "shares": _fmt(status["shares"]),
                "entry_price": _fmt(status["entry_price"]),
                "current_price": _fmt(status["current_price"]),
                "action": status["action"],
                "reason": status["reason"],
            })
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_dashboard_export.py -v`
Expected: PASS (all 8 cases)

- [ ] **Step 5: Gitignore the scratch export directory**

In `.gitignore`, add a new line: `dashboard_export/` — this directory is regenerated every cycle and only ever consumed by `merge_dashboard_export.py` before being pushed elsewhere; it must never be committed to `graywind` itself.

- [ ] **Step 6: Commit**

```bash
git add graywind_strategy/dashboard_export.py tests/test_dashboard_export.py .gitignore
git commit -m "Add dashboard_export.py: per-cycle local export writer"
```

---

### Task 3: Wire the export into `live_loop.py`

**Files:**
- Modify: `live_loop.py`
- Modify: `tests/test_live_loop.py`

**Interfaces:**
- Consumes: `write_cycle_export` from Task 2 (`graywind_strategy/dashboard_export.py`).
- Produces: `process_symbol(..., cycle_timestamp=None, cycle_trades=None, symbol_statuses=None)` — three new **optional** keyword params, defaulting to `None` (internally treated as "not collecting"), so every existing call site and test keeps working unchanged. `main()` now also writes `dashboard_export/` via `write_cycle_export` in its `finally` block, after `save_state`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_live_loop.py` (after the existing `_call` helper and its tests, before the `reconcile_positions` section):

```python
# --- dashboard export collection: process_symbol optionally records what
# happened this cycle into caller-supplied cycle_trades/symbol_statuses,
# defaulting to None (no-op) so every pre-existing call site above is
# unaffected.

def test_process_symbol_records_buy_trade_and_status_when_collectors_passed():
    cycle_trades = []
    symbol_statuses = {}
    with patch(
        "live_loop.decide_trade",
        return_value=TradeDecision(action="buy", reason="signal=buy", shares=10, stop_price=98.0, target_price=103.0),
    ):
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=MagicMock(), drawdown_breaker=MagicMock(),
            cycle_timestamp="2026-08-15T10:00:00-04:00", cycle_trades=cycle_trades, symbol_statuses=symbol_statuses,
        )
    assert cycle_trades == [{
        "timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "side": "buy",
        "qty": 10, "price": 100.0, "reason": "signal=buy",
    }]
    assert symbol_statuses["AAPL"]["action"] == "buy"
    assert symbol_statuses["AAPL"]["position_open"] is True


def test_process_symbol_records_sell_trade_on_stop_exit():
    cycle_trades = []
    symbol_statuses = {}
    open_positions = {"AAPL": _position(stop=98.0, target=103.0)}
    process_symbol(
        symbol="AAPL", signal="hold", current_price=97.0, today=date(2024, 1, 8),
        open_positions=open_positions, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
        drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        trading_client=MagicMock(), drawdown_breaker=MagicMock(),
        cycle_timestamp="2026-08-15T10:00:00-04:00", cycle_trades=cycle_trades, symbol_statuses=symbol_statuses,
    )
    sell_trades = [t for t in cycle_trades if t["side"] == "sell"]
    assert sell_trades == [{
        "timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "side": "sell",
        "qty": 10, "price": 97.0, "reason": "stop/target exit",
    }]


def test_process_symbol_records_hold_status_for_already_held_position():
    symbol_statuses = {}
    open_positions = {"AAPL": _position(stop=98.0, target=103.0, opened_date="2024-01-08")}
    process_symbol(
        symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
        open_positions=open_positions, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
        drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        trading_client=MagicMock(), drawdown_breaker=MagicMock(),
        cycle_timestamp="2026-08-15T10:00:00-04:00", cycle_trades=[], symbol_statuses=symbol_statuses,
    )
    assert symbol_statuses["AAPL"]["action"] == "hold"
    assert symbol_statuses["AAPL"]["position_open"] is True
    assert symbol_statuses["AAPL"]["shares"] == 10


def test_process_symbol_without_collectors_behaves_exactly_as_before():
    # No cycle_timestamp/cycle_trades/symbol_statuses passed -- must not
    # raise, matching every pre-existing call site in this file.
    trading_client = MagicMock()
    process_symbol(
        symbol="AAPL", signal="hold", current_price=100.0, today=date(2024, 1, 8),
        open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
        drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        trading_client=trading_client, drawdown_breaker=MagicMock(),
    )
    trading_client.submit_order.assert_not_called()
```

Also add, in the `main()` section near the bottom of the file:

```python
def test_main_calls_write_cycle_export_after_save_state():
    fake_account = MagicMock()
    fake_account.equity = "10000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

    def fake_fetch_bars(client, symbol, start, end):
        return [_FakeBar(100.0, datetime(2024, 1, 8, 10, 0, tzinfo=ET))]

    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k",
         }), \
         patch("live_loop.TradingClient", return_value=fake_trading_client), \
         patch("live_loop.StockHistoricalDataClient"), \
         patch("live_loop.NewsClient"), \
         patch("live_loop.load_state", return_value=fake_state), \
         patch("live_loop.save_state"), \
         patch("live_loop.fetch_bars", side_effect=fake_fetch_bars), \
         patch("live_loop.compute_signals", side_effect=lambda df: df.assign(signal="hold")), \
         patch("live_loop.decide_trade", return_value=TradeDecision(action="hold", reason="no buy signal")), \
         patch("live_loop.write_cycle_export") as mock_export:
        live_loop.main()

    mock_export.assert_called_once()
    kwargs = mock_export.call_args.kwargs
    assert kwargs["symbols"] == live_loop.WATCHLIST
    assert kwargs["equity"] == 10000.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_live_loop.py -v`
Expected: FAIL — `process_symbol()` raises `TypeError: unexpected keyword argument 'cycle_timestamp'`; `test_main_calls_write_cycle_export_after_save_state` fails with `AttributeError: <module 'live_loop'> does not have the attribute 'write_cycle_export'`

- [ ] **Step 3: Update `live_loop.py`**

Add the import near the top, alongside the other `graywind_strategy` imports:

```python
from graywind_strategy.dashboard_export import write_cycle_export
```

Add a module-level constant near `WATCHLIST`:

```python
DASHBOARD_EXPORT_DIR = "dashboard_export"
```

Change `process_symbol`'s signature and body. Full new version of the function:

```python
def process_symbol(symbol, signal, current_price, today, open_positions, equity,
                    pdt_throttle, position_sizer, drawdown_breaker_ok,
                    fred_api_key, news_client, finnhub_api_key, trading_client,
                    drawdown_breaker, cycle_timestamp=None, cycle_trades=None,
                    symbol_statuses=None):
    """Resolves one symbol's decision for this cycle: sell-on-stop/target
    exit if a held position crossed its stop or target, otherwise
    decide_trade() for a fresh entry -- but only if the symbol isn't
    already held (the skip-if-holding guard that keeps a sustained-uptrend
    "buy" signal from re-entering a position already open). Mutates
    `open_positions` in place (mirroring the backtester's own
    open_positions bookkeeping in graywind_strategy/backtester.py) and
    submits orders via `trading_client`; both are directly observable in
    tests via mocks, which is the point of extracting this out of main().

    `cycle_timestamp`/`cycle_trades`/`symbol_statuses` are optional
    dashboard-export collectors -- when omitted (None), no export data is
    recorded and behavior is identical to before this parameter existed,
    so every pre-existing caller/test needs no changes.

    `pending_same_day_trades` is computed from `open_positions` AFTER this
    symbol's own position (if any) has already been resolved/deleted above
    -- so it naturally excludes the symbol currently being evaluated,
    matching the "other symbols only" contract documented in
    pdt_throttle.py/pipeline.py, without needing an explicit exclusion.
    """
    if cycle_trades is None:
        cycle_trades = []
    if symbol_statuses is None:
        symbol_statuses = {}

    position = open_positions.get(symbol)
    if position is not None and (current_price <= position["stop"] or current_price >= position["target"]):
        order = MarketOrderRequest(
            symbol=symbol, qty=position["shares"],
            side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
        )
        trading_client.submit_order(order)
        cycle_trades.append({
            "timestamp": cycle_timestamp, "symbol": symbol, "side": "sell",
            "qty": position["shares"], "price": current_price, "reason": "stop/target exit",
        })
        # opened_date is stored/compared here as an ISO string (round-trips
        # through CSV via state_store.py); backtester.py's equivalent
        # comparison uses a `date` object instead since it never leaves
        # memory -- a future refactor unifying the two representations must
        # preserve each caller's own idiom.
        opened_date = datetime.fromisoformat(position["opened_date"]).date()
        if opened_date == today:
            pdt_throttle.record_day_trade(today)
        del open_positions[symbol]
        # Mirrors the backtester's per-exit update_equity call (see the
        # bar-by-bar loop in backtester.py) -- catches a same-cycle drawdown
        # breach triggered by this exit before evaluating later symbols in
        # this same cycle, rather than waiting for the next cycle's single
        # per-cycle update in main().
        drawdown_breaker.update_equity(equity)
        print(f"{symbol}: submitted sell for {position['shares']} shares (stop/target exit)")
        position = None  # eligible for a fresh same-cycle entry below, same as the backtester

    if position is None:
        pending_today = sum(
            1 for p in open_positions.values() if p["opened_date"] == today.isoformat()
        )
        decision = decide_trade(
            symbol=symbol, signal=signal, as_of_date=today,
            current_price=current_price, account_equity=equity,
            pdt_throttle=pdt_throttle, position_sizer=position_sizer,
            drawdown_breaker_ok=drawdown_breaker_ok,
            fred_api_key=fred_api_key, news_client=news_client,
            finnhub_api_key=finnhub_api_key,
            pending_same_day_trades=pending_today,
        )
        if decision.action == "buy":
            order = MarketOrderRequest(
                symbol=symbol, qty=decision.shares,
                side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            )
            trading_client.submit_order(order)
            open_positions[symbol] = {
                "entry_price": current_price, "shares": decision.shares,
                "stop": decision.stop_price, "target": decision.target_price,
                "opened_date": today.isoformat(),
            }
            cycle_trades.append({
                "timestamp": cycle_timestamp, "symbol": symbol, "side": "buy",
                "qty": decision.shares, "price": current_price, "reason": decision.reason,
            })
            symbol_statuses[symbol] = {
                "position_open": True, "shares": decision.shares, "entry_price": current_price,
                "current_price": current_price, "action": "buy", "reason": decision.reason,
            }
            print(f"{symbol}: submitted buy for {decision.shares} shares")
        else:
            symbol_statuses[symbol] = {
                "position_open": False, "shares": None, "entry_price": None,
                "current_price": current_price, "action": decision.action, "reason": decision.reason,
            }
            print(f"{symbol}: {decision.action} ({decision.reason})")
    else:
        symbol_statuses[symbol] = {
            "position_open": True, "shares": position["shares"], "entry_price": position["entry_price"],
            "current_price": current_price, "action": "hold",
            "reason": f"already holding {position['shares']} shares",
        }
        print(f"{symbol}: already holding {position['shares']} shares, skipping entry evaluation")
```

Change `main()`. Add these lines right after `today = datetime.now(ET).date()` (before `state = load_state()`):

```python
    cycle_timestamp = datetime.now(ET).isoformat()
    cycle_trades = []
    symbol_statuses = {}
```

Add `equity = None` right next to the existing `starting_equity = state["starting_equity"]` initialization (so `equity` is always defined even if `get_account()` raises before assignment):

```python
    starting_equity = state["starting_equity"]
    equity = None
```

Inside the `for symbol in WATCHLIST:` loop, pass the three new arguments into the existing `process_symbol(...)` call (add these three lines to the existing call's kwargs):

```python
                    cycle_timestamp=cycle_timestamp, cycle_trades=cycle_trades,
                    symbol_statuses=symbol_statuses,
```

Finally, in the `finally:` block, after the existing `save_state({...})` call, add:

```python
        write_cycle_export(
            export_dir=DASHBOARD_EXPORT_DIR,
            timestamp=cycle_timestamp,
            symbols=WATCHLIST,
            equity=equity,
            today_pnl=(equity - starting_equity) if equity is not None and starting_equity else None,
            symbol_statuses=symbol_statuses,
            cycle_trades=cycle_trades,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_live_loop.py -v`
Expected: PASS (all cases, including the 3 pre-existing `main()`-level tests, which don't patch `write_cycle_export` but don't need to — it runs for real against the real `DASHBOARD_EXPORT_DIR` path in the repo working directory during those tests; confirm this is acceptable per Step 4b below, or patch it in those 3 tests if it litters the repo root during test runs)

- [ ] **Step 4b: Check for test pollution, fix if present**

Run: `pytest tests/test_live_loop.py -v && git status --short`
If `git status` shows an untracked `dashboard_export/` directory created by the test run, that's test pollution (real files written outside `tmp_path` during a unit test). Fix it by adding `patch("live_loop.write_cycle_export")` to the `with patch(...)` chains of `test_symbol_exception_does_not_abort_cycle_and_save_state_still_runs`, `test_get_account_exception_leaves_day_and_starting_equity_unchanged`, and `test_successful_equity_read_updates_day_and_starting_equity_normally` (the three pre-existing `main()`-level tests), then re-run and re-check `git status --short` is clean. Remove any stray `dashboard_export/` directory this created (`rm -rf dashboard_export`) before committing.

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add live_loop.py tests/test_live_loop.py
git commit -m "Wire dashboard_export into live_loop.py's per-cycle run"
```

---

### Task 4: Add `merge_dashboard_export.py`

**Files:**
- Create: `merge_dashboard_export.py`
- Create: `tests/test_merge_dashboard_export.py`

**Interfaces:**
- Consumes: the three files Task 2's `write_cycle_export` produces (`new_equity_point.csv`, `new_trades.csv`, `status.csv`) in a given export directory.
- Produces: `merge_export(export_dir, target_data_dir) -> None`. Task 6's GitHub Actions workflow calls this (via CLI, see Step 5 below) against a checkout of `graywind-dashboard`'s `data/` directory.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_merge_dashboard_export.py`:

```python
import csv
import os

from graywind_strategy.dashboard_export import write_cycle_export
from merge_dashboard_export import merge_export


def _read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _make_export(export_dir, timestamp, equity, trades=None, symbols=("AAPL",)):
    write_cycle_export(
        export_dir=export_dir, timestamp=timestamp, symbols=list(symbols),
        equity=equity, today_pnl=equity - 10000.0 if equity else None,
        symbol_statuses={}, cycle_trades=trades or [],
    )


def test_merge_creates_target_files_on_first_run(tmp_path):
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")
    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10100.0)

    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    equity_rows = _read_csv(os.path.join(target_dir, "equity_curve.csv"))
    assert equity_rows == [{"timestamp": "2026-08-15T10:00:00-04:00", "equity": "10100.0"}]
    status_rows = _read_csv(os.path.join(target_dir, "status.csv"))
    assert len(status_rows) == 1


def test_merge_appends_equity_point_on_second_run_without_losing_first(tmp_path):
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")
    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10100.0)
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    _make_export(export_dir, "2026-08-15T10:15:00-04:00", 10150.0)
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    equity_rows = _read_csv(os.path.join(target_dir, "equity_curve.csv"))
    assert [r["timestamp"] for r in equity_rows] == ["2026-08-15T10:00:00-04:00", "2026-08-15T10:15:00-04:00"]
    assert [r["equity"] for r in equity_rows] == ["10100.0", "10150.0"]


def test_merge_appends_new_trades_across_two_runs(tmp_path):
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")
    trade1 = [{"timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 150.0, "reason": "signal=buy"}]
    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10100.0, trades=trade1)
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    trade2 = [{"timestamp": "2026-08-15T10:15:00-04:00", "symbol": "SPY", "side": "buy", "qty": 5, "price": 410.0, "reason": "signal=buy"}]
    _make_export(export_dir, "2026-08-15T10:15:00-04:00", 10150.0, trades=trade2)
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    trade_rows = _read_csv(os.path.join(target_dir, "trade_log.csv"))
    assert len(trade_rows) == 2
    assert trade_rows[0]["symbol"] == "AAPL"
    assert trade_rows[1]["symbol"] == "SPY"


def test_merge_does_not_append_when_a_cycle_had_zero_trades(tmp_path):
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")
    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10100.0, trades=[])
    merge_export(export_dir=export_dir, target_data_dir=target_dir)
    trade_rows = _read_csv(os.path.join(target_dir, "trade_log.csv"))
    assert trade_rows == []


def test_merge_overwrites_status_rather_than_appending(tmp_path):
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")
    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10100.0, symbols=("AAPL", "SPY"))
    merge_export(export_dir=export_dir, target_data_dir=target_dir)
    _make_export(export_dir, "2026-08-15T10:15:00-04:00", 10150.0, symbols=("AAPL", "SPY"))
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    status_rows = _read_csv(os.path.join(target_dir, "status.csv"))
    assert len(status_rows) == 2  # not 4 -- overwritten, not appended
    assert all(r["last_cycle_timestamp"] == "2026-08-15T10:15:00-04:00" for r in status_rows)


def test_two_run_round_trip_simulation_preserves_append_vs_overwrite_semantics(tmp_path):
    # The design doc's required "actually execute the workflow logic twice"
    # test: exercises the exact append (equity/trades) vs overwrite (status)
    # split end to end, the same way the real cron will run it twice in a row.
    export_dir = str(tmp_path / "export")
    target_dir = str(tmp_path / "target")

    _make_export(export_dir, "2026-08-15T10:00:00-04:00", 10000.0,
                  trades=[{"timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 150.0, "reason": "signal=buy"}])
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    _make_export(export_dir, "2026-08-15T10:15:00-04:00", 10050.0, trades=[])
    merge_export(export_dir=export_dir, target_data_dir=target_dir)

    assert len(_read_csv(os.path.join(target_dir, "equity_curve.csv"))) == 2
    assert len(_read_csv(os.path.join(target_dir, "trade_log.csv"))) == 1
    assert len(_read_csv(os.path.join(target_dir, "status.csv"))) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_merge_dashboard_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'merge_dashboard_export'`

- [ ] **Step 3: Write `merge_dashboard_export.py`**

Create `merge_dashboard_export.py` at the repo root:

```python
#!/usr/bin/env python3
"""Merges one cycle's local export directory (graywind_strategy/dashboard_export.py's
output) into a checkout of graywind-dashboard's data/ directory: equity_curve.csv and
trade_log.csv are APPENDED to (they accumulate history across every cycle ever run),
status.csv is fully OVERWRITTEN (it's a snapshot of the most recent cycle only).

Invoked by .github/workflows/live-trading.yml after cloning graywind-dashboard, and
directly by tests against scratch directories -- never against a real clone in a test.
"""
import csv
import os
import shutil
import sys

EQUITY_CURVE_FILENAME = "equity_curve.csv"
TRADE_LOG_FILENAME = "trade_log.csv"
STATUS_FILENAME = "status.csv"
EQUITY_POINT_FIELDS = ["timestamp", "equity"]
TRADE_FIELDS = ["timestamp", "symbol", "side", "qty", "price", "reason"]


def _append_csv(source_path, target_path, fieldnames):
    with open(source_path, newline="") as f:
        new_rows = list(csv.DictReader(f))
    if not new_rows:
        # Still ensure the target file exists with a header even on a
        # zero-row cycle, so the dashboard's fetch() never 404s.
        if not os.path.exists(target_path):
            os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
            with open(target_path, "w", newline="") as f:
                csv.DictWriter(f, fieldnames=fieldnames).writeheader()
        return

    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    file_exists = os.path.exists(target_path)
    with open(target_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(new_rows)


def merge_export(export_dir, target_data_dir):
    os.makedirs(target_data_dir, exist_ok=True)

    _append_csv(
        os.path.join(export_dir, "new_equity_point.csv"),
        os.path.join(target_data_dir, EQUITY_CURVE_FILENAME),
        EQUITY_POINT_FIELDS,
    )
    _append_csv(
        os.path.join(export_dir, "new_trades.csv"),
        os.path.join(target_data_dir, TRADE_LOG_FILENAME),
        TRADE_FIELDS,
    )
    shutil.copyfile(
        os.path.join(export_dir, "status.csv"),
        os.path.join(target_data_dir, STATUS_FILENAME),
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: merge_dashboard_export.py <export_dir> <target_data_dir>", file=sys.stderr)
        sys.exit(1)
    merge_export(export_dir=sys.argv[1], target_data_dir=sys.argv[2])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_merge_dashboard_export.py -v`
Expected: PASS (all 7 cases, including the two-run round-trip simulation)

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add merge_dashboard_export.py tests/test_merge_dashboard_export.py
git commit -m "Add merge_dashboard_export.py with append/overwrite semantics"
```

---

### Task 5: Scaffold the `graywind-dashboard` repo locally

**Files:**
- Create (new sibling repo): `~/Projects/graywind-dashboard/data/equity_curve.csv`
- Create: `~/Projects/graywind-dashboard/data/trade_log.csv`
- Create: `~/Projects/graywind-dashboard/data/status.csv`
- Create: `~/Projects/graywind-dashboard/index.html`
- Create: `~/Projects/graywind-dashboard/_config.yml`
- Create: `~/Projects/graywind-dashboard/README.md`

**Interfaces:**
- Consumes: the exact CSV column names Task 2/Task 4 use (`EQUITY_POINT_FIELDS`, `TRADE_FIELDS`, `STATUS_FIELDS` above) — `index.html`'s JS parsing must match them exactly.
- Produces: a private local git repo, un-pushed (no remote exists yet — this task only prepares content; Task 7 is the manual checkpoint that creates the GitHub repo and pushes it).

This task has no tests of its own (it's static HTML/CSV, not Python) — its correctness is checked by opening `index.html` directly in a browser against the seed CSVs (Step 5 below), and later end-to-end once real data flows in via Task 7's dry run.

- [ ] **Step 1: Create the directory and seed CSV files with headers only**

```bash
mkdir -p ~/Projects/graywind-dashboard/data
```

Create `~/Projects/graywind-dashboard/data/equity_curve.csv`:
```
timestamp,equity
```

Create `~/Projects/graywind-dashboard/data/trade_log.csv`:
```
timestamp,symbol,side,qty,price,reason
```

Create `~/Projects/graywind-dashboard/data/status.csv`:
```
last_cycle_timestamp,account_equity,today_pnl,symbol,position_open,shares,entry_price,current_price,action,reason
2026-08-15T00:00:00-04:00,,,AAPL,,,,,unknown,no cycle has run yet
2026-08-15T00:00:00-04:00,,,SPY,,,,,unknown,no cycle has run yet
```

- [ ] **Step 2: Create `index.html`**

Create `~/Projects/graywind-dashboard/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Graywind — Live Status</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  body { font-family: -apple-system, sans-serif; background: #0b0e11; color: #e6e6e6; margin: 0; padding: 24px; }
  h1, h2 { font-weight: 500; }
  #chart { width: 100%; height: 320px; }
  .line { fill: none; stroke: #4dabf7; stroke-width: 2; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #2a2f36; font-size: 14px; }
  th { color: #9aa4b2; font-weight: 500; }
  .pnl-positive { color: #51cf66; }
  .pnl-negative { color: #ff6b6b; }
  #trade-log { max-height: 360px; overflow-y: auto; }
</style>
</head>
<body>
<h1>Graywind — Live Status</h1>
<div id="status-panel"></div>
<h2>Equity Curve</h2>
<svg id="chart"></svg>
<h2>Trade Log</h2>
<div id="trade-log"><table id="trade-table"><thead>
  <tr><th>Timestamp</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Price</th><th>Reason</th></tr>
</thead><tbody></tbody></table></div>

<script>
function parseCSV(text) {
  const lines = text.trim().split("\n");
  const headers = lines[0].split(",");
  return lines.slice(1).filter(l => l.length > 0).map(line => {
    const values = line.split(",");
    const row = {};
    headers.forEach((h, i) => { row[h] = values[i]; });
    return row;
  });
}

async function loadCSV(path) {
  const res = await fetch(path);
  const text = await res.text();
  return parseCSV(text);
}

function renderStatus(statusRows) {
  const panel = document.getElementById("status-panel");
  if (statusRows.length === 0) { panel.textContent = "No status data yet."; return; }
  const first = statusRows[0];
  const pnl = parseFloat(first.today_pnl);
  const pnlClass = pnl > 0 ? "pnl-positive" : (pnl < 0 ? "pnl-negative" : "");
  let html = `<p>Last cycle: ${first.last_cycle_timestamp} &middot; Equity: $${first.account_equity} &middot; `
    + `Today's P&amp;L: <span class="${pnlClass}">$${first.today_pnl}</span></p>`;
  html += "<table><thead><tr><th>Symbol</th><th>Position</th><th>Action</th><th>Reason</th></tr></thead><tbody>";
  for (const row of statusRows) {
    const position = row.position_open === "True" ? `${row.shares} sh @ $${row.entry_price}` : "flat";
    html += `<tr><td>${row.symbol}</td><td>${position}</td><td>${row.action}</td><td>${row.reason}</td></tr>`;
  }
  html += "</tbody></table>";
  panel.innerHTML = html;
}

function renderTradeLog(tradeRows) {
  const tbody = document.querySelector("#trade-table tbody");
  tbody.innerHTML = "";
  for (const row of tradeRows.slice().reverse()) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${row.timestamp}</td><td>${row.symbol}</td><td>${row.side}</td>`
      + `<td>${row.qty}</td><td>${row.price}</td><td>${row.reason}</td>`;
    tbody.appendChild(tr);
  }
}

function renderEquityCurve(equityRows) {
  const svg = d3.select("#chart");
  const width = svg.node().clientWidth || 800;
  const height = 320;
  const margin = { top: 16, right: 16, bottom: 32, left: 64 };
  svg.attr("viewBox", `0 0 ${width} ${height}`);

  if (equityRows.length === 0) return;

  const data = equityRows
    .filter(r => r.equity !== "")
    .map(r => ({ time: new Date(r.timestamp), equity: parseFloat(r.equity) }));

  const x = d3.scaleTime()
    .domain(d3.extent(data, d => d.time))
    .range([margin.left, width - margin.right]);
  const y = d3.scaleLinear()
    .domain([d3.min(data, d => d.equity) * 0.98, d3.max(data, d => d.equity) * 1.02])
    .range([height - margin.bottom, margin.top]);

  const line = d3.line().x(d => x(d.time)).y(d => y(d.equity));

  svg.append("g")
    .attr("transform", `translate(0,${height - margin.bottom})`)
    .call(d3.axisBottom(x));
  svg.append("g")
    .attr("transform", `translate(${margin.left},0)`)
    .call(d3.axisLeft(y));
  svg.append("path").datum(data).attr("class", "line").attr("d", line);
}

async function main() {
  const [equityRows, tradeRows, statusRows] = await Promise.all([
    loadCSV("data/equity_curve.csv"),
    loadCSV("data/trade_log.csv"),
    loadCSV("data/status.csv"),
  ]);
  renderStatus(statusRows);
  renderTradeLog(tradeRows);
  renderEquityCurve(equityRows);
}

main();
</script>
</body>
</html>
```

- [ ] **Step 3: Create `_config.yml`**

Create `~/Projects/graywind-dashboard/_config.yml` (Bullion precedent — see `_config.yml` in the claudekit/Bullion repo — as a safeguard in case GitHub Pages' Jekyll build ever chokes on this content; harmless if unneeded since this repo has no `docs/` folder to exclude in the first place):

```yaml
# No content currently needs excluding (this repo has no docs/-style
# planning content mixed into the served site), but this file is kept as
# an explicit landing spot for exclusions if Jekyll's build ever
# misinterprets something in data/*.csv or index.html -- see the
# claudekit/Bullion repo's own _config.yml for the precedent incident.
exclude: []
```

- [ ] **Step 4: Create `README.md`**

Create `~/Projects/graywind-dashboard/README.md`:

```markdown
# graywind-dashboard

Static, unlisted dashboard for the [graywind](https://github.com/) paper-trading bot's
burn-in. No build step, no framework — `index.html` is vanilla JS + D3, reading
`data/*.csv` directly via `fetch()`.

This repo has no GitHub Actions workflow of its own. Every file under `data/` is written
and pushed here by `graywind`'s own workflow (`.github/workflows/live-trading.yml`) each
trading cycle — this repo is a pure push target, never a source of truth on its own.

Private repo, unlisted GitHub Pages URL: no login wall, but not indexed or linked
publicly either. See `graywind`'s `docs/superpowers/specs/2026-08-15-graywind-dashboard-design.md`
for the full design rationale.
```

- [ ] **Step 5: Manually verify the seed dashboard renders**

Run: `cd ~/Projects/graywind-dashboard && python3 -m http.server 8000`, then open `http://localhost:8000` in a browser.
Expected: page loads, shows "no cycle has run yet" for both AAPL and SPY in the status table, an empty trade log, and an empty (or blank) equity chart area — no JS console errors. Stop the server (Ctrl-C) once confirmed.

- [ ] **Step 6: Initialize the local git repo and commit**

```bash
cd ~/Projects/graywind-dashboard
git init
git add data/equity_curve.csv data/trade_log.csv data/status.csv index.html _config.yml README.md
git commit -m "Scaffold graywind-dashboard: seed CSVs, index.html, README"
```

---

### Task 6: GitHub Actions workflow in `graywind`

**Files:**
- Create: `.github/workflows/live-trading.yml`

**Interfaces:**
- Consumes: `live_loop.py` (Task 3), `merge_dashboard_export.py`'s CLI (Task 4), `DASHBOARD_REPO_PAT` secret (created manually in Task 7).
- Produces: a scheduled workflow — no other code depends on this file, but Task 7's dry run depends on it existing and being syntactically valid.

This task is YAML, not Python — no pytest step. Validate it via `workflow_dispatch` in Task 7 once secrets exist (that's the "cross-repo push dry run" the design doc requires before trusting the live schedule).

- [ ] **Step 1: Write the workflow file**

Create `.github/workflows/live-trading.yml`:

```yaml
name: Graywind Live Trading Cycle

# Every 15 minutes during regular US market hours. GitHub cron is UTC only
# (no daylight-saving handling) -- 13:30-20:00 UTC covers 9:30am-4:00pm ET
# during EDT (summer); during EST (winter) this fires roughly 30-60 minutes
# late/early relative to the real market open/close on the edges of the
# window, which is acceptable (is_market_hours() in live_loop.py itself
# checks real ET market hours and exits immediately outside them, so an
# extra early/late firing is a no-op, not a bug). workflow_dispatch lets
# this be run by hand for the Task 7 dry run.
on:
  schedule:
    - cron: "*/15 13-20 * * 1-5"
  workflow_dispatch:

# Lets the built-in GITHUB_TOKEN push graywind's own state/*.csv commit and
# manage the pipeline-alarm issue. DASHBOARD_REPO_PAT (a separate,
# fine-grained PAT scoped only to graywind-dashboard) is what authorizes
# the cross-repo push -- GITHUB_TOKEN alone can never reach outside this repo.
permissions:
  contents: write
  issues: write

jobs:
  live-cycle:
    runs-on: ubuntu-latest
    steps:
      - name: Check out graywind
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run the live trading cycle
        env:
          ALPACA_API_KEY: ${{ secrets.ALPACA_API_KEY }}
          ALPACA_API_SECRET: ${{ secrets.ALPACA_API_SECRET }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
        run: python3 live_loop.py

      - name: Commit and push graywind's own state
        # This step's success/failure is independent of the dashboard push
        # below -- state/*.csv is this repo's own operational continuity
        # and must be preserved even if the dashboard push later fails.
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add state/operational.csv state/positions.csv
          if git diff --cached --quiet; then
            echo "No state changes this cycle; nothing to commit."
          else
            git commit -m "Update live state for $(date -u +%FT%H:%M)"
            git push
          fi

      - name: Push this cycle's export to graywind-dashboard
        env:
          DASHBOARD_REPO_PAT: ${{ secrets.DASHBOARD_REPO_PAT }}
        run: |
          git clone "https://x-access-token:${DASHBOARD_REPO_PAT}@github.com/${{ github.repository_owner }}/graywind-dashboard.git" /tmp/graywind-dashboard
          python3 merge_dashboard_export.py dashboard_export /tmp/graywind-dashboard/data
          cd /tmp/graywind-dashboard
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/equity_curve.csv data/trade_log.csv data/status.csv
          if git diff --cached --quiet; then
            echo "No dashboard changes this cycle; nothing to commit."
          else
            git commit -m "Update dashboard data for $(date -u +%FT%H:%M)"
            git push
          fi

      - name: Ensure the pipeline-alarm label exists
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            try {
              await github.rest.issues.createLabel({
                owner: context.repo.owner,
                repo: context.repo.repo,
                name: 'pipeline-alarm',
                color: 'd93f0b',
                description: 'Live trading cycle workflow is failing',
              });
            } catch (err) {
              if (err.status !== 422) throw err; // 422 = label already exists
            }

      - name: Report failure to the alarm issue
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            const runUrl = `${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}`;
            const { data: jobsResponse } = await github.rest.actions.listJobsForWorkflowRun({
              owner: context.repo.owner,
              repo: context.repo.repo,
              run_id: context.runId,
            });
            const failedStep = jobsResponse.jobs
              .flatMap(j => j.steps || [])
              .find(s => s.conclusion === 'failure');
            const stepName = failedStep ? failedStep.name : 'unknown step';
            const now = new Date().toISOString();
            const body = `**${now}** — failing step: **${stepName}**\nRun: ${runUrl}`;

            const { data: issues } = await github.rest.issues.listForRepo({
              owner: context.repo.owner,
              repo: context.repo.repo,
              state: 'open',
              labels: 'pipeline-alarm',
            });

            if (issues.length === 0) {
              await github.rest.issues.create({
                owner: context.repo.owner,
                repo: context.repo.repo,
                title: 'Live trading cycle is failing',
                body,
                labels: ['pipeline-alarm'],
                assignees: [context.repo.owner],
              });
            } else {
              await github.rest.issues.createComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                issue_number: issues[0].number,
                body,
              });
            }

      - name: Close the alarm issue on success
        if: success()
        uses: actions/github-script@v7
        with:
          script: |
            const { data: issues } = await github.rest.issues.listForRepo({
              owner: context.repo.owner,
              repo: context.repo.repo,
              state: 'open',
              labels: 'pipeline-alarm',
            });
            const now = new Date().toISOString();
            for (const issue of issues) {
              await github.rest.issues.createComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                issue_number: issue.number,
                body: `Recovered — the run at ${now} succeeded.`,
              });
              await github.rest.issues.update({
                owner: context.repo.owner,
                repo: context.repo.repo,
                issue_number: issue.number,
                state: 'closed',
              });
            }
```

- [ ] **Step 2: Validate YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/live-trading.yml'))"`
Expected: no output, exit code 0 (confirms valid YAML before it ever reaches GitHub — a real `workflow_dispatch` run needs Task 7's secrets, so this is the only pre-push validation available in this task)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/live-trading.yml
git commit -m "Add live-trading.yml: cron cycle, state commit, dashboard push, failure alerts"
```

---

### Task 7: Manual setup + cross-repo push dry run (human checkpoint)

**Files:** none (GitHub UI/CLI actions, not code)

This task cannot be executed by an agentic worker — it requires the repo owner's GitHub credentials and account-level actions. Surface it explicitly rather than silently assuming it happened, per the design doc's "Manual Setup Required" section.

- [ ] **Step 1: Create the `graywind` GitHub repo and add the remote**

In GitHub: create a new **private** repo named `graywind` under your account. Then:
```bash
cd ~/Projects/graywind
git remote add origin https://github.com/<your-username>/graywind.git
git push -u origin main
```

- [ ] **Step 2: Create the `graywind-dashboard` GitHub repo and push the scaffold**

In GitHub: create a new **private** repo named `graywind-dashboard`. Then:
```bash
cd ~/Projects/graywind-dashboard
git remote add origin https://github.com/<your-username>/graywind-dashboard.git
git push -u origin main
```

- [ ] **Step 3: Generate the fine-grained PAT and add it as a `graywind` secret**

In GitHub Settings → Developer settings → Fine-grained personal access tokens: create a token scoped to **only** the `graywind-dashboard` repository, with **Contents: Read and write** permission (nothing else). Copy it, then in the `graywind` repo: Settings → Secrets and variables → Actions → New repository secret, name `DASHBOARD_REPO_PAT`, paste the token value.

Also add (if not already present from before this feature) the four trading/data secrets `live-trading.yml` reads: `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `FRED_API_KEY`, `FINNHUB_API_KEY`. Per the design doc, obtaining real values for these is tracked separately in `docs/superpowers/burn-in-decision.md` — for this dry run, placeholder/paper-trading values are sufficient as long as they're real enough for `live_loop.py` to run without erroring (a fully synthetic key will fail at the Alpaca API call step, which is fine for confirming the *dashboard push* half of this workflow even if the trading half doesn't complete).

- [ ] **Step 4: Enable GitHub Pages on `graywind-dashboard`**

In the `graywind-dashboard` repo: Settings → Pages → Source: "Deploy from a branch" → Branch: `main`, folder: `/ (root)`. Save. Note the resulting `https://<your-username>.github.io/graywind-dashboard/` URL — this is the unlisted dashboard URL.

- [ ] **Step 5: Cross-repo push dry run**

In the `graywind` repo on GitHub: Actions tab → "Graywind Live Trading Cycle" → "Run workflow" (this is the `workflow_dispatch` trigger). Watch the run.
Expected: the "Push this cycle's export to graywind-dashboard" step succeeds and produces a real commit in `graywind-dashboard` (check its commit history). If the trading-API steps fail (expected if using placeholder Alpaca credentials per Step 3), that's fine for this dry run's purpose **as long as** `live_loop.py`'s own `finally` block still ran and produced `dashboard_export/` — confirm by checking whether `graywind-dashboard`'s `data/status.csv` changed. If it didn't, the trading cycle failed before `write_cycle_export` even got a chance to run (e.g. `is_market_hours()` returned False, or an exception occurred above the `try` block that wraps `write_cycle_export`) — re-run with `workflow_dispatch` during actual market hours ET if needed, since `main()` exits immediately outside them by design.

- [ ] **Step 6: Visit the dashboard URL and confirm it renders**

Open `https://<your-username>.github.io/graywind-dashboard/` in a browser. Expected: the page loads, the status table shows real data from the dry run (or the "no cycle has run yet" seed rows if Step 5's trading steps failed before reaching a symbol), no JS console errors.

Once this task's checkpoints all pass, the schedule trigger takes over automatically every 15 minutes during market hours — no further manual action needed unless the pipeline-alarm issue fires.

# Graywind Manual Trade Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let clicking an open position on the Graywind dashboard place a real Alpaca order — close, sell partial, buy more, or set stop/target — through a token-gated Cloudflare Worker that dispatches a GitHub Actions run, reusing `live_loop.py`'s existing pending-sell-order settlement machinery so nothing new has to duplicate fill/PDT/tier-pool bookkeeping.

**Architecture:** Dashboard panel (vanilla JS, no new deps) → new Cloudflare Worker (`manual-trade-trigger/`, sibling to `cron-trigger/`) validates a token + the request, then calls GitHub's `workflow_dispatch` REST API → new workflow `manual-trade.yml` (same `concurrency: live-cycle` group as `live-trading.yml`, so it never races the scheduled cycle) runs `scripts/execute_manual_trade.py`, which submits the order via `alpaca-py`, updates `graywind_strategy/state_store.py` state, and appends to a new `manual_actions.csv` audit log that the dashboard renders as a "Recent actions" feed.

**Tech Stack:** Python 3.12 + `alpaca-py` (existing), vanilla JS (no framework, matches `index.html`'s existing hand-rolled CSV/fetch code), Cloudflare Workers (plain `fetch` handler, matches `cron-trigger/src/index.js`'s style — no framework), GitHub Actions `workflow_dispatch`.

**Spec:** `docs/superpowers/specs/2026-09-14-graywind-manual-trade-panel-design.md`

## Global Constraints

- Leverage/margin sizing is explicitly out of scope — do not add it anywhere in this plan.
- This only acts on positions already in `open_positions` (tiers 2/3). It never opens a brand-new symbol — that stays on the GitHub-issue approval path (`trade_approval.py`), untouched by this plan.
- Trading account is Alpaca **paper** (`TradingClient(..., paper=True)` in `live_loop.py:892`) — real dollars are not at stake, but state-file correctness still matters because it feeds the bot's own automated decisions.
- A sell-side action (close, sell-partial, set-stop/target) must never be blocked by a drawdown/rolling breaker — only **buy-more** is gated by them, exactly like an automated buy.
- Every action appends one row to `manual_actions.csv` (success or rejection) — nothing here may fail silently past the Worker's synchronous validation step.
- Before any sell-side action submits a new order, it must cancel any existing `pending_sell_order_id` on that position first and confirm the cancellation — a position must never carry two live sell-side orders at once.
- `GRAYWIND_STATE_DIR`/`GRAYWIND_DASHBOARD_DIR` env var convention (`state`/`dashboard-data` for the main "100k" account, `state/small`/`dashboard-data/small` for "small") must be followed exactly as `live_loop.py` and `live-trading.yml` already use it.

---

## File Structure

- **Create:** `graywind_strategy/manual_actions_log.py` — append/read `manual_actions.csv`, the audit trail the dashboard's "Recent actions" feed reads.
- **Create:** `scripts/execute_manual_trade.py` — CLI entrypoint the workflow runs; one handler function per action (close/sell-partial share one handler, buy-more, set-stop/target), plus the pending-order cancel guard shared by the two sell-side handlers.
- **Create:** `tests/test_manual_actions_log.py`, `tests/test_execute_manual_trade.py`.
- **Create:** `.github/workflows/manual-trade.yml` — `workflow_dispatch` workflow, `concurrency: live-cycle` (shared with `live-trading.yml`).
- **Create:** `manual-trade-trigger/wrangler.toml`, `manual-trade-trigger/src/index.js` — new Cloudflare Worker, sibling to `cron-trigger/`.
- **Modify:** `index.html` — `buildPositions` gains a click handler and an action panel; a new `buildManualActionsFeed` renders `manual_actions.csv`; `loadAccount`/`renderAccount` fetch and pass through the new file.

---

## Task 1: Manual actions log module

**Files:**
- Create: `graywind_strategy/manual_actions_log.py`
- Test: `tests/test_manual_actions_log.py`

**Interfaces:**
- Produces: `append_manual_action(dashboard_dir, row: dict) -> None`, `read_recent_manual_actions(dashboard_dir, limit=10) -> list[dict]`, `has_idempotency_key(dashboard_dir, idempotency_key) -> bool`, `MANUAL_ACTIONS_FIELDS`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_manual_actions_log.py
import os

from graywind_strategy.manual_actions_log import (
    append_manual_action, has_idempotency_key, read_recent_manual_actions,
)


def test_append_creates_file_with_header_and_row(tmp_path):
    dashboard_dir = str(tmp_path)
    append_manual_action(dashboard_dir, {
        "timestamp": "2026-09-14T10:00:00-04:00", "symbol": "AAPL", "action": "close",
        "qty": "", "status": "submitted", "reason": "AAPL: sell order o-1 submitted",
        "idempotency_key": "key-1",
    })
    path = os.path.join(dashboard_dir, "manual_actions.csv")
    assert os.path.exists(path)
    rows = read_recent_manual_actions(dashboard_dir)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["idempotency_key"] == "key-1"


def test_append_is_additive_across_calls(tmp_path):
    dashboard_dir = str(tmp_path)
    for i in range(3):
        append_manual_action(dashboard_dir, {
            "timestamp": f"2026-09-14T10:0{i}:00-04:00", "symbol": "AAPL", "action": "close",
            "qty": "", "status": "submitted", "reason": "x", "idempotency_key": f"key-{i}",
        })
    rows = read_recent_manual_actions(dashboard_dir, limit=10)
    assert [r["idempotency_key"] for r in rows] == ["key-0", "key-1", "key-2"]


def test_read_recent_returns_empty_list_when_file_missing(tmp_path):
    assert read_recent_manual_actions(str(tmp_path)) == []


def test_read_recent_respects_limit(tmp_path):
    dashboard_dir = str(tmp_path)
    for i in range(5):
        append_manual_action(dashboard_dir, {
            "timestamp": f"2026-09-14T10:0{i}:00-04:00", "symbol": "AAPL", "action": "close",
            "qty": "", "status": "submitted", "reason": "x", "idempotency_key": f"key-{i}",
        })
    rows = read_recent_manual_actions(dashboard_dir, limit=2)
    assert [r["idempotency_key"] for r in rows] == ["key-3", "key-4"]


def test_has_idempotency_key_true_after_append(tmp_path):
    dashboard_dir = str(tmp_path)
    append_manual_action(dashboard_dir, {
        "timestamp": "t", "symbol": "AAPL", "action": "close", "qty": "",
        "status": "submitted", "reason": "x", "idempotency_key": "dup-key",
    })
    assert has_idempotency_key(dashboard_dir, "dup-key") is True
    assert has_idempotency_key(dashboard_dir, "never-seen") is False


def test_has_idempotency_key_false_when_file_missing(tmp_path):
    assert has_idempotency_key(str(tmp_path), "anything") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_manual_actions_log.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'graywind_strategy.manual_actions_log'`

- [ ] **Step 3: Write the implementation**

```python
# graywind_strategy/manual_actions_log.py
"""Appends to and reads dashboard-data/manual_actions.csv, the audit trail
for every manual trade-panel action (close/sell_partial/buy_more/
set_stop_target) dispatched from index.html's position action panel.

A GitHub Actions workflow_dispatch is fire-and-forget from the browser's
side -- the Worker that triggers it returns as soon as the dispatch is
accepted, long before the script actually runs. This file is the only
place a later rejection (market closed, breaker block, Alpaca error)
becomes visible again: read back by the dashboard's "Recent actions" feed
(see index.html's buildManualActionsFeed).
"""
import csv
import os

MANUAL_ACTIONS_FILENAME = "manual_actions.csv"
MANUAL_ACTIONS_FIELDS = [
    "timestamp", "symbol", "action", "qty", "status", "reason", "idempotency_key",
]


def append_manual_action(dashboard_dir, row):
    os.makedirs(dashboard_dir, exist_ok=True)
    path = os.path.join(dashboard_dir, MANUAL_ACTIONS_FILENAME)
    file_exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANUAL_ACTIONS_FIELDS, lineterminator="\n")
        if not file_exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in MANUAL_ACTIONS_FIELDS})


def read_recent_manual_actions(dashboard_dir, limit=10):
    path = os.path.join(dashboard_dir, MANUAL_ACTIONS_FILENAME)
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[-limit:]


def has_idempotency_key(dashboard_dir, idempotency_key):
    # 500 is generous for a personal-project action log's realistic size;
    # revisit only if this file ever grows large enough to make this slow.
    return any(
        row["idempotency_key"] == idempotency_key
        for row in read_recent_manual_actions(dashboard_dir, limit=500)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_manual_actions_log.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/manual_actions_log.py tests/test_manual_actions_log.py
git commit -m "$(cat <<'EOF'
feat: add manual_actions.csv audit log for the manual trade panel

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UsxGwe1BxzJabT2ZZH3zGA
EOF
)"
```

---

## Task 2: Pending-order cancel guard

**Files:**
- Modify (create): `scripts/execute_manual_trade.py`
- Test: `tests/test_execute_manual_trade.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `cancel_existing_pending_order(trading_client, position: dict) -> bool`. Returns `True` when `position` has no `pending_sell_order_id` or the existing order was successfully cancelled (and pops the key from `position`); returns `False` and leaves `position` untouched when a cancel was attempted but could not be confirmed — callers MUST treat `False` as "abort this action, do not submit a new order."

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_execute_manual_trade.py
from unittest.mock import MagicMock

from scripts.execute_manual_trade import cancel_existing_pending_order


def test_cancel_guard_returns_true_when_no_pending_order():
    trading_client = MagicMock()
    position = {"shares": 10}
    assert cancel_existing_pending_order(trading_client, position) is True
    trading_client.cancel_order_by_id.assert_not_called()


def test_cancel_guard_cancels_and_clears_pending_id():
    trading_client = MagicMock()
    position = {"shares": 10, "pending_sell_order_id": "order-1"}
    assert cancel_existing_pending_order(trading_client, position) is True
    trading_client.cancel_order_by_id.assert_called_once_with("order-1")
    assert "pending_sell_order_id" not in position


def test_cancel_guard_returns_false_on_cancel_failure_and_leaves_position_untouched():
    trading_client = MagicMock()
    trading_client.cancel_order_by_id.side_effect = RuntimeError("already filled")
    position = {"shares": 10, "pending_sell_order_id": "order-1"}
    assert cancel_existing_pending_order(trading_client, position) is False
    assert position["pending_sell_order_id"] == "order-1"
```

`scripts/` needs an `__init__.py` for `from scripts.execute_manual_trade import ...` to resolve during pytest collection (mirrors how `tests/` itself is a plain directory pytest discovers via rootdir, not a package — check first: if `tests/test_seed_tier_pools.py` already imports `scripts.seed_tier_pools` successfully, skip this file).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_execute_manual_trade.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.execute_manual_trade'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/execute_manual_trade.py
#!/usr/bin/env python3
"""Executes one manual trade-panel action (close, sell_partial, buy_more,
set_stop_target) against Alpaca, dispatched by manual-trade.yml on behalf
of index.html's position action panel via the manual-trade-trigger
Cloudflare Worker.

Deliberately reuses graywind_strategy/state_store.py's existing schema
rather than inventing new settlement bookkeeping: a sell-side action
(close/sell_partial/set_stop_target) never settles here -- it only submits
the order and records `pending_sell_order_id`, handing settlement (real
fill price, tier_pools credit, PDT recording) to live_loop.py's existing
pending-order machinery (live_loop.py:348-430), identical to how a
stop/target exit settles today. Only buy_more updates state synchronously
here, mirroring process_pending_trades' existing approved-buy path
(live_loop.py:809-839), which assumes a market buy fills at
approximately the fetched price.

Requires ALPACA_API_KEY/ALPACA_API_SECRET in the environment (selected by
manual-trade.yml per --account) -- see .env.example.
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import (
    LimitOrderRequest, MarketOrderRequest, StopLossRequest, StopOrderRequest,
    TakeProfitRequest,
)

from fetch_alpaca_data import fetch_bars
from graywind_strategy import manual_actions_log, state_store
from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker, build_rolling_breakers
from graywind_strategy.tier_config import SYMBOL_TIER

ET = ZoneInfo("America/New_York")


def cancel_existing_pending_order(trading_client, position):
    """See module docstring's "Global Constraints" note in the plan: a
    sell-side action must never leave two live orders against the same
    shares. `position` may already carry a `pending_sell_order_id` from an
    earlier stop/target order or a close/sell-partial still awaiting
    next-cycle settlement.

    A cancel failure is treated as "state unknown, do not proceed" rather
    than trying to distinguish a transient API error from "the order
    already filled" -- guessing wrong in the filled case would submit a
    second real sell against shares that are already gone. Fails closed;
    the caller surfaces this as a rejection and the position resolves
    itself on the next live_loop cycle either way.
    """
    pending_id = position.get("pending_sell_order_id")
    if not pending_id:
        return True
    try:
        trading_client.cancel_order_by_id(pending_id)
    except Exception as exc:
        print(f"could not cancel existing pending order {pending_id}: {exc}", file=sys.stderr)
        return False
    position.pop("pending_sell_order_id", None)
    return True


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, choices=["100k", "small"])
    parser.add_argument("--symbol", required=True)
    parser.add_argument(
        "--action", required=True,
        choices=["close", "sell_partial", "buy_more", "set_stop_target"],
    )
    parser.add_argument("--qty", type=float, default=None)
    parser.add_argument("--stop-price", type=float, default=None)
    parser.add_argument("--target-price", type=float, default=None)
    parser.add_argument("--idempotency-key", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(1)  # placeholder entrypoint; replaced by main() in Task 5
```

`__init__.py` note: run `ls scripts/__init__.py` first — if `tests/test_seed_tier_pools.py` already does `from scripts.seed_tier_pools import ...` and passes today, no new `__init__.py` is needed and this step is a no-op.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_execute_manual_trade.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/execute_manual_trade.py tests/test_execute_manual_trade.py
git commit -m "$(cat <<'EOF'
feat: add pending-order cancel guard for the manual trade script

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UsxGwe1BxzJabT2ZZH3zGA
EOF
)"
```

---

## Task 3: Close / sell-partial action handler

**Files:**
- Modify: `scripts/execute_manual_trade.py`
- Test: `tests/test_execute_manual_trade.py`

**Interfaces:**
- Consumes: `cancel_existing_pending_order` (Task 2).
- Produces: `handle_close_or_sell_partial(trading_client, state: dict, symbol: str, qty: float | None) -> dict` returning `{"status": "submitted" | "rejected", "reason": str}`. `state` is a `state_store.load_state()`-shaped dict (`state["open_positions"]`); this function mutates `state["open_positions"][symbol]` in place (sets `pending_sell_order_id`) — later tasks (state save) rely on that in-place mutation.

- [ ] **Step 1: Write the failing tests**

```python
def test_close_rejects_when_no_local_position():
    trading_client = MagicMock()
    state = {"open_positions": {}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=None)
    assert result["status"] == "rejected"
    assert "no locally tracked open position" in result["reason"]
    trading_client.submit_order.assert_not_called()


def test_close_sells_full_shares_and_sets_pending_id():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-9"
    state = {"open_positions": {"AAPL": {
        "entry_price": 100.0, "shares": 10.0, "stop": 90.0, "target": 120.0,
        "opened_date": "2026-09-01",
    }}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=None)
    assert result["status"] == "submitted"
    order = trading_client.submit_order.call_args[0][0]
    assert order.symbol == "AAPL" and order.qty == 10.0 and order.side == OrderSide.SELL
    assert state["open_positions"]["AAPL"]["pending_sell_order_id"] == "order-9"


def test_sell_partial_caps_qty_at_held_shares():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-10"
    state = {"open_positions": {"AAPL": {
        "entry_price": 100.0, "shares": 10.0, "stop": 90.0, "target": 120.0,
        "opened_date": "2026-09-01",
    }}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=999.0)
    assert result["status"] == "submitted"
    order = trading_client.submit_order.call_args[0][0]
    assert order.qty == 10.0


def test_close_cancels_existing_pending_order_first():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-11"
    state = {"open_positions": {"AAPL": {
        "entry_price": 100.0, "shares": 10.0, "stop": 90.0, "target": 120.0,
        "opened_date": "2026-09-01", "pending_sell_order_id": "order-old",
    }}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=None)
    trading_client.cancel_order_by_id.assert_called_once_with("order-old")
    assert result["status"] == "submitted"
    assert state["open_positions"]["AAPL"]["pending_sell_order_id"] == "order-11"


def test_close_rejects_when_cancel_of_existing_order_fails():
    trading_client = MagicMock()
    trading_client.cancel_order_by_id.side_effect = RuntimeError("already filled")
    state = {"open_positions": {"AAPL": {
        "entry_price": 100.0, "shares": 10.0, "stop": 90.0, "target": 120.0,
        "opened_date": "2026-09-01", "pending_sell_order_id": "order-old",
    }}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=None)
    assert result["status"] == "rejected"
    trading_client.submit_order.assert_not_called()
    assert state["open_positions"]["AAPL"]["pending_sell_order_id"] == "order-old"


def test_close_rejects_when_submit_order_raises():
    trading_client = MagicMock()
    trading_client.submit_order.side_effect = RuntimeError("market closed")
    state = {"open_positions": {"AAPL": {
        "entry_price": 100.0, "shares": 10.0, "stop": 90.0, "target": 120.0,
        "opened_date": "2026-09-01",
    }}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=None)
    assert result["status"] == "rejected"
    assert "market closed" in result["reason"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_execute_manual_trade.py -v`
Expected: FAIL with `ImportError: cannot import name 'handle_close_or_sell_partial'`

- [ ] **Step 3: Write the implementation** (add to `scripts/execute_manual_trade.py`, above the `if __name__ == "__main__":` line)

```python
def handle_close_or_sell_partial(trading_client, state, symbol, qty):
    position = state["open_positions"].get(symbol)
    if position is None:
        return {"status": "rejected", "reason": f"{symbol}: no locally tracked open position"}

    sell_qty = position["shares"] if qty is None else min(qty, position["shares"])

    if not cancel_existing_pending_order(trading_client, position):
        return {
            "status": "rejected",
            "reason": f"{symbol}: could not confirm cancellation of an existing pending "
                      "order; try again next cycle",
        }

    order = MarketOrderRequest(
        symbol=symbol, qty=sell_qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
    )
    try:
        submitted = trading_client.submit_order(order)
    except Exception as exc:
        return {"status": "rejected", "reason": f"{symbol}: order submission failed ({exc})"}

    position["pending_sell_order_id"] = str(submitted.id)
    return {
        "status": "submitted",
        "reason": f"{symbol}: sell order {submitted.id} submitted for {sell_qty} shares; "
                  "settles on the next live cycle",
    }
```

Also add these imports at the top of the test file:
```python
from unittest.mock import MagicMock

from alpaca.trading.enums import OrderSide

from scripts.execute_manual_trade import (
    cancel_existing_pending_order, handle_close_or_sell_partial,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_execute_manual_trade.py -v`
Expected: PASS (9 tests total)

- [ ] **Step 5: Commit**

```bash
git add scripts/execute_manual_trade.py tests/test_execute_manual_trade.py
git commit -m "$(cat <<'EOF'
feat: add close/sell-partial handler to the manual trade script

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UsxGwe1BxzJabT2ZZH3zGA
EOF
)"
```

---

## Task 4: Buy-more action handler

**Files:**
- Modify: `scripts/execute_manual_trade.py`
- Test: `tests/test_execute_manual_trade.py`

**Interfaces:**
- Consumes: `DrawdownBreaker`, `build_rolling_breakers` (existing, `graywind_strategy/risk/drawdown_breaker.py`); `state_store.load_equity_history` (existing); `fetch_bars` (existing, `fetch_alpaca_data.py`); `SYMBOL_TIER` (existing, `graywind_strategy/tier_config.py`).
- Produces: `handle_buy_more(trading_client, data_client, state, state_dir, tier_pools, symbol, qty, today) -> dict`, same `{"status", "reason"}` shape. Mutates `state["open_positions"][symbol]` (`shares`, `entry_price`) and `tier_pools[tier]` in place.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date


def _drawdown_breaker_allows(monkeypatch):
    # Both gates default permissive with no persisted history -- matches
    # DrawdownBreaker/RollingDrawdownBreaker's own documented cold-start
    # behavior (see graywind_strategy/risk/drawdown_breaker.py).
    pass


def test_buy_more_rejects_without_qty():
    trading_client = MagicMock()
    state = {"open_positions": {"AAPL": {"shares": 10.0, "entry_price": 100.0}},
             "day": None, "starting_equity": None}
    result = handle_buy_more(
        trading_client, MagicMock(), state, "state", {2: 1000.0}, "AAPL", None, date(2026, 9, 14),
    )
    assert result["status"] == "rejected"
    assert "positive --qty" in result["reason"]


def test_buy_more_rejects_when_no_local_position():
    trading_client = MagicMock()
    state = {"open_positions": {}, "day": None, "starting_equity": None}
    result = handle_buy_more(
        trading_client, MagicMock(), state, "state", {2: 1000.0}, "AAPL", 5.0, date(2026, 9, 14),
    )
    assert result["status"] == "rejected"
    assert "no locally tracked open position" in result["reason"]


def test_buy_more_rejects_when_symbol_has_no_tier(monkeypatch):
    monkeypatch.setitem(__import__("graywind_strategy.tier_config", fromlist=["SYMBOL_TIER"]).SYMBOL_TIER, "ZZZZ", None)
    trading_client = MagicMock()
    state = {"open_positions": {"ZZZZ": {"shares": 10.0, "entry_price": 100.0}},
             "day": None, "starting_equity": None}
    result = handle_buy_more(
        trading_client, MagicMock(), state, "state", {}, "ZZZZ", 5.0, date(2026, 9, 14),
    )
    assert result["status"] == "rejected"
    assert "no tier" in result["reason"]


def test_buy_more_rejects_when_daily_breaker_blocks(monkeypatch):
    trading_client = MagicMock()
    trading_client.get_account.return_value.equity = "1000.0"
    state = {"open_positions": {"AAPL": {"shares": 10.0, "entry_price": 100.0}},
             "day": "2026-09-14", "starting_equity": 2000.0}  # already down 50% today
    with patch("scripts.execute_manual_trade.state_store.load_equity_history", return_value=[]):
        result = handle_buy_more(
            trading_client, MagicMock(), state, "state", {2: 1000.0}, "AAPL", 5.0,
            date(2026, 9, 14),
        )
    assert result["status"] == "rejected"
    assert "drawdown breaker" in result["reason"]
    trading_client.submit_order.assert_not_called()


def test_buy_more_rejects_when_tier_pool_insufficient():
    trading_client = MagicMock()
    trading_client.get_account.return_value.equity = "1000.0"
    data_client = MagicMock()
    fake_bar = MagicMock(close=100.0)
    state = {"open_positions": {"AAPL": {"shares": 10.0, "entry_price": 100.0}},
             "day": None, "starting_equity": None}
    with patch("scripts.execute_manual_trade.state_store.load_equity_history", return_value=[]), \
         patch("scripts.execute_manual_trade.fetch_bars", return_value=[fake_bar]):
        result = handle_buy_more(
            trading_client, data_client, state, "state", {2: 50.0}, "AAPL", 5.0,
            date(2026, 9, 14),
        )
    assert result["status"] == "rejected"
    assert "pool has" in result["reason"]
    trading_client.submit_order.assert_not_called()


def test_buy_more_submits_and_updates_state_and_tier_pool():
    trading_client = MagicMock()
    trading_client.get_account.return_value.equity = "1000.0"
    data_client = MagicMock()
    fake_bar = MagicMock(close=100.0)
    state = {"open_positions": {"AAPL": {"shares": 10.0, "entry_price": 100.0}},
             "day": None, "starting_equity": None}
    tier_pools = {2: 1000.0}
    with patch("scripts.execute_manual_trade.state_store.load_equity_history", return_value=[]), \
         patch("scripts.execute_manual_trade.fetch_bars", return_value=[fake_bar]):
        result = handle_buy_more(
            trading_client, data_client, state, "state", tier_pools, "AAPL", 5.0,
            date(2026, 9, 14),
        )
    assert result["status"] == "submitted"
    order = trading_client.submit_order.call_args[0][0]
    assert order.symbol == "AAPL" and order.qty == 5.0 and order.side == OrderSide.BUY
    assert state["open_positions"]["AAPL"]["shares"] == 15.0
    # weighted average: (10*100 + 5*100) / 15 == 100.0
    assert state["open_positions"]["AAPL"]["entry_price"] == 100.0
    assert tier_pools[2] == 1000.0 - 5.0 * 100.0
```

Add `from unittest.mock import patch` and `from datetime import date` to the test file's imports; `SYMBOL_TIER` already has `"AAPL": 2` in `graywind_strategy/tier_config.py`, so tests that use `"AAPL"` don't need to patch the tier map.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_execute_manual_trade.py -v`
Expected: FAIL with `ImportError: cannot import name 'handle_buy_more'`

- [ ] **Step 3: Write the implementation** (add to `scripts/execute_manual_trade.py`)

```python
def handle_buy_more(trading_client, data_client, state, state_dir, tier_pools, symbol, qty, today):
    if qty is None or qty <= 0:
        return {"status": "rejected", "reason": f"{symbol}: buy_more requires a positive --qty"}

    position = state["open_positions"].get(symbol)
    if position is None:
        return {"status": "rejected", "reason": f"{symbol}: no locally tracked open position to add to"}

    tier = SYMBOL_TIER.get(symbol)
    if tier is None:
        return {"status": "rejected", "reason": f"{symbol}: no tier in SYMBOL_TIER; refusing to size a buy"}

    account = trading_client.get_account()
    equity = float(account.equity)
    # Same formula main() uses (live_loop.py:955): reuse today's already-
    # established baseline if one exists, otherwise this cycle's equity IS
    # the baseline. Deliberately does not persist this via save_state --
    # if this runs before the day's first automated cycle, that cycle
    # still establishes its own baseline the same way; a same-day
    # difference of a few minutes' equity drift is an acceptable
    # approximation for a paper account, not a correctness bug.
    starting_equity = state["starting_equity"] if state["day"] == today.isoformat() else equity

    drawdown_breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    if starting_equity > 0:
        drawdown_breaker.start_new_day(today, starting_equity)
        drawdown_breaker.update_equity(equity)
    else:
        drawdown_breaker.trip()
    if not drawdown_breaker.can_open_new_trade():
        return {"status": "rejected", "reason": f"{symbol}: daily drawdown breaker blocks new buys right now"}

    rolling_breakers = build_rolling_breakers()
    equity_history = state_store.load_equity_history(state_dir=state_dir)
    for breaker in rolling_breakers:
        breaker.load_history(equity_history)
    if not all(b.can_open_new_trade() for b in rolling_breakers):
        return {"status": "rejected", "reason": f"{symbol}: a rolling drawdown breaker blocks new buys right now"}

    now = datetime.now(ET)
    bars = fetch_bars(data_client, symbol, now - timedelta(days=21), now)
    if not bars:
        return {"status": "rejected", "reason": f"{symbol}: could not fetch a current price"}
    current_price = bars[-1].close
    cost = qty * current_price
    pool_cash = tier_pools.get(tier, 0.0)
    if cost > pool_cash:
        return {
            "status": "rejected",
            "reason": f"{symbol}: tier {tier} pool has ${pool_cash:.2f}, needs ${cost:.2f}",
        }

    order = MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
    try:
        trading_client.submit_order(order)
    except Exception as exc:
        return {"status": "rejected", "reason": f"{symbol}: buy order submission failed ({exc})"}

    total_shares = position["shares"] + qty
    position["entry_price"] = (position["entry_price"] * position["shares"] + current_price * qty) / total_shares
    position["shares"] = total_shares
    tier_pools[tier] = pool_cash - cost
    return {"status": "submitted", "reason": f"{symbol}: bought {qty} more shares at ~{current_price}"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_execute_manual_trade.py -v`
Expected: PASS (15 tests total)

- [ ] **Step 5: Commit**

```bash
git add scripts/execute_manual_trade.py tests/test_execute_manual_trade.py
git commit -m "$(cat <<'EOF'
feat: add buy-more handler with breaker and tier-pool gates

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UsxGwe1BxzJabT2ZZH3zGA
EOF
)"
```

---

## Task 5: Set stop/target action handler

**Files:**
- Modify: `scripts/execute_manual_trade.py`
- Test: `tests/test_execute_manual_trade.py`

**Interfaces:**
- Consumes: `cancel_existing_pending_order` (Task 2).
- Produces: `handle_set_stop_target(trading_client, state, symbol, stop_price, target_price) -> dict`.

**Order-type note:** a real Alpaca OCO order requires *both* a take-profit and a stop-loss leg — it can't represent "just a stop" or "just a target." So this handler submits an OCO only when both prices are given; a single price submits a plain stop order or plain limit sell order instead. All three still set `pending_sell_order_id`, so live_loop.py's existing pending-order guard (`live_loop.py:417`, `not position.get("pending_sell_order_id")`) suppresses its own software-side stop/target check the same way regardless of which order type is resting.

- [ ] **Step 1: Write the failing tests**

```python
def test_set_stop_target_rejects_when_no_local_position():
    trading_client = MagicMock()
    state = {"open_positions": {}}
    result = handle_set_stop_target(trading_client, state, "AAPL", 90.0, 120.0)
    assert result["status"] == "rejected"


def test_set_stop_target_rejects_when_no_prices_given():
    trading_client = MagicMock()
    state = {"open_positions": {"AAPL": {"shares": 10.0, "stop": 90.0, "target": 120.0}}}
    result = handle_set_stop_target(trading_client, state, "AAPL", None, None)
    assert result["status"] == "rejected"
    assert "stop price, a target price, or both" in result["reason"]


def test_set_stop_target_both_prices_submits_oco():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-oco-1"
    state = {"open_positions": {"AAPL": {"shares": 10.0, "stop": 90.0, "target": 120.0}}}
    result = handle_set_stop_target(trading_client, state, "AAPL", 95.0, 130.0)
    assert result["status"] == "submitted"
    order = trading_client.submit_order.call_args[0][0]
    assert order.order_class == OrderClass.OCO
    assert order.qty == 10.0 and order.side == OrderSide.SELL
    assert state["open_positions"]["AAPL"]["pending_sell_order_id"] == "order-oco-1"
    assert state["open_positions"]["AAPL"]["stop"] == 95.0
    assert state["open_positions"]["AAPL"]["target"] == 130.0


def test_set_stop_target_stop_only_submits_plain_stop_order():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-stop-1"
    state = {"open_positions": {"AAPL": {"shares": 10.0, "stop": 90.0, "target": 120.0}}}
    result = handle_set_stop_target(trading_client, state, "AAPL", 95.0, None)
    assert result["status"] == "submitted"
    order = trading_client.submit_order.call_args[0][0]
    assert isinstance(order, StopOrderRequest)
    assert order.stop_price == 95.0
    assert state["open_positions"]["AAPL"]["stop"] == 95.0
    assert state["open_positions"]["AAPL"]["target"] == 120.0  # unchanged


def test_set_stop_target_target_only_submits_plain_limit_order():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-limit-1"
    state = {"open_positions": {"AAPL": {"shares": 10.0, "stop": 90.0, "target": 120.0}}}
    result = handle_set_stop_target(trading_client, state, "AAPL", None, 130.0)
    assert result["status"] == "submitted"
    order = trading_client.submit_order.call_args[0][0]
    assert isinstance(order, LimitOrderRequest) and order.order_class != OrderClass.OCO
    assert order.limit_price == 130.0
    assert state["open_positions"]["AAPL"]["target"] == 130.0


def test_set_stop_target_cancels_existing_pending_order_first():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-oco-2"
    state = {"open_positions": {"AAPL": {
        "shares": 10.0, "stop": 90.0, "target": 120.0, "pending_sell_order_id": "order-old",
    }}}
    result = handle_set_stop_target(trading_client, state, "AAPL", 95.0, 130.0)
    trading_client.cancel_order_by_id.assert_called_once_with("order-old")
    assert result["status"] == "submitted"
```

Add `from alpaca.trading.enums import OrderClass` and `from alpaca.trading.requests import LimitOrderRequest, StopOrderRequest` to the test file's imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_execute_manual_trade.py -v`
Expected: FAIL with `ImportError: cannot import name 'handle_set_stop_target'`

- [ ] **Step 3: Write the implementation** (add to `scripts/execute_manual_trade.py`)

```python
def handle_set_stop_target(trading_client, state, symbol, stop_price, target_price):
    position = state["open_positions"].get(symbol)
    if position is None:
        return {"status": "rejected", "reason": f"{symbol}: no locally tracked open position"}
    if stop_price is None and target_price is None:
        return {"status": "rejected", "reason": f"{symbol}: must supply a stop price, a target price, or both"}

    if not cancel_existing_pending_order(trading_client, position):
        return {
            "status": "rejected",
            "reason": f"{symbol}: could not confirm cancellation of an existing pending "
                      "order; try again next cycle",
        }

    shares = position["shares"]
    if stop_price is not None and target_price is not None:
        order = LimitOrderRequest(
            symbol=symbol, qty=shares, side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
            order_class=OrderClass.OCO, limit_price=target_price,
            take_profit=TakeProfitRequest(limit_price=target_price),
            stop_loss=StopLossRequest(stop_price=stop_price),
        )
    elif stop_price is not None:
        order = StopOrderRequest(
            symbol=symbol, qty=shares, side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
            stop_price=stop_price,
        )
    else:
        order = LimitOrderRequest(
            symbol=symbol, qty=shares, side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
            limit_price=target_price,
        )

    try:
        submitted = trading_client.submit_order(order)
    except Exception as exc:
        return {"status": "rejected", "reason": f"{symbol}: stop/target order submission failed ({exc})"}

    position["pending_sell_order_id"] = str(submitted.id)
    if stop_price is not None:
        position["stop"] = stop_price
    if target_price is not None:
        position["target"] = target_price
    return {"status": "submitted", "reason": f"{symbol}: stop/target order {submitted.id} resting at Alpaca"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_execute_manual_trade.py -v`
Expected: PASS (21 tests total)

- [ ] **Step 5: Commit**

```bash
git add scripts/execute_manual_trade.py tests/test_execute_manual_trade.py
git commit -m "$(cat <<'EOF'
feat: add set-stop/target handler (OCO, stop-only, or limit-only)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UsxGwe1BxzJabT2ZZH3zGA
EOF
)"
```

---

## Task 6: Wire the CLI entrypoint

**Files:**
- Modify: `scripts/execute_manual_trade.py`
- Test: `tests/test_execute_manual_trade.py`

**Interfaces:**
- Consumes: all four handlers (Tasks 3-5) and `manual_actions_log` (Task 1).
- Produces: `main(argv=None) -> int`. Always returns `0` on a handled outcome (submitted/rejected/error) — only an exception escaping the whole dispatch (state I/O failure) should propagate.

- [ ] **Step 1: Write the failing tests**

```python
from scripts.execute_manual_trade import main


def test_main_no_ops_on_repeated_idempotency_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    dashboard_dir = tmp_path / "dashboard-data"
    from graywind_strategy import manual_actions_log
    manual_actions_log.append_manual_action(str(dashboard_dir), {
        "timestamp": "t", "symbol": "AAPL", "action": "close", "qty": "",
        "status": "submitted", "reason": "x", "idempotency_key": "dup",
    })
    with patch("scripts.execute_manual_trade._dashboard_dir_for", return_value=str(dashboard_dir)), \
         patch("scripts.execute_manual_trade.TradingClient") as mock_client_cls:
        code = main([
            "--account", "100k", "--symbol", "AAPL", "--action", "close",
            "--idempotency-key", "dup",
        ])
    assert code == 0
    mock_client_cls.assert_not_called()


def test_main_dispatches_close_and_persists_state_and_logs_row(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    state_dir = tmp_path / "state"
    dashboard_dir = tmp_path / "dashboard-data"
    from graywind_strategy import state_store
    state_store.save_state(
        {"day": None, "starting_equity": None, "day_trade_dates": [],
         "open_positions": {"AAPL": {
             "entry_price": 100.0, "shares": 10.0, "stop": 90.0, "target": 120.0,
             "opened_date": "2026-09-01",
         }}},
        state_dir=str(state_dir),
    )
    state_store.save_tier_pools({1: 0.0, 2: 500.0, 3: 0.0}, state_dir=str(state_dir))

    fake_client = MagicMock()
    fake_client.submit_order.return_value.id = "order-main-1"
    with patch("scripts.execute_manual_trade._state_dir_for", return_value=str(state_dir)), \
         patch("scripts.execute_manual_trade._dashboard_dir_for", return_value=str(dashboard_dir)), \
         patch("scripts.execute_manual_trade.TradingClient", return_value=fake_client), \
         patch("scripts.execute_manual_trade.StockHistoricalDataClient"):
        code = main([
            "--account", "100k", "--symbol", "AAPL", "--action", "close",
            "--idempotency-key", "key-main-1",
        ])
    assert code == 0
    reloaded = state_store.load_state(state_dir=str(state_dir))
    assert reloaded["open_positions"]["AAPL"]["pending_sell_order_id"] == "order-main-1"
    from graywind_strategy import manual_actions_log
    rows = manual_actions_log.read_recent_manual_actions(str(dashboard_dir))
    assert rows[0]["status"] == "submitted"
    assert rows[0]["idempotency_key"] == "key-main-1"


def test_main_returns_1_when_alpaca_credentials_missing(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    code = main(["--account", "100k", "--symbol", "AAPL", "--action", "close", "--idempotency-key", "k"])
    assert code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_execute_manual_trade.py -v`
Expected: FAIL — `main`/`_state_dir_for`/`_dashboard_dir_for` don't exist yet.

- [ ] **Step 3: Write the implementation** (replace the placeholder `if __name__ == "__main__":` block in `scripts/execute_manual_trade.py`)

```python
def _state_dir_for(account):
    return "state/small" if account == "small" else "state"


def _dashboard_dir_for(account):
    return "dashboard-data/small" if account == "small" else "dashboard-data"


def main(argv=None):
    args = parse_args(argv)
    state_dir = _state_dir_for(args.account)
    dashboard_dir = _dashboard_dir_for(args.account)

    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        print("ERROR: ALPACA_API_KEY/ALPACA_API_SECRET not set", file=sys.stderr)
        return 1

    if manual_actions_log.has_idempotency_key(dashboard_dir, args.idempotency_key):
        print(f"idempotency key {args.idempotency_key} already processed; no-op")
        return 0

    trading_client = TradingClient(api_key, api_secret, paper=True)
    data_client = StockHistoricalDataClient(api_key, api_secret)
    state = state_store.load_state(state_dir=state_dir)
    tier_pools = state_store.load_tier_pools(state_dir=state_dir)
    today = datetime.now(ET).date()

    try:
        if args.action == "close":
            result = handle_close_or_sell_partial(trading_client, state, args.symbol, qty=None)
        elif args.action == "sell_partial":
            result = handle_close_or_sell_partial(trading_client, state, args.symbol, qty=args.qty)
        elif args.action == "buy_more":
            result = handle_buy_more(
                trading_client, data_client, state, state_dir, tier_pools, args.symbol,
                args.qty, today,
            )
        else:
            result = handle_set_stop_target(
                trading_client, state, args.symbol, args.stop_price, args.target_price,
            )
    except Exception as exc:
        result = {"status": "error", "reason": f"{args.symbol}: unexpected error ({exc})"}

    state_store.save_state(state, state_dir=state_dir)
    state_store.save_tier_pools(tier_pools, state_dir=state_dir)
    manual_actions_log.append_manual_action(dashboard_dir, {
        "timestamp": datetime.now(ET).isoformat(),
        "symbol": args.symbol,
        "action": args.action,
        "qty": args.qty if args.qty is not None else "",
        "status": result["status"],
        "reason": result["reason"],
        "idempotency_key": args.idempotency_key,
    })
    print(f"{args.action} {args.symbol}: {result['status']} - {result['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_execute_manual_trade.py -v`
Expected: PASS (24 tests total)

- [ ] **Step 5: Commit**

```bash
git add scripts/execute_manual_trade.py tests/test_execute_manual_trade.py
git commit -m "$(cat <<'EOF'
feat: wire the manual trade script's CLI entrypoint and idempotency guard

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UsxGwe1BxzJabT2ZZH3zGA
EOF
)"
```

---

## Task 7: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/manual-trade.yml`

**Interfaces:**
- Consumes: `scripts/execute_manual_trade.py`'s CLI (Task 6): `--account --symbol --action --qty --stop-price --target-price --idempotency-key`.
- Produces: a `workflow_dispatch`-triggered job the Cloudflare Worker (Task 8) calls by filename.

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/manual-trade.yml
name: Graywind Manual Trade Action

# Dispatched by manual-trade-trigger/ (the Cloudflare Worker behind
# index.html's position action panel) via the workflow_dispatch REST API.
# Never fired by a schedule or by a person directly -- inputs come from
# the dashboard panel's confirm step, validated once already by the
# Worker before this ever runs.
on:
  workflow_dispatch:
    inputs:
      account:
        description: "100k or small"
        required: true
      symbol:
        required: true
      action:
        description: "close | sell_partial | buy_more | set_stop_target"
        required: true
      qty:
        required: false
        default: ""
      stop_price:
        required: false
        default: ""
      target_price:
        required: false
        default: ""
      idempotency_key:
        required: true

permissions:
  contents: write

# Same group as live-trading.yml -- a manual action and a scheduled cycle
# must never read/write state/ or dashboard-data/ at the same time. They
# queue instead of racing (cancel-in-progress: false).
concurrency:
  group: live-cycle
  cancel-in-progress: false

jobs:
  manual-trade:
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

      - name: Execute the manual trade action
        env:
          ALPACA_API_KEY: ${{ inputs.account == 'small' && secrets.ALPACA_API_KEY_SMALL || secrets.ALPACA_API_KEY }}
          ALPACA_API_SECRET: ${{ inputs.account == 'small' && secrets.ALPACA_API_SECRET_SMALL || secrets.ALPACA_API_SECRET }}
        run: |
          python3 scripts/execute_manual_trade.py \
            --account "${{ inputs.account }}" \
            --symbol "${{ inputs.symbol }}" \
            --action "${{ inputs.action }}" \
            ${{ inputs.qty != '' && format('--qty {0}', inputs.qty) || '' }} \
            ${{ inputs.stop_price != '' && format('--stop-price {0}', inputs.stop_price) || '' }} \
            ${{ inputs.target_price != '' && format('--target-price {0}', inputs.target_price) || '' }} \
            --idempotency-key "${{ inputs.idempotency_key }}"

      - name: Commit and push state + dashboard data
        if: always()
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A state 2>/dev/null || true
          git add -A dashboard-data 2>/dev/null || true
          if git diff --cached --quiet; then
            echo "No changes; nothing to commit."
          else
            git commit -m "Manual trade action: ${{ inputs.action }} ${{ inputs.symbol }} (${{ inputs.account }})"
            git fetch origin main
            git rebase origin/main
            git push
          fi
```

- [ ] **Step 2: Validate YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/manual-trade.yml'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/manual-trade.yml
git commit -m "$(cat <<'EOF'
feat: add manual-trade.yml workflow_dispatch for the manual trade panel

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UsxGwe1BxzJabT2ZZH3zGA
EOF
)"
```

(No automated test — this is a thin YAML wrapper around the already-tested script; Task 11's dry run is where this gets exercised for real.)

---

## Task 8: Cloudflare Worker (manual-trade-trigger)

**Files:**
- Create: `manual-trade-trigger/wrangler.toml`
- Create: `manual-trade-trigger/src/index.js`

**Interfaces:**
- Consumes: `.github/workflows/manual-trade.yml`'s `workflow_dispatch` inputs (Task 7): `account, symbol, action, qty, stop_price, target_price, idempotency_key`.
- Produces: a POST endpoint the dashboard panel (Task 9) calls with `{token, account, symbol, action, qty, stop_price, target_price, idempotency_key}`.

- [ ] **Step 1: Write `wrangler.toml`**

```toml
name = "graywind-manual-trade-trigger"
main = "src/index.js"
compatibility_date = "2026-09-03"

# Non-secret: which repo/workflow to dispatch, same convention as
# cron-trigger/wrangler.toml. GITHUB_PAT (needs `actions: write` on this
# repo) and MANUAL_TRADE_TOKEN are set via `wrangler secret put` -- run
# these yourself so the values never pass through this session:
#   wrangler secret put GITHUB_PAT
#   wrangler secret put MANUAL_TRADE_TOKEN
[vars]
GITHUB_OWNER = "SinbadTheExplorer"
GITHUB_REPO = "graywind"
GITHUB_WORKFLOW_FILE = "manual-trade.yml"
DASHBOARD_ORIGIN = "https://sinbadtheexplorer.github.io"
```

- [ ] **Step 2: Write `src/index.js`**

```javascript
// Receives a position action from index.html's action panel, validates it,
// and dispatches manual-trade.yml via workflow_dispatch -- same shape as
// cron-trigger/src/index.js's manual GET, extended to a POST with a JSON
// body and per-request validation instead of a single shared query key.
//
// Fails closed on anything it can't confirm: a bad token, a malformed
// body, or a sell qty greater than the position's actual current shares
// (fetched fresh from this account's status.csv on GitHub, not trusted
// from the request) are all rejected with a 4xx BEFORE any dispatch --
// see docs/superpowers/specs/2026-09-14-graywind-manual-trade-panel-design.md.

const VALID_ACCOUNTS = new Set(["100k", "small"]);
const VALID_ACTIONS = new Set(["close", "sell_partial", "buy_more", "set_stop_target"]);

function corsHeaders(env) {
  return {
    "Access-Control-Allow-Origin": env.DASHBOARD_ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

async function fetchStatusRows(env, account) {
  const path = account === "small" ? "dashboard-data/small/status.csv" : "dashboard-data/status.csv";
  const url = `https://raw.githubusercontent.com/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/main/${path}`;
  const res = await fetch(url);
  if (!res.ok) return null;
  const text = await res.text();
  const lines = text.trim().split(/\r?\n/);
  const headers = lines[0].split(",");
  return lines.slice(1).map(line => {
    const values = line.split(",");
    const row = {};
    headers.forEach((h, i) => { row[h] = values[i]; });
    return row;
  });
}

function validationError(message) {
  return new Response(JSON.stringify({ error: message }), {
    status: 400, headers: { "Content-Type": "application/json" },
  });
}

async function handleManualTrade(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return validationError("malformed JSON body");
  }

  if (body.token !== env.MANUAL_TRADE_TOKEN) {
    // Same shape as cron-trigger's wrong-key handling: indistinguishable
    // from an unrecognized route, so a prober can't tell a wrong token
    // from no route at all.
    return new Response("not found", { status: 404 });
  }

  const { account, symbol, action, qty, stop_price, target_price, idempotency_key } = body;
  if (!VALID_ACCOUNTS.has(account)) return validationError("invalid account");
  if (typeof symbol !== "string" || !symbol) return validationError("invalid symbol");
  if (!VALID_ACTIONS.has(action)) return validationError("invalid action");
  if (typeof idempotency_key !== "string" || !idempotency_key) return validationError("missing idempotency_key");

  if (action === "close" || action === "sell_partial" || action === "buy_more") {
    if (action !== "close" && (typeof qty !== "number" || qty <= 0)) {
      return validationError("qty must be a positive number for this action");
    }
  }

  if (action === "close" || action === "sell_partial") {
    const rows = await fetchStatusRows(env, account);
    if (!rows) return validationError("could not verify current position; try again shortly");
    const row = rows.find(r => r.symbol === symbol);
    const heldShares = row ? parseFloat(row.shares || "0") : 0;
    if (!row || row.position_open !== "True" || heldShares <= 0) {
      return validationError(`${symbol}: no open position to act on`);
    }
    if (action === "sell_partial" && qty > heldShares) {
      return validationError(`qty ${qty} exceeds held shares (${heldShares})`);
    }
  }

  const url = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW_FILE}/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_PAT}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "graywind-manual-trade-trigger",
    },
    body: JSON.stringify({
      ref: "main",
      inputs: {
        account, symbol, action,
        qty: qty !== undefined && qty !== null ? String(qty) : "",
        stop_price: stop_price !== undefined && stop_price !== null ? String(stop_price) : "",
        target_price: target_price !== undefined && target_price !== null ? String(target_price) : "",
        idempotency_key,
      },
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    return new Response(JSON.stringify({ error: `dispatch failed: ${res.status} ${text}` }), {
      status: 502, headers: { "Content-Type": "application/json" },
    });
  }
  return new Response(JSON.stringify({ status: "dispatched" }), {
    status: 202, headers: { "Content-Type": "application/json", ...corsHeaders(env) },
  });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(env) });
    }
    if (request.method !== "POST") {
      return new Response("not found", { status: 404 });
    }
    const response = await handleManualTrade(request, env);
    Object.entries(corsHeaders(env)).forEach(([k, v]) => response.headers.set(k, v));
    return response;
  },
};
```

- [ ] **Step 3: Smoke-test locally**

Run: `cd manual-trade-trigger && npx wrangler dev` (no test framework exists for `cron-trigger` either — a manual `curl` against the local dev server is this repo's established verification level for Worker code):

```bash
curl -s -X POST http://localhost:8787 -H "Content-Type: application/json" \
  -d '{"token":"wrong","account":"small","symbol":"AAPL","action":"close","idempotency_key":"t1"}'
# Expected: "not found" (404) -- confirms the token check fails closed.
```

- [ ] **Step 4: Commit**

```bash
git add manual-trade-trigger/
git commit -m "$(cat <<'EOF'
feat: add manual-trade-trigger Cloudflare Worker

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UsxGwe1BxzJabT2ZZH3zGA
EOF
)"
```

---

## Task 9: Dashboard action panel

**Files:**
- Modify: `index.html`

**Interfaces:**
- Consumes: the deployed Worker's URL (Task 8) — added as a constant near the top of the `<script>` block.
- Produces: a click handler on each position row (extends `buildPositions`, `index.html:478`) and a panel that POSTs to the Worker.

- [ ] **Step 1: Add the Worker URL constant and token storage helpers**

Add near the top of the existing `<script>` block (after the `money`/`pct` formatters, `index.html:417`):

```javascript
const MANUAL_TRADE_WORKER_URL = "https://graywind-manual-trade-trigger.<your-subdomain>.workers.dev";

function getManualTradeToken() {
  try {
    return localStorage.getItem("graywind_manual_trade_token") || "";
  } catch {
    return "";
  }
}

function setManualTradeToken(token) {
  try {
    localStorage.setItem("graywind_manual_trade_token", token);
  } catch {
    // Private-browsing/blocked storage: the token just won't persist across
    // reloads. Non-fatal -- the panel still works for this page load.
  }
}
```

(`<your-subdomain>` is filled in with the real Worker URL once Task 8 is deployed — see Task 11.)

- [ ] **Step 2: Add the panel markup, open/close, and submit logic**

Add this function block (near `buildPositions`, `index.html:478`):

```javascript
let manualTradePanelState = null; // { accountId, symbol, shares, currentPrice }

function openManualTradePanel(accountId, symbol, shares, currentPrice) {
  manualTradePanelState = { accountId, symbol, shares, currentPrice };
  const panel = document.getElementById("manual-trade-panel");
  document.getElementById("manual-trade-symbol").textContent = symbol;
  document.getElementById("manual-trade-shares").textContent = shares;
  document.getElementById("manual-trade-token").value = getManualTradeToken();
  document.getElementById("manual-trade-result").textContent = "";
  document.getElementById("manual-trade-confirm-summary").hidden = true;
  panel.hidden = false;
}

function closeManualTradePanel() {
  document.getElementById("manual-trade-panel").hidden = true;
  manualTradePanelState = null;
}

function buildManualTradeSummary(action, qty, stopPrice, targetPrice) {
  const { symbol, currentPrice } = manualTradePanelState;
  if (action === "close") return `Sell all shares of ${symbol} at market (~${money.format(currentPrice)})`;
  if (action === "sell_partial") return `Sell ${qty} shares of ${symbol} at market (~${money.format(currentPrice)})`;
  if (action === "buy_more") return `Buy ${qty} more shares of ${symbol} at market (~${money.format(currentPrice)})`;
  const parts = [];
  if (stopPrice) parts.push(`stop at ${money.format(stopPrice)}`);
  if (targetPrice) parts.push(`target at ${money.format(targetPrice)}`);
  return `Set ${symbol} ${parts.join(" and ")}`;
}

async function submitManualTrade(action, qty, stopPrice, targetPrice) {
  const token = document.getElementById("manual-trade-token").value.trim();
  if (!token) {
    document.getElementById("manual-trade-result").textContent = "Enter your trade token first.";
    return;
  }
  setManualTradeToken(token);

  const { accountId, symbol } = manualTradePanelState;
  const idempotencyKey = crypto.randomUUID();
  const submitBtn = document.getElementById("manual-trade-submit");
  submitBtn.disabled = true;
  document.getElementById("manual-trade-result").textContent = "Submitting…";

  try {
    const res = await fetch(MANUAL_TRADE_WORKER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token, account: accountId, symbol, action,
        qty: qty ?? null, stop_price: stopPrice ?? null, target_price: targetPrice ?? null,
        idempotency_key: idempotencyKey,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (res.ok) {
      document.getElementById("manual-trade-result").textContent =
        "Submitted — check Recent Actions in about a minute.";
    } else {
      document.getElementById("manual-trade-result").textContent = `Rejected: ${body.error || res.status}`;
    }
  } catch (err) {
    document.getElementById("manual-trade-result").textContent = `Network error: ${err.message}`;
  } finally {
    submitBtn.disabled = false;
  }
}
```

- [ ] **Step 3: Add the panel HTML and wire the confirm step**

Add this markup once, right before `</body>` (a single shared panel, reused for whichever position was clicked):

```html
<div id="manual-trade-panel" hidden style="position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:100;">
  <div style="background:var(--bg-2);padding:24px;border-radius:8px;max-width:400px;width:90%;">
    <h3>Act on <span id="manual-trade-symbol"></span> (<span id="manual-trade-shares"></span> shares held)</h3>
    <label>Action:
      <select id="manual-trade-action">
        <option value="close">Close position (sell all)</option>
        <option value="sell_partial">Sell partial</option>
        <option value="buy_more">Buy more</option>
        <option value="set_stop_target">Set stop/target</option>
      </select>
    </label>
    <div id="manual-trade-qty-row"><label>Qty: <input type="number" id="manual-trade-qty" min="1" step="1"></label></div>
    <div id="manual-trade-stop-target-row" hidden>
      <label>Stop price: <input type="number" id="manual-trade-stop-price" step="0.01"></label>
      <label>Target price: <input type="number" id="manual-trade-target-price" step="0.01"></label>
    </div>
    <label>Trade token: <input type="password" id="manual-trade-token"></label>
    <div id="manual-trade-confirm-summary" hidden></div>
    <button id="manual-trade-review-btn" type="button">Review</button>
    <button id="manual-trade-submit" type="button" hidden>Confirm &amp; Submit</button>
    <button id="manual-trade-cancel" type="button">Cancel</button>
    <div id="manual-trade-result"></div>
  </div>
</div>
```

Wire it once in `main()` (`index.html:1003`), before `loadAccount(...)` calls:

```javascript
document.getElementById("manual-trade-action").addEventListener("change", (e) => {
  const isStopTarget = e.target.value === "set_stop_target";
  const isQtyAction = e.target.value === "sell_partial" || e.target.value === "buy_more";
  document.getElementById("manual-trade-qty-row").hidden = !isQtyAction;
  document.getElementById("manual-trade-stop-target-row").hidden = !isStopTarget;
});
document.getElementById("manual-trade-cancel").addEventListener("click", closeManualTradePanel);
document.getElementById("manual-trade-review-btn").addEventListener("click", () => {
  const action = document.getElementById("manual-trade-action").value;
  const qty = parseFloat(document.getElementById("manual-trade-qty").value) || null;
  const stopPrice = parseFloat(document.getElementById("manual-trade-stop-price").value) || null;
  const targetPrice = parseFloat(document.getElementById("manual-trade-target-price").value) || null;
  const summaryEl = document.getElementById("manual-trade-confirm-summary");
  summaryEl.textContent = buildManualTradeSummary(action, qty, stopPrice, targetPrice);
  summaryEl.hidden = false;
  document.getElementById("manual-trade-submit").hidden = false;
  document.getElementById("manual-trade-submit").onclick = () => submitManualTrade(action, qty, stopPrice, targetPrice);
});
```

- [ ] **Step 4: Make position rows clickable** (modify `buildPositions`, `index.html:494-501`)

Change the row template to add a click handler and pass `accountId` through (update `buildPositions(statusRows)` to `buildPositions(statusRows, accountId)`, and its one call site at `index.html:964` to `buildPositions(statusRows, accountId)`):

```javascript
return `<tr class="position-row" data-symbol="${row.symbol}" style="${isOpen ? 'cursor:pointer' : ''}">
  <td class="symbol-tag">${row.symbol}</td>
  <td class="num">${posCell}</td>
  <td class="num">${row.current_price ? money.format(parseFloat(row.current_price)) : "—"}</td>
  <td class="num">${pnlCell}</td>
  <td><span class="side-tag ${row.action === "hold" ? "flat" : row.action === "buy" ? "buy" : "sell"}">${row.action}</span></td>
  <td style="color:var(--txt-2)">${row.reason || ""}</td>
</tr>`;
```

And after `renderAccount` sets `containerEl.innerHTML` (`index.html:966`), add a delegated click listener (once, in `renderAccount`, right after the `initEquityChart` call at `index.html:969`):

```javascript
containerEl.querySelectorAll("tr.position-row[data-symbol]").forEach(tr => {
  tr.addEventListener("click", () => {
    const symbol = tr.dataset.symbol;
    const row = statusRows.find(r => r.symbol === symbol);
    if (row.position_open !== "True") return;
    openManualTradePanel(accountId, symbol, row.shares, parseFloat(row.current_price));
  });
});
```

- [ ] **Step 5: Manual verification in a browser**

Run a local static server and open the dashboard:

```bash
python3 -m http.server 8000
```

Open `http://localhost:8000/index.html`, confirm: clicking an open position opens the panel with the right symbol/shares; switching the action dropdown toggles the qty vs. stop/target inputs; "Review" shows a plausible plain-English summary; "Cancel" closes it. Submitting is not exercised here (no deployed Worker yet) — that's Task 11's live dry run. Clicking a flat (no position) row must do nothing.

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
feat: add clickable position action panel to the dashboard

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UsxGwe1BxzJabT2ZZH3zGA
EOF
)"
```

---

## Task 10: Recent-actions feed

**Files:**
- Modify: `index.html`

**Interfaces:**
- Consumes: `dashboard-data/manual_actions.csv` / `dashboard-data/small/manual_actions.csv` (Task 1's schema, written by Task 6's script).
- Produces: a rendered "Recent actions" section per account.

- [ ] **Step 1: Add a render function**

```javascript
function buildManualActionsFeed(manualActionRows) {
  if (manualActionRows.length === 0) {
    return `
      <section aria-labelledby="manual-actions-head">
        <div class="section-head"><h2 id="manual-actions-head">Recent Actions</h2></div>
        <div class="table-wrap"><div class="empty-state">No manual actions yet.</div></div>
      </section>`;
  }
  const rows = manualActionRows.slice().reverse().map(row => `
    <tr>
      <td>${fmtTime(parseTimestamp(row.timestamp))}</td>
      <td class="symbol-tag">${row.symbol}</td>
      <td>${row.action}</td>
      <td class="num">${row.qty || "—"}</td>
      <td><span class="side-tag ${row.status === "submitted" ? "buy" : "sell"}">${row.status}</span></td>
      <td style="color:var(--txt-2)">${row.reason}</td>
    </tr>`).join("");
  return `
    <section aria-labelledby="manual-actions-head">
      <div class="section-head"><h2 id="manual-actions-head">Recent Actions</h2></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Time</th><th>Symbol</th><th>Action</th><th class="num">Qty</th><th>Status</th><th>Reason</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>`;
}
```

- [ ] **Step 2: Fetch the file and render it** (modify `loadAccount`, `index.html:982`, and `renderAccount`, `index.html:944`)

`loadAccount` gains a fourth CSV fetch, tolerant of a 404 (no manual actions yet):

```javascript
async function loadManualActionsCSV(path) {
  try {
    return await loadCSV(path);
  } catch {
    return [];
  }
}
```

In `loadAccount`, add to the `Promise.all` array: `loadManualActionsCSV(\`${dataDir}/manual_actions.csv\`)`, capture it as `manualActionRows`, and pass it through to `renderAccount(...)`.

In `renderAccount`, add `${buildManualActionsFeed(manualActionRows)}` to the template string, right after `${buildPositions(statusRows, accountId)}`.

- [ ] **Step 3: Manual verification**

Drop a sample `dashboard-data/manual_actions.csv` (header + one row matching `MANUAL_ACTIONS_FIELDS`) locally, reload via `python3 -m http.server 8000`, confirm the "Recent Actions" section renders the row; delete the file and confirm the empty-state message shows instead with no console error.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
feat: render manual_actions.csv as a Recent Actions feed

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UsxGwe1BxzJabT2ZZH3zGA
EOF
)"
```

---

## Task 11: Deploy and dry-run against the small account

**Files:** none (deployment + verification only)

- [ ] **Step 1: Set Worker secrets**

```bash
cd manual-trade-trigger
npx wrangler secret put GITHUB_PAT
npx wrangler secret put MANUAL_TRADE_TOKEN
```

- [ ] **Step 2: Deploy the Worker and fill in its real URL**

```bash
npx wrangler deploy
```

Copy the printed `*.workers.dev` URL into `MANUAL_TRADE_WORKER_URL` in `index.html` (Task 9, Step 1), commit that one-line change, and push so the live dashboard points at the real Worker.

- [ ] **Step 3: Confirm the GitHub PAT can dispatch the new workflow**

```bash
curl -s -X POST https://api.github.com/repos/SinbadTheExplorer/graywind/actions/workflows/manual-trade.yml/dispatches \
  -H "Authorization: Bearer <the same PAT>" -H "Accept: application/vnd.github+json" \
  -d '{"ref":"main","inputs":{"account":"small","symbol":"AAPL","action":"close","qty":"","stop_price":"","target_price":"","idempotency_key":"manual-verify-1"}}'
```

Expected: HTTP 204. Check the Actions tab for a running `Graywind Manual Trade Action` job.

- [ ] **Step 4: Live dry run, during market hours, small account only**

From the deployed dashboard, on the **small** account's an open position:
1. **Close** a small partial or full position — confirm the workflow run succeeds, `state/small/positions.csv` shows `pending_sell_order_id` set, and the *next* scheduled `live-trading.yml` cycle settles it (check `dashboard-data/small/trade_log.csv` gains the sell row and `tier_pools.csv` is credited).
2. **Buy more** on a held small-account symbol — confirm `state/small/positions.csv` shows the increased share count and updated weighted `entry_price`, and `state/small/tier_pools.csv` is debited.
3. **Set stop/target** with both prices — confirm an OCO order appears in the Alpaca paper dashboard for that account, and `pending_sell_order_id` is set locally.
4. Trigger the **same** action twice with the same idempotency key (reuse a browser session without reloading, or replay Step 3's curl body) — confirm the second attempt no-ops (`manual_actions.csv` gains no second row for that key).
5. Confirm `dashboard-data/small/manual_actions.csv` has one row per real attempt above, and the dashboard's Recent Actions feed shows them.

- [ ] **Step 5: Only after Step 4 is fully clean, repeat once against the main ("100k") account**

Same four checks as Step 4, scoped to the main account's own state/dashboard-data paths.

---

## Self-Review

**Spec coverage:** dashboard panel (Task 9), Worker (Task 8), workflow (Task 7), script + four action handlers (Tasks 2-6), audit log + feed (Tasks 1, 10), safety (token gate in Worker, breaker gates in Task 4, cancel-guard in Task 2, qty cap in Worker + handler, idempotency in Tasks 1/6), testing (unit tests throughout, dry run in Task 11) — every spec section maps to a task.

**Placeholder scan:** no TBD/TODO; the one intentional fill-in (`<your-subdomain>` in Task 9) is resolved concretely in Task 11 Step 2, not left open.

**Type consistency:** `handle_close_or_sell_partial`/`handle_buy_more`/`handle_set_stop_target` all return the same `{"status", "reason"}` shape, consumed identically by `main()` in Task 6. `state["open_positions"][symbol]` is mutated in place by every handler and read back the same way by `main()`'s `save_state` call — verified consistent across Tasks 3-6.

# Graywind x Bullion Macro Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 4th risk gate, `macro_gate.py`, that reads Bullion's public `data.json` and blocks
new trades on a vote-count of macro stress signals (VIX, NFCI, HY OAS, yield curve slope),
additive alongside the existing vix/sentiment/earnings gates.

**Architecture:** New `graywind_strategy/gates/macro_gate.py` mirrors the shape of
`vix_gate.py`: a fail-closed fetch function (`fetch_bullion_macro_snapshot`) that raises
`MacroDataUnavailable` on any HTTP/parse/staleness failure, and a pure vote-count function
(`macro_gate`). `pipeline.py` gets a new `evaluate_macro_gate` wrapper (same shape as
`evaluate_vix_gate`) and one more blocking check in `decide_trade`, placed *after* the earnings
check so existing single-gate-failure tests that patch only 3 gates still short-circuit before
reaching it.

**Tech Stack:** Python, `requests` (injectable via `session=` param), `pytest` +
`unittest.mock.MagicMock`/`patch`/`patch.multiple`.

## Global Constraints

- Spec (source of truth): `docs/superpowers/specs/2026-08-17-graywind-bullion-macro-gate-design.md`.
- Fail closed always: any fetch/parse/staleness problem → `MacroDataUnavailable` → gate blocks
  the trade, never "skip this gate."
- No lookahead bias: only use `history` values dated **strictly before** `as_of_date` (same
  discipline as `vix_gate.py`'s `observation_end = today - 1 day`).
- `hy_oas` threshold is `5.0` in **percentage points**, not basis points — do not reintroduce a
  "500" threshold.
- Bullion's `data.json` endpoint:
  `https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/data.json`.
- `decide_trade` gets no new required parameter — the gate needs no credential.
- Thresholds (breach conditions): `vix >= 25.0`, `nfci >= 0.0`, `hy_oas >= 5.0`,
  `curve_slope < 0.0` (`curve_slope = us10y - us2y`).
- Staleness ceilings: daily fields (`vix`, `hy_oas`, `us10y`, `us2y`) = 5 days; weekly (`nfci`) =
  10 days. A found value is stale if `(as_of_date - record_date).days > ceiling` (boundary value
  itself, `== ceiling`, is still fresh — matches `vix_gate.py`'s `> MAX_STALENESS_DAYS` check).
- `history` is keyed by ISO date string (`"YYYY-MM-DD"`), each date holding whatever fields were
  freshly published that day — walk dates **descending**, take the first date strictly before
  `as_of_date` that contains the field being looked up.

---

## Task 1: `macro_gate()` vote-count function

**Files:**
- Create: `graywind_strategy/gates/macro_gate.py` (partial — just the exception and the pure
  vote-count function this task needs; `fetch_bullion_macro_snapshot` comes in Task 2)
- Test: `tests/test_macro_gate.py` (new file, partial — just `macro_gate()` tests; more tests
  added in Task 2)

**Interfaces:**
- Produces: `MacroDataUnavailable` (exception, subclass of `Exception`), `macro_gate(snapshot,
  required_breaches=2)` — `snapshot` is a `dict` with keys `"vix"`, `"nfci"`, `"hy_oas"`,
  `"curve_slope"` (all `float`); returns `True` (allow trade) when the number of breached fields
  is `< required_breaches`, `False` (block) otherwise.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_macro_gate.py
from graywind_strategy.gates.macro_gate import macro_gate


def test_macro_gate_allows_when_no_fields_breach():
    snapshot = {"vix": 14.6, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 0.48}
    assert macro_gate(snapshot) is True


def test_macro_gate_allows_when_breaches_below_required_count():
    # Only vix breaches (>= 25.0); default required_breaches=2, so 1 breach still allows.
    snapshot = {"vix": 27.0, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 0.48}
    assert macro_gate(snapshot) is True


def test_macro_gate_blocks_when_breaches_meet_required_count():
    # vix and nfci both breach at their exact threshold boundary -- 2 of 4, meets default
    # required_breaches=2.
    snapshot = {"vix": 25.0, "nfci": 0.0, "hy_oas": 2.71, "curve_slope": 0.48}
    assert macro_gate(snapshot) is False


def test_macro_gate_blocks_when_all_four_fields_breach():
    snapshot = {"vix": 30.0, "nfci": 0.5, "hy_oas": 6.0, "curve_slope": -0.5}
    assert macro_gate(snapshot) is False


def test_macro_gate_curve_slope_breach_is_less_than_not_greater_than():
    # curve_slope is the one inverted-direction field: breach is < 0.0, not >= 0.0. A
    # deeply positive curve_slope must never count as a breach.
    snapshot = {"vix": 14.6, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 2.0}
    assert macro_gate(snapshot) is True


def test_macro_gate_respects_custom_required_breaches():
    # 3 breaches, but required_breaches=4 means it takes all 4 to block.
    snapshot = {"vix": 30.0, "nfci": 0.5, "hy_oas": 6.0, "curve_slope": 0.48}
    assert macro_gate(snapshot, required_breaches=4) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_macro_gate.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError` (`graywind_strategy.gates.macro_gate`
does not exist yet).

- [ ] **Step 3: Write minimal implementation**

```python
# graywind_strategy/gates/macro_gate.py
"""Bullion macro-gate: blocks new trades when a vote-count of macro stress
signals (VIX, NFCI, HY OAS, yield curve slope), sourced from Bullion's
public daily-cron data.json, meets a configured breach threshold. Fails
closed -- any fetch, parse, or staleness failure raises
MacroDataUnavailable, which the caller (pipeline.py) must treat as a
blocked trade, never as a skipped gate. Additive alongside vix_gate.py,
which keeps its own direct FRED call unchanged.
"""

VIX_THRESHOLD = 25.0
NFCI_THRESHOLD = 0.0
HY_OAS_THRESHOLD = 5.0
CURVE_SLOPE_THRESHOLD = 0.0


class MacroDataUnavailable(Exception):
    pass


def macro_gate(snapshot, required_breaches=2):
    breaches = 0
    if snapshot["vix"] >= VIX_THRESHOLD:
        breaches += 1
    if snapshot["nfci"] >= NFCI_THRESHOLD:
        breaches += 1
    if snapshot["hy_oas"] >= HY_OAS_THRESHOLD:
        breaches += 1
    if snapshot["curve_slope"] < CURVE_SLOPE_THRESHOLD:
        breaches += 1
    return breaches < required_breaches
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_macro_gate.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gates/macro_gate.py tests/test_macro_gate.py
git commit -m "feat: add macro_gate vote-count function"
```

---

## Task 2: `fetch_bullion_macro_snapshot()` — fetch, forward-fill, staleness

**Files:**
- Modify: `graywind_strategy/gates/macro_gate.py` (add `fetch_bullion_macro_snapshot` and its
  private forward-fill helper)
- Test: `tests/test_macro_gate.py` (append)

**Interfaces:**
- Consumes: `MacroDataUnavailable` from Task 1 (same file).
- Produces: `fetch_bullion_macro_snapshot(as_of_date, session=requests)` — GETs
  `https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/data.json`, returns
  `{"vix": float, "nfci": float, "hy_oas": float, "curve_slope": float}` on success, raises
  `MacroDataUnavailable` on any failure. `as_of_date` is a `datetime.date`, required (no
  default). Later tasks (Task 3) import this name directly.

- [ ] **Step 1: Write the failing tests**

```python
# appended to tests/test_macro_gate.py
from datetime import date
from unittest.mock import MagicMock

import pytest
import requests

from graywind_strategy.gates.macro_gate import (
    MacroDataUnavailable,
    fetch_bullion_macro_snapshot,
    macro_gate,
)


def _fake_session(payload):
    fake_response = MagicMock()
    fake_response.json.return_value = payload
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    return fake_session


def test_fetch_bullion_macro_snapshot_parses_most_recent_value_per_field():
    # Mirrors the real observed gap: the newest date before as_of_date (2026-08-14) is
    # missing vix/hy_oas/us10y/us2y entirely (only slower-cadence fields were fresh that
    # day) -- the walk must skip it and land on 2026-08-10 for those fields, while nfci
    # (weekly) is found on 2026-08-11.
    history = {
        "2026-08-10": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.5, "us2y": 4.0},
        "2026-08-11": {"nfci": -0.3},
        "2026-08-14": {"spx": 5000},
    }
    session = _fake_session({"history": history})

    snapshot = fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)

    assert snapshot == {"vix": 15.0, "nfci": -0.3, "hy_oas": 2.5, "curve_slope": 0.5}


def test_fetch_bullion_macro_snapshot_never_uses_a_value_dated_on_as_of_date():
    # Lookahead-bias regression: a record dated exactly on as_of_date must never be used,
    # even though it's the "most recent" entry by date, mirroring vix_gate.py's own
    # same-day exclusion.
    history = {
        "2026-08-10": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.5, "us2y": 4.0, "nfci": -0.3},
        "2026-08-15": {"vix": 999.0, "hy_oas": 999.0, "us10y": 999.0, "us2y": 999.0, "nfci": 999.0},
    }
    session = _fake_session({"history": history})

    snapshot = fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)

    assert snapshot == {"vix": 15.0, "nfci": -0.3, "hy_oas": 2.5, "curve_slope": 0.5}


def test_fetch_bullion_macro_snapshot_raises_when_field_stale_beyond_daily_ceiling():
    # Only candidate for vix is 6 days before as_of_date -- daily ceiling is 5 days.
    history = {
        "2026-08-09": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.5, "us2y": 4.0, "nfci": -0.3},
    }
    session = _fake_session({"history": history})

    with pytest.raises(MacroDataUnavailable, match="vix"):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)


def test_fetch_bullion_macro_snapshot_accepts_field_within_daily_ceiling():
    # Exactly 5 days before as_of_date -- boundary is inclusive (not stale).
    history = {
        "2026-08-10": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.5, "us2y": 4.0, "nfci": -0.3},
    }
    session = _fake_session({"history": history})

    snapshot = fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)

    assert snapshot["vix"] == 15.0


def test_fetch_bullion_macro_snapshot_accepts_weekly_field_within_wider_ceiling():
    # nfci found 9 days before as_of_date -- would fail a 5-day daily ceiling but passes
    # its own 10-day weekly ceiling. Other fields found close-in so only nfci's ceiling is
    # exercised.
    history = {
        "2026-08-06": {"nfci": -0.3},
        "2026-08-10": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.5, "us2y": 4.0},
    }
    session = _fake_session({"history": history})

    snapshot = fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)

    assert snapshot["nfci"] == -0.3


def test_fetch_bullion_macro_snapshot_computes_curve_slope_as_us10y_minus_us2y():
    history = {
        "2026-08-10": {"vix": 15.0, "hy_oas": 2.5, "us10y": 4.63, "us2y": 4.15, "nfci": -0.3},
    }
    session = _fake_session({"history": history})

    snapshot = fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)

    assert snapshot["curve_slope"] == pytest.approx(0.48)


def test_fetch_bullion_macro_snapshot_raises_on_http_error():
    fake_session = MagicMock()
    fake_session.get.side_effect = Exception("network error")
    with pytest.raises(MacroDataUnavailable):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=fake_session)


def test_fetch_bullion_macro_snapshot_raises_on_http_error_status():
    fake_response = MagicMock()
    fake_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    with pytest.raises(MacroDataUnavailable):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=fake_session)


def test_fetch_bullion_macro_snapshot_raises_on_missing_history_key():
    session = _fake_session({"fields": {}})
    with pytest.raises(MacroDataUnavailable):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)


def test_fetch_bullion_macro_snapshot_raises_when_no_value_found_for_field_at_all():
    # history exists but never contains hy_oas at all -- walk exhausts with nothing found.
    history = {
        "2026-08-10": {"vix": 15.0, "us10y": 4.5, "us2y": 4.0, "nfci": -0.3},
    }
    session = _fake_session({"history": history})
    with pytest.raises(MacroDataUnavailable, match="hy_oas"):
        fetch_bullion_macro_snapshot(date(2026, 8, 15), session=session)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_macro_gate.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_bullion_macro_snapshot'`

- [ ] **Step 3: Write minimal implementation**

Append to `graywind_strategy/gates/macro_gate.py` (add these imports to the top of the file,
alongside the existing module docstring and threshold constants from Task 1):

```python
from datetime import datetime

import requests

BULLION_DATA_URL = "https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/data.json"
DAILY_STALENESS_CEILING_DAYS = 5
WEEKLY_STALENESS_CEILING_DAYS = 10

_FIELD_CEILINGS = {
    "vix": DAILY_STALENESS_CEILING_DAYS,
    "hy_oas": DAILY_STALENESS_CEILING_DAYS,
    "us10y": DAILY_STALENESS_CEILING_DAYS,
    "us2y": DAILY_STALENESS_CEILING_DAYS,
    "nfci": WEEKLY_STALENESS_CEILING_DAYS,
}


def _most_recent_value_before(history, field, as_of_date, ceiling_days):
    for date_str in sorted(history.keys(), reverse=True):
        record_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if record_date >= as_of_date:
            continue
        record = history[date_str]
        if field not in record:
            continue
        if (as_of_date - record_date).days > ceiling_days:
            raise MacroDataUnavailable(
                f"no fresh value for '{field}': most recent is {record_date}, "
                f"older than the {ceiling_days}-day staleness ceiling"
            )
        return record[field]
    raise MacroDataUnavailable(f"no value found for '{field}' in history before {as_of_date}")


def fetch_bullion_macro_snapshot(as_of_date, session=requests):
    try:
        response = session.get(BULLION_DATA_URL, timeout=10)
        response.raise_for_status()
        history = response.json()["history"]
    except MacroDataUnavailable:
        raise
    except Exception as exc:
        raise MacroDataUnavailable(str(exc)) from exc

    values = {
        field: _most_recent_value_before(history, field, as_of_date, ceiling)
        for field, ceiling in _FIELD_CEILINGS.items()
    }

    return {
        "vix": values["vix"],
        "nfci": values["nfci"],
        "hy_oas": values["hy_oas"],
        "curve_slope": values["us10y"] - values["us2y"],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_macro_gate.py -v`
Expected: PASS (all tests from Task 1 and Task 2)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gates/macro_gate.py tests/test_macro_gate.py
git commit -m "feat: add fetch_bullion_macro_snapshot with forward-fill and staleness checks"
```

---

## Task 3: Wire `macro_gate` into `pipeline.py`

**Files:**
- Modify: `graywind_strategy/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `MacroDataUnavailable`, `fetch_bullion_macro_snapshot`, `macro_gate` from
  `graywind_strategy.gates.macro_gate` (Tasks 1 and 2).
- Produces: `evaluate_macro_gate(as_of_date, session=requests, required_breaches=2)` — returns
  `True`/`False`, fail-closed on `MacroDataUnavailable`. `decide_trade` gains no new parameter.

- [ ] **Step 1: Write the failing tests**

Add near the top of `tests/test_pipeline.py`, alongside the existing per-gate imports:

```python
from graywind_strategy.gates.macro_gate import MacroDataUnavailable
from graywind_strategy.pipeline import evaluate_macro_gate  # add to the existing pipeline import block
```

Add these tests near the other `evaluate_*_gate` tests (after
`test_evaluate_earnings_gate_fails_closed_on_fetch_error`, before `_passing_gates`):

```python
def test_evaluate_macro_gate_fails_closed_on_fetch_error():
    with patch(
        "graywind_strategy.pipeline.fetch_bullion_macro_snapshot",
        side_effect=MacroDataUnavailable("boom"),
    ):
        assert evaluate_macro_gate(as_of_date=date(2024, 1, 8)) is False


def test_evaluate_macro_gate_passes_through_on_success():
    snapshot = {"vix": 14.6, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 0.48}
    with patch(
        "graywind_strategy.pipeline.fetch_bullion_macro_snapshot", return_value=snapshot
    ) as mock_fetch:
        assert evaluate_macro_gate(as_of_date=date(2024, 1, 8)) is True
    mock_fetch.assert_called_once_with(date(2024, 1, 8), session=requests)
```

Add `import requests` to the top of `tests/test_pipeline.py` if not already present (it is not —
confirm with `grep -n "^import requests" tests/test_pipeline.py` before adding, to avoid a
duplicate import).

Update the existing `_passing_gates()` helper (around line 57) to add the 4th entry:

```python
def _passing_gates():
    return patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=lambda **kw: True,
        evaluate_sentiment_gate=lambda **kw: True,
        evaluate_earnings_gate=lambda **kw: True,
        evaluate_macro_gate=lambda **kw: True,
    )
```

Add a new blocking test, mirroring `test_decide_trade_blocks_on_vix_gate_failure` exactly (place
it directly after `test_decide_trade_blocks_on_earnings_gate_failure`):

```python
def test_decide_trade_blocks_on_macro_gate_failure():
    with patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=MagicMock(return_value=True),
        evaluate_sentiment_gate=MagicMock(return_value=True),
        evaluate_earnings_gate=MagicMock(return_value=True),
        evaluate_macro_gate=MagicMock(return_value=False),
    ):
        decision = decide_trade(
            symbol="AAPL", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=100.0, account_equity=10000.0,
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    assert decision.action == "blocked"
    assert decision.reason == "macro_gate"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ImportError: cannot import name 'evaluate_macro_gate'` (and, once that's fixed
in Step 3 below without the `decide_trade` wiring, `test_decide_trade_blocks_on_macro_gate_failure`
would still fail on `decision.reason` — confirm both failure modes are gone after Step 3).

- [ ] **Step 3: Write minimal implementation**

In `graywind_strategy/pipeline.py`, add the import (alongside the other gate imports at the top):

```python
from graywind_strategy.gates.macro_gate import MacroDataUnavailable, fetch_bullion_macro_snapshot, macro_gate
```

`requests` is not yet imported in `pipeline.py` — add `import requests` near the top (it is used
as `evaluate_macro_gate`'s default `session` argument, the same way `fetch_latest_vix` uses it as
a default inside `vix_gate.py`, but here the default lives in `pipeline.py`'s own signature).

Add the wrapper function, placed after `evaluate_earnings_gate`:

```python
def evaluate_macro_gate(as_of_date, session=requests, required_breaches=2):
    try:
        snapshot = fetch_bullion_macro_snapshot(as_of_date, session=session)
    except MacroDataUnavailable:
        return False
    return macro_gate(snapshot, required_breaches)
```

In `decide_trade`, add one more blocking check, placed **after** the earnings check (so the
existing single-gate-failure tests, which patch only vix/sentiment/earnings and expect an
early return, never reach this unpatched call):

```python
        if not evaluate_earnings_gate(symbol=symbol, finnhub_api_key=finnhub_api_key, as_of_date=as_of_date):
            return TradeDecision(action="blocked", reason="earnings_gate")
        if not evaluate_macro_gate(as_of_date=as_of_date):
            return TradeDecision(action="blocked", reason="macro_gate")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: PASS — full suite green, 164 (baseline) + 6 (Task 1) + 10 (Task 2) + 3 (Task 3) = 183
tests passing (exact new-test count per this plan; confirm no unexpected failures elsewhere).

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/pipeline.py tests/test_pipeline.py
git commit -m "feat: wire macro_gate into decide_trade as a 4th blocking gate"
```

---

## Self-Review Notes

- **Spec coverage:** Architecture (Task 1 + Task 2 split of `macro_gate.py`), Data Flow /
  forward-fill algorithm (Task 2), Error Handling — HTTP failure, malformed/missing `history`,
  per-field staleness naming the field (Task 2) — Testing section's full list (vote-count edges,
  fetch parsing/backward-walk/staleness/lookahead/HTTP/malformed-JSON, pipeline wrapper +
  `_passing_gates` + blocking test) are each covered by a task above. Out-of-scope items
  (touching `vix_gate.py`, weighted/z-score composite, extra Bullion fields, backtest-period
  history-depth handling) are correctly not implemented anywhere in this plan.
- **Placeholder scan:** no TBD/TODO markers; every step has runnable code.
- **Type consistency:** `macro_gate(snapshot, required_breaches=2)` (Task 1) is called
  identically in Task 2 is not needed (Task 2 doesn't call `macro_gate`) and in Task 3's
  `evaluate_macro_gate` with `macro_gate(snapshot, required_breaches)` — signature matches.
  `fetch_bullion_macro_snapshot(as_of_date, session=requests)` (Task 2) is called identically in
  Task 3's `evaluate_macro_gate`. `MacroDataUnavailable` is defined once (Task 1) and
  imported/used consistently in Tasks 2 and 3.

# Graywind x Bullion Macro Gate — Design

**Amendment (2026-08-17, post-ship):** the vote below shipped as "2 of 4" including `vix`, but
`vix`'s vote turned out to be redundant with the pre-existing `evaluate_vix_gate` (same FRED
VIXCLS series, same 25.0 threshold, runs first in `decide_trade`) — it could only ever fire when
it was *wrong* (Bullion's forward-filled value stale-high while live FRED was actually fine). The
user decided to drop `vix` from the vote; `macro_gate()` is now "2 of 3" over
`nfci`/`hy_oas`/`curve_slope`. `vix` is still fetched into the snapshot (harmless, matches Bullion's
data shape) but no longer counted. The rest of this document is the original, as-approved design —
read the "2 of 4"/`vix`-vote language below as historical, not current behavior.

**Date:** 2026-08-17
**Status:** approved, not yet implemented
**Prior art:** `graywind_strategy/gates/vix_gate.py` (the gate this design mirrors almost exactly —
same fail-closed exception pattern, same `session=requests` injectable, same
`as_of_date`/lookahead-bias discipline), `graywind_strategy/pipeline.py` (the three existing
gate wrappers and `decide_trade`'s `gates_always_pass` bypass this design joins).

## Goal

Graywind currently reads a single macro signal directly (`vix_gate.py` hits FRED for VIXCLS).
[[Bullion]] (a sibling side project — `/Users/thanhnguyen/minhthanh0403/claude-projects/claudekit`)
already computes and publishes a richer, already-fitted macro dataset (VIX, NFCI, credit spreads,
yield curve, and more) on a daily cron, free and public on GitHub Pages. This design adds a 4th
gate, `macro_gate.py`, that reads Bullion's public `data.json` as a vote-count risk gate —
reusing existing free infrastructure instead of inventing new modeling work or needing new
secrets. It is **additive**: `vix_gate.py`'s direct FRED call stays exactly as-is; the two gates
are independent and both must pass.

## Architecture

New file **`graywind_strategy/gates/macro_gate.py`**, same shape as the existing three gates
(`vix_gate.py`, `sentiment_gate.py`, `earnings_gate.py`):

- **`fetch_bullion_macro_snapshot(as_of_date, session=requests)`** — GETs Bullion's public
  `https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/data.json` and returns a
  plain `dict`: `{"vix": float, "nfci": float, "hy_oas": float, "curve_slope": float}`.
- **`macro_gate(snapshot, required_breaches=2)`** — a **vote-count**, not a weighted/z-score
  composite. Each field has one fixed stress threshold; blocks if `required_breaches` (of 4)
  trip. Chosen over a fancier composite score because every existing gate in this codebase is a
  single hardcoded threshold — vote-count stays equally auditable ("2 of 4 stress signals
  tripped") without inventing weights unvalidated by Bullion itself.
- **`pipeline.py`**: add `evaluate_macro_gate(as_of_date, session=requests, required_breaches=2)`
  (same wrapper shape as `evaluate_vix_gate`) plus one more `if not evaluate_macro_gate(...):
  return blocked` line in `decide_trade`, joining the existing `gates_always_pass` bypass
  alongside the vix/sentiment/earnings gates. `decide_trade` needs no new required parameter —
  unlike `fred_api_key`/`finnhub_api_key`, reading Bullion's public JSON needs no credential.

**Thresholds** (values as published in Bullion's `data.json`, confirmed against the live file):

| Field | Threshold | Breach condition |
|---|---|---|
| `vix` | 25.0 | `vix >= 25.0` |
| `nfci` | 0.0 | `nfci >= 0.0` |
| `hy_oas` | 5.0 | `hy_oas >= 5.0` (**percentage points, not basis points** — Bullion's `hy_oas` field mirrors FRED's `BAMLH0A0HYM2` raw units, e.g. `2.71` means 2.71%; an earlier session's "500bps" framing was a unit error, corrected here) |
| `curve_slope` (`us10y - us2y`) | 0.0 | `curve_slope < 0.0` |

## Data Flow

Bullion's `data.json` (confirmed by fetching the live file) has two relevant top-level keys:

- **`fields`** — each field's single most-recent `{value, published, ref_date, cadence,
  source}`. Fine for "right now," but **not usable for `as_of_date` in the past** (the
  backtester's use case), since it only ever reflects the newest values.
- **`history`** — a dict keyed by **ISO date string**, where each date's value is a dict of
  `{field_name: value}` containing only whatever fields were freshly published as of that date
  (e.g. `"2026-08-13": {"vix": 14.6, "hy_oas": 2.71, "us10y": 4.63, "us2y": 4.15, ...}`). This is
  the shape `fetch_bullion_macro_snapshot` actually walks — a correction from an earlier
  session's assumption that `history` was keyed by field name instead.

**Forward-fill algorithm:** for each of the 5 raw values needed (`vix`, `nfci`, `hy_oas`,
`us10y`, `us2y` — `curve_slope` is derived, not fetched directly), walk `history`'s date keys
**descending, strictly before `as_of_date`** (same no-lookahead discipline as `vix_gate.py`'s
`observation_end = today - 1 day`), and take the value from the first date whose record actually
contains that field. Confirmed real cadences directly from `data.json`'s own
`fields.<name>.cadence`: `vix`/`hy_oas`/`us10y`/`us2y` are `"daily"`, `nfci` is `"weekly"`.
`curve_slope = us10y - us2y`, computed only after both inputs individually clear their own
staleness check.

## Error Handling

- HTTP failure (network error, timeout, non-2xx status) → `MacroDataUnavailable`.
- Malformed JSON, or a response missing the `"history"` key → `MacroDataUnavailable`.
- A field with no candidate value within its staleness ceiling (daily fields: 5 days, matching
  `vix_gate.py`'s existing `MAX_STALENESS_DAYS`; weekly `nfci`: 10 days) → `MacroDataUnavailable`,
  naming the specific field. This is a real, observed case, not hypothetical: the newest date
  present in `history` as of this design (`2026-08-14`) is missing `vix`/`hy_oas`/`us10y`/`us2y`
  entirely — only slower-cadence fields (`spx`, `xlk`, etc.) were fresh that day. The
  walk-backward logic survives this by finding the next older date within the ceiling; it only
  raises if none exists.
- `macro_gate(snapshot, ...)` itself needs no error handling — by the time it runs,
  `fetch_bullion_macro_snapshot` has already guaranteed all 4 values present and fresh, or raised.
- `evaluate_macro_gate` in `pipeline.py` catches `MacroDataUnavailable` and returns `False`
  (blocks), exactly like `evaluate_vix_gate` — fail-closed, never "skip this gate."

## Testing

**`tests/test_macro_gate.py`** (new, mirrors `test_vix_gate.py`'s conventions — `session=requests`
injectable, `MagicMock` fake responses):
- `macro_gate`: allows when breaches < `required_breaches`; blocks at/above the threshold; blocks
  when all 4 breach.
- `fetch_bullion_macro_snapshot`: parses the most-recent-before-`as_of_date` value per field from
  a crafted `history` dict; walks backward past a date missing recent fields (the real observed
  `2026-08-14` gap); raises when a field is stale beyond its ceiling; accepts a field within its
  own (weekly vs. daily) ceiling; raises on HTTP failure and on a malformed/missing `history` key;
  correctly computes `curve_slope`; and a dedicated lookahead-bias regression test (mirroring
  `vix_gate.py`'s own) confirming a value dated exactly on `as_of_date` is never used.

**`tests/test_pipeline.py` additions** — same shape as the existing per-gate tests:
- `test_evaluate_macro_gate_fails_closed_on_fetch_error` / `_passes_through_on_success`, patching
  `graywind_strategy.pipeline.fetch_bullion_macro_snapshot` (mirrors how `evaluate_vix_gate`'s
  tests patch `fetch_latest_vix` the same way).
- `_passing_gates()`'s existing `patch.multiple(...)` helper gets a 4th entry:
  `evaluate_macro_gate=lambda **kw: True` — every existing `gates_always_pass=False` test that
  relies on this helper needs no other change.
- `test_decide_trade_blocks_on_macro_gate_failure`, matching
  `test_decide_trade_blocks_on_vix_gate_failure`'s exact pattern.

No `backtester.py`/`live_loop.py`-level test changes are needed: both already forward gate
evaluation through `decide_trade` opaquely, and the macro gate needs no new required parameter
threaded through either caller — unlike the credentialed gates, reading Bullion's public JSON
needs no key.

## Out of Scope

- Any change to `vix_gate.py` itself, or consolidating it with the new macro gate — the user
  chose to keep both rather than touch working/tested code.
- A weighted or z-score composite instead of vote-counting — rejected as unvalidated modeling
  work Bullion itself doesn't provide.
- Any Bullion field beyond `vix`/`nfci`/`hy_oas`/`us10y`/`us2y` — Bullion publishes 23 fields
  total; only these 4 (5 raw) feed this gate.
- Backtest-period behavior if Bullion's own `data.json` history doesn't extend far enough back to
  cover a given backtest window — not addressed here; `MacroDataUnavailable` (blocking) is the
  correct fail-closed behavior for that case already, same as any other staleness failure.

# Graywind — Sector-Aware Model Direction — Session Handoff

**Written:** 2026-08-16 · **For:** a fresh session picking up (a) the still-unverified live
paper-trading cycle, and (b) an open, *not yet scoped* direction — whether Graywind's
strategy should become sector-aware instead of one fixed rule applied to every symbol.

## Goal

Two threads, not one. First: get Graywind's live cron job to actually complete a real
market-hours cycle (still unverified — see "What has failed / risks / caveats"). Second: this
session ran a sector comparison backtest that showed the current fixed RSI(14)+SMA(10/30)
thresholds perform meaningfully worse on energy/tech sector proxies than on the live
AAPL/SPY watchlist — the user asked "what do you think about an industry-specific model,"
got a direct opinion (directionally justified by the data, but there's a shallow-overfit trap
vs. doing it properly), then asked for this handoff **before any scoping happened**. There is
no plan or spec for a sector-aware model yet — that's the first thing a resuming session
should produce, not skip to implementing.

- Relevant specs/plans (Phase 1 + dashboard, not this new direction):
  `docs/superpowers/specs/2026-08-13-graywind-phase1-mvp-design.md`,
  `docs/superpowers/specs/2026-08-15-graywind-dashboard-design.md`
- Burn-in gating decision (still governs when Phase 2 can start):
  `docs/superpowers/burn-in-decision.md`
- Prior handoff (dashboard build, not superseded by this one — different thread, read only if
  you're touching the dashboard): `docs/superpowers/graywind-dashboard-live-handoff.md`

## How to resume (do this first)

1. Confirm state: `git -C ~/Projects/graywind log --oneline -3` — most recent
   commit should be `37101a6` ("Fix backtester lookahead bias, capital check, and drawdown
   blindness; fix Alpaca IEX feed"). Branch is `main`, no feature branch in flight.
2. Check whether a real live cycle has run yet: visit
   `https://sinbadtheexplorer.github.io/graywind/` — if it still shows "no cycle has run
   yet," the live loop has not successfully completed since this handoff (see caveat below on
   why that was likely broken until `37101a6`).
3. Decide which thread you're resuming — live-cycle verification (small, concrete) or the
   sector-model direction (large, needs a plan/spec first via `superpowers:brainstorming` +
   `superpowers:writing-plans`, do not start coding it directly).
4. **Immediate next action:** confirm the live GitHub Actions cron job actually succeeds on
   its next scheduled run (see caveat below — this is blocking and unverified, not assumed
   done).

## Current state (active files)

**Branch:** `main`, 2 commits ahead of the previous handoff's reference point (`77f9a12`).

**Files created / changed (committed in `37101a6`):**
- `graywind_strategy/backtester.py` — three correctness fixes, all TDD'd: (1) entries/exits
  now fill at the *next* bar's open instead of the signal bar's own close (was lookahead
  bias); (2) buys are clamped/skipped against actual cash left after other same-bar fills
  (was no buying-power check); (3) `DrawdownBreaker.update_equity()` now gets mark-to-market
  equity (realized + unrealized on open positions), not realized-only equity.
- `fetch_alpaca_data.py` — `fetch_bars()` now requests `feed=DataFeed.IEX` explicitly. Free/
  paper Alpaca accounts get a 401-adjacent `"subscription does not permit querying recent SIP
  data"` error without this — **this is the most likely reason the live cron job has never
  confirmed a successful cycle** (see burn-in-decision.md's precondition).
- `tests/test_backtester.py`, `tests/test_fetch_alpaca_data.py` — new/updated tests for all of
  the above. 145/145 tests passing after this commit.
- `scripts/fetch_sector_data.py` (new) — fetches XLE/XLK/XLV 15-min bars into `data/sector/`
  (gitignored), separate from the live watchlist's `alpaca_data/`.
- `scripts/run_sector_backtest.py` (new) — runs the fixed backtester independently per symbol
  (fresh $10k each, not pooled) across AAPL/SPY/XLE/XLK/XLV and prints a comparison table.

**Files later work will modify (untouched so far):**
- `graywind_strategy/strategy_engine.py` — the fixed-threshold RSI(14)+SMA(10/30) logic a
  sector-aware model would need to touch. Currently one rule for every symbol, no sector
  awareness at all.
- `fetch_alpaca_data.py`'s `WATCHLIST = ["AAPL", "SPY"]` — the **live** watchlist. Not touched
  this session on purpose; the sector ETFs were fetched to a separate script/directory
  specifically so this stays untouched pending a real decision.

**Scratch workspace / traps:**
- ⚠️ `data/sector/*.csv` and `alpaca_data/*.csv` are gitignored, fetched fresh this session,
  and will go stale — don't trust their contents without re-running the fetch scripts.
- ⚠️ `docs/superpowers/burn-in-decision.md` cites a Sharpe of 5.209 from
  `scripts/task11_integration_run.py` — that run predates this session's backtester fixes
  (lookahead bias especially), so that number is now known to be inflated. The burn-in
  *decision* (require real-data burn-in regardless of backtest numbers) still holds; the
  cited number does not.

**Not mine — leave alone:** `docs/superpowers/graywind-dashboard-brainstorm-handoff.md`,
`docs/superpowers/graywind-dashboard-live-handoff.md`, `docs/superpowers/archive/` — dashboard
thread, unrelated to this session's work.

## What has changed

- Commit `37101a6`: the three backtester bugs and the IEX feed fix (see "Current state"
  above). Pushed to `origin/main`.
- Ran `scripts/run_sector_backtest.py` (not committed — output was printed, not saved to a
  file) against ~6 months of 15-min bars per symbol, fixed backtester, `gates_always_pass=True`
  (no FRED/Finnhub keys available this session), fresh $10k equity per symbol:

  | Symbol | Trades | Sharpe | Max Drawdown | Win Rate |
  |---|---|---|---|---|
  | AAPL (live) | 65 | 1.672 | 4.211% | 53.125% |
  | SPY (live) | 27 | 1.271 | 4.173% | 53.846% |
  | XLE (energy) | 61 | 0.918 | 7.469% | 46.667% |
  | XLK (tech) | 83 | 0.357 | 10.780% | 43.902% |
  | XLV (health) | 27 | 1.220 | 3.080% | 53.846% |

  XLK performs ~5x worse on Sharpe than AAPL with ~2.6x the drawdown, despite AAPL itself
  being a tech stock — the current thresholds are not "tech-robust," they're closer to
  AAPL/SPY-specific. XLV (health/defensive) held up close to AAPL/SPY; XLE (energy) sits in
  between.

## What has failed / risks / caveats

- **UNVERIFIED: a real live market-hours cycle has never been confirmed to succeed**, even
  after the IEX feed fix in `37101a6`. That fix was applied and pushed, but no scheduled run
  has been observed to complete successfully since. Do not assume it works — check the
  dashboard URL or Actions run history first.
- **UNVERIFIED: whether the live GitHub Actions repo secrets (`ALPACA_API_KEY`,
  `ALPACA_API_SECRET`) match the key pair the user regenerated locally this session.** The
  user regenerated their Alpaca key pair mid-session (the original had an invalid/placeholder
  secret) and said they updated the GitHub secret to match, but this was not independently
  verified (no `gh` CLI available in that session's shell) — confirm by checking Actions run
  logs for auth errors, not by trusting this note.
- The sector comparison table above is **one 6-month backtest window, not out-of-sample
  validated** — it's evidence the current thresholds aren't sector-robust, not a validated
  sector-specific model. Treat it as "there's a real problem here," not "here's the fix."
- No plan or spec exists yet for a sector-aware model. The user explicitly deferred scoping
  ("let's not talk about scope") — don't skip straight to implementation from this handoff.

## What's next (ordered)

1. Verify the live cycle: check the dashboard / Actions run history for the first successful
   scheduled run since `37101a6`. If it's still failing, debug from real error output, not
   assumption — the IEX fix was the most likely culprit but may not be the only one.
2. Independently confirm the GitHub repo secrets are current (Settings → Secrets and
   variables → Actions on `SinbadTheExplorer/graywind`).
3. Only once (1) and (2) are resolved: if picking up the sector-aware model thread, start with
   `superpowers:brainstorming` on the real question underneath the data above — is this a
   threshold-retuning problem (cheap, real overfitting risk) or a signal-logic problem (RSI/SMA
   crossover may not even be the right signal type for a defensive sector)? Don't default to
   the cheap version without deciding that first. Follow with `superpowers:writing-plans`
   before touching `strategy_engine.py`.
4. If retuning or adding sector-specific logic: any validation must be out-of-sample (e.g.
   held-out time window per sector), not the same backtest-and-eyeball this session did —
   that was sized as "is there a problem," not "does this fix generalize."

## Verification idioms used in this project

- Full test suite: `python3 -m pytest tests/ -q` (145 passing as of `37101a6`).
- Sector comparison: `python3 scripts/run_sector_backtest.py` (needs `data/sector/*.csv` and
  `alpaca_data/*.csv` present — re-fetch first if stale via `scripts/fetch_sector_data.py` and
  `fetch_alpaca_data.py`, both need `ALPACA_API_KEY`/`ALPACA_API_SECRET` in the environment,
  e.g. `ALPACA_API_KEY="..." ALPACA_API_SECRET="..." python3 scripts/fetch_sector_data.py` —
  env vars set via a separate `export` command do NOT persist to the next shell invocation in
  this harness; pass them inline on the same command line).
- This project follows TDD (red/green) for any backtester or fetch-logic change — see
  `tests/test_backtester.py`'s existing tests for the mocking convention (`decide_trade` is
  patched via `unittest.mock.patch`, not called against real signal generation).

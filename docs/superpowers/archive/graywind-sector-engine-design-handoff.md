# Graywind — Sector-Aware Engine Design — Session Handoff

**Written:** 2026-08-16 · **For:** a fresh session continuing brainstorming on the
sector-aware strategy engine (architecture approved, design not yet complete), plus the
still-carried-forward live-cycle verification thread.

## Goal

Same two threads as the previous handoff, now further along on one of them. First: get
Graywind's live cron job to actually complete a real market-hours cycle (still unverified).
Second: the sector-aware model direction got decomposed into three separate subsystems —
(1) a sector-aware strategy engine, (2) an automated external financial-data feed (analyst
ratings, earnings estimates), (3) a YouTube-transcript-derived prediction signal from
"reputable sources." The user chose to brainstorm (1) first. This session ran a root-cause
analysis on *why* sectors backtest differently, got the user's approval on the technical
direction and the high-level architecture, and stopped there — the design is **partially
presented, not finished**, and nothing has been written to a spec file yet.

- Relevant specs/plans (Phase 1 + dashboard, unrelated to this new direction):
  `docs/superpowers/specs/2026-08-13-graywind-phase1-mvp-design.md`,
  `docs/superpowers/specs/2026-08-15-graywind-dashboard-design.md`
- Burn-in gating decision (still governs when Phase 2 can start):
  `docs/superpowers/burn-in-decision.md`
- Prior handoff this one supersedes (same thread — read that one only if this file's "What
  has changed" section is unclear on how we got here):
  `docs/superpowers/graywind-sector-model-handoff.md`

## How to resume (do this first)

1. Confirm state: `git -C /Users/thanhnguyen/Projects/graywind log --oneline -3` — most
   recent commit should still be `37101a6`. No code was written this session — it was pure
   design/discussion — so `git status` should be clean apart from these handoff docs.
2. Re-check the live dashboard: `https://sinbadtheexplorer.github.io/graywind/` — as
   of this handoff it still shows an empty equity curve and trade log. The user's working
   theory this session is that the gap is simply because it was Sunday (market closed), not
   a code problem — **plausible but not independently confirmed** from Actions run history
   (no `gh` CLI available in this session either). Don't assume either explanation; check
   real run history once a weekday has passed.
3. Re-invoke `superpowers:brainstorming` for the sector-engine design — but **resume from
   design Section 2 (data flow)**, not from scratch. Section 1 (architecture) was already
   presented and approved this session; re-litigating it wastes the user's time.
4. **Immediate next action:** present the data-flow section of the design (how
   `sector_config.py` + `volatility.py` derive per-symbol parameters and how they're wired
   into `pipeline.py`/`backtester.py`), then error-handling and testing sections, per the
   brainstorming skill's normal flow.

## Current state (active files)

**Branch:** `main`, 0 commits ahead of `37101a6` — no code changed this session.

**Files created / changed this session:** none. This was a design-only session; the root
cause analysis below was run as ad-hoc Python, not saved to a script.

**Files later work will modify (per the architecture approved this session, untouched so
far):**
- `graywind_strategy/strategy_engine.py` — `compute_signals()` needs a `confirmation_bars`
  parameter; a crossover should only fire after the condition holds for K consecutive bars,
  not on the first bar (see "What has changed" for why).
- `graywind_strategy/pipeline.py` (`decide_trade`) — needs to look up per-symbol
  thresholds/K instead of using `strategy_engine.py`'s module-level constants.
- `fetch_alpaca_data.py`'s `WATCHLIST = ["AAPL", "SPY"]` — the user wants this expanded to
  include new sector symbols, but see the sequencing caveat below before doing this.

**Files the design calls for that don't exist yet:**
- `graywind_strategy/sector_config.py` — `SYMBOL_SECTOR` mapping (symbol → sector tag) and
  reverse lookup. Sector tags exist for *future* non-volatility caveats (an energy oil-price
  gate, a tech earnings-surprise gate, etc.), not used for threshold math directly.
- `graywind_strategy/volatility.py` — computes a symbol's trailing volatility (e.g. ATR(14)
  as % of price) and maps it to a confirmation-bars count `K` (proposed low/med/high →
  K=1/2/3) and any threshold adjustment.

**Scratch workspace / traps:**
- ⚠️ `data/sector/*.csv` and `alpaca_data/*.csv` are gitignored and will go stale — re-fetch
  before trusting (same caveat as the prior handoff; nothing has changed here).
- ⚠️ The hold-time root-cause analysis below was run inline, not saved as a script — if you
  need to reproduce it, re-run against current CSVs (see "Verification idioms"), don't treat
  the numbers as re-derivable from a committed file.

**Not mine — leave alone:** `docs/superpowers/graywind-phase1-mvp-handoff.md` (Phase 1 MVP
thread, unrelated), `docs/superpowers/archive/` (older archived handoffs).

## What has changed

- Ran a root-cause analysis (not the same as the prior session's sector comparison table —
  this one splits each symbol's own trades by hold time) on XLK and AAPL using the fixed
  backtester against `data/sector/xlk.csv` / `alpaca_data/aapl.csv`:

  | | XLK <1 day hold | XLK ≥1 day hold | AAPL <1 day hold | AAPL ≥1 day hold |
  |---|---|---|---|---|
  | Trades | 14 | 27 | 4 | 28 |
  | Win rate | 21% | 56% | 25% | 57% |
  | Avg P&L | -1.21% | +0.82% | -1.54% | +0.97% |

  **Finding:** the failure signature (short-hold trades lose, long-hold trades win) is
  nearly identical on both symbols — this is a general whipsaw problem in the RSI/SMA
  signal, not sector-specific broken logic. The actual sector difference is that XLK
  generates proportionally more short-hold (whipsaw) entries — 34% of its trades vs 13% for
  AAPL — because its higher short-term volatility trips the crossover threshold prematurely
  more often.
- Based on that finding, the user approved: **retune (volatility-scaled thresholds), not
  rebuild signal logic.** Different-signal-logic-per-sector was explicitly ruled out by this
  data, not just deferred.
- The sector-aware direction was decomposed into 3 subsystems (engine / external data feed /
  YouTube signal) after the user's initial answer bundled automated external data *and*
  YouTube-transcript ingestion together — those are materially different builds (a data
  pipeline vs. transcript scraping + LLM signal extraction from sources of dubious
  reliability) and need separate specs. User chose to brainstorm the engine first.
- Presented 3 architecture approaches for the engine (A: static per-sector config table, B:
  fully dynamic per-symbol volatility scaling with no sector concept, C: hybrid — sector tag
  as the organizing unit for future caveats, volatility-scaled confirmation-bars filter
  within each sector). **User chose C.**
- Presented and got approval on Section 1 (architecture) of the C design: one parametrized
  engine (not N separate files per industry); a new confirmation-bars filter as the actual
  whipsaw fix; the two new files above; proposed initial roster beyond AAPL/SPY — energy →
  XOM/CVX, tech → NVDA/MSFT, health → JNJ/UNH. **The roster was proposed by the assistant and
  only implicitly accepted alongside the rest of the architecture — re-confirm it explicitly
  rather than assuming it's locked in.**
- User also said the new symbols should reach the **live** paper-trading watchlist, not stay
  backtest-only — see the sequencing caveat below, which was raised but not resolved.

## What has failed / risks / caveats

- **Nothing has failed** — this was a design-only session, no code was written or run
  against production.
- **UNVERIFIED (carried forward): live cron still hasn't completed a real market-hours
  cycle.** Checked the public dashboard this session — still empty. User attributes the gap
  to Sunday market closure; plausible, not independently confirmed via Actions run history.
- **UNVERIFIED (carried forward): GitHub Actions repo secrets** (`ALPACA_API_KEY`,
  `ALPACA_API_SECRET`) still not independently confirmed current — nothing addressed this
  since the prior handoff.
- **Design is incomplete.** Only architecture (Section 1) has been presented and approved.
  Data flow, error handling, and testing sections have not been presented. No spec file
  exists yet. Do not skip to `superpowers:writing-plans` or start implementing
  `sector_config.py`/`volatility.py` from this handoff alone — finish the design and get it
  written + self-reviewed + user-approved first, per `superpowers:brainstorming`'s normal
  flow.
- **Open, unresolved tension: live-watchlist sequencing.** The user's literal answer was
  "expand live watchlist now too" (ahead of burn-in confirmation on the existing AAPL/SPY
  pair). The assistant flagged that this means live-trading on: (a) a cron that has never
  confirmed a successful cycle, and (b) volatility-scaled thresholds for symbols that
  haven't been backtested at all yet — but did not get an explicit resolution from the user
  on whether to sequence backtest-validate-then-flip-watchlist, or genuinely flip it as soon
  as the code exists. **Raise this explicitly with the user before wiring `WATCHLIST`,
  don't assume either interpretation.**
- The individual-company roster (XOM/CVX, NVDA/MSFT, JNJ/UNH) needs its own backtest data
  fetched and run before it's trusted for anything — right now it's a proposed list, not
  validated.

## What's next (ordered)

1. Re-invoke `superpowers:brainstorming`, resume at design Section 2 (data flow: exactly how
   `sector_config.py` + `volatility.py` compute K/thresholds and how `pipeline.py` /
   `backtester.py` consume them), then continue through error-handling and testing sections.
   Do not re-present Section 1.
2. Before finalizing the spec: explicitly re-confirm the individual-company roster, and
   explicitly resolve the live-watchlist sequencing question (see caveat above) with the
   user rather than picking one silently.
3. Once the full design is presented and approved: write the spec to
   `docs/superpowers/specs/<today's date>-graywind-sector-engine-design.md`, run the
   self-review checklist (placeholders, contradictions, scope, ambiguity), commit it, then
   ask the user to review the file before invoking `superpowers:writing-plans`.
4. Any out-of-sample validation plan in the spec must reuse a genuinely held-out time window
   per symbol — the whipsaw analysis above and the prior session's sector comparison were
   both diagnostic ("is there a problem"), not validation that a fix generalizes.
5. Separately, unblocked, can happen anytime: verify the live cron on the next weekday
   market-hours run, and independently confirm the GitHub repo secrets are current (Settings
   → Secrets and variables → Actions on `SinbadTheExplorer/graywind`).

## Verification idioms used in this project (for the resuming session)

- Full test suite: `python3 -m pytest tests/ -q` (145 passing as of `37101a6`; no code
  changed since, should still hold).
- Sector comparison table: `python3 scripts/run_sector_backtest.py` (needs
  `data/sector/*.csv` and `alpaca_data/*.csv` present — re-fetch first if stale via
  `scripts/fetch_sector_data.py` and `fetch_alpaca_data.py`, both need
  `ALPACA_API_KEY`/`ALPACA_API_SECRET` passed inline on the same command line, e.g.
  `ALPACA_API_KEY="..." ALPACA_API_SECRET="..." python3 scripts/fetch_sector_data.py` — env
  vars set via a separate `export` do NOT persist to the next shell invocation in this
  harness).
- Hold-time whipsaw breakdown (ad hoc, not a saved script — reproduce manually): load a
  symbol's CSV with `pandas.read_csv(..., parse_dates=["time"])`, call
  `run_backtest({symbol: df}, starting_equity=10000.0, gates_always_pass=True)`, pair up
  `buy`/`sell` trades from `result.trades` into round trips, split by
  `(sell_time - buy_time) < 24h` vs `>= 24h`, compare win rate and average P&L% per bucket.
- This project follows TDD (red/green) for any backtester/strategy_engine/pipeline change —
  see `tests/test_backtester.py`'s mocking convention (`decide_trade` patched via
  `unittest.mock.patch`, not called against real signal generation).

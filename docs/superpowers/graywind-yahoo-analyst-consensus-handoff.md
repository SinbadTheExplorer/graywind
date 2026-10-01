# Graywind — Yahoo Analyst-Consensus Position-Sizer — Session Handoff

**Written:** 2026-08-18 · **For:** a fresh session resuming `superpowers:brainstorming`
mid-flow, to get final design approval and write/commit the design spec. **No spec, no code,
no commit exist yet for this feature** — this handoff captures a fully-worked design that has
not been written to disk.

## Goal

Add a Yahoo Finance analyst-consensus signal to Graywind's live-trading pipeline, as a
**continuous position-size multiplier** (not a boolean blocking gate like the existing five).
This is the first of three tracks decomposed out of the broader "professional analysis
sources" brainstorm — Reddit and YouTube are separate, fully unstarted tracks, not to be
designed together with this one.

- Full source-list history/reasoning: memory `project-graywind-analysis-sources.md` in
  `~/.claude/projects/-Users-me/memory/`.
- Immediate predecessor handoff (pre-brainstorm, now superseded by the work below):
  `docs/superpowers/graywind-analysis-sources-handoff.md`.
- No spec file exists yet — writing one is the next action.

## How to resume (do this first)

1. Confirm state: `git -C ~/Projects/graywind log --oneline -3` — top should
   be `994b249` on `main`, in sync with `origin/main`, same as when this handoff was written.
2. Re-invoke `superpowers:brainstorming` (already in progress — do not restart from scratch;
   read this whole handoff first, it contains the fully-worked design).
3. There is no plan or ledger yet — this hasn't passed the design-approval gate. Trust this
   handoff's "What's next" section, not any assumption about prior progress.
4. **Immediate next action:** ask the user the one open question below (`gates_always_pass`
   interaction), get final approval on the whole 7-section design, then write
   `docs/superpowers/specs/2026-08-18-graywind-yahoo-analyst-consensus-design.md` (adjust the
   date if resuming later) and commit it.

## Current state (active files)

**Branch:** `main` at `994b249`, in sync with `origin/main`. **Nothing on disk yet for this
feature** — no files created or changed. The design below exists only in this handoff and in
the brainstorming conversation transcript, not in the repo.

**Locked decisions from the clarifying-question phase (all resolved, do not re-ask):**
1. Data to pull: analyst consensus — recommendation trend + analyst price target. Not news
   headlines (redundant with `sentiment_gate.py`'s Alpaca/Benzinga feed), not earnings
   estimates (different from the existing `earnings_gate.py`, which only tracks the date).
2. Gate shape: **not** a boolean pass/fail gate like vix/sentiment/earnings/macro/sector — a
   continuous adjustment. This is a new mechanism with no prior precedent in this pipeline.
3. What it adjusts: **position size only**, via `position_sizer`. Not stop/target levels.
4. Fetch-failure behavior: neutral multiplier (`1.0`, no adjustment) — never blocks the trade.
5. Fetch cadence: **cache once per day per symbol**, not every ~15-minute cycle — to avoid
   hammering `yfinance`'s unofficial endpoint across the whole watchlist on every cron firing.
6. Scoring approach: **Approach A**, user-approved — two independent bounded sub-multipliers
   (recommendation-based, price-target-based), averaged. (Rejected alternatives: one combined
   weighted formula, or dropping price target and using recommendation trend alone.)

**The full 7-section design, as presented and mostly approved (reproduce exactly, this is the
actual content to carry into the spec, not a summary to re-derive):**

1. **Architecture** — new module `graywind_strategy/gates/analyst_consensus.py` (kept in the
   existing `gates/` directory for consistency, even though it doesn't block); new cache file
   `state/analyst_consensus.csv`; new `evaluate_analyst_consensus_multiplier` wrapper in
   `pipeline.py`, following the same `fetch_X` / pure-logic / `evaluate_X` three-layer split as
   the other gates, but returning `float` instead of `bool`.
2. **Data fetch** — `fetch_analyst_consensus(symbol)` uses `yfinance.Ticker(symbol).info`,
   reading `recommendationMean` (1.0 = Strong Buy … 5.0 = Strong Sell) and `targetMeanPrice`.
   Missing/`None` fields or a fetch exception both raise `AnalystDataUnavailable`.
3. **Scoring (Approach A)**:
   - `multiplier_rec = 1.15 - 0.075 * (recommendation_mean - 1)` → Strong Buy (1.0) = 1.15x,
     Hold (3.0) = 1.00x, Strong Sell (5.0) = 0.85x.
   - `multiplier_target = 1.0 + clamp((target_mean - current_price) / current_price, -0.15,
     0.15)` → capped at ±15% analyst-price-target upside/downside.
   - `multiplier = (multiplier_rec + multiplier_target) / 2` (naturally bounded to
     `[0.85, 1.15]`, no extra clamp needed).
4. **Caching** — `state/analyst_consensus.csv`, columns
   `symbol,date,recommendation_mean,target_mean,multiplier`. Before fetching, check for a
   `(symbol, today)` row; reuse if present. If absent: fetch, compute, append the row, write.
   A missing or malformed file/row is a cache miss (re-fetch), never a crash. Committed by the
   `live-trading.yml` workflow the same way `state/positions.csv` already is.
5. **Error handling** — `evaluate_analyst_consensus_multiplier` catches
   `AnalystDataUnavailable` from a fresh fetch and returns `1.0`.
6. **Integration into `pipeline.py`** — applied immediately after the existing sizing call in
   `decide_trade`, **before** the `if shares <= 0` hold-check:
   ```python
   shares = position_sizer.shares_to_buy(account_equity, current_price, stop_price)
   shares = round(shares * evaluate_analyst_consensus_multiplier(
       symbol=symbol, as_of_date=as_of_date, current_price=current_price))
   if shares <= 0:
       return TradeDecision(action="hold", reason="position size rounds to zero shares")
   ```
7. **Testing** — TDD per project convention. New `tests/test_analyst_consensus.py` covering
   the scoring formula's boundary values (Strong Buy/Sell endpoints, ±15% clamp, Hold =
   neutral), fetch-failure → neutral-multiplier, and cache hit/miss/malformed-row behavior,
   mirroring `test_earnings_gate.py`'s shape. `pipeline.py`'s existing `decide_trade` tests get
   one new case confirming the multiplier is applied to `shares`.

**A real architecture finding baked into the caching design above (do not re-derive, verified
by reading `.github/workflows/live-trading.yml` directly):** every ~15-minute live cycle is a
**fresh GitHub Actions process** — checkout → install deps → run `live_loop.py` → exit — there
is no long-lived daemon. An in-memory cache would NOT survive between cycles. This is why the
cache must be a persisted file (`state/analyst_consensus.csv`), following the exact precedent
of `state/operational.csv` / `state/positions.csv`, both committed by the workflow's existing
`git add -A state` step.

**Scratch workspace / traps:**
- ⚠️ No spec file exists yet at any path — do not look for one, write it fresh.
- ⚠️ Don't confuse this with `sentiment_gate.py` (existing, shipped, uses Alpaca/Benzinga news
  headlines) — this is a separate, new source and a separate mechanism (multiplier, not gate).

**Not mine — leave alone:** `docs/superpowers/burn-in-decision.md` (live paper-trading burn-in
clock, unrelated), `docs/superpowers/graywind-dashboard-redesign-handoff.md` (separate,
unrelated dashboard-redesign track — do not merge context with this one),
`docs/superpowers/graywind-phase1-mvp-handoff.md` (older, tracked, unrelated),
`docs/superpowers/archive/` (superseded handoffs), `state/*.csv` / `dashboard-data/*.csv`
(live-cron output, updates every ~15 min during market hours regardless of this work).

## What has changed

Nothing shipped. A full design was worked out conversationally (clarifying questions →
approach proposal → 7-section design) but never written to a spec file, never committed. This
handoff exists because the user asked for a handoff mid-brainstorm, before the final
"write the spec" step.

## What has failed / risks / caveats

- **Nothing has failed — nothing has been implemented yet.**
- **One open question, NOT yet answered by the user** — must be resolved before final design
  approval: should the analyst-consensus multiplier still apply when `decide_trade` is called
  with `gates_always_pass=True` (the existing flag that bypasses the 5 blocking gates for
  synthetic/testing runs)? Claude's stated recommendation in the brainstorm was **yes, always
  apply it regardless of `gates_always_pass`**, reasoning that flag is documented specifically
  for bypassing *blocking* gates and this isn't one — but the user had not confirmed this before
  asking for the handoff. Do not treat this as settled; ask it explicitly on resume.
- **The 7-section design overall has not received final "yes, write the spec" approval** — the
  user approved the scoring sub-decision ("Approach A") specifically, and the full design was
  presented in the message immediately before the handoff was requested. Get an explicit
  whole-design approval before writing the spec file, per the brainstorming skill's own gate
  (do not skip from "presented" to "written" without approval).
- **Unverified assumption carried into the design, not yet checked against real data:**
  `yfinance.Ticker(symbol).info`'s `recommendationMean` / `targetMeanPrice` fields are assumed
  present and correctly named based on general `yfinance` knowledge, not verified against the
  actual installed `yfinance` version in this repo's `requirements.txt`. The existing
  `sentiment_gate.py`'s own docstring (a very relevant precedent — read it) documents a real
  past incident where an assumed field name (`symbol_or_symbols`) silently failed in a
  different library (`alpaca-py`) because pydantic swallowed the bad kwarg. **Before writing
  the spec (or at latest, before implementation), verify the actual field names by inspecting
  the installed `yfinance` package** (`python3 -c "import yfinance; print(yfinance.__version__)"`
  then inspect `Ticker.info` keys against a real symbol, or read the installed source) —
  do not assume the design's field names are correct without this check.

## What's next (ordered)

1. Ask the user the `gates_always_pass` open question (see above).
2. Get explicit approval on the full 7-section design as reproduced in this handoff (not just
   the scoring sub-decision).
3. **Before finalizing the spec**, verify `yfinance`'s actual field names against the installed
   version (see the caveat above) — fold the verified names into the spec, or note in the spec
   if they differ from what's written here.
4. Write `docs/superpowers/specs/2026-08-18-graywind-yahoo-analyst-consensus-design.md`
   (brainstorming skill checklist item 6), following the 7 sections above.
5. Run the brainstorming skill's spec self-review (placeholders, contradictions, scope,
   ambiguity) and fix inline (checklist item 7).
6. Ask the user to review the committed spec file (checklist item 8).
7. On approval, invoke `superpowers:writing-plans` to create the implementation plan
   (checklist item 9) — this is the brainstorming skill's terminal step; do not invoke any
   other implementation skill directly.
8. Once Yahoo is shipped, return to the Reddit and YouTube tracks as their own separate
   brainstorm → spec → plan cycles (per `project-graywind-analysis-sources.md`) — Reddit's
   validation/control design is explicitly load-bearing and must not be deferred once that
   track starts.

## Verification idioms used in this project (for the resuming session)

- Full Python test suite: `python3 -m pytest tests/ -q` (196 passing as of `994b249`).
- No `gh` CLI in this environment — check GitHub Actions run history via the public REST API
  (works unauthenticated for a public repo):
  ```
  curl -s "https://api.github.com/repos/SinbadTheExplorer/graywind/actions/workflows/live-trading.yml/runs?per_page=10" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); [print(r['run_number'], r['status'], r['conclusion'], r['event'], r['created_at']) for r in d['workflow_runs']]"
  ```
- Live public dashboard: `https://sinbadtheexplorer.github.io/graywind/`.
- This project follows TDD (red/green) for any `gates/`/`pipeline.py`/`strategy_engine.py`/
  `backtester.py` change.
- For any multi-task Python implementation: `superpowers:writing-plans` →
  `superpowers:subagent-driven-development` in an isolated worktree, with a whole-branch final
  review before merge — the template used by the per-sector gate pattern
  (`docs/superpowers/plans/2026-08-18-graywind-per-sector-gate.md`), to be repeated here once
  the spec is written and approved.

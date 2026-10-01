# Graywind — Professional Analysis Sources — Session Handoff

**Written:** 2026-08-18 · **For:** a fresh session (or this user) about to START brainstorming a
new feature — pulling professional financial analysis/commentary (Morningstar, Robinhood,
Investopedia, Yahoo, YouTube) into Graywind's trading signal. **Nothing has been built yet.**
This is a pre-brainstorm handoff, capturing the user's stated direction before any design or
code exists, not a resume-mid-build one.

## Goal

The user wants Graywind's live-trading pipeline to incorporate "professional analysis" from
five named sources: **Morningstar, Robinhood, Investopedia, Yahoo, and YouTube**. This directly
extends two subsystems that were explicitly decomposed-but-not-started during the 2026-08-17
sector-engine brainstorm:
- **Subsystem 2: automated external financial data** (analyst ratings, earnings estimates) —
  previously "no provider chosen yet"; the user has now named 4 candidate sources (Morningstar,
  Robinhood, Investopedia, Yahoo).
- **Subsystem 3: YouTube-transcript-derived prediction signal** — previously flagged as the
  riskiest piece of the original decomposition; still unresolved.

Full history: memory `project-graywind-sector-engine.md` in
`/Users/thanhnguyen/.claude/projects/-Users-thanhnguyen/memory/` (the original 3-way subsystem
decomposition, root-cause analysis behind subsystem 1 shipping first, and why 2/3 were
deferred). This repo's existing gate pattern (`graywind_strategy/gates/`) is what any new
source will plug into — most recently extended by the per-sector gate pattern (spec:
`docs/superpowers/specs/2026-08-18-graywind-per-sector-gate-design.md`, shipped `994b249`).

No spec or plan exists yet for this work — writing one is the first next action.

## How to resume (do this first)

1. Confirm state: `git -C /Users/thanhnguyen/Projects/graywind log --oneline -3` — top should
   be `994b249` on `main`, in sync with `origin/main`.
2. Read memory `project-graywind-sector-engine.md` for the subsystem 2/3 history and the
   reasoning already done there.
3. There is no ledger or plan to resume — this hasn't been brainstormed yet.
4. **Immediate next action:** invoke `superpowers:brainstorming` on this. Do NOT start writing
   code or picking a data provider before that — five sources is very likely too much for one
   spec (see "What's next" below).

## Current state (active files)

**Branch:** `main` at `994b249`, in sync with `origin/main`. Nothing on disk yet for this
feature — no files created or changed.

**Relevant prior art (read, don't modify without a plan):**
- `graywind_strategy/gates/sentiment_gate.py` — the closest existing analog: fetches Alpaca
  News headlines, scores with VADER, gates on a threshold. Any new source that produces a bool
  gate (vs. a continuous adjustment) should look like this file's shape.
- `graywind_strategy/gates/earnings_gate.py` — fetches Finnhub's earnings calendar; the
  existing template for "date-based external data + staleness ceiling."
- `graywind_strategy/gates/macro_gate.py` — fetches Bullion's own public `data.json`; the
  existing template for "vote-count across several external fields, fail-closed on fetch
  failure."
- `graywind_strategy/gates/sector_gates.py` (shipped 2026-08-18, `994b249`) — the newest gate
  pattern: a per-sector registry/dispatcher. If any of these 5 sources ends up sector-specific
  (e.g. Morningstar analyst ratings mattering more for some sectors), this is the plug-in
  point, not a new mechanism.
- `graywind_strategy/pipeline.py`'s `decide_trade` — currently calls 5 gates
  (vix/sentiment/earnings/macro/sector) inside `if not gates_always_pass:`. A 6th+ source most
  likely becomes another gate call here, following the same fail-closed contract (own
  `XDataUnavailable` exception, wrapped by an `evaluate_X_gate` function that returns `False`
  on fetch failure).

**Scratch workspace / traps:**
- ⚠️ None yet — no code exists for this feature.
- ⚠️ Don't confuse this with `sentiment_gate.py`'s existing Alpaca-News-based sentiment —
  that's already shipped and live. This handoff is about *additional*, named-source analysis
  on top of it, not a replacement for it.

**Not mine — leave alone:** `docs/superpowers/burn-in-decision.md` (Graywind's live
paper-trading burn-in clock, started 2026-08-17, unrelated to this), `docs/superpowers/archive/`
(older handoffs), `state/*.csv` / `dashboard-data/*.csv` (live-cron output, updates every
~15 min during market hours regardless of this work).

## What has changed

Nothing. This handoff exists to capture the user's stated direction before any
brainstorming/design/code happens, so a fresh session doesn't lose the specific source list.

## What has failed / risks / caveats

- **Nothing has failed — nothing has been attempted yet.**
- **Real open risk, flag before writing any plan:** none of the 4 named financial-data sites
  (Morningstar, Robinhood, Investopedia, Yahoo) are known to have a public, ToS-compliant API
  for this kind of automated fetching. Yahoo Finance is commonly accessed via
  unofficial/reverse-engineered endpoints (e.g. the `yfinance` library), which Yahoo's own ToS
  has historically restricted; Robinhood's API is likewise unofficial/reverse-engineered;
  Morningstar and Investopedia are typically scrape-only. Per this user's own project workflow
  (`~/.claude/CLAUDE.md`), the Brainstorming stage has a hard gate: validate plausibility
  before committing, and abort/rescope if a dependency can't reasonably be met — historically
  applied to hardware/compute ceilings, but the same principle applies to data-source access
  here. **This should be the very first thing resolved in brainstorming, source by source**,
  before any design work: is there a legitimate way to pull from each site, or does it get
  dropped/rescoped?
- **Scope risk:** 5 sources is very likely 5 (or more) independent pieces of work, similar to
  how the original "feed Graywind sector data" idea already split into 3 subsystems on
  2026-08-17. The brainstorming skill's own guidance is to flag oversized scope immediately and
  decompose into sub-project specs rather than trying to design all 5 sources at once.
- **YouTube specifically was already flagged as the riskiest piece** in the 2026-08-17
  brainstorm — transcript ingestion + LLM extraction, plus a real open question about whether
  financial YouTubers are a reliable signal at all vs. reactive/engagement-driven content. That
  skepticism still applies; it isn't resolved by the user naming it again here.
- **Investopedia is an odd fit as a live "signal" source** — it's overwhelmingly
  educational/reference content (definitions, "how X works" articles), not per-symbol analysis
  or ratings like the other four. Worth surfacing to the user early rather than assuming: what
  is Investopedia actually expected to contribute? (E.g. it may be intended to inform gate
  *design* — understanding a concept before building a check — rather than being a live,
  per-symbol data feed like the other four.)

## What's next (ordered)

1. Invoke `superpowers:brainstorming` on "pull professional analysis from
   Morningstar/Robinhood/Investopedia/Yahoo/YouTube into Graywind." Expect the first real move
   to be scope decomposition, not design — per the brainstorming skill's own rule, flag the
   5-source scope immediately rather than spending questions refining one source at a time.
2. Per source, resolve the access-legitimacy question above before designing anything against
   it (this is the hardware-ceiling-equivalent gate from the user's workflow, applied to data
   access instead of compute).
3. Once (2) narrows the list to sources that are actually buildable, decompose into separate
   sub-project specs — one source (or a natural grouping, e.g. "analyst-rating aggregators":
   Morningstar + Robinhood + Yahoo vs. "YouTube signal" as its own track) at a time, each
   getting its own spec → plan → implementation cycle, matching how subsystem 1 (volatility
   engine) and the per-sector gate pattern each shipped independently.
4. Whichever source ships first should follow the existing gate pattern (see "Current state"
   above) — a new `graywind_strategy/gates/<source>_gate.py` with its own `XDataUnavailable`
   exception and `fetch_...`/pure-logic split, wired into `pipeline.py`'s `decide_trade` as
   another gate, exactly like vix/sentiment/earnings/macro/sector.

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
  review before merge — exactly the pipeline the per-sector gate pattern just went through
  (`docs/superpowers/plans/2026-08-18-graywind-per-sector-gate.md`), and the template to repeat
  here once a specific source is scoped.

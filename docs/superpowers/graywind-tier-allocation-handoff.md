# Graywind Portfolio-Tier Allocation — Session Handoff

**Written:** 2026-08-26 · **For:** whoever starts sub-project 2c (symbol picks per tier) or
sub-project 3 (news-interpretation upgrade), or anyone auditing what shipped in this round.
**Implementation is done, reviewed, merged, and pushed — nothing is mid-flow.**

## Goal

Split Graywind's (a paper-trading bot) capital into three hard-partitioned risk tiers
(70/20/10) as part of a larger capital-scaling redesign (scaling the account down from
Alpaca's default $100k to $1,000). This piece — sub-project 2a+2b of that redesign — built the
*plumbing*: the tier config, the per-tier cash tracking, tiers 2/3 reusing the existing
intraday engine scoped to their own pool, and tier 1's new buy-and-hold monthly rebalance.
Picking the actual symbols for each tier (2c) is separate, later work.

- Spec: `docs/superpowers/specs/2026-08-26-graywind-tier-allocation-design.md`
- Plan: `docs/superpowers/plans/2026-08-26-graywind-tier-allocation.md` (has a correction note
  added post-merge — see "What has changed" below)
- Progress ledger (recovery map): it lived at
  `.superpowers/sdd/2026-08-26-graywind-tier-allocation/progress.md` inside the now-deleted
  worktree — **this no longer exists on disk**. It was gitignored scratch by design; git
  history (the commits below) is the permanent record now. Don't go looking for it.
- Sibling memory: `project-graywind-capital-redesign.md` (auto-memory, not in this repo) has
  the full 3-sub-project picture and cross-links to sub-project 1 (already shipped 2026-08-25).

## How to resume (do this first)

1. Confirm you're on `main`, up to date: `git log --oneline -5` should show
   `03fb9d3 Merge branch 'worktree-graywind-tier-allocation'` at or near the top (there may be
   newer cron auto-commits above it — that's normal, see "Verification idioms" below).
2. If starting 2c or 3, re-invoke `superpowers:brainstorming` first — both are real design
   work, not a continuation of this plan.
3. Trust `git log` over this doc's prose if they ever disagree — this doc was written from
   git, not memory, but memory here means the LLM's, not the ledger's; the SDD ledger itself
   is gone (see above), so git is now the only recovery map.
4. **Immediate next action:** nothing is blocked or waiting. The one manual step nobody has
   done yet: seed `state/tier_pools.csv` with real starting cash (e.g. `1,700.0` / `2,200.0` /
   `3,100.0` for a $1,000 account) — see "What's next" below.

## Current state (active files)

**Branch:** `main`, tier-allocation work landed via merge commit `03fb9d3`
(`7fe408b..03fb9d3` is this feature's range; `0196a6e..bdbff51` is the original worktree
branch's own commit range before the merge).

**Files created (committed):**
- `graywind_strategy/tier_config.py` — `SYMBOL_TIER = {}`, `TIER_TARGET_WEIGHTS = {1: 0.70, 2:
  0.20, 3: 0.10}`, `TIER1_SYMBOL_WEIGHTS = {}`, plus a module-level `assert` that the two
  symbol dicts stay disjoint (added in the final-review fix round — see below). **Both symbol
  dicts are still empty** — that's deliberate, see "What has changed."
- `graywind_strategy/tier1_rebalance.py` — pure drift/sizing math for tier 1's monthly
  rebalance (`RebalanceOrder`, `compute_rebalance_orders`, `should_rebalance_this_month`,
  `DRIFT_THRESHOLD = 0.05`). No I/O in this file at all.

**Files changed (committed):**
- `graywind_strategy/state_store.py` — added `load_tier_pools`/`save_tier_pools`
  (`state/tier_pools.csv`) and `load_rebalance_state`/`save_rebalance_state`
  (`state/tier1_rebalance.csv`), same CSV round-trip idiom as the existing `load_state`/
  `save_state`.
- `live_loop.py` — `process_symbol()` gained an optional `tier_pools` param: when a symbol is
  tagged in `SYMBOL_TIER` AND `tier_pools` is passed, sizing/settlement is scoped to that
  tier's pool instead of the whole account; otherwise behavior is byte-for-byte unchanged.
  `main()` now loads `tier_pools`/`rebalance_state` at startup, threads `tier_pools` into its
  real `process_symbol(...)` call (this exact wiring was the Critical bug — see below), runs
  `run_tier1_rebalance()` once a month (gated by `should_rebalance_this_month`), and saves
  both new state files in the `finally` block alongside the existing `save_state`.

**Files later work (2c) will touch:**
- `graywind_strategy/tier_config.py` — 2c's whole job is adding real entries to `SYMBOL_TIER`
  and `TIER1_SYMBOL_WEIGHTS`. No other plumbing change should be needed — that was the explicit
  design goal (see spec §1 "Rollout ordering").
- `state/tier_pools.csv` — needs its real starting-cash split seeded manually (see "What's
  next").

**Scratch workspace / traps:**
- ⚠️ The SDD ledger directory this plan used no longer exists (deleted per
  `subagent-driven-development`'s own finish step, gitignored scratch). Don't assume it's
  there; it isn't.
- ⚠️ `state/*.csv` and `dashboard-data/*.csv` are live-cron output, committed automatically
  every ~15 min during market hours by a GitHub Actions workflow unrelated to this feature —
  expect `main` to have moved since this doc was written just from those auto-commits. Not a
  conflict signal.
- ⚠️ **`state/tier_pools.csv` and `state/tier1_rebalance.csv` do not exist on disk yet** (as of
  this writing) — they get created by the *next* live cycle that runs after this merge
  (`save_tier_pools`/`save_rebalance_state` in `main()`'s `finally` block). Don't be alarmed if
  they're missing; check the next cron commit.

**Not mine — leave alone:** `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` is
an **untracked** file that appeared in the working tree during this session, alongside an
already-merged commit `741508c` ("docs: add design spec for news-debate shadow mode
(sub-project 3)") — this is a different, concurrent session's work on sub-project 3 (the
news-interpretation upgrade), not part of this handoff. Don't move, archive, or read it as if
it were part of this effort. If you're picking up sub-project 3, that handoff is the one to
read instead of this one.

## What has changed

- All 4 planned tasks (tier config + state persistence, tier-1 rebalance pure logic, tiers
  2/3 pool-scoped sizing in `live_loop.py`, tier-1 rebalance trigger in `main()`) implemented
  via `superpowers:subagent-driven-development` in an isolated worktree, each with its own
  clean task-level review (zero Critical/Important findings across all 4).
- **The final whole-branch review caught a real Critical bug no task-level review could see:**
  `main()`'s only real call to `process_symbol(...)` never actually passed
  `tier_pools=tier_pools` — it defaulted to `None`, so the entire tiers-2/3 sizing/settlement
  feature was unreachable in production regardless of what 2c ever put in `SYMBOL_TIER`. Every
  task's own tests passed because they called `process_symbol` directly with `tier_pools=`,
  masking the missing production wiring. This is a **plan defect** (the plan's Task 3 never
  had a step wiring `main()`'s call site), not implementer error.
- Same fix round (one round, all findings addressed, re-reviewed clean) also added:
  - A `tier1_equity <= 0` guard in `compute_rebalance_orders` — the shipped default (before
    manual cash-seeding) is exactly `0.0`, which would otherwise raise `ZeroDivisionError`,
    silently swallowed by `main()`'s exception handler, producing a permanent monthly no-op.
  - The `SYMBOL_TIER`/`TIER1_SYMBOL_WEIGHTS` disjointness assert in `tier_config.py`.
  - Patches for the 4 new state functions added to every `test_live_loop.py` test that calls
    `main()` directly — before this fix, running the test suite wrote real files into the
    repo's actual `state/` directory (this had already happened once mid-session and produced
    stray untracked files that had to be manually cleaned up and investigated).
  - Task 3's 5 tier-scoped tests were retargeted from tier 1 to tier 2 as their fixture (the
    6th, testing the untagged fallback, correctly stayed untagged) — using tier 1 in those
    tests had been silently normalizing exactly the symbol-routing configuration the spec
    forbids (a tier-1-tagged symbol going through the intraday engine at all).
  - `docs/superpowers/plans/2026-08-26-graywind-tier-allocation.md` got two small correction
    notes appended in place (search the file for "Correction found during") — one fixing a
    wrong manual-verification expectation in the original plan's Step 9, one documenting the
    missing-wiring plan defect above. Read the plan's live text, not a recollection of its
    first draft.
- **265/265 tests passing** as of merge (`.venv/bin/python -m pytest tests/ -q`).

## What has failed / risks / caveats

- **Nothing is currently broken or blocked.** Everything above is merged, tested, and pushed.
- **Ships with zero practical effect today, by design.** `SYMBOL_TIER` and
  `TIER1_SYMBOL_WEIGHTS` both start empty; every new code path either falls back to today's
  exact pre-existing behavior (tiers 2/3, via the `tier is not None and tier_pools is not
  None` guard) or no-ops entirely with zero I/O (tier 1, via `if not TIER1_SYMBOL_WEIGHTS:
  return []`). This was verified end-to-end by both the task-level and whole-branch reviews,
  not just assumed.
- **Deferred, not forgotten (parked as Minor findings in the now-deleted ledger — worth
  reading before 2c, since 2c is exactly what could activate them):**
  - A tier-1 rebalance buy debits `tier_pools[1]` but is never recorded in `open_positions`.
    If a symbol were ever mapped into *both* `SYMBOL_TIER` and `TIER1_SYMBOL_WEIGHTS`
    simultaneously (which the new assert now prevents, but only if 2c respects it), tier
    equity accounting would be wrong. The assert is the actual guard; keep it.
  - `save_tier_pools` writes only the tiers present in the dict it's given, not always all 3
    rows — inert under every current caller (all go through `load_tier_pools`'s always-full
    default), but a future caller passing a partial dict could silently drop a row.
  - Two different definitions of "tier equity" coexist by design: `process_symbol` (tiers 2/3)
    uses cost basis, `run_tier1_rebalance` (tier 1) uses live mark-to-market re-derived from
    Alpaca's real position list each run. Justified (tiers 2/3 mirrors `backtester.py`'s
    existing `committed_capital` pattern) but undocumented in the code itself beyond this doc.
  - Pool cash settles at signal/bar-close price, not actual fill price, with no reconciliation
    path — same imprecision the rest of the bot already has for its equity tracking, just now
    also true of the per-tier ledgers.
  - `state/operational.csv`/`state/positions.csv` aren't gitignored and have no structural
    guard against a future `main()`-level test forgetting to patch `save_state` (pre-existing,
    not introduced by this work, just newly relevant since this work already tripped the
    equivalent bug once for the two new tier files).

## What's next (ordered)

1. **Manual, whenever you're ready to actually activate any of this:** edit
   `state/tier_pools.csv` (create it if `main()` hasn't run since the merge yet) with real
   starting cash per tier — e.g. `tier,cash` / `1,700.0` / `2,200.0` / `3,100.0` for a $1,000
   account, matching the 70/20/10 split. No code does this automatically, matching
   sub-project 1's precedent of the Alpaca balance change itself being a manual step.
2. **Sub-project 2c** (symbol picks per tier): start a fresh `superpowers:brainstorming`
   session. Its entire job, per the spec's explicit rollout design, is adding real entries to
   `SYMBOL_TIER` (tiers 2/3) and `TIER1_SYMBOL_WEIGHTS` (tier 1, weights should sum to 1.0) in
   `graywind_strategy/tier_config.py` — verify during that brainstorm whether that's still
   true given real symbol research, since it was a design intent, not a runtime-enforced
   contract (the disjointness assert only catches double-mapping, not a mis-scoped 2c).
3. **Sub-project 3** (news-interpretation upgrade): unrelated to this work; a concurrent
   session already has a design spec for it (`741508c`, see "Not mine — leave alone" above) —
   read that handoff, not this one, if picking that up.

## Verification idioms used in this project (for the resuming session)

- Full test suite: **use the project's `.venv`**, not system `python3` —
  `.venv/bin/python -m pytest tests/ -q`. System Python lacks `yfinance` and other deps and
  will fail to even collect several test files (`test_analyst_consensus.py`,
  `test_backtester.py`, `test_live_loop.py`, `test_pipeline.py`).
- Local checkouts of this repo drift stale fast (a 15-min live cron auto-commits to `main`
  continuously) — `git fetch origin main` and diff against `origin/main` before trusting a
  local working tree's state, or read files straight from a ref with `git show
  origin/main:<path>`.
- GitHub Actions run history (works unauthenticated for this public repo, no `gh` CLI needed):
  ```
  curl -s "https://api.github.com/repos/SinbadTheExplorer/graywind/actions/workflows/live-trading.yml/runs?per_page=10" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); [print(r['run_number'], r['status'], r['conclusion'], r['event'], r['created_at']) for r in d['workflow_runs']]"
  ```
- Live public dashboard: `https://sinbadtheexplorer.github.io/graywind/`.
- This project follows TDD (red/green) for any `gates/`/`pipeline.py`/`strategy_engine.py`/
  `backtester.py`/`risk/`/`live_loop.py` change, and uses `superpowers:brainstorming` →
  `superpowers:writing-plans` → `superpowers:subagent-driven-development` for multi-step
  Python implementation work, per this session's own execution. **Always check
  `git branch -a` and `git log --all --oneline` for unmerged work before starting a new
  sizing/risk-related change** — this exact codebase had a fully-built, tested, unmerged
  branch sit untouched for 5 days earlier in this redesign effort with zero mention anywhere.

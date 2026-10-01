# Graywind — Tier-1 Gating Decision + Tier-Pool Funding Fix — Session Handoff

**Written:** 2026-09-01 · **For:** whoever picks up Graywind next — likely to push this
session's commit, verify it against a real cycle, and decide on the DeepSeek question
below.

## Goal

Two threads, worked together because they both trace back to the 2026-08-31 real-capital
readiness audit's tier-related findings:

1. **Should tier 1 (70% of capital, SPY buy-and-hold) get VIX/macro exposure gating?**
   `graywind-edge-thesis.md`'s Part 2 named this as the one lever that could plausibly
   deliver the 3–10% return goal in down years, and specified its own falsification
   test. This session ran that test. **Answer: no — tested, not just discussed, and it
   failed.**
2. **`tier_pools.csv` has read $0 on every tier, on both accounts, since the pool-scoped
   sizing code shipped 2026-08-25.** Found mid-session (unrelated to #1), fixed same
   session.

Authorities (read in this order):
- `docs/superpowers/graywind-tier1-exposure-test-results.md` — full method/data/results
  for thread 1.
- `docs/superpowers/graywind-edge-thesis.md` — updated "Status of this doc" section
  points here now; read that doc first for why thread 1 mattered.
- `docs/superpowers/graywind-tier-pool-funding-gap-handoff.md` — full finding + fix for
  thread 2 (its own "RESOLVED 2026-09-01" banner is at the top; original investigation
  below it is historical record, still accurate).

## How to resume (do this first)

1. Confirm where `main` actually is: `git log --oneline -3` should show `ff9c2b6` (this
   session's fix) on top of `d56cfc6` (the prior session's real-capital-audit handoff).
   **This commit is NOT pushed yet** — `git rev-list --count origin/main..HEAD` returns
   `1` as of this writing.
2. Run the test suite: `.venv/bin/python -m pytest -q` from repo root — expect
   `434 passed` (422 baseline + 12 new for `seed_tier_pools.py`).
3. Read the two results docs above for full detail — this handoff summarizes, they're
   the source of truth.
4. **Immediate next action:** get the user's go-ahead and `git push`. This session
   deliberately stopped short of pushing — it touches live-trading automation (a new
   workflow step hitting the real Alpaca API on both accounts) on a public repo, which
   warrants an explicit go rather than a session pushing on its own judgment.

## Current state (active files)

**Branch:** `main`, 1 commit ahead of `origin/main` (`ff9c2b6`), not yet pushed.

**Files created/changed, all in `ff9c2b6`:**
- `scripts/seed_tier_pools.py` (new) — seeds `tier_pools.csv` with the real 70/20/10
  split from live Alpaca equity/positions, once, idempotently (only fires when all
  three tiers read exactly `$0`). Reports a health status other tooling can alarm on.
- `tests/test_seed_tier_pools.py` (new) — 12 tests, pure-function + mocked-Alpaca
  integration coverage, mirrors `tests/test_check_macro_health.py`'s style.
- `.github/workflows/live-trading.yml` — new "Seed or check tier pool funding" step in
  both `live-cycle` and `live-cycle-small` jobs (right after `live_loop.py` runs), plus
  "Ensure the tier-pool-alarm label exists" / "Raise or clear the tier-pool alarm"
  steps per account, modeled directly on the existing `macro-alarm` pattern.
- `docs/superpowers/graywind-edge-thesis.md` — Part 2's "Status of this doc" section
  now records the falsification test outcome and links to the results doc.
- `docs/superpowers/graywind-tier1-exposure-test-results.md` (new) — full spike
  writeup: method, data sources, both rule variants, results tables, conclusion.
- `docs/superpowers/graywind-tier-pool-funding-gap-handoff.md` — updated in place (not
  a new file) with a "RESOLVED 2026-09-01" banner and the new deferred finding below.

**Files later work will modify (untouched so far):**
- `graywind_strategy/tier1_rebalance.py` — if the deferred re-anchoring gap (see below)
  ever becomes its own task, this is where the fix goes.
- `state/tier_pools.csv`, `state/small/tier_pools.csv` — will be written by the new
  seed script on the next real cycle **after this commit is pushed**. As of this
  writing `origin/main`'s copies are still `$0` — the fix hasn't run for real yet.

**Scratch workspace / traps:**
- ⚠️ **The push hasn't happened.** Don't assume the funding fix is live until you've
  confirmed the push and a subsequent real cycle.
- ⚠️ **Local checkout goes stale within hours** once live cron resumes writing — always
  read live state via `git show origin/main:<path>`, never the local working tree
  (longstanding project convention, still true).
- ⚠️ Two other git worktrees exist under `.claude/worktrees/` — leave alone, carried
  forward unchanged from every prior handoff.
- ⚠️ `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` still has an
  uncommitted working-tree diff inherited from a 2026-08-28 session. Not touched this
  session either — still sitting there, still not blocking anything.

**Not mine — leave alone:** `scripts/fetch_serv_bars.py` (needs the user to run it
themselves with real Alpaca credentials, unrelated to this session); `.DS_Store`;
`.claude/` (worktree metadata); the five untracked files in `docs/superpowers/archive/`
(`graywind-dual-account-advisor-plans-handoff.md`,
`graywind-dual-account-tier-symbols-handoff.md`,
`graywind-news-debate-provider-cost-handoff.md`,
`graywind-performance-reports-handoff.md`,
`graywind-quant-discipline-brainstorm-handoff.md`) — pre-existing from earlier sessions,
unrelated to this work.

## What has changed

- **Thread 1 (tier-1 gating): tested via a throwaway spike, not committed to the repo**
  (per `superpowers:brainstorming`'s spike convention — the code lived in this session's
  scratchpad, not here). Two independently designed VIX/macro exposure-scaling rules —
  a raw threshold, and a confirmation-bars variant modeled on `volatility.py`'s
  already-shipped tier-2/3 whipsaw fix — were backtested against SPY buy-and-hold,
  2000–2026, using real Yahoo/FRED data. Both landed at a wash or worse on Calmar ratio
  (0.15 vs buy-and-hold's 0.15; 0.14 for the confirmed variant). **No live gating code
  was built.** Full numbers in `graywind-tier1-exposure-test-results.md`.
- **Thread 2 (funding gap): fixed, committed `ff9c2b6`.** `scripts/seed_tier_pools.py`
  + workflow wiring + `tier-pool-alarm`. 434/434 tests passing (up from 422).
- **New finding surfaced while designing the fix, deliberately NOT fixed (scope stayed
  to funding, not redesign):** `run_tier1_rebalance`'s `tier1_equity = tier_pools[1] +
  current_SPY_value` means drift is structurally ~0 once the seeded cash is invested —
  `TIER1_SYMBOL_WEIGHTS` has exactly one symbol at weight 1.0, so `target_value` always
  equals `tier1_equity` by construction. Tier 1 never re-checks itself against real
  total account equity going forward, only against its own past accumulation — it will
  silently drift from a true 70%-of-equity target over months with nothing watching.
  Same "looks healthy, isn't" shape as the original bug. Needs
  `compute_rebalance_orders` (or its caller) to receive real total account equity as its
  basis, not `tier_pools[1] + committed` — a distinct, larger change, not built here.

## What has failed / risks / caveats

- **Nothing has failed.** 434/434 tests pass; `.github/workflows/live-trading.yml`
  YAML-validated (`yaml.safe_load`).
- **UNVERIFIED: the seed script has never run against a real Alpaca account.** No live
  cycle has happened since the commit — it isn't even pushed yet. First real
  verification happens on the next live-trading cycle after push; watch
  `state/tier_pools.csv` / `state/small/tier_pools.csv` go non-zero and
  `decision_log.csv` stop showing SERV blocked with "position size rounds to zero
  shares."
- **UNVERIFIED: the `tier-pool-alarm` GitHub issue flow** (label creation, raise/clear)
  has never fired for real — same category as `macro-alarm`'s first deploy. Should
  self-verify on the first real success or failure after push.
- **KNOWN, accepted data gap in the thread-1 spike:** `BAMLH0A0HYM2` (the HY OAS series
  the live `macro_gate.py` uses) only has FRED history from 2023-09-04 forward — the
  spike used NFCI + yield-curve slope only, not the live macro gate's exact 3-factor
  vote. Documented in the results doc, not chased further; this was meant to be a cheap
  probe, not a production backtest.
- **DEFERRED, real:** the tier-1 non-reanchoring gap above. Future bounded task if the
  user wants ongoing 70%-of-equity tracking rather than a one-time-correct bootstrap.
- **DECISION PENDING, unblocked this session:** DeepSeek-via-OpenRouter for the
  news-debate gate was explicitly deferred earlier in this session's conversation
  ("revisit after tier-1 gate ships"). Thread 1 is now resolved (concluded: don't build
  gating), so this is unblocked. Real pricing was already researched this session:
  DeepSeek V3.2 via OpenRouter, ~$0.21/$0.31 per 1M input/output tokens, real estimated
  cost under $1/month at this project's call volume — cheaper than the ~$2-3/mo figure
  in the prior provider-cost handoff. Not decided or built; ask the user.

## What's next (ordered)

1. **Get the user's go-ahead, then `git push`.** Not done in this session on purpose.
2. **After push:** watch GitHub Actions run history for the next live-trading cycle,
   confirm `state/tier_pools.csv` and `state/small/tier_pools.csv` go non-zero, and that
   SERV stops blocking on zero-share sizing.
3. **Ask the user whether to proceed with DeepSeek-via-OpenRouter** for the news-debate
   gate now that it's unblocked (see pricing above).
4. Optionally scope a future bounded task for the tier-1 re-anchoring gap.
5. Keep tracking burn-in trade count (6/20 as of 2026-09-01, per
   `graywind-real-capital-done-criteria.md`) — should move faster on tier 3 and the
   small account now that their pools are no longer structurally starved.
6. Audit item #4 (diversify universe) from the real-capital readiness audit is still
   open and still correctly gated behind burn-in completion — no action needed yet.

## Verification idioms used in this project (for the resuming session)

- Tests: `.venv/bin/python -m pytest -q` from repo root — 434 passing.
- YAML: `.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/live-trading.yml'))"`.
- Live state: always `git show origin/main:<path>`, never the local checkout.
- GitHub Actions run history (public API, unauthenticated):
  `curl -s "https://api.github.com/repos/SinbadTheExplorer/graywind/actions/workflows/live-trading.yml/runs?per_page=20"`.
- Checking real repo secrets (names only): `gh secret list` (needs `gh` CLI + auth, not
  available in this sandbox) or the GitHub UI directly.
- Before starting related work, check `git branch -a` / `git worktree list` / `git log
  --all --oneline` for unmerged work — this repo has a documented history of stale
  unmerged branches.

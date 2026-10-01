# Graywind Critical Review — Session Handoff

**Written:** 2026-09-01 · **For:** whoever resumes Graywind next and needs to decide what to
build/fix before adding more features — this session did no implementation, only analysis; it
turned existing docs plus a deliberately adversarial two-persona critique into an ordered
punch list.

## Goal

No code changed this session. The goal was to stress-test where Graywind actually stands —
channeling Jensen Huang (engineering/AI-ambition lens) and Warren Buffett (capital-preservation/
circle-of-competence lens) as critics — and turn that into a concrete, prioritized to-do list
instead of leaving it as chat. The critique's factual basis is entirely the project's own prior
work; nothing below is invented:

- Edge thesis (**the single most important doc to read before building anything new**):
  `docs/superpowers/graywind-edge-thesis.md`
- Real-capital audit record: `docs/superpowers/graywind-real-capital-readiness-handoff.md`
- Owner-set kill condition / capital figure: `docs/superpowers/graywind-real-capital-done-criteria.md`
- Data-vendor / LLM-provider decision: `docs/superpowers/graywind-data-vendor-evaluation.md`
- Tier-1 exposure hypothesis test (killed): `docs/superpowers/graywind-tier1-exposure-test-results.md`
- Trade-approval advisor (written, **not started**): plan
  `docs/superpowers/plans/2026-08-26-graywind-trade-approval-advisor.md`, spec
  `docs/superpowers/specs/2026-08-26-graywind-trade-approval-advisor-design.md`
- Progress ledger: **none exists yet** for the punch list below — this handoff *is* the ledger
  until one of these items gets its own plan (which will get its own ledger per
  `superpowers:subagent-driven-development` convention).

**The core diagnosis, in one paragraph:** Graywind's entire risk stack (VIX/sentiment/earnings/
macro/sector gates, DSR overfitting correction, drawdown breaker) protects only the 30% of
capital in tiers 2/3. The 70% SPY core (tier 1) is deliberately ungated — two independently
designed VIX/macro exposure-scaling variants were backtested 2000–2026 and both washed or worse
on Calmar ratio, so tier 1 stays passive **by design**, not by omission
(`graywind-tier1-exposure-test-results.md`, closed 2026-09-01). That means, as shipped, Graywind's
expected return *is* SPY beta; the overlay's only honest job is to not subtract from that core.
The kill condition the owner already picked — tier-2/3 realized P&L in `trade_log.csv` going
negative over burn-in — is the correct test of whether the overlay is even worth keeping.

## How to resume (do this first)

1. Confirm base: `git log --oneline -5` on `main` should show `6505f8f` at or near the tip
   (a bugfix to `seed_tier_pools.py`). If `main` has moved further, re-read whatever shipped
   since — this handoff doesn't cover it.
2. Run `git status` — expect exactly the uncommitted/untracked state described in "Current
   state" below. Anything beyond that is new since this handoff and should be investigated
   before trusting this doc further.
3. **Read `docs/superpowers/graywind-edge-thesis.md` in full before writing any new gate,
   signal, or feature.** It is the authority on why tier 1 is ungated and what would actually
   have to be true to change that (a materially different exposure-scaling mechanism that beats
   the already-tested ones on Calmar ratio — not a retune of what's there).
4. **Immediate next action:** start on punch-list item 1 below (close real-capital audit item
   #4, diversify the tactical universe) via `superpowers:brainstorming` → `superpowers:writing-plans`
   — no spec exists for it yet. Do not start new trade-approval-advisor work ahead of it (see
   "What's next" for why the ordering matters).

## Current state (active files)

**Branch:** `main`, 0 commits ahead/behind what's on `origin/main` as of this session (no
commits made). Confirm with `git fetch origin main && git status` before trusting that.

**Files created this session:**
- `docs/superpowers/graywind-critical-review-handoff.md` — this file. Nothing else.

**Files later work will touch (untouched so far):**
- `docs/superpowers/graywind-real-capital-done-criteria.md` — punch-list item 2 asks for a
  concrete burn-in check-in date/trade-count to be added here.
- `graywind_strategy/tier_config.py` / a new diversification spec — punch-list item 1's target.
- `live_loop.py`, `graywind_strategy/trade_approval.py` (new), `graywind_strategy/state_store.py`
  — the trade-approval-advisor plan's targets, sequenced *after* items 1–6 (see below).

**Scratch workspace / traps:**
- ⚠️ `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` has an **uncommitted
  working-tree modification** (`git diff --stat` shows 122 insertions / 213 deletions vs `HEAD`)
  that this session did not make and did not resolve. Do not trust the on-disk copy of that file
  without first running `git diff HEAD -- docs/superpowers/graywind-news-debate-shadow-mode-handoff.md`
  to see what differs from the committed version.
- ⚠️ OpenRouter's free-tier catalog was verified withdrawn on 2026-08-31 (`graywind-data-vendor-evaluation.md`)
  — the `delegate` skill and any "route to a free model" assumption is currently unusable on this
  project. Re-probe before relying on it.
- ⚠️ `ANTHROPIC_API_KEY` is **deliberately not set** — owner decision, "too costly," not a bug.
  The news-debate shadow-mode gate is fully built/tested/merged but produces zero live rows as a
  result. Don't "fix" this by just adding the secret without re-confirming the owner still wants
  that cost; see punch-list item 3.

**Not mine — leave alone:**
- `.claude/worktrees/` contents (including the stale-but-merged `graywind-yahoo-analyst-consensus`
  checkout and the idle `agent-ac1e2a7ec9b70e6e3` worktree — framework-locked).
- Untracked scratch files present before this session: `.DS_Store`, `.claude/`,
  `scripts/fetch_serv_bars.py` — none touched or created by this session.
- `docs/superpowers/archive/*` — already archived by a prior session (untracked but
  intentionally placed there); leave as is.

## What has changed

Nothing in the codebase. What changed is analytical: this session read `graywind-edge-thesis.md`,
the real-capital-readiness memory/handoff, and the trade-approval-advisor plan, then produced a
deliberately critical two-persona review (below, condensed) and turned it into the ordered punch
list in "What's next."

**Condensed critique (full version was given to the user in chat, not otherwise filed anywhere
— reproduced here so it isn't lost):**
- *Jensen-lens:* the AI/engineering ambition (LLM bull/bear/judge debate, DSR overfitting
  correction, 5-gate risk stack) is real engineering, but concentrated entirely on the 30% sleeve
  and partly inert (news-debate shipped but unfunded). The execution substrate (GitHub Actions
  cron, GitHub Issues as an approval bus, free-tier Yahoo/Finnhub with no documented fallback) is
  the least rigorous part of the stack despite carrying real capital.
- *Buffett-lens:* the project's own edge-thesis doc already concedes the risk stack is avoidance,
  not return — SPY beta with a fee (engineering time, API cost, cron risk) attached. The one
  open real-capital-audit item (diversify) is under-prioritized relative to control-plane
  additions like the approval advisor. The small paper account has sat at its $2,000/50%-cap
  boundary with zero trades for two weeks — an entire risk regime is unvalidated, not clean.

## What has failed / risks / caveats

- **Nothing has failed.** No code was touched this session.
- **UNVERIFIED, carried forward from prior handoffs, not re-checked this session:** whether the
  small-account pipeline runs end-to-end inside market hours (no confirmed cron landing in the
  13:30–20:00 UTC window as of the last handoff that covered it) — re-check
  `dashboard-data/small/` and `state/small/` before assuming this is still true, since main has
  moved since that check.
- **Decision carried forward, do not re-litigate without new evidence:** tier 1 stays permanently
  ungated. Both tested VIX/macro exposure-scaling variants washed or worse on Calmar ratio,
  2000–2026 backtest (`graywind-tier1-exposure-test-results.md`). Reopening this needs a
  materially different mechanism, not a retune.
- **Decision carried forward, not yet written to a file with a date attached:** the burn-in kill
  check (tier-2/3 P&L in `trade_log.csv` going negative → shrink/remove the overlay) has no
  committed check-in date or trade-count trigger. This is punch-list item 2 — don't let it drift
  indefinitely.
- **The trade-approval-advisor plan is fully written and ready to execute but has zero commits
  against it** — it's a safety/control-plane feature (adds an owner-only GitHub-issue approval
  gate on every buy), not a return or diversification feature. This review's recommendation is to
  sequence it *after* punch-list items 1–6, not before, since it doesn't address the concentration
  or unverified-boundary gaps that are currently the bigger risks to real capital.

## What's next (ordered)

1. **Close real-capital audit item #4 — diversify the tactical universe** beyond AAPL/SERV. No
   spec exists yet; start with `superpowers:brainstorming` then `superpowers:writing-plans`.
   Highest priority: this is the one still-open item from the original 9-item audit and the
   critique's biggest concentration-risk flag.
2. **Write the burn-in kill-check trigger into `graywind-real-capital-done-criteria.md`** — a
   specific date or trade-count at which someone will actually read `trade_log.csv`'s tier-2/3
   P&L and act on the owner's own kill condition if it's negative.
3. **Make an explicit, dated decision on the news-debate LLM line item**: either fund it (re-verify
   the DeepSeek-via-OpenRouter ~$2–3/mo path's current pricing/availability first, since the
   free-tier landscape has already shifted once) or formally shelve/delete the shadow-mode code.
   Shipped-but-dormant is an acceptable interim state, not a permanent one.
4. **Re-probe OpenRouter's free-tier catalog** before the `delegate` skill or any "route to a free
   model" plan is relied on again for this project.
5. **Deliberately exercise the small account's $2,000 / 50%-position-cap boundary** — a manual
   test or intentional size change — rather than waiting for it to trip organically. Two weeks of
   silence there is an untested risk regime, not evidence of safety.
6. **Extend the alerting pattern already proven in `scripts/check_macro_health.py`** (the
   `macro-alarm` label after unanswered cycles) to other silent-failure surfaces — e.g., an
   account going N cycles with zero trades should page on its own, not wait for a manual audit.
7. **Only after 1–6:** execute the already-written trade-approval-advisor plan
   (`docs/superpowers/plans/2026-08-26-graywind-trade-approval-advisor.md`) via
   `superpowers:subagent-driven-development`. Separately and later, scope a *new* tier-1 exposure
   hypothesis only if a materially different mechanism is ever proposed — per the bar
   `graywind-edge-thesis.md` itself sets for reopening that question.

## Verification idioms used in this project (for the resuming session)

- Test suite: `.venv/bin/python -m pytest tests/ -q`. The last recorded count was 384 passing
  (2026-09-01 morning, before `6505f8f`) — re-run rather than trusting that number, since `main`
  has moved since and `anthropic` must be installed into `.venv` first
  (`.venv/bin/pip install anthropic` or `pip install -r requirements.txt`).
- GitHub Actions run/job/step history without `gh` CLI (works unauthenticated, public repo):
  ```
  curl -s "https://api.github.com/repos/SinbadTheExplorer/graywind/actions/workflows/live-trading.yml/runs?per_page=50"
  curl -s "https://api.github.com/repos/SinbadTheExplorer/graywind/actions/runs/<run_id>/jobs"
  ```
- Checking real repo secrets (names only, never values): only via the GitHub UI or `gh secret
  list` (needs `gh` CLI + auth); the unauthenticated REST secrets-list endpoint 401s.
- Distinguishing "missing secret" from "no cycle has run under the right conditions yet": check
  the sibling job (or the same job's prior-day run) at the exact same timestamp for the same
  symptom before concluding it's a secret — a missing secret and a closed market can look
  identical from one signal alone.
- Before starting related work: check `git branch -a` / `git worktree list` / `git log --all
  --oneline` for unmerged work — this repo has a documented history of stale unmerged branches.

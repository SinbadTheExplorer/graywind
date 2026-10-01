# Graywind Small-Account Position-Value Cap — Session Handoff

**Written:** 2026-08-20 · **For:** whoever opens/manages the pull request for this branch, or
resumes any follow-up work identified below. **Implementation is done, reviewed, and pushed —
nothing is mid-flow.** This handoff exists to record the PR-not-yet-opened state and a design
gap the final review surfaced but deliberately left unfixed.

## Goal

Two features shipped on this branch, back to back: (1) a Yahoo Finance analyst-consensus
position-size multiplier, and (2) — this session's work — a small-account mode for
`PositionSizer` that caps position value to a fraction of equity below a configurable equity
threshold, prompted by the user asking whether a $500 account should size trades differently
than a $100k one.

- Spec (this session's feature): `docs/superpowers/specs/2026-08-19-graywind-small-account-position-cap-design.md`
- Plan (this session's feature): `docs/superpowers/plans/2026-08-19-graywind-small-account-position-cap.md`
- Spec (prior feature, same branch): `docs/superpowers/specs/2026-08-18-graywind-yahoo-analyst-consensus-design.md`
- Plan (prior feature, same branch): `docs/superpowers/plans/2026-08-18-graywind-yahoo-analyst-consensus.md`
- No progress ledger exists for either — both plans' SDD workspaces (`.superpowers/sdd/...`)
  were deleted after their final whole-branch reviews came back clean, per the
  subagent-driven-development skill's own cleanup step. Trust `git log` on this branch, not a
  ledger — there isn't one anymore.

## How to resume (do this first)

1. Confirm state: `git log --oneline fd474df..HEAD` on branch
   `worktree-graywind-yahoo-analyst-consensus` — should show 13 commits (9 for the
   analyst-consensus feature, 4 for the small-account cap). `git status` should be clean.
2. Confirm the branch is pushed and current: `git status -sb` should say "up to date with
   'origin/worktree-graywind-yahoo-analyst-consensus'".
3. **Immediate next action:** open the PR. It was not created in this session — no `gh` CLI or
   API credentials were available in the sandbox this was written from. The compare URL is:
   `https://github.com/SinbadTheExplorer/graywind/compare/main...worktree-graywind-yahoo-analyst-consensus?expand=1`
   A draft title and body were already handed to the user in this session's chat (not
   repeated here — if you need it and don't have the chat, just write a PR summarizing the two
   features from their specs).

## Current state (active files)

**Branch:** `worktree-graywind-yahoo-analyst-consensus`, 13 commits ahead of local `main` at
`fd474df`. Working tree clean. Pushed to `origin/worktree-graywind-yahoo-analyst-consensus` as
of commit `4262241`.

**Files created/changed for the small-account cap feature (commits `53d13f5..4262241`):**
- `docs/superpowers/specs/2026-08-19-graywind-small-account-position-cap-design.md` — the design,
  including a Goal section that was rewritten mid-review (see "What has changed" below) — read
  the current version, not any recollection of an earlier draft.
- `docs/superpowers/plans/2026-08-19-graywind-small-account-position-cap.md` — the implementation
  plan, fully executed.
- `graywind_strategy/risk/position_sizing.py` — `PositionSizer.__init__` gained
  `small_account_threshold=2000.0` and `small_account_cap_fraction=0.50`, both validated (`>= 0`
  and `(0, 1]` respectively); `shares_to_buy` applies the cap via `min(...)` when
  `account_equity < small_account_threshold`.
- `tests/test_position_sizing.py` — 8 new tests (4 behavioral + 3 validation + not double-counted
  with the earlier 4 pre-existing tests it started with... total file now has 13 tests).

**Not touched, by design:** `graywind_strategy/pipeline.py`, `live_loop.py`, `backtester.py` —
all three construct `PositionSizer(risk_fraction=0.01)` and pick up the new defaults for free.
This was verified against the real call sites during the final review, not just assumed.

**Scratch workspace / traps:**
- ⚠️ Local `main` (`fd474df`, "Add design spec for Yahoo analyst-consensus position sizer") is
  **one commit ahead of `origin/main`** (`994b249`). That commit is docs-only and is an ancestor
  of this feature branch too, so it's harmless — but when the PR is opened against
  `origin/main`, GitHub's diff will include that one extra doc commit since `origin/main`
  doesn't have it yet. Don't be surprised by it; it's not part of this branch's actual feature
  work.
- ⚠️ `state/*.csv` / `dashboard-data/*.csv` — live-cron output, updates every ~15 min during
  market hours regardless of this work. Not related to either feature on this branch.

**Not mine — leave alone:** `docs/superpowers/burn-in-decision.md`,
`docs/superpowers/graywind-dashboard-redesign-handoff.md`,
`docs/superpowers/graywind-phase1-mvp-handoff.md`, `docs/superpowers/archive/` — all unrelated,
pre-existing tracks.

## What has changed

- **Small-account cap implemented, reviewed, fixed, re-reviewed clean, and pushed.** Went
  through the full brainstorming → writing-plans → subagent-driven-development cycle: one task,
  one implementer (haiku), one task-level reviewer (haiku, approved with no issues), one final
  whole-branch reviewer (opus).
- **The final whole-branch review found the design spec's own rationale was wrong** (see below)
  — not a code defect, a documentation-accuracy defect. One fix round corrected it; a scoped
  re-review confirmed the fix. The shipped `position_sizing.py` code was never flagged as
  needing a change — only the spec's prose.
- Full suite: **232/232 passing** (`.venv/bin/python -m pytest tests/ -q` — note: use the
  project's `.venv`, not system `python3`; system `python3` lacks `yfinance` and other deps and
  will fail to even collect 4 test files).
- Branch pushed to origin at `4262241`.

## What has failed / risks / caveats

- **Nothing has failed — the feature works and is tested.**
- **A real design gap was found and explicitly NOT fixed, by design — this is the one thing a
  resuming session should actually think about, not just note.** The final reviewer empirically
  verified that under this pipeline's real config (`stop_pct=0.02`, `risk_fraction=0.01`,
  hardcoded and never overridden by any real caller), position-value-as-a-fraction-of-equity is
  **the same (~50%, worst case ~69% on sub-$1 stocks) at every account size** — a $500 account
  and a $500,000 account both land in the same range. The equity-gated cap this session shipped
  only protects accounts below $2,000; it does nothing for the actual failure mode (a tight stop
  — `stop_pct < risk_fraction` — or a very cheap stock), which can happen at any equity level and
  isn't gated by account size at all. This is now stated accurately in the spec's Goal section
  and logged as a follow-up in the spec's "Deferred, not forgotten" section: *"A value cap keyed
  to `risk_fraction/stop_pct` (or an unconditional cap) instead of to account equity, which would
  target the actual failure mode... rather than gating on account size."* **If someone later
  wants the sizing math to be genuinely more conservative for small accounts (not just
  narrowly capped below $2,000), that follow-up — not a tweak to the current threshold/fraction
  — is the right next design, and it would need its own brainstorm.** The user has not been told
  this changes the practical value of what shipped today; worth surfacing if they ask "did this
  fix the $500 problem" — the honest answer is "partially, and the part it doesn't fix isn't
  equity-specific."
- **PR not yet created** — see "What's next."

## What's next (ordered)

1. Open the PR at the compare URL above (or via `gh pr create` if `gh` becomes available), using
   the two features' specs as the source of truth for the description.
2. Once the PR is up, this worktree stays in place for any review feedback — normal
   `finishing-a-development-branch` convention, no special handling needed.
3. If/when someone wants to actually close the general-case sizing gap (not just the
   equity-gated narrow case shipped today), start a **new** brainstorm from the "Deferred, not
   forgotten" line in `docs/superpowers/specs/2026-08-19-graywind-small-account-position-cap-design.md`
   — don't just extend this feature's threshold/fraction, the axis itself (equity) was shown not
   to be the right one.
4. Reddit and YouTube analysis-source tracks are still separate, unstarted work — see
   `docs/superpowers/graywind-analysis-sources-handoff.md` and memory
   `project-graywind-analysis-sources.md`. Unrelated to this branch's two features.

## Verification idioms used in this project (for the resuming session)

- Full Python test suite: **use the venv** — `.venv/bin/python -m pytest tests/ -q` (232 passing
  as of `4262241`). Plain `python3 -m pytest` will fail to collect `test_analyst_consensus.py`,
  `test_backtester.py`, `test_live_loop.py`, `test_pipeline.py` with `ModuleNotFoundError:
  yfinance` — it's hitting system Python, not the project's virtualenv.
- No `gh` CLI in this sandbox — check GitHub Actions run history via the public REST API (works
  unauthenticated for a public repo):
  ```
  curl -s "https://api.github.com/repos/SinbadTheExplorer/graywind/actions/workflows/live-trading.yml/runs?per_page=10" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); [print(r['run_number'], r['status'], r['conclusion'], r['event'], r['created_at']) for r in d['workflow_runs']]"
  ```
- Live public dashboard: `https://sinbadtheexplorer.github.io/graywind/`.
- This worktree's sandbox cannot run git commands against the main checkout
  (`~/Projects/graywind`) — any `git -C <path-outside-this-worktree>` or `cd`
  out of `~/Projects/graywind/.claude/worktrees/graywind-yahoo-analyst-consensus`
  is refused. Local-merge-to-main is not possible from a session running in this worktree; push
  + PR is the only integration path available from here.
- Project follows TDD (red/green) for any `gates/`/`pipeline.py`/`strategy_engine.py`/
  `backtester.py`/`risk/` change, and uses `superpowers:writing-plans` →
  `superpowers:subagent-driven-development` for multi-step Python implementation work, per this
  session's own execution.

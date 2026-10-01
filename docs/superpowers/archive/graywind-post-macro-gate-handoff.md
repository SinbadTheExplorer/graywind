# Graywind — Post Macro-Gate Session Handoff

**Written:** 2026-08-17 · **For:** a fresh session picking up Graywind after the Bullion
macro-gate work shipped. There is no in-progress design or implementation thread right now —
this handoff exists to hand off two real open items (one design decision, one unverified
operational fact) and to record that the macro-gate thread is done, not resumable.

## Goal

Nothing is actively being built. The most recently completed thread was the Bullion x Graywind
macro-gate integration (a 4th risk gate reading a sibling project's public macro dataset).
It shipped and merged to `main` this session. Authorities, for reference/history:
- Spec: `docs/superpowers/specs/2026-08-17-graywind-bullion-macro-gate-design.md`
- Plan: `docs/superpowers/plans/2026-08-17-graywind-bullion-macro-gate.md`
- Progress ledger: **deleted** — per `superpowers:subagent-driven-development`'s own convention,
  the SDD workspace (`.superpowers/sdd/2026-08-17-graywind-bullion-macro-gate/`) was removed
  after the final review went clean and the branch merged. Git history is the record now; see
  "What has changed" below for the full commit range and what each commit did.
- Memory (background/history, kept current with this handoff):
  `~/.claude/projects/-Users-me/memory/project-graywind-bullion-macro-gate.md`

## How to resume (do this first)

1. Confirm state: `git -C ~/Projects/graywind log --oneline -3` — most recent
   commit should be `60edac0`, on `main`. `git status` should be clean apart from the pre-existing
   untracked handoff docs listed below.
2. There is no plan or ledger to resume — the macro-gate thread is finished, not paused. Do NOT
   re-invoke `superpowers:writing-plans` or `superpowers:subagent-driven-development` against the
   macro-gate plan file; it already executed to completion and its workspace is gone.
3. **Immediate next action:** there isn't one — this handoff is a checkpoint, not a resume point.
   The two items in "What's next" below are candidate *new* threads, not continuations. Ask the
   user which (if either) they want to pick up; don't assume.

## Current state (active files)

**Branch:** `main`, 16 commits ahead of `origin/main` (nothing has been pushed this session or
the ones before it — this has been true across multiple recent handoffs, not new).

**Files created/changed by the macro-gate thread (all committed, range `9759d59..60edac0`):**
- `docs/superpowers/specs/2026-08-17-graywind-bullion-macro-gate-design.md` — design spec.
- `docs/superpowers/plans/2026-08-17-graywind-bullion-macro-gate.md` — implementation plan (3
  tasks).
- `graywind_strategy/gates/macro_gate.py` (new) — `MacroDataUnavailable`, `macro_gate()`,
  `fetch_bullion_macro_snapshot()`.
- `tests/test_macro_gate.py` (new).
- `graywind_strategy/pipeline.py` — new `evaluate_macro_gate` wrapper, 4th blocking check in
  `decide_trade`, docstrings updated to say "four" gates (mostly — see traps below).
- `tests/test_pipeline.py`, `tests/test_live_loop.py` — gate wiring test coverage; both files'
  independent `_passing_gates()` helpers updated (this was a real collateral-fix caught only by
  running the *full* suite mid-task — see the plan's Task 3 for why two files needed the same
  one-line change).
- `graywind_strategy/backtester.py` — docstring-only changes (gate count references).

**Scratch workspace / traps:**
- ⚠️ **`graywind_strategy/pipeline.py:85`** — the `drawdown_breaker_ok` docstring still says
  "the three gates below." This is a known, deliberately-deferred miss: the final-review fix
  wave updated 4 of 5 stale "three gates" references but this 5th one wasn't in the fix's
  explicit location list, and both the fix implementer and the re-reviewer flagged it and chose
  not to touch it unprompted rather than silently expand scope. Purely cosmetic — worth a
  one-line touch-up whenever someone's next in that file, not urgent.
- ⚠️ **`docs/superpowers/graywind-bullion-macro-gate-design-handoff.md`** and
  **`graywind-sector-engine-design-handoff.md`** (both untracked, in this same directory) —
  archived to `docs/superpowers/archive/` as part of writing this handoff, since both threads
  they describe are now fully shipped. Do not resume from them; this file supersedes both.
- ⚠️ Bullion's `data.json` (the macro gate's live external dependency) can drift schema/units
  without warning — if you touch `macro_gate.py` again, re-fetch
  `https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/data.json` and re-verify
  against the spec rather than trusting a memory description, the same discipline the original
  design session used to catch two real unit/shape errors before they shipped.

**Not mine — leave alone:** `docs/superpowers/graywind-phase1-mvp-handoff.md` (tracked in git,
unrelated Phase 1 MVP thread), `docs/superpowers/burn-in-decision.md`, `docs/superpowers/archive/`
(older archived handoffs, including the two just added this session).

## What has changed

- **The Bullion macro-gate thread shipped end-to-end this session**, from "spec awaiting
  approval" through merge to `main`:
  - User approved the committed spec as-written (confirmed against live Bullion data and a
    164-test baseline first).
  - `superpowers:writing-plans` produced a 3-task plan.
  - `superpowers:subagent-driven-development` executed it in an isolated worktree
    (`.worktrees/bullion-macro-gate`, now removed): Task 1 (vote-count function), Task 2
    (fetch/forward-fill/staleness), Task 3 (pipeline wiring) — each individually implemented,
    reviewed clean, and committed (`bea398c`, `cedeb73`, `cb0c9b7`).
  - **The final whole-branch review (dispatched on the most capable model, specifically because
    per-task reviews can't see cross-task/composition issues) found 2 real Critical bugs by
    testing the shipped code against Bullion's actual live `data.json`, not just the mocked unit
    tests:**
    1. The weekly NFCI staleness ceiling (10 days) had zero margin against the real
       FRED-release-lag-through-Bullion's-cron latency chain — would have fail-closed (blocked
       ALL trading) roughly one weekday per week, starting the day after merge. Not hypothetical:
       verified against the live file's actual dates.
    2. The forward-fill walk ran outside `fetch_bullion_macro_snapshot`'s `try` block, so
       malformed Bullion data would crash `decide_trade` with a raw exception instead of failing
       closed — violated the pipeline's own documented "must never propagate an exception"
       invariant.
  - Both fixed in one consolidated fix wave (`60edac0`), independently re-verified by a scoped
    re-review (all 6 findings from that review — 2 Critical, 2 Important, ~2 Minor — addressed or
    explicitly parked with a ruling), then merged to `main` locally (fast-forward, no conflicts)
    and the worktree/branch cleaned up.
  - Test suite: 164 → 187 passing.

## What has failed / risks / caveats

- **Nothing has failed.** The two Critical bugs above were caught and fixed *before* merge, not
  after — they never reached `main` in a broken state.
- **UNVERIFIED, carried forward unresolved from the prior handoff (unrelated to macro-gate):**
  re-checked this session via
  `curl -s "https://api.github.com/repos/SinbadTheExplorer/graywind/actions/workflows/live-trading.yml/runs?per_page=10"`
  — still only 2 runs total, both manual `workflow_dispatch` from Saturday 2026-08-15. **Zero
  `schedule`-triggered runs have completed as of this handoff.** The live-trading cron's first
  real unattended market-hours cycle still hasn't been confirmed. Check again with the same
  command.
- **Open design question, NOT a bug, deliberately not touched this session:** `macro_gate`'s own
  VIX vote is redundant with the pre-existing, unrelated `evaluate_vix_gate` — that gate runs
  first in `decide_trade` and blocks outright on the identical FRED VIXCLS series at the identical
  25.0 threshold, so macro_gate's vix vote can only ever fire when it would be *wrong* (Bullion's
  forward-filled value stale-high while live FRED is actually below 25). Effective gate is "2 of
  {nfci, hy_oas, curve_slope}," not the "2 of 4 stress signals" the spec's own auditability
  framing claims. Full detail in
  `~/.claude/projects/-Users-me/memory/project-graywind-bullion-macro-gate.md`.
  This needs a decision from whoever owns the spec (drop vix from the vote → 2-of-3, or keep it
  and document the pre-emption) — do not silently resolve it in a future session without asking.

## What's next (ordered)

There is no mandated next step — both items below are optional, independent, and the user's
call on whether/when to pick either up:

1. **If asked to resolve the vix-redundancy question:** this is a design decision, not an
   implementation task — use `superpowers:brainstorming` with the user first (present the two
   options above), don't jump straight to editing `macro_gate.py`.
2. **If asked to verify the live cron:** re-run the `curl` command above; if a `schedule`-event
   run now appears and succeeded, that closes out a long-standing unverified item across several
   past handoffs — update
   `~/.claude/projects/-Users-me/memory/project-graywind-phase1.md`
   (currently says "Burn-in clock NOT started") accordingly.
3. Otherwise: nothing is pending. Ask the user what they want to work on next.

## Verification idioms used in this project (for the resuming session)

- Full test suite: `python3 -m pytest tests/ -q` (187 passing as of `60edac0`).
- **No `gh` CLI in this environment.** Check GitHub Actions run history via the public REST API
  instead (works unauthenticated for a public repo):
  ```
  curl -s "https://api.github.com/repos/SinbadTheExplorer/graywind/actions/workflows/live-trading.yml/runs?per_page=10" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); [print(r['run_number'], r['status'], r['conclusion'], r['event'], r['created_at']) for r in d['workflow_runs']]"
  ```
- Bullion's live public data file, for grounding any macro-gate work in real data rather than a
  memory description: `curl -s "https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/data.json"`.
- This project follows TDD (red/green) for any `gates/`/`pipeline.py`/`strategy_engine.py`/
  `backtester.py` change — see `tests/test_vix_gate.py`'s `MagicMock`-session mocking convention
  and `tests/test_pipeline.py`'s `patch.multiple(...)`-based `_passing_gates()` helper.
- For any multi-task implementation: `superpowers:writing-plans` →
  `superpowers:subagent-driven-development` in an isolated worktree, with a whole-branch final
  review on the most capable model before merge — this exact flow caught 2 real Critical bugs
  this session that three individually-clean per-task reviews missed. Don't skip the final
  review to save time.

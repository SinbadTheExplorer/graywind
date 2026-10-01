# Graywind x Bullion Macro Gate — Session Handoff

**Written:** 2026-08-17 · **For:** a fresh session continuing the Graywind x Bullion macro-gate
design thread — spec is written and committed, waiting on the user's review before
`superpowers:writing-plans` runs. Also carries forward: the sector-aware engine thread from the
prior handoff is now fully SHIPPED (not a resume target), and an unrelated live-cron
verification check.

## Goal

Feed Bullion's (a sibling side project) public macro dataset into Graywind's trading model as a
new 4th risk gate (`macro_gate.py`), additive alongside the existing vix/sentiment/earnings
gates. This session resumed the design from architecture+data-flow (approved in an earlier
session) through error-handling and testing, corrected two wrong assumptions against the real
live data, wrote the spec, and is now waiting on user sign-off before planning/implementation.

- Spec (fully written, approved section-by-section, self-reviewed, committed — the design's
  single source of truth): `docs/superpowers/specs/2026-08-17-graywind-bullion-macro-gate-design.md`
- No plan file yet — `superpowers:writing-plans` has not been invoked for this thread.
- No progress ledger yet — implementation hasn't started.
- Prior memory (background/history, now partially superseded by the spec — the spec is more
  current on anything they disagree about):
  `/Users/thanhnguyen/.claude/projects/-Users-thanhnguyen/memory/project-graywind-bullion-macro-gate.md`

## How to resume (do this first)

1. Confirm state: `git -C /Users/thanhnguyen/Projects/graywind log --oneline -3` — most recent
   commit should be `9759d59`. `git status` should be clean apart from the pre-existing untracked
   handoff docs listed below (nothing from this session's macro-gate work is uncommitted).
2. Read the spec: `docs/superpowers/specs/2026-08-17-graywind-bullion-macro-gate-design.md`. It
   is complete (architecture, data flow, error handling, testing, out-of-scope) and was approved
   section-by-section by the user this session, self-reviewed for placeholders/consistency, and
   committed.
3. **Immediate next action:** ask the user whether they've reviewed the spec and want changes, or
   are ready to proceed. If ready, invoke `superpowers:writing-plans` on this spec — do NOT
   re-run `superpowers:brainstorming` from scratch, the design is done. If the user asks for
   changes, make them directly in the spec file, re-run the self-review, and re-commit before
   moving to writing-plans.

## Current state (active files)

**Branch:** `main`, 11 commits ahead of `37101a6` (the base the *previous* handoff was written
against). All 11 are already committed; nothing is staged or uncommitted.

**Files created this session (all committed):**
- `docs/superpowers/specs/2026-08-17-graywind-bullion-macro-gate-design.md` — the macro-gate
  design spec described above. This is the only macro-gate-thread artifact that exists yet — no
  `macro_gate.py`, no plan file, no tests. Do not assume any code exists.
- Everything else in the 11-commit range (`d0adfae`..`9f3c815`) is the **separate, now-complete**
  sector-aware strategy engine thread — see "What has changed" below. Unrelated to macro-gate
  work; don't conflate the two threads.

**Files later macro-gate work will create (don't exist yet):**
- `graywind_strategy/gates/macro_gate.py` — per the spec: `fetch_bullion_macro_snapshot`,
  `macro_gate`, exception `MacroDataUnavailable`.
- `tests/test_macro_gate.py` (new file).

**Files later macro-gate work will modify (untouched so far):**
- `graywind_strategy/pipeline.py` — needs a new `evaluate_macro_gate` wrapper and one more
  blocking check in `decide_trade`, joining the existing `gates_always_pass` bypass. Per the
  spec, needs **no new required parameter** on `decide_trade` (the gate needs no credential).
- `tests/test_pipeline.py` — the shared `_passing_gates()` `patch.multiple(...)` helper (around
  line 57) needs a 4th entry, `evaluate_macro_gate=lambda **kw: True`, or every existing
  `gates_always_pass=False` decide_trade test will start failing once the new gate is wired in.

**Scratch workspace / traps:**
- ⚠️ **Do not trust this memory file's original description of Bullion's `data.json` shape** —
  it said `history` was keyed by field name; the real file (fetched live this session) keys
  `history` by ISO date string instead, each date holding whatever fields were fresh that day.
  The spec has the corrected shape; the memory file has since been corrected too, but if a future
  session reads an even older cached description, don't trust it — refetch
  `https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/data.json` and check.
- ⚠️ **HY OAS units:** Bullion's `hy_oas` field is in percentage points (e.g. `2.71` = 2.71%),
  matching FRED's raw series — NOT basis points. An earlier session's "500bps" framing was wrong;
  the correct threshold is `5.0`. This is already fixed in the spec — just don't let a stale
  "500" resurface from an old memory or conversation summary.
- ⚠️ `docs/superpowers/graywind-sector-engine-design-handoff.md` and
  `graywind-sector-model-handoff.md` (both untracked, sitting alongside this file) describe the
  **sector-engine** thread, which is now fully shipped (see below) — they are historical record
  only, not a resume target. Don't act on their "What's next" sections.

**Not mine — leave alone:** `docs/superpowers/graywind-phase1-mvp-handoff.md` (Phase 1 MVP
thread, unrelated, tracked in git), `docs/superpowers/archive/` (older archived handoffs).

## What has changed

- **The sector-aware strategy engine thread (from the prior handoff) is fully SHIPPED this
  session**, merged to `main` at `9f3c815`. This was a separate, already-completed piece of work
  before the macro-gate thread started — full detail below for context, but it is NOT something
  to resume:
  - Resumed its brainstorming from data-flow through testing, corrected the design from fixed
    ATR% cutoffs to self-relative percentile ranking, wrote+committed the spec, wrote+committed
    the implementation plan, executed all 7 tasks via `superpowers:subagent-driven-development`
    in an isolated worktree (each task individually reviewed clean), ran a final whole-branch
    review (Opus) that found 2 real Important gaps (a `SIGNAL_LOOKBACK` sizing error and a
    silent missing-column failure mode in `run_backtest`), fixed both in one fix wave, re-review
    confirmed clean, merged the worktree branch to `main` locally, cleaned up the worktree.
  - Test suite: 145 → 164 passing.
  - Roster symbols (XOM/CVX/NVDA/MSFT/JNJ/UNH) are fetchable/backtestable via new scripts but
    **deliberately NOT on `live_loop.py`'s `WATCHLIST`** yet (still `["AAPL", "SPY"]`) — that's a
    separate, later decision pending real backtest validation.
- **The macro-gate thread (this handoff's actual subject)** resumed brainstorming from
  error-handling through testing this session, corrected the `data.json` shape and the HY OAS
  unit assumption against the real live file, presented and got approval on both remaining
  sections, wrote the spec, self-reviewed it, committed it (`9759d59`). **No implementation
  exists yet for this thread.**
- Checked the separate, unrelated live-cron verification thread: via the public GitHub Actions
  API (no `gh` CLI in this environment — used `curl` against
  `api.github.com/repos/SinbadTheExplorer/graywind/actions/workflows/live-trading.yml/runs`
  instead), confirmed only 2 runs exist total, both manual `workflow_dispatch` on Saturday
  2026-08-15 (both succeeded). Zero `schedule`-triggered runs — but this isn't a bug: the
  workflow file itself only landed on `main` that same Saturday, and Monday 2026-08-17 (today) is
  the first weekday since then; as of this session it was still morning UTC, before the
  13:30-20:00 UTC market-hours cron window opens. **Still genuinely unverified** — check again
  after ~14:00 UTC today via the same `curl` command.

## What has failed / risks / caveats

- **Nothing has failed.** The macro-gate spec is complete and internally consistent; the
  sector-engine work is shipped and its final review (including an independent empirical
  re-derivation of the trickiest numeric claims) came back clean after one fix round.
- **UNVERIFIED (separate thread, not blocking macro-gate work):** the live cron still hasn't
  completed a real `schedule`-triggered market-hours cycle. See "What has changed" above for the
  full context — check back after ~14:00 UTC today.
- **The macro-gate spec's approval is not yet a green light to implement.** Per
  `superpowers:brainstorming`'s normal flow, the user still needs to review the *written* spec
  file (not just the sections as presented in conversation) before `superpowers:writing-plans`
  runs. Don't skip that gate even though every section was individually approved during
  presentation — the file itself hasn't been explicitly signed off on yet as of this handoff.
- Bullion's `data.json` is itself a live external dependency this design has zero control over —
  if its schema changes (field names, the `history`/`fields` split, cadences) before
  implementation happens, re-fetch and re-verify against the spec before trusting it, the same
  way this session caught the `history`-shape and HY-OAS-units errors by actually fetching it
  instead of trusting a memory description.

## What's next (ordered)

1. Confirm with the user that the committed spec
   (`docs/superpowers/specs/2026-08-17-graywind-bullion-macro-gate-design.md`) is approved as
   written (or get their requested changes and re-commit).
2. Invoke `superpowers:writing-plans` against that spec to produce
   `docs/superpowers/plans/<date>-graywind-bullion-macro-gate.md`. Follow the file/interface
   conventions the spec already pins down (function names, the `MacroDataUnavailable` exception,
   the `session=requests` injectable, the exact threshold values) rather than re-deriving them.
3. Execute the plan — `superpowers:subagent-driven-development` was used for the sector-engine
   plan this session and worked well (isolated worktree, per-task review, whole-branch final
   review with a real fix round); the same approach is a reasonable default here too, but that's
   the resuming session's/user's call, not a mandate.
4. Separately, unblocked, anytime: re-check the live cron via the `curl`-against-the-Actions-API
   idiom in "Verification idioms" below, now that the market-hours window has had a chance to
   fire.

## Verification idioms used in this project (for the resuming session)

- Full test suite: `python3 -m pytest tests/ -q` (164 passing as of `9f3c815`; the macro-gate
  spec commit `9759d59` is docs-only, no code change, so this count should still hold).
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
  and `tests/test_pipeline.py`'s `patch.multiple(...)`-based `_passing_gates()` helper; the new
  macro gate's tests should mirror both exactly (this is also spelled out in the spec's Testing
  section).

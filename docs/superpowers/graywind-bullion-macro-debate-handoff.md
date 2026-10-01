# Graywind × Bullion Macro-Event Debate — Session Handoff

**Written:** 2026-09-13 (supersedes the 2026-09-13 version committed at `15164cb` — same
feature, now **merged to local `main`** with a post-review fix wave applied; the prior
version was written while still on the feature branch, pre-fix, pre-merge). **For:** a fresh
session checking in on the Bullion macro-event shadow debate, or debugging why
`dashboard-data/macro_debate_log.csv` doesn't exist yet.

## Goal

Read Bullion's market-wide news feed (`news.json` — Fed policy, geopolitics, macro
headlines; not per-symbol) once per trading cycle, make one forced-structured-output
DeepSeek call, and log a small set of probability-weighted event readings
(`event`/`probability`/`implication`) to a new CSV for later human review. Like
`news_debate.py`, this **never gates a trade** — `pipeline.py::decide_trade()` has no path
into it. VADER and the existing `macro_gate.py` breach-count gate are unaffected.

All 6 tasks of the plan are done, a final whole-branch review found 1 Critical + 2 Important
+ 4 Minor issues, all 7 were fixed and re-reviewed clean, and the branch is **merged into
local `main`** (not yet pushed — see below). The feature has **two independent operational
blockers** before it will ever log a real row in production — see "What has failed / risks /
caveats"; neither is a defect in this code.

- Spec (binding authority): `docs/superpowers/specs/2026-09-12-graywind-bullion-macro-debate-design.md`
- Plan (all 6 tasks executed): `docs/superpowers/plans/2026-09-12-graywind-bullion-macro-debate.md`
- Progress ledger: deleted after the final review went clean (per
  `superpowers:subagent-driven-development`'s own convention) — reconstruct from commit
  messages + this handoff if needed.

## How to resume (do this first)

1. **Location:** this is merged into local `main` at `/Users/thanhnguyen/Projects/graywind`.
   The feature branch `graywind-bullion-macro-debate` and its worktree are **deleted** —
   don't look for either.
2. **Local `main` is 12 commits ahead of `origin/main` and NOT pushed.** Confirm with
   `git status --short --branch` (expect `## main...origin/main [ahead 12]`) before
   assuming anything here is live. That 12 = 2 pre-existing commits from an earlier,
   unrelated session (a tier-2/3 settlement fix and a code-review fix wave, both already on
   `main` before this feature branch forked) + 8 commits from this feature
   (`f26848f`..`6c58664`) + 2 merge commits (`4f36560` merging `origin/main` in, `e96c5c3`
   merging the feature branch in). Run `git log --oneline -12` to see all of them by name.
3. Run the test suite: `.venv/bin/python -m pytest tests/ -q` — expect **`526 passed`** (524
   after Task 5, +2 from the final-review fix wave's new tests: an out-of-range-probability
   test and an empty-headlines test).
4. **Immediate next action — check both blockers before assuming either is fixed:**
   - `gh secret list --repo SinbadTheExplorer/graywind` — confirm whether
     `DEEPSEEK_API_KEY` has been added. As of 2026-09-13 it is **absent** (list shows only
     `ALPACA_API_KEY`, `ALPACA_API_KEY_SMALL`, `ALPACA_API_SECRET`,
     `ALPACA_API_SECRET_SMALL`, `CLOUDFARE_API_KEY`, `FINNHUB_API_KEY`, `FRED_API_KEY` — no
     `DEEPSEEK_API_KEY`).
   - `curl -s https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/news.json`
     and inspect `generated_at` — as of 2026-09-13 it is still `2026-09-05T00:02:31Z`,
     unchanged across multiple checks spanning at least 2026-09-12 through 2026-09-13 (now
     8+ days stale against this feature's 48h ceiling). The value not moving at all across a
     full day+ is itself evidence Bullion's news cron isn't merely lagging — it's not
     running.
5. Whenever ready to push: `git push origin main` — nothing has pushed this session's work
   (or the 2 pre-existing commits) to `origin/main` yet. This is a plain decision, not a
   conflict to resolve — the merge already reconciled local/remote history cleanly.

## Current state (active files)

- `graywind_strategy/gates/macro_debate.py`: `MacroNewsUnavailable` exception;
  `BULLION_NEWS_URL`; `STALENESS_CEILING_HOURS = 48`;
  `fetch_bullion_headlines(session=requests) -> list[dict]` — now also raises
  `MacroNewsUnavailable("Bullion news feed returned zero headlines")` on an empty-but-fresh
  feed (`macro_debate.py:66,74`, added in the fix wave — a fresh feed with zero headlines
  used to still reach the LLM, which could fabricate events from nothing); `MacroEvent`
  dataclass (`event`, `probability`, `implication`); `evaluate_macro_events(llm_client,
  headlines) -> list[MacroEvent]` — now range-validates `probability` into `[0.0, 1.0]` and
  raises `ValueError` if out of range (`macro_debate.py:150-151`, added in the fix wave —
  DeepSeek's schema `minimum`/`maximum` aren't server-enforced on the non-`/beta` endpoint
  this module uses, same documented gap as `news_debate.py`'s `strict` no-op, now
  cross-referenced in this module's docstring too); `evaluate_macro_debate(llm_client,
  session=requests) -> list[dict]` (orchestration — fetch then evaluate, raises on any
  failure, does not catch anything itself).
- `graywind_strategy/dashboard_export.py`: `MACRO_DEBATE_LOG_FILENAME =
  "macro_debate_log.csv"`; `MACRO_DEBATE_LOG_FIELDS = ["timestamp", "event", "probability",
  "implication"]`; `log_macro_debate(rows, dashboard_dir=DEFAULT_DASHBOARD_DIR)` — same
  append-forever, header-once, no-op-on-empty semantics as `log_news_debate`. Untouched by
  the fix wave.
- `live_loop.py` — wired, **and reordered by the fix wave (this is the important change from
  the prior handoff):**
  - Imports: `evaluate_macro_debate` (line 49), `log_macro_debate` (line 52, alongside
    `log_news_debate`).
  - `run_macro_debate_cycle(llm_client, cycle_timestamp, macro_debate_rows)` (line 255) —
    unchanged logic: fails open, catches any exception, prints `macro debate shadow-mode
    error, skipping this cycle's row: {exc}` to stderr, appends nothing on failure.
  - `macro_debate_rows = []` initialized alongside `debate_rows = []` (line 914).
  - **Call site moved** (line 1081): `if llm_client is not None and account_label ==
    "100k":` — now runs **AFTER** the `for symbol in WATCHLIST:` loop finishes (including
    its own per-symbol `except`), not before it. The original placement (before the loop)
    was a **plan/spec defect** — it would have delayed every symbol's real stop/target exit
    check and buy/sell decision behind a synchronous Bullion fetch + DeepSeek round trip,
    directly reversing this same file's own documented precedent for the sibling news-debate
    feature (search "final-review Fix 3" in this file). Caught by the final whole-branch
    review, fixed in `6c58664`.
  - **Account gate added** (same line, `and account_label == "100k"`): both the main
    ($100k) and small-account jobs in `.github/workflows/live-trading.yml` pass
    `DEEPSEEK_API_KEY`, and Bullion's feed is account-independent — without this gate the
    feature would run twice per cycle (double cost, double calls, a second undocumented CSV
    at `dashboard-data/small/macro_debate_log.csv`). Now it only runs on the main account
    job. `log_macro_debate` no-ops on an empty `rows` list, so the small-account job writes
    no file at all (confirmed: `ls dashboard-data/small/macro_debate_log.csv` →
    not found).
  - **Log-write try/except split** (lines 1134-1141): `log_news_debate` and
    `log_macro_debate` used to share one `try/except` — a `log_news_debate` failure would
    silently skip `log_macro_debate` too, and the stderr message always said "news debate"
    regardless of which writer actually failed. Now two independent blocks, each with its
    own accurate message.
  - Module docstring (near the top) updated to name both `news_debate_log.csv` and
    `macro_debate_log.csv` as gated by `DEEPSEEK_API_KEY` (previously only mentioned the
    former).
- `tests/test_macro_debate.py`: 12 tests (10 from Tasks 1-3, +2 from the fix wave —
  out-of-range-probability and empty-headlines-list).
- `tests/test_dashboard_export.py`: 2 tests for `log_macro_debate` (unchanged by fix wave).
- `tests/test_live_loop.py`: 2 tests for `run_macro_debate_cycle` (unchanged by fix wave —
  they test the function itself, not its call-site placement in `main()`; this repo doesn't
  unit-test `main()`'s internal statement ordering for the sibling feature either).
- **Not created yet:** `dashboard-data/macro_debate_log.csv` and
  `dashboard-data/small/macro_debate_log.csv` — confirmed absent via `ls` this session (the
  latter will now never appear at all, by design, once the account gate above is live —
  only the former is expected once both blockers clear).

**Not mine — leave alone:** the sibling worktrees `.claude/worktrees/agent-ac1e2a7ec9b70e6e3`
and `.claude/worktrees/graywind-yahoo-analyst-consensus` under the primary checkout; anything
under `state/small` or `dashboard-data/small` beyond what's noted above (the separate
small-account pipeline, unrelated to this feature).

## What has changed

Since the prior handoff (`15164cb`, still on the feature branch):

- A final whole-branch review (dispatched per `superpowers:subagent-driven-development`,
  most capable model) found 1 Critical (call-site ordering), 2 Important (double-run
  across accounts; unvalidated probability), and 4 Minor issues.
- All 7 fixed in one commit, `6c58664` — see "Current state" above for what changed and
  where. A scoped re-review verdicted all 7 ADDRESSED with no new breakage.
- The branch was merged: first `origin/main` was pulled into local `main` (`4f36560` — 216
  commits, entirely automated dashboard-data/state files from the live cron, zero conflicts,
  zero code changes), then the feature branch was merged on top (`e96c5c3` — clean, after
  removing two untracked duplicate spec/plan files from the main checkout that were
  byte-identical to what the merge brought in).
- Feature branch and its worktree deleted after the merge (`git branch -d` + `git worktree
  remove`) — both are gone; don't look for them.
- Full suite verified green on the merged result: **526 passed**.

## What has failed / risks / caveats

- **Nothing has failed in this code.** The final review's Critical/Important findings were
  all fixed and re-verified; the merge was clean; the suite is green.
- **Bullion's `news.json` feed is confirmed stale, past this feature's own 48h ceiling — a
  Bullion-side blocker, not a Graywind one.** Checked repeatedly across 2026-09-12 and
  2026-09-13: `generated_at` has not moved from `2026-09-05T00:02:31Z` at all. Until
  Bullion's news cron is fixed, `fetch_bullion_headlines` will raise
  `MacroNewsUnavailable` on essentially every real cycle. This is expected fail-open
  behavior, not a bug — but the feature is effectively dormant on ship.
- **Second, independent blocker, strictly upstream of the one above: `DEEPSEEK_API_KEY` is
  not set as a repo secret.** Verified via `gh secret list` multiple times this session.
  Without it, `llm_client` stays `None` in `live_loop.py`, and `run_macro_debate_cycle` is
  never even called — the Bullion staleness check above never gets a chance to run. This
  secret is shared with the pre-existing `news_debate.py` feature (also DeepSeek-based,
  also blocked on the same missing secret) — setting it once unblocks both.
- **The sibling handoff (`graywind-news-debate-shadow-mode-handoff.md`) is stale on this
  exact point** — it refers to `ANTHROPIC_API_KEY` and `pip install anthropic`, both
  superseded by the 2026-09-02 DeepSeek swap. Do not follow that document's secret name or
  install step for either feature; use `DEEPSEEK_API_KEY` and the already-installed `openai`
  package. (Not fixing that file here — out of scope; flagging so a resuming session doesn't
  act on the stale name.)
- **No live smoke test against the real DeepSeek API or the real Bullion feed has
  happened.** All tests mock both the HTTP call and the LLM client.
- **This branch's work is merged to local `main` but NOT pushed to `origin/main`.** Don't
  assume this is live in production until `git push origin main` happens — that push also
  carries the 2 pre-existing unrelated commits that were sitting unpushed before this
  feature branch even started.
- **DEFERRED BY DESIGN, not a defect:** no promotion bar for this signal (mirroring
  `graywind-news-debate-promotion-bar.md`) — deliberately not written yet, since zero rows
  exist to check criteria against. Also deferred: fixing Bullion's cron (belongs to the
  Bullion project) and any comparison/analysis script. The final review additionally noted,
  as a non-blocking observation for later: this feature has no equivalent to
  `check_macro_health.py`'s external monitoring for "the Bullion host looks green from
  outside but the feed is actually dead" — worth a line in a future deferred-items pass, not
  urgent for a shadow-only feature whose dormancy is already documented here.

## What's next (ordered)

1. **Add the `DEEPSEEK_API_KEY` GitHub Actions repo secret** (manual, human-only step,
   shared with `news_debate.py`) — without this, `run_macro_debate_cycle` never executes at
   all, regardless of Bullion's feed state.
2. **Separately, check whether Bullion's news cron has been fixed:**
   `curl -s https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/news.json`
   and inspect `generated_at` — needs to be within 48h of the check time. Both #1 and #2
   must be true before a row can appear.
3. **Push local `main` to `origin/main`** (`git push origin main`) — currently 12 commits
   ahead, none pushed. Do this whenever the account owner is ready; it's a plain push, no
   conflict to resolve (the merge already reconciled history).
4. Once #1 and #2 are both true and pushed, trigger a `workflow_dispatch` run of
   `live-trading.yml` during market hours (13:30-20:00 UTC weekday) and confirm
   `dashboard-data/macro_debate_log.csv` gains rows; scan the Actions run log for any `macro
   debate shadow-mode error` warnings even on a run that does log rows.
5. Let shadow-mode history accumulate; revisit the deferred promotion bar only once real
   history exists to check criteria against.

## Verification idioms used in this project (for the resuming session)

- Test suite: `.venv/bin/python -m pytest tests/ -q` — `526 passed` as of this session.
- **Checking real repo secrets (names only, never values):** `gh secret list --repo
  SinbadTheExplorer/graywind` works directly in this environment (`gh` CLI installed
  and authenticated) — this corrects the older `news_debate.py` handoff's claim that `gh`
  isn't available; that was true in whatever environment wrote that handoff, not this one.
- Bullion feed staleness check: `curl -s
  https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/news.json | head -c
  400` and read `generated_at` — no auth needed, public GitHub Pages URL.
- Ahead/behind state against `origin/main`: `git status --short --branch` or `git log
  --oneline origin/main..HEAD` — don't assume `main == origin/main` without checking; this
  session found local `main` 216 commits behind (automated data, synced cleanly) and, before
  that sync, already 2 commits ahead on unrelated work.
- Before starting related work, check `git branch -a` / `git worktree list` / `git log --all
  --oneline` for unmerged work — this repo has a documented history of stale unmerged
  branches and multiple concurrent worktrees.

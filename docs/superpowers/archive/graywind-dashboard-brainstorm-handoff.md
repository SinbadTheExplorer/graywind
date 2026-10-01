# Graywind Dashboard — Brainstorming Session Handoff

**Written:** 2026-08-14 · **For:** a fresh session resuming mid-`superpowers:brainstorming`
for a new Graywind dashboard feature. Graywind Phase 1 itself (the trading bot) is
**fully complete and merged to `main`** — this handoff is only about a follow-on feature
requested after that merge, not about resuming Phase 1 work.

## Goal

Build a public-facing dashboard for the Graywind trading bot, modeled on the Bullion
project's live-data pipeline pattern (GitHub Actions cron does the real work → commits a
JSON data file → GitHub Pages serves a static page reading it). The user explicitly wants
this as a **private GitHub repo**.

- No spec file exists yet — brainstorming has not reached the "write design doc" step.
- No plan file exists yet.
- No SDD workspace/ledger exists for this (that's only created once `writing-plans` /
  `subagent-driven-development` starts, which hasn't happened).
- Phase 1's own artifacts (already committed, for reference only — do not re-verify or
  re-touch them): `docs/superpowers/plans/2026-08-13-graywind-phase1-handrolled-mvp.md`,
  `docs/superpowers/specs/2026-08-13-graywind-phase1-handrolled-design.md`,
  `docs/superpowers/burn-in-decision.md`.

## How to resume (do this first)

1. Confirm you're in the right repo: `cd ~/Projects/graywind` (a **separate
   repo** from wherever this session's harness/worktree started — that's normal, this
   project has always been operated cross-repo via absolute paths from a `claudekit`/Bullion
   worktree; see "Traps" below).
2. Confirm state: `git rev-parse --abbrev-ref HEAD` should say `main`,
   `git log --oneline -1` should show `1682e85` (Phase 1's final commit) as the most recent
   *Graywind* commit — nothing dashboard-related has been committed yet.
3. Re-invoke `superpowers:brainstorming` — this resumes mid-flow, not fresh. **Do not
   re-ask the four questions already answered below** — read "What has changed" first and
   pick up exactly where this doc says to.
4. **Immediate next action:** the user was asked "single private repo containing both bot
   and dashboard (Approach A) vs. two separate repos (Approach B)?" and responded "write
   hand off" instead of answering. **Re-ask that exact question first**, using the text in
   "What's next" below — do not assume an answer.

## Current state (active files)

**Branch:** `main`, 0 commits ahead of Phase 1's final state (`1682e85`) — nothing new has
been written to disk for this feature yet. This whole session was pure conversation.

**Files created / changed so far:** none. This handoff file itself is the only new file.

**Files later work will create (once the approach question is answered):**
- A design spec at `docs/superpowers/specs/<date>-graywind-dashboard-design.md` (per
  `brainstorming`'s normal next step, once Approach A/B is settled and the remaining design
  sections are presented and approved).
- Depending on the answer: either new files inside this same repo (GH Actions workflow,
  dashboard HTML, a `docs/` Pages folder) or an entirely separate second repo.

**Scratch workspace / traps:**
- ⚠️ **This repo currently has no `git remote` at all.** `git remote -v` returns empty —
  Graywind has been 100% local this whole project. Pushing to GitHub for the first time
  (creating the private repo, adding the remote) is itself an unstarted step, not yet
  discussed in detail (no repo name was chosen).
- ⚠️ **No real trading credentials exist anywhere in this project.** Per
  `docs/superpowers/burn-in-decision.md`, the burn-in clock hasn't started because
  `ALPACA_API_KEY`/`ALPACA_API_SECRET`/`FRED_API_KEY`/`FINNHUB_API_KEY` were never
  obtained — every number produced so far came from synthetic data with gates stubbed.
  This dashboard work is a **parallel, independent track** from "get real credentials and
  start the burn-in" — the user hasn't said which to prioritize first, and the dashboard's
  own GitHub Actions cron will need those same four credentials as GitHub repo secrets
  once it's built (same pattern as Bullion's `FRED_API_KEY` secret). Flag this to the user
  if it isn't obvious which should happen first.
- ⚠️ **This session operates on the Graywind repo from a *different* project's worktree**
  (`claudekit`/Bullion, at a fixed absolute path) via plain single-line Bash commands with
  no `cd`-chaining or compound commands — that sandbox restriction is real and already
  discovered/worked around during this session; expect the same restriction on resume and
  just keep commands simple and single-purpose (one `cd && git ...` per Bash call fails;
  separate calls work).
- **Not mine — leave alone:** `docs/superpowers/graywind-phase1-mvp-handoff.md` (the old,
  superseded LEAN-era handoff — tracked in git, already correctly left in place per this
  project's archiving convention, do not move or delete it) and
  `docs/superpowers/graywind-phase1-handrolled-pivot-handoff.md` (the pivot handoff,
  untracked, also pre-existing — both are Phase 1 artifacts, not part of this feature).

## What has changed

Pure conversation, no commits. In order, the following were decided (verbatim answers,
so a resuming session can trust them without re-asking):

1. **Bot execution moves from local cron to GitHub Actions.** User confirmed explicitly:
   *"if we want to always be aware and trade responsibly, gotta do github cloud of
   course."* Reasoning given: not about CPU load (the script is trivially light either
   way) — about reliability. A local cron only fires if the Mac is awake/logged in/not
   asleep at that exact 15-minute mark during market hours; a missed cycle silently gaps
   the 4-week burn-in record. GitHub Actions runs on schedule regardless of the Mac's
   state. **This is settled — do not re-litigate it.**
2. **Direct architectural consequence of #1 (stated, not yet formally re-confirmed but
   follows necessarily):** `state/live_state.json` is currently `.gitignore`d and
   local-only (per Task 12's original design, when the bot only ever ran locally). GitHub
   Actions runners are ephemeral — nothing survives between separate scheduled runs except
   what's committed to the repo. So this state file **must become tracked and committed
   every cycle**, the same way Bullion's `data.json` is committed by its own workflow.
   This is a real change to already-shipped Phase 1 code (`graywind_strategy/state_store.py`,
   `.gitignore`), not just new dashboard code — make sure the design doc says so explicitly
   when it's written, and that the implementation plan includes un-gitignoring and adjusting
   `state_store.py`/the workflow accordingly.
3. **Dashboard content: "Status + full history"** (user's exact choice, not the cheaper
   "current status only" option). Required: an equity curve chart across the whole burn-in
   period, a scrollable trade log, plus the "current status" basics (open positions,
   today's P&L, last-cycle timestamp, per-symbol gate/decision reasoning). This is more
   data to design and persist than a snapshot-only dashboard — the design doc needs a real
   answer for *where the historical equity-curve points and trade-log entries accumulate
   over time* (most likely: append-only, alongside the operational state file from point
   #2, analogous to how Bullion's `data.json` is fully regenerated each run but Graywind's
   history needs to *accumulate* across runs rather than being recomputed from scratch —
   this is a real design difference from Bullion worth thinking through carefully, not
   just copying the pattern blindly).
4. **Privacy model: "Private repo + unlisted public URL is fine"** (user's exact choice).
   Confirmed understanding: on GitHub's free tier, a private repo keeps source/trade-history
   out of search engines and the public repo listing, but a GitHub Pages site built from
   it is still reachable by anyone with the exact URL (no login wall) — true access control
   needs GitHub Pro. User accepted this tradeoff explicitly. **No auth layer needed in the
   design.**

Then two architecture approaches were proposed for repo structure — **this is the open
question, not yet answered:**

- **Approach A (recommended by the assistant):** one private repo. `~/Projects/graywind`
  itself becomes the GitHub repo — bot code, the new GitHub Actions workflow, and the
  dashboard HTML all live together, matching Bullion's structure exactly (single repo,
  `docs/` folder serves GitHub Pages, reuse Bullion's `_config.yml` Jekyll-exclude
  workaround — see `~/claude-projects/claudekit/_config.yml`
  and `.github/workflows/daily-data.yml` in the Bullion/claudekit repo for the exact
  working reference pattern, including its secret-name-typo lesson and failure-alert-issue
  automation, both worth reusing here).
- **Approach B:** two repos — a private one for the bot/strategy logic, a separate
  (possibly public, since it'd only ever contain sanitized position/P&L data) repo purely
  for the dashboard. More isolation if the unlisted URL ever leaked (wouldn't expose
  strategy source), but doubles setup/maintenance for what's explicitly a
  time-constrained personal project (see the user's global workflow doc — tight time
  budget across all side projects since starting college).

The user's response to "which approach?" was **"write hand off"** — not an answer. Do not
assume Approach A was accepted just because the assistant recommended it.

## What has failed / risks / caveats

- **Nothing has failed.** This is pure pre-implementation brainstorming; no code has been
  written or tested for this feature yet.
- **UNVERIFIED / not yet done, in order of what blocks what:**
  1. The Approach A vs. B question (see "What's next").
  2. Once answered, brainstorming's remaining design sections (data flow specifics for the
     accumulating history — point #2 above is the crux of it — cron schedule details, exact
     new-repo name/GitHub setup, dashboard visual design/tech) still need to be presented
     and approved section-by-section per the `brainstorming` skill's normal flow. None of
     that has happened yet — the conversation never got past approach selection.
  3. No design doc has been written to disk at all.
- **Decision carried forward, not yet written into any spec:** state persistence must move
  from gitignored-local to committed-in-repo (point #2 above). Whoever writes the eventual
  spec must not silently keep the old local-file assumption from Task 12's original design.

## What's next (ordered)

1. **Re-ask the approach question verbatim** (don't skip straight to building): *"Single
   private repo containing both the bot and dashboard (Approach A), or two separate
   repos (Approach B)?"* — with the tradeoffs from "What has changed" item 5 above.
2. Once answered, continue `superpowers:brainstorming`'s normal flow: propose/confirm the
   remaining design pieces (accumulating-history data model, GH Actions cron schedule for
   every-15-min-during-market-hours, new repo creation/naming, dashboard tech/visual
   design — plain HTML+JS like `financial-map.html`'s pattern is a reasonable default to
   propose, not yet discussed), present each section, get approval.
3. Write the design doc to `docs/superpowers/specs/<today's date>-graywind-dashboard-design.md`,
   run the self-review checklist (placeholder scan, internal consistency, scope check,
   ambiguity check), commit it.
4. Ask the user to review the written spec file before proceeding further.
5. Once approved, invoke `superpowers:writing-plans` to produce the implementation plan —
   do not invoke any other implementation skill directly.
6. Execute via `superpowers:subagent-driven-development`, following this project's own
   established discipline from Phase 1: fresh subagent per task, task-scoped review with
   fix loops, hand-verify any math/boundary logic before dispatching (this project caught
   a real bug in nearly every one of Phase 1's 13 tasks this way), and a final whole-branch
   review before calling it done.

## Verification idioms used in this project (for the resuming session)

- Bash calls that touch `~/Projects/graywind` from this session's actual
  sandboxed worktree must be simple, single-purpose commands — no `&&`-chaining a `cd` with
  further commands in one call. Reads/writes work fine; the sandbox specifically objects to
  "too complex to verify it stays inside the worktree" on compound commands.
- The venv at `~/Projects/graywind/.venv` has all of Phase 1's Python deps
  already installed; reuse it for anything dashboard-side that's Python (e.g. a script that
  formats history into the dashboard's JSON) rather than creating a second one.
- Bare `pytest tests/ -q` now works from the repo root (a `conftest.py` was added during
  Phase 1's final review specifically to fix this) — no `python -m` prefix needed.
- This project's standing discipline, proven repeatedly in Phase 1: verify claims by
  actually running code, not by reading it — several of Phase 1's real bugs were only
  caught because a reviewer reverted a fix in a scratch copy and confirmed the regression
  test actually failed. Apply the same standard to any dashboard data-pipeline claims
  (e.g. "the cron job's committed state actually round-trips correctly across two separate
  ephemeral runs" deserves an actual two-run simulation, not just code review).

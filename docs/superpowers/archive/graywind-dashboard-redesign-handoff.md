# Graywind — Dashboard Redesign Session Handoff

**Written:** 2026-08-17 · **For:** a fresh session picking up Graywind after this session's
work: the VIX-vote design decision was resolved and shipped, the burn-in clock was confirmed
started, and the live dashboard (`index.html`) got a full visual-craft pass so the user can
show it to other people. Nothing is mid-flight — this is a checkpoint, not a resume point.

## Goal

Three separate threads closed out this session, in order:
1. **Resolve the macro-gate VIX-vote redundancy** — carried forward from the prior handoff as
   an open design question, not a bug. User decided: drop VIX from the vote.
2. **Confirm whether the live-trading cron has ever completed a real market-hours cycle** —
   carried forward as UNVERIFIED across several prior handoffs.
3. **Make the dashboard presentable** — the user's own words: "i just want to optimize the UI
   to look better and more impressive so i can show people." This was executed directly via
   the `impeccable:impeccable` design skill (a "bolder + polish within the existing identity"
   pass, per the user's explicit choice — see "What has changed" below), **not** through
   `superpowers:writing-plans` / SDD. There is no spec, plan, or progress ledger for this
   thread — none was written, and none is needed to continue it.

Full history/rationale for items 1 and 2: `docs/superpowers/graywind-post-macro-gate-handoff.md`
(previous handoff, now superseded by this one but still useful for the macro-gate shipping
story) and memory `project-graywind-bullion-macro-gate.md` /
`project-graywind-phase1.md` in `~/.claude/projects/-Users-me/memory/`.

## How to resume (do this first)

1. Confirm state: `git -C ~/Projects/graywind log --oneline -3` — most recent
   commit should be `2f51f0e`, on `main`. `git status` should be clean apart from the untracked
   handoff docs listed below. Local `main` is **in sync with `origin/main`** (0 ahead, 0
   behind) — everything in this handoff is already pushed and live.
2. There is no plan or ledger to resume for any of the three threads above — all three shipped
   to completion this session. Don't re-invoke `writing-plans`/SDD against them.
3. **Immediate next action:** there isn't a mandated one. The one real open thread is the
   sector-engine roster validation (see "What's next" #1) — it's blocked on the user running
   two scripts locally with their own Alpaca credentials, not on anything I can do unattended.
   Ask the user whether they've run it yet before assuming it's still pending.

## Current state (active files)

**Branch:** `main` at `2f51f0e`, **pushed, in sync with `origin/main`.**

**Files created/changed this session (all committed):**
- `graywind_strategy/gates/macro_gate.py` (`ab2c025`) — removed the `vix >= VIX_THRESHOLD`
  breach check and the now-dead `VIX_THRESHOLD` constant from `macro_gate()`. Gate is now
  "2 of {nfci, hy_oas, curve_slope}," not "2 of 4." `vix` is still fetched into every snapshot
  (harmless) but no longer counted.
- `tests/test_macro_gate.py` (`ab2c025`) — rewrote vote-count tests off vix; added
  `test_macro_gate_ignores_vix_even_when_it_would_tip_the_old_vote` as the actual regression
  pin (a case where old and new code disagree, not just one where they happened to agree).
  Full suite: 187 → 188 passing.
- `docs/superpowers/specs/2026-08-17-graywind-bullion-macro-gate-design.md` (`ab2c025`) —
  left the original as-approved design intact as a historical record, added a top-of-file
  amendment note pointing at the vix-vote change so a future reader doesn't take the "2 of 4"
  language at face value.
- `index.html` (`54bc1a0`) — full dashboard redesign. See "What has changed" for detail.
- `state/*.csv`, `dashboard-data/*.csv` (multiple `github-actions[bot]` commits,
  `407cf18`..`242b0f1`) — real live-cron output, not mine, merged in via two
  `Merge origin/main: pull in live-cron state/dashboard commits` merge commits
  (`d50d92e`, `2f51f0e`). These will keep updating every ~15min during market hours regardless
  of what a resuming session does — expect `git status`/`git log` to show more of them by the
  time you read this.

**Files later work will modify (untouched so far):**
- `live_loop.py`'s `WATCHLIST` — still exactly `["AAPL", "SPY"]`. The sector-engine roster
  expansion (6 new symbols) is validated-but-not-flipped; see "What's next" #1-2.

**Scratch workspace / traps:**
- ⚠️ **`docs/superpowers/graywind-post-macro-gate-handoff.md`** (untracked) — this session's
  starting-point handoff, now superseded by this file. Per this project's handoff convention
  it's being archived to `docs/superpowers/archive/` as part of writing this one. Do not resume
  from it; read this file instead.
- ⚠️ **`docs/superpowers/graywind-phase1-mvp-handoff.md`** — tracked in git, describes the
  original Phase 1 MVP build. Left in place (tracked files aren't archived by convention), but
  it predates almost everything in this handoff — treat `project-graywind-phase1` memory and
  this file as more current.
- ⚠️ **Dashboard "since burn-in start" reads -0.05% and today's P&L is negative** as of this
  writing. This is **not a red flag** — it's the bid/ask spread on one AAPL entry a few hours
  into a burn-in window that's supposed to run 4 weeks / 20 trades before anyone should draw a
  performance conclusion (`docs/superpowers/burn-in-decision.md`). Don't mistake early noise
  for a problem to fix.
- ⚠️ A temporary local test artifact — `python3 -m http.server` was run on port 8743 in this
  repo directory to verify the dashboard, plus a throwaway headless-Chrome probe script at
  `/tmp/gw_probe.mjs` (outside the repo, gitignored territory, nothing to clean up here). Both
  were stopped/are ephemeral; nothing was left running.

**Not mine — leave alone:** `docs/superpowers/burn-in-decision.md`, `docs/superpowers/archive/`
(archived handoffs, including the one this session adds), `docs/superpowers/plans/`,
`docs/superpowers/specs/` (other than the one amendment noted above).

## What has changed

**1. Macro-gate VIX vote — resolved and shipped (`ab2c025`).** `evaluate_vix_gate` already
blocks outright on the identical FRED VIXCLS series/threshold earlier in `decide_trade`, so
`macro_gate`'s own VIX vote could only ever fire when it was *wrong*. Asked the user directly
(not silently resolved, per the prior handoff's explicit instruction not to assume); they chose
to drop VIX from the vote. Shipped via TDD: wrote a regression test red first (vix+hy_oas breach
under the old 4-field vote → blocks; same snapshot under the new 3-field vote → allows), then
fixed the code, confirmed green, ran the full suite (188 passing), committed.

**2. Live-trading cron — confirmed working, burn-in clock started.** Checked GitHub Actions run
history early in the session (10:05 UTC): zero `schedule`-triggered runs, still just the 2 old
manual `workflow_dispatch` runs. Traced why: `live-trading.yml`'s cron
(`*/15 13-20 * * 1-5` UTC) first went live on `origin/main` on **Saturday** 2026-08-15 — a
non-trading day — and the only weekday since was *that same Monday*, checked before its 13:00
UTC window had even opened. Not a bug, just elapsed time. Re-checked after 13:00 UTC: **two,
then four, scheduled runs had fired and succeeded**, each pushing real `state/*.csv` /
`dashboard-data/*.csv` via `github-actions[bot]` with a genuine Alpaca paper-account balance
(`$100,000` starting equity, one real AAPL buy). Per `burn-in-decision.md`, the clock starts
"when that real-data run begins" — **it has now begun, 2026-08-17.** Target: 4 weeks or 20 real
trades, whichever is later (~2026-09-14+). Memory (`project-graywind-phase1.md`,
`project-graywind-sector-engine.md`) updated to reflect this; it was the last unresolved
"UNVERIFIED" item carried across several prior handoffs.

**3. Dashboard redesign — shipped (`54bc1a0`, merged/pushed as `2f51f0e`).** User wanted it to
"look better and more impressive" for showing other people. Before touching anything, asked the
user a real fork: keep the dark-gold identity shared with Bullion/Mk Ultra and execute it
better, or give Graywind its own distinct visual identity (a much bigger undertaking under
`impeccable`'s `new-work` flow). **User chose: keep the shared identity, execute it better** —
so this ran as a whole-page `bolder`+`polish` pass within the existing world, not a from-scratch
redesign. What changed, concretely:
- Equity is now the dominant hero number (was one cell in a metrics grid), with a real
  today's-P&L delta chip and a stat row (since-burn-in-start %, open positions, trades logged)
  — every number computed from the same three CSVs the old version already loaded
  (`dashboard-data/equity_curve.csv`/`trade_log.csv`/`status.csv`), nothing fabricated.
- D3 equity chart: gradient area fill, `curveMonotoneX` smoothing, hover crosshair + tooltip.
  **Caught in testing, not by inspection:** the x-axis was formatting every tick as "Aug 17"
  (duplicated 6x) because both live data points so far are from the same day — fixed by
  switching to a time-of-day (`%H:%M`) format when the domain span is under ~20 hours.
- Positions panel: added per-symbol unrealized P&L (`(current − entry) × shares`), computed
  client-side from fields already in `status.csv`.
- Real empty/error states with a retry button — the old version failed silently on a bad fetch.
- Typography: **committed fully to a single IBM Plex Mono voice.** Original draft paired it
  with Space Grotesk for headings; ran `impeccable`'s mechanical `detect.mjs` scanner, which
  flagged Space Grotesk as an "overused AI-default" face (it's on the exact list `craft-floor.md`
  itself names as saturated). Dropped it rather than argue with a correct mechanical finding —
  an all-mono UI is also just a better fit for a trading-terminal subject than a sans+mono pair.
- **Verified, not just eyeballed:** served the repo locally (`python3 -m http.server`), drove
  headless Chrome via the `headless-chrome-verification` skill's CDP probe template at desktop
  (1280px), tablet (768px), and mobile (390px) widths. Confirmed: real data renders (hero
  equity, both chart paths, position/trade rows, fonts), zero console errors, zero horizontal
  overflow at any width, `detect.mjs` clean after the font fix.

## What has failed / risks / caveats

- **Nothing has failed.** All three threads shipped clean; the x-axis bug and the overused-font
  finding were both caught and fixed *before* commit, not after.
- **UNVERIFIED / blocked on the user, not on further coding:** the sector-engine 6-symbol
  roster fetch/validation (`scripts/fetch_roster_data.py` + `scripts/validate_sector_engine.py`)
  hasn't run yet. It needs real `ALPACA_API_KEY`/`ALPACA_API_SECRET` locally, which currently
  only exist as GitHub Actions secrets. Offered three ways to supply them (user creates a local
  `.env`, run it as a one-off GH Actions job, or the user runs it themselves and pastes back the
  output) — **user chose the third**, specifically to keep real keys out of the chat transcript.
  See "What's next" #1 for the exact commands already given to the user.
- **Carried forward, not touched this session:** `pipeline.py`'s `drawdown_breaker_ok`
  docstring at (around) line 85 still says "the three gates below" — cosmetic, deliberately
  deferred across two prior handoffs, still true.
- The burn-in window is 4 weeks / 20 trades old as of *today*. Don't draw any performance
  conclusion from it yet, positive or negative — the dashboard will show real volatility long
  before it shows anything statistically meaningful.

## What's next (ordered)

1. **If the user has run the roster validation:** they were given this exact sequence to run
   locally (not through Claude, to keep credentials out of the transcript):
   ```
   cd ~/Projects/graywind
   export ALPACA_API_KEY=... ALPACA_API_SECRET=...
   python3 scripts/fetch_roster_data.py
   python3 scripts/validate_sector_engine.py
   ```
   `validate_sector_engine.py` prints a table of short-hold vs. long-hold win rates with the
   confirmation-bars filter on vs. off, per symbol, on a held-out 20% window. Read the output
   against the bar the shipped design set: filter-on should raise short-hold win rate relative
   to filter-off without gutting long-hold performance. If they haven't run it, ask — don't
   assume either way.
2. **Only after #1 passes:** decide (with the user, it's their call how aggressive to be) how
   `live_loop.py`'s `WATCHLIST` changes — full replace with the 8-symbol roster, or an additive
   change. This was explicitly left as "an explicit future decision, not done yet" when the
   sector engine shipped; don't resolve it silently.
3. **No dashboard code changes are needed for the roster expansion** — confirmed this session
   that `index.html` renders every row generically off `row.symbol` from the CSVs; new symbols
   will just appear once `live_loop.py` starts trading them and the cron runs.
4. Otherwise: keep an eye on burn-in progress periodically (`state/operational.csv`, GitHub
   Actions run history) rather than proactively coding — nothing else is queued.

## Verification idioms used in this project (for the resuming session)

- Full Python test suite: `python3 -m pytest tests/ -q` (188 passing as of `ab2c025`).
- **No `gh` CLI in this environment.** Check GitHub Actions run history via the public REST API
  (works unauthenticated for a public repo):
  ```
  curl -s "https://api.github.com/repos/SinbadTheExplorer/graywind/actions/workflows/live-trading.yml/runs?per_page=10" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); [print(r['run_number'], r['status'], r['conclusion'], r['event'], r['created_at']) for r in d['workflow_runs']]"
  ```
- Live public dashboard: `https://sinbadtheexplorer.github.io/graywind/` (returns 200 as
  of this writing; may take a minute or two to redeploy after a push).
- Bullion's live public data file (macro-gate grounding): `curl -s "https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/data.json"`.
- **For any `index.html`/dashboard change:** don't trust a static read of the file — serve it
  (`python3 -m http.server` from the repo root, since `fetch()` of local CSVs needs `http://`,
  not `file://`) and drive it with the `headless-chrome-verification` skill's CDP probe template
  (`~/.claude/skills/headless-chrome-verification/templates/cdp_probe.mjs`) at multiple widths.
  This caught a real x-axis formatting bug this session that a static read would have missed.
  If the `impeccable` design-hook doesn't auto-fire, run its detector manually:
  `node <impeccable skill base dir>/scripts/detect.mjs --json index.html`.
- This project follows TDD (red/green) for any `gates/`/`pipeline.py`/`strategy_engine.py`/
  `backtester.py` change — see `tests/test_macro_gate.py`'s newest test for the pattern (a case
  where old and new behavior disagree, not one where they happen to already agree).
- For any multi-task Python implementation: `superpowers:writing-plans` →
  `superpowers:subagent-driven-development` in an isolated worktree, with a whole-branch final
  review before merge. For UI/visual work on an established surface: the `impeccable:impeccable`
  skill directly (no plan/ledger needed) — but still verify visually, not just by reading code.

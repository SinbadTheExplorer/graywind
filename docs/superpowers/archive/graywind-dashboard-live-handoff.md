# Graywind Dashboard — Live Handoff

**Written:** 2026-08-15 · **For:** a fresh session resuming work on the Graywind dashboard —
either verifying the first real market-hours cycle, or starting the visual restyle to match
Bullion/Mk Ultra.

## Goal

Give the Graywind trading bot a public dashboard (equity curve, trade log, current status)
driven by a GitHub Actions cron. This session took that from "brainstorm handoff" all the way
to a live, deployed, publicly-reachable site — but with the real end-to-end cycle still
unverified, and a fresh visual-design ask just added on top.

- Design spec (living doc, includes a "Revision" section documenting the two-repo→one-repo
  reversal): `docs/superpowers/specs/2026-08-15-graywind-dashboard-design.md`
- Original implementation plan (two-repo version; marked superseded at its top, kept as
  historical record): `docs/superpowers/plans/2026-08-15-graywind-dashboard.md`
- Prior handoff this one supersedes: `docs/superpowers/graywind-dashboard-brainstorm-handoff.md`
  (that one covers only the brainstorm; this one covers everything built and deployed since)

## How to resume (do this first)

1. Confirm state: `git -C /Users/thanhnguyen/Projects/graywind rev-parse --abbrev-ref HEAD`
   should say `main`; `git -C /Users/thanhnguyen/Projects/graywind log --oneline -1` should
   show `77f9a12` as the most recent commit.
2. Check whether a real cycle has run yet: visit
   `https://sinbadtheexplorer.github.io/graywind/` — if it still says "no cycle has run
   yet" for both AAPL and SPY, no real market-hours cycle has completed since this handoff was
   written. If it shows real data, the end-to-end path is proven; update this handoff's
   "UNVERIFIED" section below rather than trusting this note forever.
3. Read "What's next" below and pick up there — do not re-litigate the two-repo-vs-one-repo
   decision (already settled, see the design doc's Revision section) or re-run Task 7's setup
   steps (already done, see "Current state" below).

## Current state (active files)

**Branch:** `main`, 12 commits ahead of Phase 1's final commit (`1682e85`). No feature branch
in flight — everything is merged.

**Repo is now PUBLIC** on GitHub — this is a real scope change from the original design
(which assumed a private repo + unlisted-URL dashboard). `graywind_strategy/` source code and
full trade history are visible to anyone. Do not silently re-assume "private, unlisted-URL
only" from the design doc's older language.

**Public URLs (live now):**
- Repo: `https://github.com/SinbadTheExplorer/graywind`
- Dashboard: `https://sinbadtheexplorer.github.io/graywind/`

**Files created / changed (committed, `main` at `77f9a12`):**
- `graywind_strategy/state_store.py` — CSV-based internal state (`state/positions.csv`,
  `state/operational.csv`), replaces the old `live_state.json`.
- `graywind_strategy/dashboard_export.py` — pure per-cycle export writer (equity point, new
  trades, refreshed status) to a local scratch dir.
- `live_loop.py` — wired to call `dashboard_export.write_cycle_export(...)` in `main()`'s
  `finally` block; `process_symbol()` gained optional collector params, backward-compatible.
- `merge_dashboard_export.py` — merges the scratch export into `dashboard-data/` (append for
  equity/trades, overwrite for status).
- `.github/workflows/live-trading.yml` — cron every 15 min, 9:30am–4:00pm ET, Mon–Fri; runs
  the bot, commits `state/*.csv` + `dashboard-data/*.csv` in one push. No PAT, no second repo
  (that was the two-repo version's design, reversed same-day).
- `index.html` (repo root) — the dashboard itself: vanilla JS + D3, `fetch()`s
  `dashboard-data/*.csv`, currently styled plain dark-blue (**not yet** Bullion-styled — see
  "What's next").
- `dashboard-data/{equity_curve,trade_log,status}.csv` — seed files, tracked in git.
- `_config.yml` — excludes `docs/` from Jekyll (this repo's `docs/` holds private planning
  markdown, same situation as Bullion's own `_config.yml`).

**Scratch workspace / traps:**
- ⚠️ **`dashboard_export/` (no hyphen, singular local scratch dir) is gitignored and
  ephemeral** — do not confuse it with `dashboard-data/` (hyphenated, tracked, the real
  committed history). `dashboard_export/` only exists transiently during a workflow run or a
  local `live_loop.py` invocation.
- ⚠️ **`state/` doesn't exist on disk in a fresh checkout** — it's created at runtime by the
  first successful `save_state()` call. This is expected; a resuming session should not treat
  its absence as a bug.
- ⚠️ **`~/.ssh/id_ed25519_github`** — a dedicated SSH keypair generated this session
  specifically for pushing to GitHub, with its public key added to the
  `SinbadTheExplorer` GitHub account. Live and in use (`~/.ssh/config` has a
  `Host github.com` block pointing at it). Not project-specific, but worth knowing it exists
  if git push auth ever needs debugging.
- ⚠️ **Four GitHub Actions secrets are set on the repo** (`ALPACA_API_KEY`,
  `ALPACA_API_SECRET`, `FRED_API_KEY`, `FINNHUB_API_KEY`) — added this session, after a first
  attempt used wrong names (`API_KEY_ALPACA` etc.) that was caught and corrected before it
  could cause the exact silent-failure class that already happened once on the sibling Bullion
  project (secret name typo → empty value → failure with no clear cause). Names are confirmed
  correct as of this session; if the workflow ever fails with a credentials error, check the
  secret names first, not the code.

**Not mine — leave alone:**
- `docs/superpowers/graywind-phase1-mvp-handoff.md` — tracked in git, Phase 1 (LEAN-era)
  artifact, already correctly left in place per this project's archiving convention.
- `docs/superpowers/burn-in-decision.md` — the separate gate for when Phase 1's burn-in clock
  itself starts (see "What has failed / risks / caveats" below — this dashboard work doesn't
  change that gate).

## What has changed

Twelve commits since Phase 1 (`1682e85..77f9a12`), in order:
1. `cb5607f`, `f4e214d` — design doc (two-repo version, then a factual correction to the
   internal-state field names discovered while writing the plan).
2. `6c86c7d` — implementation plan (two-repo version).
3. `d9413db` → `81cd286` — six SDD tasks, each implemented + task-reviewed clean: CSV state
   migration, `dashboard_export.py`, `live_loop.py` wiring, `merge_dashboard_export.py`, the
   GitHub Actions workflow, and (in a now-deleted separate repo) the dashboard scaffold.
4. `eb07079`, `b5cc3e4` — the final whole-branch review (dispatched on the most capable
   available model) found 2 Critical + 2 Important bugs invisible to any single task's
   diff — a CRLF-vs-JS-parser mismatch across the two repos' boundary, and a GitHub-cron/
   market-hours mismatch that would've filed false alerts ~5x/day. Both fixed in one wave,
   verified ADDRESSED by a scoped re-review. Merged to `main` here.
5. `88328ec`, `77f9a12` — mid-session the user reversed the two-repo decision to one repo.
   Deleted the now-unused `graywind-dashboard` repo (never pushed anywhere, cost nothing to
   undo), moved `index.html` to `graywind`'s own root, renamed the CSV folder to
   `dashboard-data/` (`data/` was already claimed by a pre-existing `.gitignore` entry for
   cached Alpaca bars), simplified the workflow to one commit+push. A follow-up code-review
   pass on the collapse itself caught and fixed a real bug: `git add -A state dashboard-data`
   is atomic, so it silently drops a legitimate `dashboard-data` update whenever `state/`
   doesn't exist yet (true on the very first run) — fixed by splitting into two independent
   `git add` calls, reproduced and confirmed both the bug and the fix directly.

Full test suite: 139 passing as of `77f9a12` (`pytest tests/ -q` from the repo root, no venv
needed — system `pytest`/`python3` at `/opt/homebrew/bin/` work fine in this environment).

**Since the last commit** (not code, done live via browser automation, no new commits):
created the `graywind` GitHub repo, force-pushed local `main` over GitHub's auto-generated
initial commit, made the repo public (GitHub Pages isn't available for private repos on this
account's plan — user's explicit choice when told), enabled Pages (root-served from `main`),
added the four trading secrets (corrected after an initial naming mismatch), and ran two
`workflow_dispatch` dry runs.

## What has failed / risks / caveats

**Nothing has failed** — both dry runs succeeded, secrets are confirmed correctly named, the
cycle-detection gate correctly skipped the merge step both times.

- **UNVERIFIED: no real market-hours cycle has run yet.** Both `workflow_dispatch` dry runs
  this session landed outside 9:30am–4:00pm ET, so `is_market_hours()` returned `False` and
  `live_loop.py` exited before ever reaching the trading logic, `state/*.csv`, or
  `dashboard-data/*.csv`. This proves the trigger fires, the workflow runs cleanly, and the
  cycle-detection gate correctly skips the merge step when there's nothing to merge — it does
  **not** prove the real commit+push path works, or that a real Alpaca/FRED/Finnhub API call
  succeeds with the credentials now configured. The 15-minute cron is live and will fire
  automatically during the next real market-hours window; check the dashboard URL after that
  to confirm real data appears, or check `https://github.com/SinbadTheExplorer/graywind/actions`
  for a run whose "Run the live trading cycle" step doesn't say "outside market hours, exiting".
- **Repo visibility is a real scope change, not a detail.** The original design assumed a
  private repo with only an unlisted dashboard URL exposed. It's now a fully public repo —
  strategy source, trade history, Actions logs, everything. If privacy matters again later,
  that's a fresh decision to make explicitly, not something to silently revert to.
- **Burn-in clock status needs a fresh read, not an assumption carried from memory.** Prior
  session memory says "no real credentials exist anywhere in this project" — that's now false
  (this session added real `ALPACA_API_KEY` etc. as repo secrets). But `docs/superpowers/burn-in-decision.md`'s
  actual gate is **4 weeks of live paper trading OR 20 real trades, whichever is later**, with
  no PDT violations and no unhandled exceptions — that clock starts only once real cycles
  actually begin running with these credentials, which (per the UNVERIFIED point above) hasn't
  been confirmed yet. Read that file directly before answering "has burn-in started" — don't
  infer it from "secrets exist now."

## What's next (ordered)

1. **Confirm a real market-hours cycle has run.** Check the dashboard URL or the Actions tab
   (see "UNVERIFIED" above). If a run failed with a real error (not "outside market hours"),
   that's the first thing to debug — read the failed step's log directly, don't guess.
2. **Restyle the dashboard to match Bullion/Mk Ultra** — the user's explicit request at the
   end of this session, not yet started (no design work, no CSS changes). Current `index.html`
   is plain dark-blue D3 styling from the original brainstorm's scaffold task. Target: the
   look of `financial-map.html` in the sibling Bullion project
   (`/Users/thanhnguyen/minhthanh0403/claude-projects/claudekit/financial-map.html`) — **look
   at that actual file for the real styling** (colors, typography, layout conventions), not
   just the "dark gold theme" name from that project's `CLAUDE.md`
   (`/Users/thanhnguyen/minhthanh0403/claude-projects/claudekit/CLAUDE.md`), since the name
   alone won't capture spacing/component conventions worth matching. This is a visual-only
   change — don't touch the CSV-fetching/parsing logic (`parseCSV`, `loadCSV`, the CRLF
   hardening) while restyling; that logic was hard-won across two review passes this session.
   Given it's a design-facing change, consider whether `frontend-design` or `impeccable`
   skill guidance applies before diving into CSS by hand.
3. Once burn-in criteria are actually met (per `burn-in-decision.md`, not before), Phase 2/3
   work on the bot itself can be considered — separate track from this dashboard work.

## Verification idioms used in this project (for the resuming session)

- `pytest tests/ -q` from `/Users/thanhnguyen/Projects/graywind` — no venv needed, system
  `pytest`/`python3` at `/opt/homebrew/bin/` work directly in this environment.
- YAML syntax check when Python's `yaml` module isn't importable here (it wasn't, this
  session): `ruby -ryaml -e "YAML.load_file('.github/workflows/live-trading.yml')"`.
- A local static-file check for `index.html`/`dashboard-data/*.csv` changes: `python3 -m
  http.server <port>` from the repo root, then `curl` the paths directly — faster than waiting
  on a real GitHub Pages deploy for a quick sanity check.
- CRLF-related JS changes: verify with a throwaway `node -e '...'` script feeding simulated
  `\r\n` input through the actual `parseCSV` function text, rather than assuming a fix works —
  this caught nothing new this session but is how the CRLF fix was independently re-verified
  after the single-repo file move, and it's cheap enough to do again for any future parser
  change.
- This project's standing discipline, unchanged: verify claims by actually running
  code/commands, not by reading them. Every review pass this session that found a real bug
  (the final whole-branch review, and the follow-up review on the single-repo collapse) found
  it by reproducing the failure directly, not by inspection alone.

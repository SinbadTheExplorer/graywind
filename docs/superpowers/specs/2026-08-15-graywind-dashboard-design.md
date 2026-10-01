# Graywind Dashboard — Design

**Date:** 2026-08-15
**Status:** implemented (two-repo version merged to `main` at `b5cc3e4`), then revised same-day
to a single-repo layout before any GitHub-side setup (Task 7) happened — see "Revision" below.
**Prior art referenced:** Bullion's live-data pipeline (`financial-map.html`,
`.github/workflows/daily-data.yml`, `_config.yml` in
`~/claude-projects/claudekit`)

## Revision (2026-08-15, same day as initial implementation)

The two-repo design below (Approach B) was fully implemented, task-reviewed, whole-branch
reviewed, and merged to `graywind`'s `main`. Before Task 7 (creating the GitHub repos) ever
ran, the decision was reversed: **one repo instead of two.** Nothing had been pushed to
GitHub yet, so this cost nothing to undo. The sections below are updated in place to reflect
the single-repo (Approach A) layout; where a decision changed, the original reasoning is kept
for context but marked superseded rather than deleted.

Consequence: the separate `graywind-dashboard` repo that Task 5 scaffolded was deleted
(it was never pushed anywhere, so nothing depended on it). Its `index.html` moved into
`graywind` at repo root.

## Goal

A public-facing (but unlisted) dashboard for the Graywind trading bot's paper-trading
burn-in: current status, an equity curve across the whole burn-in period, and a scrollable
trade log. Built on the same "cron does the work, static site reads committed data" pattern
Bullion already proved out, adapted for two repos instead of one and CSV instead of JSON.

Graywind Phase 1 (the bot itself) is complete and merged to `main` (`1682e85`). This is a
follow-on feature, independent of the still-unstarted burn-in clock (see
`docs/superpowers/burn-in-decision.md` — real Alpaca/FRED/Finnhub credentials are still
needed before burn-in starts; that is tracked separately from this dashboard work).

## Repo Structure — one repo (Approach A, supersedes the original Approach B decision)

- **`graywind`** (existing, this repo) — private, unlisted GitHub Pages URL (keeps it out of
  search engines and repo listings, but the exact URL is reachable by anyone — GitHub's free
  tier has no login wall for Pages; true access control needs GitHub Pro). Bot code, strategy
  logic, and the dashboard's static frontend + data all live here together.

*(Superseded reasoning, kept for context: the original Approach B chose two repos for extra
isolation if the unlisted dashboard URL ever leaked, since a separate repo would keep the
bot's strategy source out of reach even then. Reversed same-day, before any GitHub-side setup,
because the added setup/maintenance cost — a second repo, a cross-repo PAT, a second set of
GitHub Pages settings — wasn't worth it for a personal project on a tight time budget, and the
isolation benefit was judged marginal: the dashboard data alone (trade log, equity curve)
already reveals the strategy's approximate behavior even without the source.)*

## Data Format — CSV everywhere, no JSON

Applies to both the bot's internal operational state and the dashboard's display data.
Rationale: this data is small (thousands of rows/year at most), accumulates via git commits
every cycle, and needs clean single-line diffs plus zero-dependency parsing in vanilla
browser JS. Heavier "market-leading" formats (Parquet, Arrow, DuckDB-wasm) are built for
large-scale analytics workloads this project will never reach, and would add real
dependency/load-time cost for no benefit. SQLite was rejected because binary diffs defeat
the point of a git-committed accumulating log. NDJSON was rejected because it's still JSON
syntax, which doesn't address the underlying preference against JSON.

### `graywind` repo — internal operational state (replaces `live_state.json`)

Not read by any browser; Python-internal only. Decomposed into two small tabular files
instead of one nested JSON object. Field names below are corrected against the actual
`state_store.py`/`live_loop.py` state shape (`day_trade_dates`, `day`, `starting_equity`,
`open_positions`) discovered while writing the implementation plan — not the approximate
names guessed during brainstorming:

- **`state/positions.csv`** — one row per open position:
  `symbol,entry_price,shares,stop,target,opened_date`. **Overwritten** each cycle (reflects
  current holdings, not history).
- **`state/operational.csv`** — single header + single data row:
  `day,starting_equity,day_trade_dates`, where `day_trade_dates` is a semicolon-joined list
  of ISO dates (PDT throttle's rolling-window memory) in one field — semicolon isn't the CSV
  delimiter, so no quoting is needed. **Overwritten** each cycle.

Both paths come out of `.gitignore` and are committed by the bot's workflow every cycle —
required because GitHub Actions runners are ephemeral and nothing survives between separate
scheduled runs except what's committed to the repo. This is a real change to already-shipped
Phase 1 code (`graywind_strategy/state_store.py`, `.gitignore`), not just new dashboard code.

### `graywind` repo — dashboard display data

Lives at `dashboard-data/`, **not** `data/` — `graywind`'s `.gitignore` already has a bare
`data/` entry (for cached Alpaca bars), which would silently swallow these CSVs if the same
name were reused. This collision only became visible once the collapse actually moved files
into `graywind`'s tree; it didn't exist in the two-repo version.

- **`dashboard-data/equity_curve.csv`** — `timestamp,equity`. **Append-only.**
- **`dashboard-data/trade_log.csv`** — `timestamp,symbol,side,qty,price,reason`. **Append-only.**
- **`dashboard-data/status.csv`** — open positions, today's P&L, last-cycle timestamp,
  per-symbol gate/decision reasoning. **Overwritten** each cycle (a snapshot, not history).

`index.html` lives at `graywind`'s repo root (not inside `dashboard-data/`) — GitHub Pages'
classic "deploy from a branch" only supports serving from the repo root or from `/docs`, and
`/docs` is already `graywind`'s private planning-docs folder (specs, plans, handoffs), so root
is the only option that doesn't require relocating that existing convention.

## Execution Model

- Bot execution moves from local cron to **GitHub Actions**, scheduled every 15 minutes,
  9:30am–4:00pm ET, Monday–Friday. Local cron only fires if the Mac is awake/logged
  in/unlocked at that exact moment; a missed cycle silently gaps the 4-week burn-in record.
  Actions runs regardless of the Mac's state.
- The `graywind` workflow runs `live_loop.py`, which writes `state/positions.csv` +
  `state/operational.csv` and (via `merge_dashboard_export.py`) the incremental dashboard
  update (one new equity point, any new trade rows, a refreshed status row) into
  `dashboard-data/`. The workflow then commits and pushes **all of it in one step** — no
  second repo, no PAT, no cross-repo clone. *(Superseded: the two-repo version needed to
  commit `graywind`'s own state independently of a separate cross-repo push, specifically so
  a PAT/network failure on the second push couldn't lose the first commit. With everything in
  one repo there's only one push to succeed or fail, so that whole failure mode — and the
  workflow complexity built to handle it — no longer applies.)*

## Dashboard Frontend

Single static `index.html` at `graywind`'s repo root, vanilla JS + D3, no build step, no
framework — same pattern as `financial-map.html`. `fetch()`s the three `dashboard-data/*.csv`
files at load time, parses them client-side (plain string splitting, no CSV library needed at
this scale — the parser's line-splitting was hardened against Python's CSV writers' `\r\n`
line endings during the two-repo version's final review, and that fix carries forward
unchanged), renders:
- An equity curve chart across the full burn-in period.
- A scrollable trade log table.
- A status panel: open positions, today's P&L, last-cycle timestamp, per-symbol
  gate/decision reasoning.

Served via GitHub Pages from `graywind` itself, root-served (not `/docs`, since that's
already the private planning-docs folder). `_config.yml` at repo root excludes `docs/` from
Jekyll processing — the actual pattern Bullion uses (site at repo root, `docs/` excluded),
not the "docs/ folder serves Pages" description from the original brainstorm, which didn't
match Bullion's real configuration.

## Error Handling

- **Push failure** (network blip, conflict) now affects state and dashboard data together
  (one repo, one push) rather than being a risk isolated to a second cross-repo push. A
  failed push means neither commits that cycle; the next cycle's push carries both forward.
  *(Superseded: the two-repo version needed an explicit independence guarantee between the
  state commit and the dashboard push specifically because they were two separate pushes to
  two separate remotes. That distinction doesn't exist anymore.)*
- **A failed trading cycle** (gate rejection, broker API error) still writes a `status.csv`
  row reflecting that outcome — "last cycle failed / no trade" is a real status, not a
  missing file. The workflow must still commit `state/*.csv`/`dashboard-data/*.csv` even when
  `live_loop.py` itself exits non-zero (they're written by its `finally` block regardless) —
  this was Important Finding #3 from the two-repo version's final review and remains equally
  true in the single-repo version; the fix (`if: always()` on the commit step) carries
  forward.
- The out-of-market-hours cron/false-alarm gap (Critical Finding #2 from the two-repo
  version's final review — GitHub cron can't track DST, so scheduled runs outside real market
  hours produced no `dashboard_export/` output and crashed the merge step) is unaffected by
  the repo-count change and its fix (a "did this cycle actually run" gate) carries forward too.
- Reuse Bullion's existing failure-alert pattern (`.github/workflows/daily-data.yml`'s
  auto-filed GitHub issue on workflow failure), so a silent cron failure — the exact failure
  mode already seen once on Bullion — gets surfaced instead of going quiet.

## Testing

- **Two-run round-trip simulation**: actually execute the workflow logic twice in sequence
  against a scratch copy of the CSVs, and confirm the second run correctly *appends* (not
  overwrites) `equity_curve.csv`/`trade_log.csv` while correctly *overwriting*
  `status.csv`/`positions.csv`/`operational.csv`. Verified by running it, not by reading the
  code, per this project's standing discipline (Phase 1 caught real bugs this way in nearly
  every task).
- **Push dry run**: trigger the workflow manually (`workflow_dispatch`) and confirm a real
  commit lands in `graywind` before trusting the live schedule. *(Superseded: this used to be
  specifically a "cross-repo push" dry run verifying PAT write-access; with one repo there's
  no PAT and no second remote to validate — it's just a normal workflow dry run now.)*
- `pytest tests/` gets new cases for the CSV read/write paths in `state_store.py`, replacing
  whatever covered the old JSON path. (Already done, carries forward unchanged.)

## Manual Setup Required (not automatable, human-only steps)

`graywind` currently has **no git remote at all** — it has been 100% local this entire
project. Before the workflow can run for real, the user must, outside of Claude Code:

1. Create the `graywind` GitHub repo (private) and add it as this local repo's remote, push.
2. Enable GitHub Pages on `graywind` itself, root-served.

*(Superseded: the two-repo version's list also included creating a second GitHub repo and
generating/storing a fine-grained PAT as a `DASHBOARD_REPO_PAT` secret. Both steps are gone —
one repo means one remote and no PAT to manage.)*

The implementation plan should surface these as explicit checkpoints, not assume they've
silently happened.

## Explicitly Out of Scope

- Any authentication/access-control layer on the dashboard (accepted tradeoff of the
  unlisted-URL privacy model).
- Starting the burn-in clock itself, or obtaining real Alpaca/FRED/Finnhub credentials —
  tracked separately in `docs/superpowers/burn-in-decision.md`, independent of this feature.
- Any change to the strategy/decision logic in `graywind_strategy/` beyond the state
  persistence format.

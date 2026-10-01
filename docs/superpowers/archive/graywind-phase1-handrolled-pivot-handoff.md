# Graywind Phase 1 — LEAN-to-Hand-Rolled Pivot — Session Handoff

**Written:** 2026-08-13 · **For:** a fresh session resuming mid-`superpowers:brainstorming`,
partway through rewriting the Phase 1 spec to drop LEAN Engine entirely. **Supersedes the
prior handoff's "What's next"** (`graywind-phase1-mvp-handoff.md`, same directory, commit
`6d62609` on this branch) — that doc's QuantConnect-token chase is now moot; read this one
first, only fall back to the older doc for its "Verification idioms" section, which is
still partly relevant (Docker check idiom no longer applies, general "verify claims
independently" discipline still does).

## Goal

Graywind Phase 1 proves a full data → signal → risk-checked order → paper-fill → backtest
pipeline for a rule-based (RSI + moving-average crossover) intraday US-equities strategy,
before any ML or real capital. The pipeline choice changed mid-session (see "What has
changed"); the underlying goal has not.

- **Old spec/plan (now stale, LEAN-based)**: `docs/superpowers/specs/2026-08-13-graywind-phase1-mvp-design.md`,
  `docs/superpowers/plans/2026-08-13-graywind-phase1-mvp.md` (both on `main`, committed).
  **Do not implement against these** — they describe the LEAN Engine/`lean-cli` stack that
  this session abandoned. They still exist because the rewrite isn't written yet.
- **New spec**: not yet written to disk. A full draft was presented to the user in chat
  and is reproduced in full below in "What's next" — nothing to search for, it only exists
  in this handoff until someone writes it to
  `docs/superpowers/specs/<new-date>-graywind-phase1-handrolled-design.md`.
- Progress ledger (recovery map): `.superpowers/sdd/2026-08-13-graywind-phase1-mvp/progress.md`
  — **gitignored, lives only inside the worktree**, describes the now-obsolete LEAN
  blocker chase. Read it for history, not for next steps.

## How to resume (do this first)

1. `cd ~/Projects/graywind/.worktrees/graywind-phase1-mvp` — confirm
   `git rev-parse --abbrev-ref HEAD` says `graywind-phase1-mvp`, and
   `git log --oneline main..HEAD` shows exactly one commit, `6d62609` (the prior handoff).
   `git status --short` should show only `M .gitignore` and `?? requirements.txt` — if it
   shows anything else, something changed since this handoff was written; investigate
   before trusting the rest of this doc.
2. Re-invoke `superpowers:brainstorming` (not `subagent-driven-development` yet — the spec
   isn't approved or written). It should recognize this as mid-flow, not a fresh start.
3. **Immediate next action:** present the design in "What's next" below to the user
   verbatim (or read it aloud/paraphrased), and ask the exact question the prior session
   was mid-asking: *"Does this look right overall, or is there a section you want changed
   before I write it into the spec file?"* Do not silently write the spec file without
   this confirmation — the brainstorming skill's hard gate requires user approval of the
   design before it's written, and that approval was never given (the user asked for a
   handoff instead of answering).

## Current state (active files)

**Branch:** `graywind-phase1-mvp`, 1 commit ahead of base `fc82b30` (the prior handoff
commit, `6d62609`).

**Files created (committed on `main`, before this branch — now stale, superseded by the
pivot, not yet formally replaced):**
- `docs/superpowers/specs/2026-08-13-graywind-phase1-mvp-design.md` — old LEAN-based spec.
- `docs/superpowers/plans/2026-08-13-graywind-phase1-mvp.md` — old 10-task LEAN-based plan.

**Files committed on this branch:**
- `docs/superpowers/graywind-phase1-mvp-handoff.md` (`6d62609`) — the prior handoff. Its
  "What's next" (resume QuantConnect token chase, resume implementer agent
  `ae4d147e22aaed407`) is **obsolete** — do not follow it. Its background on *why* LEAN was
  abandoned is still accurate and worth reading once.

**Uncommitted working-tree changes (from the abandoned LEAN Task 1 attempt — partially
reusable, partially stale, see traps below):**
- `.gitignore` — modified, appended `data/`, `alpaca_data/`, `__pycache__/`, `*.pyc`,
  `.venv/`, `venv/`, `.env`, `backtests/` to the pre-existing `.worktrees/` line. Still
  mostly valid for the new hand-rolled approach (`alpaca_data/`, `.venv/`, `.env` all still
  apply); `backtests/` may still apply if the new backtester writes results there too —
  decide when the new plan is written.
- `requirements.txt` — untracked, currently `lean\nalpaca-py\npytest` — **stale**, `lean`
  must be dropped and `pandas`, `pandas-ta-classic`, `vaderSentiment`, `requests` added
  once the new plan's Task 1 is written.
- `.venv/` — created locally (gitignored, never tracked), has `lean`, `alpaca-py`, `pytest`
  installed. Reusable as-is for `alpaca-py`/`pytest`; will need the new packages added
  on top, `lean` itself is harmless left installed but unused.

**Scratch workspace / traps:**
- ⚠️ `.superpowers/sdd/2026-08-13-graywind-phase1-mvp/` (gitignored SDD ledger +
  `task-1-brief.md` + `task-1-report.md`) documents the **abandoned** LEAN/QuantConnect
  blocker chase. Real history, not a bug that it exists, but none of it describes future
  work anymore — a fresh session should not resume implementer agent `ae4d147e22aaed407`
  for anything, its Task 1 brief (LEAN scaffold) no longer matches the plan.
- ⚠️ The QuantConnect account (User Id `1786597952`, org `fc101acdea2b7db9704baad94f8bc8ec`)
  and whatever happened with its API-token reset are now **irrelevant** — the whole reason
  to chase that token (running `lean init`) doesn't apply to the new architecture. No need
  to check that email inbox on this account's behalf anymore.
- ⚠️ Docker Desktop, installed mid-way through the prior session, is **no longer needed**
  — the new architecture has no Docker dependency at all.

**Not mine — leave alone:** nothing pre-existing besides the docs/ files listed above.

## What has changed

This session (in the parent conversation, not yet reflected in any commit) did NOT touch
code. It was pure research + design, conducted in a **different worktree** (the Bullion
project's) that happened to also be resuming this Graywind context — all of the actual
findings below apply to the `graywind` repo regardless of which directory the
conversation ran in.

- **Confirmed, with QuantConnect's own docs and forum**: free-tier QuantConnect accounts
  have **zero** API/CLI access, by design, not a bug — "To use the CLI, you must be a
  member in an organization on a paid tier." This closes the "reset token, check email"
  path the prior handoff left open; even a valid token wouldn't have unblocked `lean init`
  on a free account.
- **Verified the open-source LEAN engine itself** (as opposed to `lean-cli`) ships default
  `config.json` with `job-user-id: "0"`, empty `api-access-token`, empty
  `job-organization-id` — meaning a raw `docker run` against the engine, bypassing
  `lean-cli` entirely, needs no QC account. Considered and **rejected** as too much
  hand-rolled Docker/data-format work for this project's size and the user's time budget,
  in favor of dropping LEAN outright.
- **Evaluated three free alternative backtesting frameworks, rejected all three**:
  - NautilusTrader — genuinely free/MIT, actively developed, but its Alpaca integration is
    an unshipped RFC (`nautechsystems/nautilus_trader#3374`, opened 2026-01-01). Maintainer
    said explicitly "not in the near term" (2026-01-06 comment). Two competing community
    forks exist, both incomplete as of the most recent activity (2026-05-08): one "not yet
    functional" as of April, the other "experimental... not a complete generic official
    adapter" as of May. **Verdict: don't build Phase 1 on this. Worth rechecking before any
    future Phase 2 planning** (Nautilus is the strongest long-term engine of the three, if
    the adapter ever ships).
  - zipline-reloaded — free, but backtest-only (no live/paper execution layer at all,
    the old live-trading extension is dead), needs its own data-bundle ingestion step,
    designed for daily cross-sectional research, not intraday single-symbol signals.
  - backtrader — free, but explicitly characterized as frozen/dead for new 2026 projects;
    its Alpaca link was always an unofficial, unmaintained third-party package.
  - **Common gap across all three**: none give free live/paper order execution — that's
    specifically what LEAN's paid tier was buying. This is why the final decision bypasses
    third-party frameworks entirely rather than swapping to another one.
- **Decision (confirmed with user)**: hand-roll the pipeline directly on `pandas` +
  `alpaca-py`, using Alpaca's own free market-data and paper-trading REST APIs for both the
  backtest leg and the live-fill leg. No third-party trading framework at all.
- **Researched and verified four "genuinely free, no blocking account gate" resources** to
  fold into the redesigned spec (user explicitly requested this — "any online free
  resources we can use to improve our algorithm must be included"):
  - `pandas-ta-classic` (github.com/xgboosted/pandas-ta-classic) — actively maintained
    fork of pandas-ta (the original has sustainability/donation-risk warnings on its own
    site); 250+ indicators, no TA-Lib dependency required.
  - Alpaca's News API (already included free with any Alpaca account, no new signup, 6+
    years of headlines) + VADER (local, free, lexicon-based, no API) for a rule-based
    sentiment gate — deliberately a threshold check, not a trained model, to stay
    consistent with the existing "no ML/RL model" non-goal.
  - FRED's `VIXCLS` daily-close series (free, instant API key — same integration pattern
    already proven working in the Bullion project) for a coarse daily VIX circuit breaker.
  - Finnhub's earnings-calendar endpoint (free tier, confirmed no credit card required, key
    issued immediately on email confirmation, 60 calls/min) for an earnings-date entry
    blackout. Confirmed first that **Alpaca's own Corporate Actions API does not cover
    earnings dates** (only dividends/mergers/spinoffs/splits) — Finnhub fills a real gap,
    it's not redundant with Alpaca.
- **User explicitly chose the fullest option** when asked to scope the free-resource
  addition (three options offered: recommended zero-new-account set / that set plus
  earnings-blackout / implementation-quality only) — picked "B: recommended set, plus
  earnings-date blackout," accepting the one new Finnhub account this requires.
- **One existing spec decision was revised, not silently changed**: the current spec's
  non-goal "no regime filter" is narrowed (not deleted) to permit exactly one coarse daily
  VIX threshold rule. Everything else in the non-goals list (no ML/RL, no multi-symbol
  portfolio optimization, no limit orders, no Kelly sizing) is untouched.
- **A full design was presented to the user in chat and not yet approved** — see "What's
  next" for the complete text. The user asked for this handoff instead of answering
  approve/revise, so the brainstorming flow's approval gate is still open.

## What has failed / risks / caveats

- **Nothing has technically failed.** The LEAN blocker was a genuine spec/plan gap, not
  implementer error (see the prior handoff), and this session's response to it (research →
  compare alternatives → redesign) is complete except for the final user sign-off.
- **UNVERIFIED / not yet done, in order of what blocks what:**
  1. The design below has not been approved by the user.
  2. Once approved, it has never been written to a spec file — do that next, following
     `superpowers:brainstorming`'s "Write design doc" step (path:
     `docs/superpowers/specs/<today's date>-graywind-phase1-handrolled-design.md`), then its
     self-review checklist (placeholder scan, internal consistency, scope check, ambiguity
     check), then get the user to review the written file before moving on.
  3. The old plan (`docs/superpowers/plans/2026-08-13-graywind-phase1-mvp.md`, 10 tasks) is
     entirely LEAN-shaped — every task from Task 1's `lean init`/`lean project-create`
     through Task 9's `lean live deploy` assumes the abandoned stack. It needs a full
     rewrite via `superpowers:writing-plans`, not a patch, once the new spec is approved
     and written. Do not try to salvage individual old-plan tasks piecemeal; the
     architecture changed too much (LEAN's `QCAlgorithm`/`OnData` hooks vs a plain Python
     loop; `lean backtest` vs a hand-rolled backtester; `lean live deploy` vs a scheduled
     script) for that to be safe.
  4. None of the four new free-resource integrations (pandas-ta-classic, Alpaca
     News+VADER, FRED VIX, Finnhub earnings) have been implemented or even scaffolded —
     everything about them so far is research and a design decision, not code.
- **Decision carried forward, overriding nothing but worth restating**: gates (VIX/
  sentiment/earnings) must fail closed — if a gate's own data source is unreachable, that
  gate should block the trade, not skip itself. This was a design decision made in
  conversation, not yet written into any spec file; make sure it survives into the actual
  spec doc when written.

## What's next (ordered)

1. **Re-present this design to the user and get an explicit approve/revise answer** before
   writing anything to disk (the brainstorming skill's hard gate). Full text of what was
   presented:

   > **Scope decisions (changed from current spec)**
   > - Framework: drop LEAN Engine/`lean-cli` entirely. Replaced with `pandas` +
   >   `pandas-ta-classic` for signal computation, `alpaca-py` for historical bars and live
   >   paper order execution. $0 cost, no account beyond what's already required.
   > - Non-goal revised: "no regime filter" narrowed to allow exactly one coarse rule-based
   >   VIX threshold gate — not a learned regime-detection system. All other non-goals
   >   (no ML/RL, no multi-symbol portfolio optimization, no limit orders, no Kelly sizing)
   >   unchanged.
   > - New free-resource additions, all verified free with no blocking account gate:
   >   `pandas-ta-classic` (signal math), Alpaca News API + VADER (sentiment gate, free,
   >   local), FRED `VIXCLS` (VIX circuit breaker, free, instant key), Finnhub earnings
   >   calendar (earnings blackout, free tier, no card, instant key).
   >
   > **Architecture — 6 components (was 5)**
   > 1. Data Ingestion — `fetch_alpaca_data.py` (kept, same shape) pulls 15-min AAPL/SPY
   >    bars from Alpaca into local CSVs, now feeding a pandas DataFrame directly instead
   >    of a LEAN `PythonData` reader.
   > 2. Strategy Engine — RSI + MA crossover via `pandas_ta_classic` on the DataFrame,
   >    same signal logic/thresholds as before.
   > 3. Signal Augmentation Gates (NEW) — three independent boolean gates a raw buy signal
   >    must pass: VIX gate (block if yesterday's FRED VIXCLS close exceeds a threshold),
   >    sentiment gate (block if VADER's compound score on recent Alpaca News headlines is
   >    below a negative threshold), earnings gate (block if Finnhub shows an earnings date
   >    within N days). All three are simple threshold rules, not trained models.
   > 4. Risk Management — same three components as today (PDT throttle, position sizing +
   >    stop/target, drawdown breaker), unchanged logic, called from a plain Python loop
   >    instead of `QCAlgorithm` hooks.
   > 5. Execution & Routing — `alpaca-py`'s `TradingClient` places market orders directly
   >    against Alpaca's paper endpoint, replacing LEAN's brokerage integration.
   > 6. Backtesting & Evaluation — a hand-rolled bar-by-bar backtest loop over the
   >    historical DataFrame (Sharpe/drawdown/win-rate computed manually), plus the same
   >    PDT-compliance assertion script, reading its own trade log instead of LEAN's
   >    results JSON.
   >
   > **Fail-closed rule for the new gates**: if VIX/sentiment/earnings data is unreachable
   > for a symbol, that gate defaults to block, not skip.
   >
   > **Live path**: a scheduled loop script (market hours only) fetches the latest bar +
   > gate data every 15 minutes, evaluates signal → gates → risk checks → order, same code
   > paths as backtest. Replaces `lean live deploy`.
   >
   > **Testing**: pure-Python unit tests for PDT/position-sizing/drawdown (unchanged) plus
   > new pure-Python unit tests for the three gates (fixture data, no live API calls in
   > tests). Integration validation is a real end-to-end backtest run against real fetched
   > data, replacing the `lean backtest` requirement.
   >
   > **Environment setup**: Python 3.11+, `pandas`, `pandas-ta-classic`, `alpaca-py`,
   > `vaderSentiment`, `requests`, `pytest`. No Docker, no `lean-cli`. Accounts needed:
   > Alpaca paper (already required), FRED API key (free, instant), Finnhub API key (free,
   > instant, no card).

2. On approval (with any requested changes folded in), write the spec to
   `docs/superpowers/specs/<today's date>-graywind-phase1-handrolled-design.md`, run the
   self-review checklist from `superpowers:brainstorming`, then ask the user to review the
   written file.
3. Once the spec is approved, invoke `superpowers:writing-plans` to fully rewrite the
   10-task plan — every task changes shape (see "What has failed" item 3 above). Do not
   reuse the old plan's task numbering/content as a starting point beyond high-level shape
   (env setup → risk modules → data fetch → strategy engine → gates → wire risk → backtest
   → live config → burn-in decision).
4. Once the new plan exists, resume via `superpowers:subagent-driven-development` as
   before. Task 1 will look substantially different from the old one (no `lean init`/
   `lean project-create`; instead: `pip install` the new package set, scaffold a plain
   Python package structure).
5. Update `requirements.txt` and `.gitignore` per the new plan's Task 1 rather than
   patching the current stale/partial versions by hand before the plan exists.

## Verification idioms used in this project (for the resuming session)

- The ledger (`.superpowers/sdd/2026-08-13-graywind-phase1-mvp/progress.md`) describes only
  the now-abandoned LEAN chase — useful for history, not for verifying anything about the
  new direction. A fresh ledger entry should be added once the new plan starts executing.
- This project's standing discipline (inherited from the Bullion project this workflow
  comes from, and reinforced by the LEAN detour itself): **verify claims independently
  before acting on them** — this session's whole pivot came from actually reading
  QuantConnect's docs/forum and the raw `nautilus_trader` GitHub issue/comments via
  `curl`+the GitHub API rather than trusting a summary, and from actually confirming
  Finnhub's "no credit card" claim and Alpaca's Corporate Actions API scope via search
  before relying on either. Apply the same standard to the four new free-resource
  integrations before wiring them into the plan — confirm each API's real response shape
  and rate limits against a live test call, not just documentation prose.

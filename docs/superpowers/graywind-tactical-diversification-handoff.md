# Graywind Tactical Diversification + Capital Scale-Up — Session Handoff

**Written:** 2026-09-03 · **For:** whoever resumes Graywind next — this session did no
trading-code implementation, only decisions + doc updates + a dashboard-content draft. It
closes punch-list item 1 from the (now-archived) `graywind-critical-review-handoff.md` at
the decision level; implementation is deliberately deferred.

## Goal

Two decisions needed writing down before they drift, plus one safe UI addition drafted
ready to build:

1. **Which symbols diversify the tactical universe beyond AAPL/SERV** (real-capital audit
   item #4, the last of 9 still open) — now decided, not yet implemented in
   `tier_config.py`/`sector_config.py`. Still gated behind burn-in, same as before.
2. **The real-capital scale-up ceiling** — owner decided $1,000 is what the existing $500
   first tranche is allowed to grow into *after it proves itself*, not a second tranche to
   jump to independently. Written into
   `docs/superpowers/graywind-real-capital-done-criteria.md` this session (uncommitted).
3. **A dashboard symbol-reference table** — the owner wants a standing UI panel in
   `index.html` listing every candidate symbol with tier/sector/what-to-watch, so they can
   read it themselves each time they check the site. Content is fully drafted below. This
   piece has **no burn-in dependency and touches no trading logic** — safe to build now,
   independently of item 1's gate.

Authorities:
- No spec exists for item 1 — small enough to go straight from conversation to decision,
  same precedent as `docs/superpowers/graywind-tier1-pool-credit-timing-fix-handoff.md`.
- `docs/superpowers/graywind-real-capital-done-criteria.md` — owner-decisions ledger,
  updated this session (see "On scaling beyond $500" and the "Owner decisions" table).
- `docs/superpowers/specs/2026-08-26-graywind-dual-account-tier-symbols-design.md` — the
  guardrail mechanism (`validate_symbol_addition`, `TIER_GUARDRAILS`,
  `MAX_SYMBOLS_PER_SECTOR=3`) and the original AAPL/SERV starter-pick precedent this
  decision extends.
- `docs/superpowers/archive/graywind-critical-review-handoff.md` (moved there this
  session, see below) — punch-list items 2, 4, 5, 6, 7 are still open and **unrelated to
  this session**; read it if picking those up.

## How to resume (do this first)

1. **Confirm base — read this before trusting anything about `main`:** run
   `git log origin/main..main --oneline`. If it still shows `3000363` ("Fix tier-1
   rebalance pool-credit timing..."), that commit is **local-only, never pushed**, despite
   `graywind-tier1-pool-credit-timing-fix-handoff.md` calling it "SHIPPED and merged to
   main." The live GitHub Actions cron trades off `origin/main` — until this is pushed,
   production is still running the old optimistic-credit code the fix replaced. This
   session found it but did not push it (out of scope, and pushing needs the owner's
   explicit go-ahead per this project's norms). **Confirm with the owner before pushing.**
2. Run `git status` — expect exactly the state in "Current state" below.
3. Read this handoff in full — no spec/ledger exists for item 1 beyond this doc.
4. **Immediate next action:** build the dashboard symbol-reference table (What's next #1)
   — it's the only piece of this handoff that's actually buildable right now. Everything
   else either needs burn-in to clear or needs the owner's confirmation first.

## Current state (active files)

**Branch:** `main`, 1 commit ahead of `origin/main` (`3000363`, unpushed — see trap
above), 2 commits behind (`cc1b507`, `125629b` — routine live-cron state/dashboard-data
updates, harmless, will resolve on next pull).

**Files changed this session (uncommitted):**
- `docs/superpowers/graywind-real-capital-done-criteria.md` — added the $500→$1,000
  scale-up-ceiling decision to the "Owner decisions" table and a new "On scaling beyond
  $500" subsection; updated the closing "does not authorize" bullet to match.
- `docs/superpowers/archive/graywind-critical-review-handoff.md` — moved here from
  `docs/superpowers/` (was untracked, dated 2026-09-01; per handoff-doc convention only
  the 2 most recent handoffs stay in the main directory — this one plus
  `graywind-tier1-pool-credit-timing-fix-handoff.md` (2026-09-03) are now the 2 most
  recent, so the critical-review one moved to `archive/`). **Not superseded** — items
  2/4/5/6/7 of its punch list are still open, only item 1 (this handoff) is closed.

**Files this session did NOT touch (what the actual implementation later touches):**
- `graywind_strategy/tier_config.py` — still `SYMBOL_TIER = {"AAPL": 2, "SERV": 3}`,
  `TIER1_SYMBOL_WEIGHTS = {"SPY": 1.0}`. The promotion in "What's next" #2 edits this.
- `graywind_strategy/sector_config.py` — still only `tech`/`energy`/`health`/`robotics`
  tags exist. No `nuclear` or `quantum` tag yet.
- `live_loop.py` `WATCHLIST` — still `["AAPL", "SERV"]`.
- `tests/test_tier_config.py:11-12` — asserts `SYMBOL_TIER` by exact equality, **will
  fail the instant any symbol is promoted**; update in the same change, per the
  pre-existing note in `graywind-real-capital-audit-execution-handoff.md`.
- `index.html` — dashboard. The new symbol-reference table (What's next #1) is additive;
  it does not touch the existing per-account sections (`buildPositions`, `buildTradeLog`,
  `buildPerformanceReport`, all in this file).

**Scratch workspace / traps:**
- ⚠️ **Unpushed commit, see "How to resume" step 1** — the single most important trap in
  this handoff. Don't assume `main` == `origin/main` for this repo going forward without
  checking; the prior handoff's "shipped and merged" language was locally true but
  operationally false.
- ⚠️ `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` still carries its
  uncommitted working-tree modification, **unresolved across three consecutive handoffs
  now** (critical-review 9/1 → tier1-pool-credit-timing-fix 9/3 → this one). Nobody has
  actioned "commit if intentional, else revert to HEAD."
- ⚠️ `docs/superpowers/graywind-real-capital-done-criteria.md`'s edit this session is
  **uncommitted** — deliberate, this session was decision/documentation only per the
  owner's explicit "write handoff, we will implement."

**Not mine — leave alone:** `.DS_Store`, `.claude/`, `scripts/fetch_serv_bars.py`,
pre-existing `docs/superpowers/archive/*` entries — untracked, not touched this session.

## What has changed

- **Decided, not implemented:** tactical-universe diversification — full symbol/sector/
  tier table below, plus the exact `tier_config.py`/`sector_config.py` diff it produces.
- **Decided, written to done-criteria doc (uncommitted):** real-capital ceiling is
  $1,000, reached by scaling the *existing* $500 tranche up after it meets the
  still-deferred Phase-3 advance bar — not an independently-sized second tranche.
- **Drafted, not implemented:** dashboard symbol-reference table content (below), ready
  to drop into `index.html` as a new static section.
- **Flagged, not scoped:** deeper Bullion↔Graywind integration beyond the existing
  `macro_gate.py` dependency — see "What has failed / risks" below.

### The diversification decision

Guardrail bands (`tier_config.py` `TIER_GUARDRAILS`, unchanged): tier 2 needs $2B+ market
cap / 500k+ avg daily volume; tier 3 needs $300M+ / 100k+. `MAX_SYMBOLS_PER_SECTOR = 3`.

Market-cap figures below are **live web-search snapshots taken 2026-09-03** (sources:
stockanalysis.com via search), **not** run through the actual `validate_symbol_addition()`
guardrail (that needs live Finnhub + Alpaca calls). Several of these names are volatile
enough that the number could differ by the time someone actually runs the guardrail — see
"What has failed / risks" below. Treat tier placement as provisional until re-verified.

| Symbol | Sector | Proposed tier | Snapshot market cap (2026-09-03) | Why this tier |
|---|---|---|---|---|
| AAPL | tech | 2 (existing) | multi-trillion | already live |
| NVDA | tech | 2 | multi-trillion | clears $2B floor trivially |
| MSFT | tech | 2 | multi-trillion | clears $2B floor trivially; fills tech's 3/3 sector cap |
| XOM | energy | 2 (existing) | large-cap | already live |
| CVX | energy | 2 | large-cap | clears floor; correlated with XOM (both crude-price beta) |
| JNJ | health | 2 | large-cap | clears floor |
| UNH | health | 2 | large-cap | clears floor |
| CEG | nuclear *(new tag)* | 2 | $83B–$118B (wide range this year) | clears floor easily |
| CCJ | nuclear *(new tag)* | 2 | $36B–$51B (wide range this year) | clears floor easily |
| RGTI | quantum *(new tag)* | 2 | ~$5.2B | clears $2B floor |
| SERV | robotics | 3 (existing) | ~$423M (as of original 8/26 pick) | already live |
| QUBT | quantum *(new tag)* | 3 | ~$1.8B, ranged $1.6B–$2.6B all year | **under** the $2B tier-2 floor at snapshot time — lands in tier 3 by the numbers, not by "spirit" |

**Sector cap check:** tech 3/3 (full), energy 2/3, health 2/3, nuclear 2/3, quantum 2/3
(1 in tier 2, 1 in tier 3 — sector caps are per-tier, not global, so this is fine), robotics
1/3. No conflicts.

**Design call made this session, not yet implemented:** `nuclear` is tagged as its **own**
sector, separate from `energy` (oil/gas) — same precedent as SERV getting `robotics`
instead of being folded into `tech`. Nuclear-utility economics (regulated rates, AI-datacenter
power-purchase deals) don't move with crude oil the way XOM/CVX do; tagging them together
would either falsely cap total energy-adjacent exposure at 3, or falsely treat two
uncorrelated bets as if they satisfied the sector-cap's diversification intent. The owner
explicitly wants heavy energy-adjacent exposure, which is what motivated this split.

Resulting diff (**not yet applied** — apply only after burn-in clears, per What's next #2):

```python
# tier_config.py
SYMBOL_TIER = {
    "AAPL": 2, "NVDA": 2, "MSFT": 2,
    "XOM": 2, "CVX": 2,
    "JNJ": 2, "UNH": 2,
    "CEG": 2, "CCJ": 2,
    "RGTI": 2,
    "SERV": 3,
    "QUBT": 3,
}
# TIER1_SYMBOL_WEIGHTS unchanged: {"SPY": 1.0}

# sector_config.py — SYMBOL_SECTOR additions
SYMBOL_SECTOR.update({
    "RGTI": "quantum", "QUBT": "quantum",
    "CEG": "nuclear", "CCJ": "nuclear",
})
```

### Dashboard symbol-reference table — content, ready to implement

Owner's ask: a standing table in the live dashboard (not buried in a doc) so they can
read what each candidate symbol is and what to watch, every time they check the site.
This is reference copy, not live data — no CSV/JSON fetch needed.

| Symbol | Sector | Tier | What it is | What to watch |
|---|---|---|---|---|
| AAPL | tech | 2 | iPhone/hardware ecosystem + services | Single-product concentration (iPhone still >50% of revenue); China exposure cuts both ways (manufacturing + sales market) |
| NVDA | tech | 2 | AI/datacenter GPU supplier, dominant position | Priced for perfection — any AI-capex slowdown from hyperscaler customers hits it disproportionately; export-control risk on China sales |
| MSFT | tech | 2 | Cloud (Azure) + enterprise software + OpenAI stake | Azure capex is a bet on AI demand materializing; EU/US antitrust scrutiny |
| XOM | energy | 2 | Integrated oil major | Tracks crude price directly — no oil-specific gate exists in Graywind yet, so this trades blind to OPEC+ decisions |
| CVX | energy | 2 | Integrated oil major | Highly correlated with XOM — holding both isn't much more diversification than one twice |
| JNJ | health | 2 | Diversified pharma + medtech | Litigation overhang (talc lawsuits recurring headline risk); patent-cliff risk on individual drugs |
| UNH | health | 2 | Largest US health insurer | Sensitive to US healthcare policy/regulation headlines (Medicare Advantage rates, DOJ scrutiny); real earnings-day volatility |
| CEG | nuclear | 2 | Largest US nuclear power generator | Increasingly an AI-capex proxy via datacenter power-purchase-agreement headlines (Microsoft, Meta); regulatory approval risk on those deals |
| CCJ | nuclear | 2 | Largest western uranium miner/fuel supplier | Tracks uranium spot price, not electricity price — different driver than CEG; geopolitical supply risk (Kazakhstan/Russia) |
| RGTI | quantum | 2 | Rigetti Computing, superconducting-qubit hardware | Narrative/hype stock — moves on quantum-computing headlines unrelated to its own fundamentals; heavy retail-trader gap risk |
| SERV | robotics | 3 | Serve Robotics, AI sidewalk delivery | Small-cap, single-customer-concentrated (Uber Eats), pre-profitability — the deliberate "gamble" slot |
| QUBT | quantum | 3 | Quantum Computing Inc., photonic/quantum-inspired | Extreme volatility (52-week range $6.18–$25.84); dilution risk — small quantum names frequently raise capital via share offerings |
| SPY | — (tier 1) | 1 | S&P 500 index ETF, buy-and-hold core | 70% of every account's capital; deliberately ungated (two tested VIX/macro exposure-scaling variants both washed on Calmar ratio, see `graywind-edge-thesis.md`) |

**Implementation sketch (not built this session):** in `index.html`, add a new build
function alongside `buildPositions`/`buildTradeLog`/`buildPerformanceReport` (all in this
file, `buildPositions` starts at line 393 as of this session's read). Unlike those, this
table is **static content, not per-account live data** — same universe applies to both
the $100k and $2k dashboards, so render it once (e.g. above `#app`'s `accounts-grid`, or
as its own top-level `<section>`), not inside `renderAccount()`. No new CSV/JSON source
needed; the table content above can be inlined as a JS array of objects.

## What has failed / risks / caveats

- **Nothing has failed.** No trading code was touched this session.
- **UNVERIFIED:** every market-cap figure above is a 2026-09-03 web-search snapshot, not
  a live `validate_symbol_addition()` run. CEG alone ranged $83B–$118B within the same
  year per the sources checked — re-verify all figures, especially RGTI/QUBT/CEG, at the
  moment of actual promotion (What's next #2), not from this table.
- **QUBT's tier placement is the most fragile call here.** It sits right at the tier-2/3
  boundary (~$1.8B vs. the $2B floor) and has ranged $1.6B–$2.6B this year — a routine
  price move could flip which tier it numerically qualifies for by the time burn-in
  clears. Re-run the guardrail check fresh; don't trust the table above at promotion time.
- **The `nuclear`-as-separate-sector call is a design decision, not a guardrail
  requirement** — `MAX_SYMBOLS_PER_SECTOR` doesn't care what a sector is named, only how
  many symbols share a tag. If a future session tags CEG/CCJ as `energy` instead, the
  sector-cap math changes (energy would be 4/3 in tier 2, over cap) and one of
  XOM/CVX/CEG/CCJ would need to drop or move tiers. Don't silently relabel this.
- **Bullion↔Graywind integration is flagged, not scoped.** What's concretely already
  true: `graywind_strategy/gates/macro_gate.py` already fetches
  `BULLION_DATA_URL = "https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/data.json"`
  for macro stress signals (NFCI, HY OAS, yield curve slope, VIX) — this is the existing
  sibling-project precedent the owner referenced. What's **not** decided: whether/how to
  extend this to sector-specific signals for the new nuclear/quantum/energy names (e.g.
  pulling Bullion's news/indices data as an input to a future sector gate). This needs
  its own `superpowers:brainstorming` session — nothing was designed here, and inventing
  an integration ad hoc risks building the wrong shape (same reasoning the dual-account
  spec used to park the "stock advisor pivot" idea rather than fold it in ad hoc).

## What's next (ordered)

1. **Build the dashboard symbol-reference table now** — no gate, no dependency on
   anything else in this handoff. Use the content table above verbatim; follow the
   implementation sketch in "What has changed."
2. **When burn-in clears** (2026-09-14 earliest, or the 20th real trade, whichever is
   later — tracked via the weekly Monday check-in already scheduled in
   `graywind-real-capital-done-criteria.md`): re-verify every market cap/volume figure
   live via `validate_symbol_addition()`, in this order — energy (XOM/CVX already live,
   no new work) → nuclear (CEG, CCJ) → health (JNJ, UNH) → quantum (RGTI, then QUBT last,
   since its tier placement is the most likely to have moved). Tech is already at its 3/3
   cap, so NVDA/MSFT need no ordering decision, just confirmation they still clear the
   floor. Then hand-edit `SYMBOL_TIER`/`SYMBOL_SECTOR`, update the exact-equality
   assertion in `test_tier_config.py`, and add every new symbol to `WATCHLIST` in
   `live_loop.py`.
3. **Before step 2, resolve the unpushed-commit trap** — confirm with the owner whether
   `3000363` should be pushed to `origin/main`. It's unrelated to this session's scope but
   sits directly in the way: a fresh checkout by the promotion work will look like it
   already has the fix when the live pipeline doesn't.
4. **Whenever convenient, separately:** resolve
   `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md`'s stray working-tree
   diff — unresolved for three sessions running now.
5. **When the owner wants to pursue it:** scope Bullion↔Graywind sector-signal
   integration via `superpowers:brainstorming`. Not blocking any of the above.
6. **Commit this session's done-criteria doc edit** — currently uncommitted, either on
   its own or folded into whichever future commit ships the symbol promotion.
7. **Unrelated, still open from the archived critical-review handoff** (punch-list items
   2/4/5/6/7): burn-in kill-check date is now written (done-criteria doc), but news-debate
   LLM funding decision, OpenRouter re-probe, small-account boundary exercise, and
   extending the alarm pattern beyond `macro_gate` are all still open. See
   `docs/superpowers/archive/graywind-critical-review-handoff.md` for the full list.

## Verification idioms used in this project (for the resuming session)

- Test suite: `.venv/bin/python -m pytest tests/ -q` — re-run rather than trusting any
  cached count, per this project's repeated experience of the number drifting between
  sessions.
- **New this session — check for unpushed local commits before trusting any "shipped"
  claim:** `git log origin/main..main --oneline`. A non-empty result means `main` has
  work `origin/main` (and therefore the live cron) does not.
- Live state: always `git show origin/main:dashboard-data/trade_log.csv` (and
  `equity_curve.csv`), never the local checkout — it goes stale within hours.
- Burn-in status: weekly Monday check-in already scripted in
  `docs/superpowers/graywind-real-capital-done-criteria.md`.
- Checking whether a handoff/doc file is tracked before archiving or trusting it:
  `git ls-files --error-unmatch <path>` (exits non-zero if untracked).

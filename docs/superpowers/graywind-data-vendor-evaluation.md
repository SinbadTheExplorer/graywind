# Graywind — Data-Vendor Ceiling Evaluation

**Date:** 2026-08-31

**Why this doc exists:** audit item #8
(`graywind-real-capital-readiness-handoff.md`). Graywind's data inputs are free/unofficial
tiers that are fine for paper trading but carry no SLA. The audit flagged this as the same
*shape* of failure that killed Reign (camera/sensor ceiling) and the local-LLM project
(8GB RAM ceiling) — a hard external limit discovered mid-build rather than scoped up
front. This evaluates it **before** real capital, per
`graywind-real-capital-done-criteria.md`, whose vendor abort-gate this closes.

**Pricing caveat, read first:** the figures below are approximate ranges and orders of
magnitude, not quotes. Vendor pricing changes frequently. **Verify current pricing against
each vendor's own page before committing spend** — nothing here should be treated as a
current price.

---

## The actual dependency graph

Traced from the code, not assumed. This matters because two of the five inputs are not
what the audit's one-line summary implied.

| Input | Source | Where | Called |
|---|---|---|---|
| VIX gate | **FRED** (`api.stlouisfed.org`) | `gates/vix_gate.py` | Per symbol, per cycle |
| Sentiment gate | **Alpaca News API** (`alpaca-py` NewsClient) + local VADER | `gates/sentiment_gate.py` | Per symbol, per cycle |
| Earnings gate | **Finnhub free** (`/calendar/earnings`) | `gates/earnings_gate.py` | Per symbol, per cycle |
| Macro gate | **The owner's own Bullion GitHub Pages `data.json`** | `gates/macro_gate.py` | Per symbol, per cycle |
| Analyst consensus | **yfinance** (unofficial Yahoo scraper) | `gates/analyst_consensus.py` | Only on buy decisions, cached in `state/analyst_consensus.csv` |
| Bars + execution | **Alpaca** | `fetch_alpaca_data.py`, `live_loop.py` | Per symbol, per cycle |
| Symbol validation | **Finnhub free** (`/stock/profile2`) | `tier_config.py` | Only when adding a symbol |

**Two corrections to the audit's framing:**

1. **The VIX gate does not use yfinance.** It uses FRED. `yfinance` is confined to
   analyst consensus, which is called only on buy decisions and is cached — a far smaller
   exposure than "yfinance underpins the gates" implies.
2. **The macro gate is not a vendor dependency at all — it is a self-dependency.** It
   fetches `sinbadtheexplorer.github.io/claudekit/bullion-live-map/data.json`, the
   output of the owner's *own* Bullion project cron. See the dedicated section below;
   this is the most under-examined input in the system.

**Load:** cron is `*/15 13-20 * * 1-5` — every 15 min, ~8h, weekdays ≈ **32 cycles/day**,
doubled to ~64 by the small-account job. At 2 live symbols that is ~128 calls/day each to
FRED, Finnhub, Alpaca News, and the Bullion JSON. Well inside every free tier **today** —
the risk is not current volume, it is what happens when the roster grows.

---

## Per-input failure modes

### 1. The Bullion `data.json` self-dependency — **ranked #1 risk**

The macro gate depends on a GitHub Pages artifact produced by a *different personal
project's* scheduled workflow. No vendor SLA discussion would ever surface this.

**What is already handled — and handled well.** `macro_gate.py` defines
`DAILY_STALENESS_CEILING_DAYS = 7` and `WEEKLY_STALENESS_CEILING_DAYS = 14`, and
`_most_recent_value_before` raises `MacroDataUnavailable` when the newest record for a
field is older than its ceiling. **Graywind therefore cannot trade on frozen macro data.**
Stale-data-trading, the obvious worry, is already designed out.

**What is NOT handled — the actual residual risk.** The gate **fails closed**:
`evaluate_macro_gate` catches `MacroDataUnavailable` and returns
`GateResult(passed=False, detail="MacroDataUnavailable")`, which makes `decide_trade`
return `blocked / macro_gate` (`pipeline.py:186-189`). So if Bullion's cron dies — an
unset secret expanding to `""`, a repo rename, Pages disabled, or the hardcoded URL at
`macro_gate.py:30` going 404 — then **8 days later Graywind silently stops opening any new
position, indefinitely, on every symbol.**

The failure is quiet in the worst way: in `decision_log.csv`, a dead upstream project and
a genuine risk-off macro reading both appear as `blocked / macro_gate`. Nothing alerts.
The system looks healthy — cron green, no `pipeline-alarm` issue, equity flat — while
having actually ceased trading. During burn-in this would also stall trade accumulation
against the 20-trade floor, and the cause would not be obvious.

**Fix, in order of value:**
1. **Alert on sustained `MacroDataUnavailable`.** The signal already exists — it is
   recorded in the `GateResult.detail` — and this repo already has a `pipeline-alarm`
   GitHub-issue mechanism for cron failures. Wiring "N consecutive cycles blocked with
   `MacroDataUnavailable`" into that alarm is the highest-value change here and costs
   nothing. Distinguishing "the macro gate said no" from "the macro gate could not answer"
   is the whole point.
2. **Consider pointing the macro gate directly at FRED.** VIX, NFCI, HY OAS, and the
   10y/2y series are all FRED series, and FRED is already a Graywind dependency — free,
   authoritative, government-run. The Bullion hop adds a failure mode without adding data.
   Note also that Bullion's own `data.json` sources some fields from Yahoo, so the current
   design inherits a yfinance-class dependency indirectly.

### 2. yfinance — highest *vendor* risk, but small blast radius

- **Unofficial.** It scrapes endpoints Yahoo does not document or guarantee, and it
  breaks historically when Yahoo changes response shape or adds challenges. Fixes arrive
  on the library's schedule, not yours.
- **Aggressive, opaque rate limiting**, sometimes IP-based — and GitHub Actions runners
  use shared egress IPs, so throttling can be caused by unrelated tenants.
- **Terms-of-service risk** for automated access, which is a different posture once real
  money is involved.
- **Pinned at `1.6.0`**, so a Yahoo-side change breaks it with no automatic recovery.

**Mitigating:** it only affects a *position-size multiplier* on buy decisions, is cached,
and a failure degrades sizing rather than blocking or mis-firing trades. **Blast radius is
small — do not over-prioritize this over item #1 above.**

### 3. Finnhub free tier — the one that breaks first *on growth*

- **~60 calls/min** on the free tier (this codebase already notes the limit in
  `backtester.py`'s comment about multi-week backtests).
- Live load is trivial today, but **`validate_symbol_addition` and any real-data backtest
  are the burst consumers.** The diversification work will hit this well before live
  trading does.
- Free-tier earnings-calendar coverage is thinner and less timely than paid, which matters
  for a *blackout* gate — a missed earnings date means trading into an event the gate
  exists to avoid.

### 4. FRED — lowest risk

Government-run, free, documented, stable, generous limits. Requires an API key and has no
formal SLA, but is the least likely input to fail. **No action needed.**

### 5. Alpaca — lowest *data* risk, highest *concentration* risk

Bars, news, and execution all come from one provider. Free market data is typically IEX
feed rather than full-market SIP consolidated tape, which means thinner quotes and
possibly less representative fills. This matters more for entry/exit price realism than
for signal generation. But note the structural point: **an Alpaca outage does not degrade
Graywind, it stops it entirely** — data and execution fail together.

---

## Ranked: what breaks first

1. **Bullion `data.json` stops updating** — most likely, and it does not corrupt trading,
   it *silently halts* it (fail-closed) with no alert distinguishing it from a real
   risk-off call.
2. **Finnhub free-tier limits** — the first *vendor* wall, hit by diversification and
   backtesting, not by live cycles.
3. **yfinance breaks on a Yahoo change** — likely eventually; small blast radius.
4. **Alpaca free-data quality shows up in fills** — gradual, only visible with real money.
5. **FRED** — unlikely.

---

## Paid options (verify all figures before spending)

| Need | Option | Approx. cost | Replaces |
|---|---|---|---|
| Market data | **Alpaca paid market data** (full SIP tape) | roughly $10–100/mo depending on tier | Better fills/quotes; consolidates on the existing broker, no new integration |
| Fundamentals + earnings | **Finnhub paid** | roughly $50+/mo | Finnhub free limits and thin earnings coverage |
| Broad market/fundamentals | **Polygon.io** | roughly $30–200/mo by tier | Could replace yfinance *and* some Finnhub use |
| Macro | **FRED** | free | Nothing — already the right tool |

**Consolidating on Alpaca is the most attractive direction** because it is already the
broker, already authenticated, and already integrated — it adds no new failure surface.

---

## Recommended migration order

Deliberately ordered cheapest-and-highest-value first. **Steps 1–2 cost nothing and should
happen before any spending at all.**

1. ~~**Alert on sustained `MacroDataUnavailable`.**~~ **DONE 2026-08-31.**
   `scripts/check_macro_health.py` reads `decision_log.csv` and raises a GitHub issue
   labelled `macro-alarm` after 8 consecutive cycles (~2h) with no macro answer, and
   closes it on recovery. Two constraints shaped it: the check must **not** fail the job
   (`live-cycle-small` declares `needs: live-cycle` and would be skipped), and it needs
   its **own** label (the existing "Close the alarm issue on success" step closes every
   open `pipeline-alarm` issue, which would auto-clear this one every green cycle).
   Required a companion fix: `decision_log.csv` previously wrote `""` for an unavailable
   macro reading, indistinguishable from the gate never being reached — `live_loop.py`
   now emits an `unavailable` sentinel, mirroring the `_fmt_earnings_value` precedent.
2. **Point the macro gate directly at FRED.** Free. Removes the self-dependency, and the
   indirect Yahoo dependency inside it, without losing any data.
3. **Do nothing about yfinance yet.** Cached, buy-path only, degrades gracefully. Revisit
   only if it actually breaks.
4. **Re-evaluate Finnhub when diversifying the universe** — that work, not live trading,
   is what hits the limit. Paying earlier buys nothing.
5. **Consider Alpaca paid market data only once real capital is deployed and fills can be
   compared against expectations.** Before that, there is no evidence the free feed is
   costing anything.

**Conclusion for the abort gate:** there is **no hard vendor ceiling that blocks the $500
tranche.** Unlike Reign's camera FOV or the local-LLM RAM limit, every constraint here is
soft (rate limits, data quality) and every one has a cheap or free mitigation. The genuine
finding is not a vendor at all — it is the undetected-staleness risk in the self-hosted
macro dependency, which is fixable for free and should be fixed before real capital.

## Related

- `docs/superpowers/graywind-real-capital-done-criteria.md` — the abort gate this closes.
- `docs/superpowers/graywind-real-capital-readiness-handoff.md` — the audit list.

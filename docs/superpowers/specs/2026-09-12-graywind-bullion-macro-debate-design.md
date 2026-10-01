# Graywind × Bullion Macro-Event Debate — Design Spec

**Written:** 2026-09-12

## Goal

Add a second, independent shadow-mode LLM signal — separate from the existing per-symbol
`news_debate.py` — that reads Bullion's market-wide news feed (Fed policy, geopolitics,
macro headlines; not per-symbol news) and logs a small set of probability-weighted event
readings once per trading cycle: "what might happen, how likely, and what it implies."
Like `news_debate.py`, this **never gates a trade** — it only accumulates history for a
human to review later. VADER and the existing `macro_gate.py` breach-count gate are
unaffected and unchanged.

This is not a new capability that needs training or a new model: DeepSeek (already wired
into this repo for `news_debate.py`, already paid for at ~$2-3/month for that feature) can
read text and produce a calibrated probability estimate directly, given the right prompt
and a forced-schema tool call. No fine-tuning, no new provider, no new secret.

## Why a second module, not an extension of `news_debate.py`

- `news_debate.py` is per-symbol (one bull/bear/judge debate per WATCHLIST symbol per
  cycle, keyed on that symbol's own headlines) and its `debate_score`/`vader_score` schema
  is the fixed input to the already-written
  `docs/superpowers/graywind-news-debate-promotion-bar.md`. Changing that schema to fit a
  different (macro, multi-event, probability-shaped) output would break the promotion
  bar's binding column contract for a feature that hasn't even started collecting rows yet.
- Bullion's news feed (`news.json`) is market-wide, not symbol-specific — it has no natural
  per-symbol join key. A single call once per cycle (not once per symbol) is both the
  cheaper and the structurally correct shape.
- Keeping the two modules separate mirrors this repo's existing pattern of one gate file
  per concern (`macro_gate.py` vs `sentiment_gate.py` vs `news_debate.py`) rather than
  merging unrelated signals into one file.

## Why shadow mode, not a gate

Same reasoning as `news_debate.py`'s spec
(`docs/superpowers/specs/2026-08-25-graywind-news-debate-shadow-mode-design.md`): no
principled way to calibrate a probability-driven signal into a real gate threshold without
first watching it against real, not-yet-happened outcomes. A promotion bar (mirroring
`graywind-news-debate-promotion-bar.md`) is explicitly **deferred** — see "Deferred, not
forgotten" below — writing one now, before a single row has been logged, would be
inventing criteria with no data to sanity-check them against.

## Components

### 1. `graywind_strategy/gates/macro_debate.py` (new module)

- `MacroNewsUnavailable(Exception)` — raised on any fetch/parse/staleness failure. Named
  and shaped like `macro_gate.py`'s `MacroDataUnavailable`, but note the caller's
  obligation differs: `macro_gate.py`'s exception must fail the trade **closed**
  (it's a real gate); this one must fail **open** (shadow-mode only, per `news_debate.py`'s
  established error-handling convention) — the exception type is named separately, not
  reused, specifically so no future reader can copy-paste a `except MacroDataUnavailable`
  handler expecting closed-fail semantics onto this open-fail signal.
- `BULLION_NEWS_URL = "https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/news.json"`
  — confirmed live 2026-09-12 (`curl` returned 200 with a `generated_at`/`headlines` JSON
  envelope, sibling to `macro_gate.py`'s `BULLION_DATA_URL`).
- `STALENESS_CEILING_HOURS = 48` — matches `fetch_bullion_news.py`'s own `MAX_AGE_HOURS`
  filtering window on the producing side; a `generated_at` older than this raises
  `MacroNewsUnavailable` rather than silently debating stale headlines as if fresh.
  **Caveat found during this spec's research:** the live feed's `generated_at` was
  `2026-09-05` when checked on `2026-09-12` — 7 days stale, past this ceiling. Bullion's
  news cron is not running reliably right now. This module will raise on essentially every
  call until that's fixed on the Bullion side — expected and correct behavior (fail open,
  loud stderr print, no logged row), not a bug in this module. Flagged here so it isn't
  mistaken for a broken implementation when shadow rows fail to appear at first.
- `fetch_bullion_headlines(session=requests) -> list[dict]` — fetches `BULLION_NEWS_URL`,
  raises `MacroNewsUnavailable` on request failure, non-200, malformed JSON, missing
  `generated_at`/`headlines` keys, or staleness beyond the ceiling. Returns the raw
  `headlines` list (each item has `headline`, `category`, `sentiment`, `published`, `link`,
  `image` per `fetch_bullion_news.py`'s `build_news_envelope`).
- `MacroEvent` dataclass: `event: str`, `probability: float` (`0.0..1.0`),
  `implication: str`.
- `evaluate_macro_events(llm_client, headlines) -> list[MacroEvent]` — **one** DeepSeek
  call (not three, unlike `news_debate.py`'s bull/bear/judge — there is no opposing-side
  structure to a macro-event read, so one forced tool call is the right shape and keeps
  this feature to roughly 1 call/cycle instead of `news_debate.py`'s 3-calls/symbol/cycle).
  Forces a single tool choice, `submit_macro_events`, returning `1..5` events, each with
  `event`/`probability`/`implication`, `additionalProperties: false` throughout — same
  forced-structured-output discipline as `news_debate.py::_tool_call`, including the same
  `extra_body={"thinking": {"type": "disabled"}}` requirement (DeepSeek-v4-flash rejects a
  forced `tool_choice` with HTTP 400 while thinking mode defaults on — see
  `news_debate.py`'s module docstring for the upstream issue link; this module hits the
  identical constraint and needs the identical flag).
- `evaluate_macro_debate(llm_client, session=requests) -> list[dict]` — orchestration:
  calls `fetch_bullion_headlines`, then `evaluate_macro_events`, and returns a list of
  plain dicts (`{"event":..., "probability":..., "implication":...}`, one per event, no
  timestamp) ready for the caller to stamp with `cycle_timestamp` and append to a rows
  list — same contract shape as `news_debate.py::evaluate_shadow_debate`. **Raises on any
  failure** (does not catch anything itself); the caller owns the fail-open catch, exactly
  as `evaluate_shadow_debate`'s own docstring specifies for the same reason.

No per-cycle cache is needed (unlike `news_debate.py`'s per-symbol cache): this runs once
per cycle, not once per WATCHLIST symbol, so there is no repeat-call-within-one-run case to
dedupe.

### 2. `graywind_strategy/dashboard_export.py` (extend)

- `MACRO_DEBATE_LOG_FILENAME = "macro_debate_log.csv"`
- `MACRO_DEBATE_LOG_FIELDS = ["timestamp", "event", "probability", "implication"]`
- `log_macro_debate(rows, dashboard_dir=DEFAULT_DASHBOARD_DIR)` — append-forever CSV
  writer, identical structure to the existing `log_news_debate` (header written once, one
  row per event, no-op on empty `rows`).

### 3. Wiring into `live_loop.py`

- New import: `from graywind_strategy.gates.macro_debate import evaluate_macro_debate`
- Extend the existing `from graywind_strategy.dashboard_export import ...` line to also
  import `log_macro_debate`.
- New helper function `run_macro_debate_cycle(llm_client, cycle_timestamp, macro_debate_rows)`
  — a standalone, directly-testable function (mirrors why `process_symbol` is its own
  function rather than inline in `main()`'s loop): wraps `evaluate_macro_debate` in the
  fail-open try/except and appends timestamped rows to `macro_debate_rows`. Called **once
  per cycle** in `main()`, right after `cycle_timestamp = datetime.now(ET).isoformat()`
  (`live_loop.py:886`) and before the `for symbol in WATCHLIST:` loop (`live_loop.py:1002`)
  — deliberately outside the per-symbol loop, since Bullion's feed is not symbol-specific
  and calling it once per cycle instead of once per symbol keeps this feature at roughly
  `26 cycles/day` worth of calls, not `26 × len(WATCHLIST)`.
- `macro_debate_rows = []` initialized alongside the existing `debate_rows = []`
  (`live_loop.py:891`).
- `log_macro_debate(macro_debate_rows, dashboard_dir=dashboard_dir)` called alongside the
  existing `log_news_debate(debate_rows, dashboard_dir=dashboard_dir)` call
  (`live_loop.py:1085`), inside the same already-guarded `try:` block (a shadow-logging
  write failure here must not prevent the real dashboard export from running — same
  guard, same reasoning, already in place for `log_news_debate`).

No new environment variable, no new GitHub Actions secret, no `requirements.txt` change:
this reuses the exact same `llm_client` (DeepSeek, built once in `main()` from
`DEEPSEEK_API_KEY`) that `news_debate.py` already uses, and `requests` is already a
dependency (`macro_gate.py` uses it today).

## Error handling

Fails **open**, same as `news_debate.py`: any failure (Bullion fetch, staleness, malformed
LLM output) is caught by `run_macro_debate_cycle`, printed to stderr, and produces zero
rows that cycle — the rest of the trading cycle proceeds unaffected. Never fails closed;
this signal cannot delay or block a real order.

## Testing

- `tests/test_macro_debate.py`: `fetch_bullion_headlines` (mocked `session.get` — success,
  non-200, malformed JSON, and a `generated_at` past `STALENESS_CEILING_HOURS` all raise
  `MacroNewsUnavailable`); `evaluate_macro_events` (mocked `llm_client`, same
  `_fake_tool_response`-style MagicMock pattern as `tests/test_news_debate.py`, verifying
  the forced `tool_choice`, the `thinking: disabled` flag, and that a well-formed response
  parses into the right `MacroEvent` list); `evaluate_macro_debate` orchestration (mocks
  both fetch and LLM call, confirms the returned dicts contain no `timestamp` key).
- Extend `tests/test_dashboard_export.py` with a round-trip test for `log_macro_debate`,
  mirroring its existing `log_news_debate` test.
- Extend `tests/test_live_loop.py` with tests for `run_macro_debate_cycle`: a successful
  call appends timestamped rows; an exception (mocked `evaluate_macro_debate` with
  `side_effect`) does not raise and appends nothing — mirroring
  `test_process_symbol_debate_exception_does_not_block_real_decision_or_propagate`'s
  pattern but for the new cycle-level function instead of `process_symbol`.
- No test makes a real DeepSeek or Bullion network call.

## Deferred, not forgotten

- A promotion bar for this signal (shadow → authoritative) — not written yet, deliberately.
  `graywind-news-debate-promotion-bar.md` was written only after that shadow feature
  already existed conceptually; writing a bar for a feature with zero logged rows risks
  inventing criteria with nothing to check them against. Revisit once
  `dashboard-data/macro_debate_log.csv` has real history (and once Bullion's news cron
  staleness issue noted above is actually fixed enough to produce any rows at all).
- Fixing Bullion's stale news cron — out of scope for this repo; belongs to the Bullion
  project, and is a real blocker for this feature ever logging a row, not a Graywind bug.
- Any comparison/analysis script (a `scripts/analyze_macro_debate.py` analog to the
  deferred `scripts/analyze_news_debate_shadow.py`) — same reasoning as that deferral: no
  rows yet, nothing to build the analysis against.

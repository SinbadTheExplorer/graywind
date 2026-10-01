# Graywind × Bullion Macro-Event Debate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a shadow-mode-only signal that reads Bullion's market-wide news feed once per
trading cycle and logs a small set of DeepSeek-produced probability/implication readings
("what might happen, how likely, what it means") to a new CSV, without ever gating a trade.

**Architecture:** A new sibling gate module (`graywind_strategy/gates/macro_debate.py`,
separate from the existing per-symbol `news_debate.py`) fetches Bullion's `news.json`, makes
one forced-structured-output DeepSeek call, and returns a list of event dicts. A new
cycle-level helper in `live_loop.py` (`run_macro_debate_cycle`) calls it once per cycle
(not once per WATCHLIST symbol), fails open on any error, and appends rows to a new
`dashboard-data/macro_debate_log.csv` via a new `log_macro_debate` export function.

**Tech Stack:** Python, `openai` client pointed at DeepSeek's API (already a dependency),
`requests` (already a dependency), `pytest` + `unittest.mock.MagicMock` for tests.

**Spec:** `docs/superpowers/specs/2026-09-12-graywind-bullion-macro-debate-design.md`

## Global Constraints

- This is shadow-mode only: no code in this plan may add any path from
  `macro_debate.py` or its `live_loop.py` wiring into `graywind_strategy/pipeline.py` or
  `decide_trade()`. A task that would create such a path is out of scope for this plan.
- Fails **open**, never closed: any exception in the macro-debate path must be caught,
  printed to stderr, and produce zero rows for that cycle — it must never raise out of
  `main()` or delay/block order submission.
- No new environment variable, no new GitHub Actions secret, no new `requirements.txt`
  entry — reuse the existing `DEEPSEEK_API_KEY`-backed `llm_client` and the existing
  `requests` dependency.
- `additionalProperties: false` and forced `tool_choice` on every DeepSeek call, with
  `extra_body={"thinking": {"type": "disabled"}}` — matches `news_debate.py::_tool_call`
  exactly; omitting the `thinking` flag makes every real call fail with an HTTP 400 (see
  spec).
- Required fields read via direct dict indexing (not `.get()`) so a malformed LLM response
  raises loudly inside `evaluate_macro_events`/`evaluate_macro_debate`, to be caught by the
  caller's fail-open wrapper — never silently defaulted.

---

### Task 1: `macro_debate.py` — Bullion headline fetch with staleness guard

**Files:**
- Create: `graywind_strategy/gates/macro_debate.py`
- Test: `tests/test_macro_debate.py`

**Interfaces:**
- Produces: `MacroNewsUnavailable(Exception)`; `BULLION_NEWS_URL: str`;
  `STALENESS_CEILING_HOURS: int`; `fetch_bullion_headlines(session=requests) -> list[dict]`
  (each dict has at least a `"headline"` key).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_macro_debate.py
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.macro_debate import (
    MacroNewsUnavailable,
    STALENESS_CEILING_HOURS,
    fetch_bullion_headlines,
)


def _fake_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    def _raise():
        if status >= 400:
            raise Exception(f"HTTP {status}")
    resp.raise_for_status.side_effect = _raise
    return resp


def test_fetch_bullion_headlines_returns_headlines_list_on_fresh_feed():
    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "generated_at": fresh,
        "headlines": [{"headline": "Fed signals pause", "category": "federal"}],
    }
    session = MagicMock()
    session.get.return_value = _fake_response(payload)

    result = fetch_bullion_headlines(session=session)

    assert result == [{"headline": "Fed signals pause", "category": "federal"}]


def test_fetch_bullion_headlines_raises_on_http_error():
    session = MagicMock()
    session.get.return_value = _fake_response({}, status=500)

    with pytest.raises(MacroNewsUnavailable):
        fetch_bullion_headlines(session=session)


def test_fetch_bullion_headlines_raises_on_malformed_json():
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.side_effect = lambda: None
    resp.json.side_effect = json.JSONDecodeError("bad", "doc", 0)
    session.get.return_value = resp

    with pytest.raises(MacroNewsUnavailable):
        fetch_bullion_headlines(session=session)


def test_fetch_bullion_headlines_raises_on_missing_keys():
    session = MagicMock()
    session.get.return_value = _fake_response({"unexpected": "shape"})

    with pytest.raises(MacroNewsUnavailable):
        fetch_bullion_headlines(session=session)


def test_fetch_bullion_headlines_raises_when_stale_past_ceiling():
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(hours=STALENESS_CEILING_HOURS + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"generated_at": stale, "headlines": [{"headline": "old news"}]}
    session = MagicMock()
    session.get.return_value = _fake_response(payload)

    with pytest.raises(MacroNewsUnavailable):
        fetch_bullion_headlines(session=session)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_macro_debate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'graywind_strategy.gates.macro_debate'`

- [ ] **Step 3: Write minimal implementation**

```python
# graywind_strategy/gates/macro_debate.py
"""Bullion macro-event shadow debate -- SHADOW MODE ONLY, cycle-level (not
per-symbol). Reads Bullion's market-wide news.json (Fed policy, geopolitics,
macro headlines -- distinct from news_debate.py's per-symbol headlines) and
logs a probability-weighted read of a handful of events once per trading
cycle. This module's output never gates a trade: pipeline.py::decide_trade()
has no code path into anything here. See
docs/superpowers/specs/2026-09-12-graywind-bullion-macro-debate-design.md.

Provider: same DeepSeek client (already wired for news_debate.py) -- no new
secret, no new dependency. See news_debate.py's module docstring for why
`extra_body={"thinking": {"type": "disabled"}}` is required on every call
(DeepSeek-v4-flash otherwise rejects a forced tool_choice with an HTTP 400).
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

NEWS_DEBATE_MODEL = "deepseek-v4-flash"
NEWS_DEBATE_MAX_TOKENS = 1024

BULLION_NEWS_URL = "https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/news.json"
STALENESS_CEILING_HOURS = 48

SUBMIT_EVENTS_TOOL_NAME = "submit_macro_events"


class MacroNewsUnavailable(Exception):
    pass


@dataclass
class MacroEvent:
    event: str
    probability: float
    implication: str


def fetch_bullion_headlines(session=requests):
    try:
        response = session.get(BULLION_NEWS_URL, timeout=10)
        response.raise_for_status()
        payload = response.json()
        generated_at = datetime.strptime(
            payload["generated_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        headlines = payload["headlines"]
    except MacroNewsUnavailable:
        raise
    except Exception as exc:
        raise MacroNewsUnavailable(str(exc)) from exc

    age = datetime.now(timezone.utc) - generated_at
    if age > timedelta(hours=STALENESS_CEILING_HOURS):
        raise MacroNewsUnavailable(
            f"Bullion news feed is {age} old, older than the "
            f"{STALENESS_CEILING_HOURS}h staleness ceiling"
        )
    return headlines
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_macro_debate.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gates/macro_debate.py tests/test_macro_debate.py
git commit -m "feat: add Bullion macro-news fetch with staleness guard for shadow debate"
```

---

### Task 2: `macro_debate.py` — structured DeepSeek call producing probability events

**Files:**
- Modify: `graywind_strategy/gates/macro_debate.py`
- Test: `tests/test_macro_debate.py`

**Interfaces:**
- Consumes: `MacroEvent` (Task 1); `SUBMIT_EVENTS_TOOL_NAME`, `NEWS_DEBATE_MODEL`,
  `NEWS_DEBATE_MAX_TOKENS` (Task 1).
- Produces: `evaluate_macro_events(llm_client, headlines) -> list[MacroEvent]`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_macro_debate.py
from graywind_strategy.gates.macro_debate import MacroEvent, evaluate_macro_events


def _fake_tool_response(tool_name, input_dict):
    fake_tool_call = MagicMock()
    fake_tool_call.function.name = tool_name
    fake_tool_call.function.arguments = json.dumps(input_dict)
    fake_message = MagicMock()
    fake_message.tool_calls = [fake_tool_call]
    fake_choice = MagicMock()
    fake_choice.message = fake_message
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    return fake_response


def test_evaluate_macro_events_parses_response_into_macro_events():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_macro_events",
        {"events": [
            {"event": "Fed cuts rates in December", "probability": 0.6,
             "implication": "Bullish for rate-sensitive equities"},
        ]},
    )

    result = evaluate_macro_events(fake_client, [{"headline": "Fed signals pause"}])

    assert result == [MacroEvent(
        event="Fed cuts rates in December", probability=0.6,
        implication="Bullish for rate-sensitive equities",
    )]


def test_evaluate_macro_events_forces_tool_and_disables_thinking():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_macro_events", {"events": [
            {"event": "e", "probability": 0.5, "implication": "i"},
        ]},
    )

    evaluate_macro_events(fake_client, [{"headline": "Fed signals pause"}])

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {
        "type": "function", "function": {"name": "submit_macro_events"},
    }
    assert call_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    prompt_text = call_kwargs["messages"][0]["content"]
    assert "Fed signals pause" in prompt_text


def test_evaluate_macro_events_raises_on_malformed_response():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_macro_events", {"events": [{"event": "e"}]},
    )

    with pytest.raises(KeyError):
        evaluate_macro_events(fake_client, [{"headline": "x"}])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_macro_debate.py -v`
Expected: FAIL with `ImportError: cannot import name 'evaluate_macro_events'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to graywind_strategy/gates/macro_debate.py

_EVENTS_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "event": {"type": "string"},
                    "probability": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "implication": {"type": "string"},
                },
                "required": ["event", "probability", "implication"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["events"],
    "additionalProperties": False,
}


def _headlines_block(headlines):
    if not headlines:
        return "(no recent headlines)"
    return "\n".join(f"- {h['headline']}" for h in headlines)


def _tool_call(llm_client, prompt, tool_name, schema):
    response = llm_client.chat.completions.create(
        model=NEWS_DEBATE_MODEL,
        max_tokens=NEWS_DEBATE_MAX_TOKENS,
        tools=[{
            "type": "function",
            "function": {
                "name": tool_name,
                "description": "Submit 1-5 macro events implied by these headlines, "
                                "each with a probability and what it implies for markets.",
                "parameters": schema,
                "strict": True,
            },
        }],
        tool_choice={"type": "function", "function": {"name": tool_name}},
        messages=[{"role": "user", "content": prompt}],
        extra_body={"thinking": {"type": "disabled"}},
    )
    for tool_call in response.choices[0].message.tool_calls or []:
        if tool_call.function.name == tool_name:
            return json.loads(tool_call.function.arguments)
    raise ValueError(f"macro_debate: no {tool_name} tool call in response")


def evaluate_macro_events(llm_client, headlines):
    prompt = (
        "You are a macro markets analyst. Given these recent market-wide "
        "headlines, identify 1-5 concrete events they suggest might happen "
        "(policy moves, economic releases, geopolitical developments), each "
        "with a probability from 0.0 to 1.0 and a one-sentence implication "
        "for markets.\n\nHeadlines:\n" + _headlines_block(headlines)
    )
    result = _tool_call(llm_client, prompt, SUBMIT_EVENTS_TOOL_NAME, _EVENTS_TOOL_SCHEMA)
    return [
        MacroEvent(
            event=item["event"],
            probability=float(item["probability"]),
            implication=item["implication"],
        )
        for item in result["events"]
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_macro_debate.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gates/macro_debate.py tests/test_macro_debate.py
git commit -m "feat: add DeepSeek structured call producing macro event probabilities"
```

---

### Task 3: `macro_debate.py` — top-level orchestration

**Files:**
- Modify: `graywind_strategy/gates/macro_debate.py`
- Test: `tests/test_macro_debate.py`

**Interfaces:**
- Consumes: `fetch_bullion_headlines` (Task 1), `evaluate_macro_events` (Task 2).
- Produces: `evaluate_macro_debate(llm_client, session=requests) -> list[dict]` — each dict
  has keys `event`, `probability`, `implication` (no `timestamp` key; the caller adds it).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_macro_debate.py
from unittest.mock import patch

from graywind_strategy.gates.macro_debate import evaluate_macro_debate


def test_evaluate_macro_debate_returns_dicts_without_timestamp():
    with patch(
        "graywind_strategy.gates.macro_debate.fetch_bullion_headlines",
        return_value=[{"headline": "Fed signals pause"}],
    ), patch(
        "graywind_strategy.gates.macro_debate.evaluate_macro_events",
        return_value=[MacroEvent(event="e", probability=0.5, implication="i")],
    ):
        result = evaluate_macro_debate(llm_client=object())

    assert result == [{"event": "e", "probability": 0.5, "implication": "i"}]


def test_evaluate_macro_debate_propagates_fetch_failure():
    with patch(
        "graywind_strategy.gates.macro_debate.fetch_bullion_headlines",
        side_effect=MacroNewsUnavailable("stale"),
    ):
        with pytest.raises(MacroNewsUnavailable):
            evaluate_macro_debate(llm_client=object())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_macro_debate.py -v`
Expected: FAIL with `ImportError: cannot import name 'evaluate_macro_debate'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to graywind_strategy/gates/macro_debate.py

def evaluate_macro_debate(llm_client, session=requests):
    """Fetches Bullion's market-wide headlines and runs the macro-event
    debate on them, returning plain dicts (no timestamp -- the caller
    stamps `cycle_timestamp` and appends to its own rows list, same
    contract shape as news_debate.py::evaluate_shadow_debate).

    Raises on any failure (headline fetch, staleness, malformed debate
    output) -- does not catch anything itself. The caller
    (live_loop.py::run_macro_debate_cycle) owns the fail-open catch, since
    only the caller knows this is a shadow-mode-only call that must never
    affect the real trade cycle.
    """
    headlines = fetch_bullion_headlines(session=session)
    events = evaluate_macro_events(llm_client, headlines)
    return [
        {"event": e.event, "probability": e.probability, "implication": e.implication}
        for e in events
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_macro_debate.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gates/macro_debate.py tests/test_macro_debate.py
git commit -m "feat: add evaluate_macro_debate orchestration for macro-event shadow debate"
```

---

### Task 4: `dashboard_export.py` — `log_macro_debate`

**Files:**
- Modify: `graywind_strategy/dashboard_export.py`
- Test: `tests/test_dashboard_export.py`

**Interfaces:**
- Produces: `MACRO_DEBATE_LOG_FILENAME: str`, `MACRO_DEBATE_LOG_FIELDS: list[str]`,
  `log_macro_debate(rows, dashboard_dir=DEFAULT_DASHBOARD_DIR)`.

- [ ] **Step 1: Write the failing test**

First, check how the existing `log_news_debate` round-trip test is written (same file,
`tests/test_dashboard_export.py`) and mirror its exact fixture/assertion style — do not
guess its shape; open the file and copy its pattern for the new test below, adjusting only
the field names:

```python
# append to tests/test_dashboard_export.py, mirroring the existing
# log_news_debate round-trip test's fixture/tmp_path style exactly
from graywind_strategy.dashboard_export import (
    MACRO_DEBATE_LOG_FIELDS,
    MACRO_DEBATE_LOG_FILENAME,
    log_macro_debate,
)


def test_log_macro_debate_appends_rows_and_writes_header_once(tmp_path):
    dashboard_dir = str(tmp_path)
    row1 = {
        "timestamp": "2026-09-12T10:00:00-04:00", "event": "Fed cuts rates",
        "probability": 0.6, "implication": "Bullish for rate-sensitive equities",
    }
    row2 = {
        "timestamp": "2026-09-12T10:15:00-04:00", "event": "CPI comes in hot",
        "probability": 0.3, "implication": "Bearish for growth stocks",
    }

    log_macro_debate([row1], dashboard_dir=dashboard_dir)
    log_macro_debate([row2], dashboard_dir=dashboard_dir)

    path = os.path.join(dashboard_dir, MACRO_DEBATE_LOG_FILENAME)
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["event"] for r in rows] == ["Fed cuts rates", "CPI comes in hot"]
    assert list(rows[0].keys()) == MACRO_DEBATE_LOG_FIELDS


def test_log_macro_debate_noop_on_empty_rows(tmp_path):
    dashboard_dir = str(tmp_path)
    log_macro_debate([], dashboard_dir=dashboard_dir)
    assert not os.path.exists(os.path.join(dashboard_dir, MACRO_DEBATE_LOG_FILENAME))
```

(Add `import csv` and `import os` at the top of `tests/test_dashboard_export.py` if not
already present — check first.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_dashboard_export.py -v`
Expected: FAIL with `ImportError: cannot import name 'log_macro_debate'`

- [ ] **Step 3: Write minimal implementation**

```python
# In graywind_strategy/dashboard_export.py, right after the existing
# NEWS_DEBATE_LOG_FIELDS block (after line 34):
MACRO_DEBATE_LOG_FILENAME = "macro_debate_log.csv"
MACRO_DEBATE_LOG_FIELDS = ["timestamp", "event", "probability", "implication"]
```

```python
# Right after the existing log_news_debate function definition:
def log_macro_debate(rows, dashboard_dir=DEFAULT_DASHBOARD_DIR):
    """Appends shadow-mode macro-event-debate rows to
    <dashboard_dir>/macro_debate_log.csv -- same append-forever semantics
    as log_news_debate (list of rows, no-op on empty, header written once).
    See docs/superpowers/specs/2026-09-12-graywind-bullion-macro-debate-design.md.
    """
    if not rows:
        return
    os.makedirs(dashboard_dir, exist_ok=True)
    path = os.path.join(dashboard_dir, MACRO_DEBATE_LOG_FILENAME)
    file_exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MACRO_DEBATE_LOG_FIELDS, lineterminator="\n")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dashboard_export.py -v`
Expected: PASS (all existing tests plus the 2 new ones)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/dashboard_export.py tests/test_dashboard_export.py
git commit -m "feat: add log_macro_debate for the macro-event shadow debate log"
```

---

### Task 5: Wire into `live_loop.py`

**Files:**
- Modify: `live_loop.py:47` (imports), `live_loop.py:50` (imports), `live_loop.py:891`
  (row-list init), `live_loop.py:1001-1002` (cycle-level call site), `live_loop.py:1085`
  (log call site)
- Test: `tests/test_live_loop.py`

**Interfaces:**
- Consumes: `evaluate_macro_debate` (Task 3), `log_macro_debate` (Task 4).
- Produces: `run_macro_debate_cycle(llm_client, cycle_timestamp, macro_debate_rows)` — a
  standalone function (not inline in `main()`), directly unit-testable the same way
  `process_symbol` is.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_live_loop.py
from unittest.mock import patch

import live_loop


def test_run_macro_debate_cycle_appends_timestamped_rows():
    rows = []
    with patch(
        "live_loop.evaluate_macro_debate",
        return_value=[{"event": "e", "probability": 0.5, "implication": "i"}],
    ):
        live_loop.run_macro_debate_cycle(
            llm_client=object(), cycle_timestamp="2026-09-12T10:00:00-04:00",
            macro_debate_rows=rows,
        )

    assert rows == [{
        "timestamp": "2026-09-12T10:00:00-04:00",
        "event": "e", "probability": 0.5, "implication": "i",
    }]


def test_run_macro_debate_cycle_exception_does_not_raise_and_appends_nothing():
    rows = []
    with patch("live_loop.evaluate_macro_debate", side_effect=RuntimeError("stale feed")):
        # Must not raise -- fail-open, same contract as process_symbol's
        # news-debate handling.
        live_loop.run_macro_debate_cycle(
            llm_client=object(), cycle_timestamp="2026-09-12T10:00:00-04:00",
            macro_debate_rows=rows,
        )

    assert rows == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v -k macro_debate_cycle`
Expected: FAIL with `AttributeError: module 'live_loop' has no attribute 'run_macro_debate_cycle'`

- [ ] **Step 3: Write minimal implementation**

Edit `live_loop.py:47` — change:
```python
from graywind_strategy.gates.news_debate import evaluate_shadow_debate
```
to:
```python
from graywind_strategy.gates.news_debate import evaluate_shadow_debate
from graywind_strategy.gates.macro_debate import evaluate_macro_debate
```

Edit `live_loop.py:50` — change:
```python
from graywind_strategy.dashboard_export import write_cycle_export, log_news_debate
```
to:
```python
from graywind_strategy.dashboard_export import write_cycle_export, log_news_debate, log_macro_debate
```

Add a new top-level function, placed right before `def process_symbol(` (`live_loop.py:253`):
```python
def run_macro_debate_cycle(llm_client, cycle_timestamp, macro_debate_rows):
    """Runs the Bullion macro-event shadow debate once for this cycle
    (not once per WATCHLIST symbol -- Bullion's feed is market-wide, not
    symbol-specific) and appends timestamped rows to macro_debate_rows.
    Fails open: any exception (Bullion fetch, staleness, malformed LLM
    output) is caught, printed to stderr, and produces no row this cycle --
    it must never affect the real trading cycle. See
    docs/superpowers/specs/2026-09-12-graywind-bullion-macro-debate-design.md.
    """
    try:
        for event in evaluate_macro_debate(llm_client=llm_client):
            macro_debate_rows.append({"timestamp": cycle_timestamp, **event})
    except Exception as exc:
        print(f"macro debate shadow-mode error, skipping this cycle's row: {exc}",
              file=sys.stderr)
```

Edit `live_loop.py:891` (right after the existing `debate_rows = []`) — change:
```python
    debate_cache = {}
    debate_rows = []
```
to:
```python
    debate_cache = {}
    debate_rows = []
    macro_debate_rows = []
```

Edit around `live_loop.py:1001-1002` — change:
```python
        now = datetime.now(ET)
        for symbol in WATCHLIST:
```
to:
```python
        now = datetime.now(ET)
        if llm_client is not None:
            run_macro_debate_cycle(
                llm_client=llm_client, cycle_timestamp=cycle_timestamp,
                macro_debate_rows=macro_debate_rows,
            )
        for symbol in WATCHLIST:
```

Edit around `live_loop.py:1085` (inside the existing guarded `try:` block that calls
`log_news_debate`) — change:
```python
            log_news_debate(debate_rows, dashboard_dir=dashboard_dir)
```
to:
```python
            log_news_debate(debate_rows, dashboard_dir=dashboard_dir)
            log_macro_debate(macro_debate_rows, dashboard_dir=dashboard_dir)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v -k macro_debate_cycle`
Expected: PASS (2 passed)

Then run the full suite to confirm nothing else broke:

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all tests passed (previous total plus the ~12 new tests from Tasks 1-5)

- [ ] **Step 5: Commit**

```bash
git add live_loop.py tests/test_live_loop.py
git commit -m "feat: wire Bullion macro-event shadow debate into the live trading cycle"
```

---

### Task 6: Handoff doc

**Files:**
- Create: `docs/superpowers/graywind-bullion-macro-debate-handoff.md`

- [ ] **Step 1: Write the handoff**

Follow this repo's own handoff convention (see
`docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` for the exact shape: How to
resume, Current state, What has changed, What has failed/risks/caveats, What's next,
Verification idioms). Must explicitly state, in "What has failed / risks / caveats":

- Bullion's `news.json` feed was confirmed 7 days stale (`generated_at: 2026-09-05` checked
  on `2026-09-12`) during this plan's own research — past this feature's own 48h staleness
  ceiling. Until Bullion's news cron is fixed, `fetch_bullion_headlines` will raise
  `MacroNewsUnavailable` on essentially every real cycle, and
  `dashboard-data/macro_debate_log.csv` will not gain rows. This is expected fail-open
  behavior, not a bug in this feature — but it means the feature is effectively dormant on
  ship, same shape as the original `news_debate.py` launch being blocked on a missing
  secret. State plainly that this is a **Bullion-side blocker**, not a Graywind one.
- No live smoke test against the real DeepSeek API or the real Bullion feed has happened —
  same caveat pattern as `news_debate.py`'s own handoff history.
- Next action for a resuming session: check whether Bullion's news cron has been fixed
  (`curl -s https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/news.json`
  and inspect `generated_at`); if fresh, trigger a `workflow_dispatch` run during market
  hours and confirm `dashboard-data/macro_debate_log.csv` gains rows.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/graywind-bullion-macro-debate-handoff.md
git commit -m "docs: add handoff for the Bullion macro-event shadow debate"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers `fetch_bullion_headlines`/staleness; Task 2 covers
  `evaluate_macro_events`; Task 3 covers `evaluate_macro_debate` orchestration; Task 4
  covers the logging function; Task 5 covers `live_loop.py` wiring (imports, row-list init,
  cycle-level call site, log call site); Task 6 covers the handoff documenting the known
  Bullion-side staleness blocker. The spec's "Deferred, not forgotten" items (promotion
  bar, Bullion cron fix, analysis script) are intentionally not tasks in this plan.
- **Placeholder scan:** no TBD/TODO markers; every code step has real, complete code; no
  step says "similar to Task N" without the actual code inline.
- **Type consistency:** `MacroEvent(event, probability, implication)` defined in Task 1,
  used identically in Tasks 2 and 3; `evaluate_macro_debate` returns dicts with keys
  `event`/`probability`/`implication` (no `timestamp`), and `run_macro_debate_cycle` (Task
  5) is the only place `timestamp` is added — consistent across all tasks that touch this
  shape.

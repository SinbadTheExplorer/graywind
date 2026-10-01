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

Also see news_debate.py's module docstring for why the tool schema's
`strict: true` (below) is a harmless no-op on the standard (non-`/beta`)
endpoint this module also uses -- DeepSeek does not enforce it server-side
there, which is why `evaluate_macro_events` below validates `probability`
itself instead of trusting the schema's `minimum`/`maximum` alone.
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
    if not headlines:
        # A fresh feed with zero recent headlines is not the same as a dead
        # feed, but sending `_headlines_block([])` -- "(no recent
        # headlines)" -- to the LLM still leaves the prompt demanding 1-5
        # events, so the model has nothing to ground a real read in and can
        # only fabricate predictions from nothing. Those would get logged
        # indistinguishably from a real read, since this log is the
        # feature's only artifact.
        raise MacroNewsUnavailable("Bullion news feed returned zero headlines")
    return headlines


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
    events = []
    for item in result["events"]:
        probability = float(item["probability"])
        # The tool schema declares minimum: 0.0, maximum: 1.0, but DeepSeek
        # does not enforce that server-side on the standard endpoint this
        # module uses (see the module docstring) -- a model returning 60
        # for "60%" would otherwise silently write 60.0 into the log, which
        # is this feature's only artifact and therefore otherwise
        # undetectable.
        if not (0.0 <= probability <= 1.0):
            raise ValueError(
                f"macro_debate: probability {probability} out of range [0.0, 1.0]"
            )
        events.append(MacroEvent(
            event=item["event"],
            probability=probability,
            implication=item["implication"],
        ))
    return events


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

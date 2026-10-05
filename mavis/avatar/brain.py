"""Ask the already-running MAVIS backend, and hear the answer as it is written.

Direct HTTP rather than MCP: this is a GUI app on the same machine as the
server, so it calls the backend the way mcp_tools.call_ask does, without an
MCP layer in between.

`sentences()` reads /ask/stream and yields each sentence the moment it is
complete, which is what lets him start speaking after one sentence instead of
after the whole reply.
"""
import json
import os
from contextlib import aclosing

import httpx

from avatar.speech import SentenceCutter

# How long an ordinary answer should be, asked of the backend. This used to be
# the biggest lever on latency (every character was converted before he spoke);
# with sentence-by-sentence speech it is only about not rambling. The backend
# gives the news its own, larger budget.
#
# Override without editing code, to tune it against a real run:
#     export MAVIS_MAX_ANSWER_CHARS=300
DEFAULT_MAX_ANSWER_CHARS = 200
# The backstop for a model that ignores its budget: he stops at the end of the
# sentence that crosses this. Well above the news budget, so a compliant
# answer is never cut.
MAX_SPOKEN_CHARS = 1000


def _budget_from_env(raw) -> int:
    """Parse the override, falling back rather than refusing to import.

    A bare int() here would raise on an empty or malformed value *at import
    time*, so the whole avatar would fail to start over a mistyped tuning knob.
    A LaunchAgent plist is exactly where an empty env value comes from, and
    every other failure path in this project degrades loudly instead of dying.
    """
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ANSWER_CHARS
    return value if value > 0 else DEFAULT_MAX_ANSWER_CHARS


MAX_ANSWER_CHARS = _budget_from_env(os.environ.get("MAVIS_MAX_ANSWER_CHARS"))


class BrainError(RuntimeError):
    pass


def _base_url() -> str:
    return os.environ.get("MAVIS_URL", "http://localhost:8000")


_client = None


def _shared_client() -> httpx.AsyncClient:
    """One client for the session: the connection stays open between answers."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(base_url=_base_url(), timeout=60.0)
    return _client


async def fragments(query: str, *, client: httpx.AsyncClient | None = None):
    """The answer's text as the backend writes it."""
    client = client or _shared_client()
    try:
        async with client.stream(
            "POST", "/ask/stream",
            json={"query": query, "max_chars": MAX_ANSWER_CHARS},
            headers={"X-API-Key": os.environ.get("MAVIS_API_KEY", "")},
        ) as resp:
            if resp.status_code != 200:
                raise BrainError(f"MAVIS backend returned {resp.status_code}")
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except ValueError as exc:
                    raise BrainError("MAVIS backend sent a non-JSON line") from exc
                if "error" in message:
                    raise BrainError(str(message["error"]))
                if message.get("done"):
                    return
                if message.get("delta"):
                    yield message["delta"]
    except httpx.RequestError as exc:
        raise BrainError(f"MAVIS backend unreachable: {exc}") from exc


async def sentences(query: str, *, client: httpx.AsyncClient | None = None):
    """The answer one whole sentence at a time, stopping at the backstop."""
    cutter, spoken = SentenceCutter(), 0
    # aclosing: stopping at the backstop must close the HTTP stream now, not
    # whenever the abandoned generator is collected.
    async with aclosing(fragments(query, client=client)) as stream:
        async for text in stream:
            for sentence in cutter.push(text):
                yield sentence
                spoken += len(sentence)
                if spoken >= MAX_SPOKEN_CHARS:
                    return
    for sentence in cutter.flush():
        yield sentence

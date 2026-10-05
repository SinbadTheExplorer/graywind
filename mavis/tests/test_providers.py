"""The brevity budget that keeps spoken answers short.

Length is latency for the avatar: voice conversion runs at ~1.5x realtime, so
every character the model writes is time Johnny stands there silent. These
tests pin both halves of that -- that asking for brevity works, and that not
asking leaves every other caller exactly as it was.
"""
import httpx
import pytest

import providers


class _FakeResponse:
    status_code = 200

    def __init__(self, captured):
        self._captured = captured

    def json(self):
        return {"choices": [{"message": {"content": "an answer"}}]}


class _FakeClient:
    """Captures the JSON body instead of calling Groq."""

    def __init__(self, captured, **kwargs):
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self._captured.update(json)
        return _FakeResponse(self._captured)


@pytest.fixture
def sent(monkeypatch):
    captured = {}
    monkeypatch.setattr(providers, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        providers.httpx, "AsyncClient",
        lambda **kwargs: _FakeClient(captured, **kwargs),
    )
    return captured


@pytest.mark.asyncio
async def test_no_system_message_when_no_budget_is_given(sent):
    """The MCP wrapper and CLI must keep getting the prompt they always got."""
    await providers.groq_answer("what is the watchlist")

    roles = [m["role"] for m in sent["messages"]]
    assert roles == ["user"]


@pytest.mark.asyncio
async def test_a_budget_adds_a_system_message_before_the_question(sent):
    await providers.groq_answer("what is the watchlist", max_chars=200)

    messages = sent["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "200" in messages[0]["content"]
    assert "what is the watchlist" in messages[1]["content"]


def test_brevity_instruction_scales_with_the_budget():
    assert "1 short sentence" in providers._brevity_instruction(110)
    assert "4 short sentences" in providers._brevity_instruction(440)


def test_brevity_instruction_never_asks_for_zero_sentences():
    """A tiny budget must still ask for one sentence, not none."""
    assert "1 short sentence" in providers._brevity_instruction(10)


def test_brevity_instruction_forbids_markdown():
    """Answers are read aloud; bullet characters get spoken or mangled."""
    assert "markdown" in providers._brevity_instruction(200).lower()


# -- groq_stream: the spoken answer, as it is written --------------------------

import json  # noqa: E402


def _sse(*fragments):
    events = [json.dumps({"choices": [{"delta": {"content": f}}]}) for f in fragments]
    # A reasoning-only event and a usage-only event: neither is answer text.
    events.insert(0, json.dumps({"choices": [{"delta": {"reasoning": "hm"}}]}))
    events.append(json.dumps({"choices": [], "usage": {}}))
    return "".join(f"data: {e}\n\n" for e in events) + "data: [DONE]\n\n"


async def _collect(handler, **kwargs):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return [t async for t in providers.groq_stream("q", client=client, **kwargs)]


@pytest.mark.asyncio
async def test_stream_yields_only_the_answer_text(monkeypatch):
    monkeypatch.setattr(providers, "GROQ_API_KEY", "k")
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, text=_sse("Gold ", "bids."))

    assert await _collect(handler, max_chars=200) == ["Gold ", "bids."]
    assert seen["stream"] is True
    assert seen["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_stream_speaks_in_character_and_keeps_the_brevity_budget(monkeypatch):
    monkeypatch.setattr(providers, "GROQ_API_KEY", "k")
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, text=_sse("ok"))

    await _collect(handler, context="CTX", max_chars=200, instruction="READ THE NEWS")
    system = [m["content"] for m in seen["messages"] if m["role"] == "system"]
    assert system[0] == providers.PERSONA
    assert system[1] == "READ THE NEWS"
    assert "under 200 characters" in system[2]
    assert seen["messages"][-1] == {"role": "user", "content": "CTX\n\nQuestion: q"}


@pytest.mark.asyncio
async def test_the_unspoken_path_is_not_given_the_persona(monkeypatch):
    """/ask serves the MCP tool and the CLI; they want the plain answer."""
    captured = {}
    monkeypatch.setattr(providers, "GROQ_API_KEY", "k")
    monkeypatch.setattr(providers.httpx, "AsyncClient",
                        lambda **kw: _FakeClient(captured, **kw))
    await providers.groq_answer("q")
    assert [m["role"] for m in captured["messages"]] == ["user"]
    assert "reasoning_effort" not in captured


@pytest.mark.asyncio
async def test_stream_refusal_and_outage_are_provider_errors(monkeypatch):
    monkeypatch.setattr(providers, "GROQ_API_KEY", "k")
    with pytest.raises(providers.ProviderError, match="429"):
        await _collect(lambda request: httpx.Response(429, text="slow down"))

    def offline(request):
        raise httpx.ConnectError("offline")
    with pytest.raises(providers.ProviderError, match="unreachable"):
        await _collect(offline)


@pytest.mark.asyncio
async def test_stream_without_a_key_is_a_provider_error(monkeypatch):
    monkeypatch.setattr(providers, "GROQ_API_KEY", None)
    with pytest.raises(providers.ProviderError, match="GROQ_API_KEY"):
        await _collect(lambda request: httpx.Response(200, text=_sse("x")))

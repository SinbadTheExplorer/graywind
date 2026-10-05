import json

import httpx
import pytest

from avatar import brain


def _client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler),
                             base_url="http://localhost:8000")


def _stream(*messages):
    return httpx.Response(200, text="".join(json.dumps(m) + "\n" for m in messages))


async def _sentences(handler, query="what's up"):
    async with _client_for(handler) as client:
        return [s async for s in brain.sentences(query, client=client)]


@pytest.mark.asyncio
async def test_sentences_come_out_whole_however_the_text_was_fragmented(monkeypatch):
    monkeypatch.setenv("MAVIS_API_KEY", "testkey")

    def handler(request):
        assert request.url.path == "/ask/stream"
        assert request.headers["x-api-key"] == "testkey"
        assert json.loads(request.content) == {
            "query": "what's up", "max_chars": brain.MAX_ANSWER_CHARS}
        return _stream({"delta": "Night City "}, {"delta": "burns. The U.S"},
                       {"delta": ". dollar "}, {"delta": "holds."},
                       {"done": True, "citations": [], "grounded": False})

    assert await _sentences(handler) == ["Night City burns.", "The U.S. dollar holds."]


@pytest.mark.asyncio
async def test_a_runaway_answer_stops_at_the_end_of_a_sentence():
    """The backstop for a model that ignores its budget: never mid-word."""
    def handler(request):
        return _stream(*[{"delta": "This is a sentence. "}] * 200, {"done": True})

    out = await _sentences(handler)
    assert all(s == "This is a sentence." for s in out)
    total = sum(len(s) for s in out)
    assert brain.MAX_SPOKEN_CHARS <= total < brain.MAX_SPOKEN_CHARS + 40


@pytest.mark.asyncio
async def test_an_error_line_mid_answer_raises_after_the_sentences_before_it():
    def handler(request):
        return _stream({"delta": "One. Two"}, {"error": "Groq error 503"})

    got = []
    async with _client_for(handler) as client:
        with pytest.raises(brain.BrainError, match="Groq error 503"):
            async for sentence in brain.sentences("q", client=client):
                got.append(sentence)
    assert got == ["One."]


@pytest.mark.asyncio
async def test_an_empty_answer_yields_nothing():
    assert await _sentences(lambda request: _stream({"done": True})) == []


@pytest.mark.asyncio
async def test_backend_error_status_raises():
    with pytest.raises(brain.BrainError, match="401"):
        await _sentences(lambda request: httpx.Response(401, json={"detail": "no"}))


@pytest.mark.asyncio
async def test_backend_unreachable_raises():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(brain.BrainError, match="unreachable"):
        await _sentences(handler)


@pytest.mark.asyncio
async def test_a_line_that_is_not_json_raises():
    with pytest.raises(brain.BrainError, match="non-JSON"):
        await _sentences(lambda request: httpx.Response(200, text="<html>oops\n"))


@pytest.mark.parametrize("raw", ["", "abc", "-5", "0", None])
def test_a_bad_budget_override_falls_back_instead_of_failing_import(raw):
    assert brain._budget_from_env(raw) == brain.DEFAULT_MAX_ANSWER_CHARS


def test_a_good_budget_override_is_used():
    assert brain._budget_from_env("300") == 300

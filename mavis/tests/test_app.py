import pytest
from fastapi.testclient import TestClient

import app as app_module
import auth
import rate_limit


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")


@pytest.fixture(autouse=True)
def reset_rate_limit():
    rate_limit._request_log.clear()


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_status_is_open_without_auth(client):
    resp = client.get("/status")

    assert resp.status_code == 200


def test_status_has_only_ok(client):
    assert client.get("/status").json() == {"ok": True}


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_and_openapi_are_gone(client, path):
    assert client.get(path).status_code == 404


def test_ask_rejects_a_query_over_500_chars(client):
    resp = client.post("/ask", json={"query": "x" * 501},
                       headers={"X-API-Key": "secret123"})
    assert resp.status_code == 422


@pytest.mark.parametrize("asked,expected", [(100000, 600), (1, 50), (200, 200)])
def test_max_chars_is_clamped(client, monkeypatch, asked, expected):
    seen = {}

    async def fake_answer(query, context=None, max_chars=None):
        seen["max_chars"] = max_chars
        return "ok"

    monkeypatch.setattr(app_module, "groq_answer", fake_answer)
    client.post("/ask", json={"query": "hi", "max_chars": asked},
                headers={"X-API-Key": "secret123"})
    assert seen["max_chars"] == expected


def test_groq_error_body_never_reaches_the_caller(client, monkeypatch):
    import httpx
    import providers

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            return httpx.Response(401, text="invalid api key gsk_LEAKED_secret")

    monkeypatch.setattr(providers, "GROQ_API_KEY", "x")
    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeClient)
    resp = client.post("/ask", json={"query": "hi"}, headers={"X-API-Key": "secret123"})
    assert resp.status_code == 502
    assert "LEAKED" not in resp.text and "gsk_" not in resp.text


def test_ask_over_cap_is_429_and_never_calls_groq(client, monkeypatch):
    import usage

    async def must_not_run(*a, **k):
        raise AssertionError("Groq was called over the cap")

    monkeypatch.setattr(app_module, "groq_answer", must_not_run)
    owner = auth.lookup("secret123")
    usage.record(owner, "llm", owner.per_day_llm)
    resp = client.post("/ask", json={"query": "hi"}, headers={"X-API-Key": "secret123"})
    assert resp.status_code == 429
    assert "tapped out" in resp.json()["detail"]


def test_stream_over_cap_says_tapped_out_and_never_calls_groq(client, monkeypatch):
    import usage

    def must_not_run(*a, **k):
        raise AssertionError("Groq was called over the cap")

    monkeypatch.setattr(app_module, "groq_stream", must_not_run)
    owner = auth.lookup("secret123")
    usage.record(owner, "llm", owner.per_day_llm)
    lines = _spoken(client, "what is the capital of France")
    assert lines == [{"error": "I'm tapped out for today, choom. Call me tomorrow."}]


def test_each_answer_is_counted_once(client, monkeypatch):
    import usage

    async def fake_answer(query, context=None, max_chars=None):
        return "ok"

    monkeypatch.setattr(app_module, "groq_answer", fake_answer)
    client.post("/ask", json={"query": "hi"}, headers={"X-API-Key": "secret123"})
    client.post("/ask", json={"query": "hi"}, headers={"X-API-Key": "secret123"})
    assert usage.today_totals("owner-env")["llm"] == 2


def test_ask_without_api_key_is_rejected(client):
    resp = client.post("/ask", json={"query": "what is graywind's watchlist"})

    assert resp.status_code == 401


def test_ask_merges_bullion_and_graywind_citations(client, monkeypatch):
    async def fake_groq_answer(query, context=None, max_chars=None):
        fake_groq_answer.seen_context = context
        return "fake answer"

    monkeypatch.setattr(app_module, "groq_answer", fake_groq_answer)

    resp = client.post(
        "/ask",
        json={"query": "what is graywind's watchlist"},
        headers={"X-API-Key": "secret123"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "fake answer"
    assert any(c.get("id") == "watchlist" for c in body["citations"])
    assert "Graywind trading bot" in fake_groq_answer.seen_context


def test_ask_is_rate_limited(client, monkeypatch):
    async def fake_groq_answer(query, context=None, max_chars=None):
        return "fake answer"

    monkeypatch.setattr(app_module, "groq_answer", fake_groq_answer)
    monkeypatch.setattr(rate_limit, "MAX_REQUESTS_PER_WINDOW", 1)

    headers = {"X-API-Key": "secret123"}
    ok = client.post("/ask", json={"query": "hi"}, headers=headers)
    blocked = client.post("/ask", json={"query": "hi"}, headers=headers)

    assert ok.status_code == 200
    assert blocked.status_code == 429


def test_ask_defaults_to_no_length_limit(client, monkeypatch):
    """The MCP wrapper and CLI callers must keep getting full answers."""
    seen = {}

    async def fake_answer(query, context=None, max_chars=None):
        seen["max_chars"] = max_chars
        return "a full length answer"

    monkeypatch.setattr(app_module, "groq_answer", fake_answer)

    resp = client.post("/ask", json={"query": "what is the watchlist"},
                       headers={"X-API-Key": "secret123"})

    assert resp.status_code == 200
    assert seen["max_chars"] is None


def test_ask_passes_max_chars_through_when_given(client, monkeypatch):
    """The spoken avatar asks for a short answer, because length is latency."""
    seen = {}

    async def fake_answer(query, context=None, max_chars=None):
        seen["max_chars"] = max_chars
        return "short answer"

    monkeypatch.setattr(app_module, "groq_answer", fake_answer)

    resp = client.post("/ask", json={"query": "what is the watchlist",
                                     "max_chars": 200},
                       headers={"X-API-Key": "secret123"})

    assert resp.status_code == 200
    assert seen["max_chars"] == 200

def test_ungrounded_question_about_our_own_system_is_refused(client, monkeypatch):
    """Both of these were observed live, with zero citations and full
    confidence: "what is the macro gate" came back about electronics, and
    "how much capital does tier 1 get" came back as Basel III. The model is
    never called for these -- a guess is the failure, not a slow guess."""
    called = []

    async def explode(*a, **kw):
        called.append(1)
        raise AssertionError("the model must not be asked at all")

    monkeypatch.setattr(app_module, "groq_answer", explode)

    for query in ("what is the macro gate",
                  "how much capital does tier 1 get",
                  "explain the drawdown breaker"):
        resp = client.post("/ask", json={"query": query},
                           headers={"X-API-Key": "secret123"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["grounded"] is False
        assert body["citations"] == []
        assert "guessing" in body["answer"]
    assert not called


def test_a_general_question_still_gets_a_general_answer(client, monkeypatch):
    """The guard must not turn him into a machine that only reads files.
    "What is gold" is not about Graywind and deserves a real answer."""
    async def fake(query, context=None, max_chars=None):
        return "Gold is a store of value."

    monkeypatch.setattr(app_module, "groq_answer", fake)

    resp = client.post("/ask", json={"query": "what is the capital of France"},
                       headers={"X-API-Key": "secret123"})

    assert resp.status_code == 200
    assert resp.json()["answer"] == "Gold is a store of value."



# -- /ask/stream: the spoken path ---------------------------------------------

import json  # noqa: E402

import news  # noqa: E402
from providers import ProviderError  # noqa: E402


def _lines(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def _spoken(client, query):
    resp = client.post("/ask/stream", json={"query": query, "max_chars": 200},
                       headers={"X-API-Key": "secret123"})
    assert resp.status_code == 200
    return _lines(resp)


def _fake_stream(seen, *fragments, fail=None):
    async def fake(query, context=None, max_chars=None, instruction=None):
        seen.update(query=query, context=context, max_chars=max_chars,
                    instruction=instruction)
        for fragment in fragments:
            yield fragment
        if fail:
            raise fail
    return fake


def test_stream_without_api_key_is_rejected(client):
    assert client.post("/ask/stream", json={"query": "hi"}).status_code == 401


def test_stream_sends_the_answer_in_fragments_then_a_done_line(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(app_module, "groq_stream", _fake_stream(seen, "Gold ", "bids."))

    lines = _spoken(client, "what is the capital of France")

    assert lines[:2] == [{"delta": "Gold "}, {"delta": "bids."}]
    assert lines[2]["done"] is True and lines[2]["grounded"] is False
    assert seen["max_chars"] == 200 and seen["instruction"] is None


def test_stream_refuses_ungrounded_questions_about_our_own_system(client, monkeypatch):
    async def explode(*a, **kw):
        raise AssertionError("the model must not be asked at all")
        yield  # pragma: no cover

    monkeypatch.setattr(app_module, "groq_stream", explode)

    lines = _spoken(client, "what is the macro gate")

    assert "guessing" in lines[0]["delta"]
    assert lines[1] == {"done": True, "citations": [], "grounded": False}


def test_a_provider_failure_arrives_as_an_error_line(client, monkeypatch):
    monkeypatch.setattr(app_module, "groq_stream",
                        _fake_stream({}, "Half an ", fail=ProviderError("Groq error 503")))

    lines = _spoken(client, "what is the capital of France")

    assert lines == [{"delta": "Half an "}, {"error": "Johnny's line dropped. Try again."}]


def test_news_is_answered_from_headlines_fetched_now(client, monkeypatch):
    seen = {}
    items = [{"type": "news", "title": "Bond yields hit a 24-year high",
              "source": "Reuters", "published": None, "link": "https://example.com/1"}]

    async def fake_headlines(query):
        return items

    monkeypatch.setattr(news, "headlines", fake_headlines)
    monkeypatch.setattr(app_module, "groq_stream", _fake_stream(seen, "Yields up, says Reuters."))

    lines = _spoken(client, "what's the news")

    # He starts talking before the feed is fetched.
    assert lines[0]["delta"].strip() in news.OPENERS
    assert lines[1] == {"delta": "Yields up, says Reuters."}
    assert "Reuters" in seen["context"] and "24-year high" in seen["context"]
    assert seen["instruction"] == news.INSTRUCTION
    assert seen["max_chars"] == news.NEWS_MAX_CHARS       # not the caller's 200
    assert lines[-1] == {"done": True, "citations": items, "grounded": True}


def test_news_with_no_feed_says_so_instead_of_reciting_from_memory(client, monkeypatch):
    async def no_headlines(query):
        return []

    async def explode(*a, **kw):
        raise AssertionError("no headlines means the model is not asked")
        yield  # pragma: no cover

    monkeypatch.setattr(news, "headlines", no_headlines)
    monkeypatch.setattr(app_module, "groq_stream", explode)

    lines = _spoken(client, "what's the news")

    assert lines[1]["delta"] == news.UNAVAILABLE
    assert lines[2]["grounded"] is False


def test_the_news_debate_gate_is_a_project_question_not_a_news_request(client, monkeypatch):
    async def explode(query):
        raise AssertionError("must not fetch headlines for a Graywind term")

    monkeypatch.setattr(news, "headlines", explode)

    lines = _spoken(client, "how does the news debate work")

    assert "guessing" in lines[0]["delta"]


def test_ask_stream_with_env_key_still_200(client, monkeypatch):
    # The desktop avatar's call: the original env key, now an owner record.
    async def fake_events(query, max_chars, rec):
        yield {"delta": "hi"}
        yield {"done": True, "citations": [], "grounded": False}

    monkeypatch.setattr(app_module, "_answer_events", fake_events)
    resp = client.post("/ask/stream", json={"query": "hi", "max_chars": 200},
                       headers={"X-API-Key": "secret123"})
    assert resp.status_code == 200
    assert '"delta": "hi"' in resp.text


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_blank_query_is_refused_free(client, monkeypatch, query):
    import usage
    resp = client.post("/ask", json={"query": query}, headers={"X-API-Key": "secret123"})
    assert resp.status_code == 422
    assert usage.today_totals()["llm"] == 0


def test_failed_answer_is_refunded(client, monkeypatch):
    import usage
    from fastapi import HTTPException

    async def broken(*a, **k):
        raise HTTPException(502, "Johnny's line dropped. Try again.")

    monkeypatch.setattr(app_module, "groq_answer", broken)
    for _ in range(3):
        assert client.post("/ask", json={"query": "hi"},
                           headers={"X-API-Key": "secret123"}).status_code == 502
    assert usage.today_totals("owner-env")["llm"] == 0


def test_stream_failure_before_first_word_is_refunded(client, monkeypatch):
    import usage
    monkeypatch.setattr(app_module, "groq_stream",
                        _fake_stream({}, fail=ProviderError("Groq error 503")))
    _spoken(client, "what is the capital of France")
    assert usage.today_totals("owner-env")["llm"] == 0


def test_stream_failure_after_words_is_still_counted(client, monkeypatch):
    import usage
    monkeypatch.setattr(app_module, "groq_stream",
                        _fake_stream({}, "Half an ", fail=ProviderError("Groq error 503")))
    _spoken(client, "what is the capital of France")
    assert usage.today_totals("owner-env")["llm"] == 1


def test_groq_timeout_is_a_quiet_502(client, monkeypatch):
    import httpx
    import providers

    class TimeoutClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k):
            raise httpx.ReadTimeout("slow upstream at 10.0.0.5")

    monkeypatch.setattr(providers, "GROQ_API_KEY", "x")
    monkeypatch.setattr(providers.httpx, "AsyncClient", TimeoutClient)
    resp = client.post("/ask", json={"query": "hi"}, headers={"X-API-Key": "secret123"})
    assert resp.status_code == 502
    assert "10.0.0.5" not in resp.text


def test_broken_usage_store_refuses_instead_of_spending(client, monkeypatch):
    import sqlite3
    import usage

    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    async def must_not_run(*a, **k):
        raise AssertionError("Groq was called with no usage count")

    monkeypatch.setattr(usage, "charge", locked)
    monkeypatch.setattr(app_module, "groq_answer", must_not_run)
    resp = client.post("/ask", json={"query": "hi"}, headers={"X-API-Key": "secret123"})
    assert resp.status_code == 503
    monkeypatch.setattr(app_module, "groq_stream", must_not_run)
    assert _spoken(client, "what is the capital of France") == [
        {"error": "Johnny's line dropped. Try again."}]


def test_call_answers_count_against_the_cap(monkeypatch):
    import asyncio
    import call
    import call_route
    import usage
    owner = auth.lookup("secret123")
    usage.record(owner, "llm", owner.per_day_llm)
    deps = call_route._call_deps(owner)

    async def run():
        async for _ in deps.answer("what is the capital of France"):
            pass

    with pytest.raises(call.AnswerError) as info:
        asyncio.run(run())
    assert "tapped out" in str(info.value)

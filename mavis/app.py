import asyncio
import contextlib
import json
import sqlite3
import sys

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

import auth
import grounding
import guards
import usage
import graywind_grounding
import news
from providers import ProviderError, groq_answer, groq_stream
from rate_limit import check_rate_limit

@contextlib.asynccontextmanager
async def _lifespan(_app):
    import call_route
    call_route.warm_up_in_background()
    yield


# No /docs, /redoc or /openapi.json: they hand anyone a map of every route.
app = FastAPI(lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)

from avatar import brain as avatar_brain  # noqa: E402

MAX_QUERY_CHARS = int(guards.env_number("MAVIS_MAX_QUERY_CHARS", 500, minimum=1))
# 600 unless the owner's own MAVIS_MAX_ANSWER_CHARS knob asks for more.
MIN_ANSWER_CHARS = 50
MAX_ANSWER_CHARS = max(600, avatar_brain.MAX_ANSWER_CHARS)


class AskRequest(BaseModel):
    query: str = Field(max_length=MAX_QUERY_CHARS)
    # Optional, and None for every existing caller: the MCP wrapper and the CLI
    # want full answers. Only the spoken avatar sets it, because there a long
    # answer is a long silence while it is voice-converted.
    max_chars: int | None = None

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value):
        # An empty question still costs a paid model call; refuse it free.
        value = value.strip()
        if not value:
            raise ValueError("query is empty")
        return value

    @field_validator("max_chars")
    @classmethod
    def _clamp(cls, value):
        # Client-chosen, so clamped: a 100k-character "answer" is a token bill.
        if value is None:
            return None
        return max(MIN_ANSWER_CHARS, min(MAX_ANSWER_CHARS, value))


@app.get("/status")
def status():
    # Liveness only: the model name and auth setup are nobody else's business.
    return {"ok": True}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


class ChargeUnavailable(Exception):
    """The usage store failed; refuse rather than spend uncounted."""


async def _charge_llm(rec) -> None:
    """One answer against the key's and everyone's daily cap.

    Raises usage.CapExceeded (audited) or ChargeUnavailable. Runs in a thread:
    SQLite's lock wait must not freeze every other call on the event loop.
    """
    try:
        await asyncio.to_thread(usage.charge, rec, "llm", 1)
    except usage.CapExceeded as exc:
        await asyncio.to_thread(usage.audit, "cap_hit", rec.id, kind="llm", which=exc.which)
        raise
    except (sqlite3.Error, OSError) as exc:
        _log(f"usage: charge failed, refusing: {exc!r}")
        raise ChargeUnavailable() from exc


async def _refund_llm(rec) -> None:
    """The model failed before a word was delivered: give the answer back."""
    try:
        await asyncio.to_thread(usage.refund, rec, "llm", 1)
    except (sqlite3.Error, OSError) as exc:
        _log(f"usage: refund failed: {exc!r}")


@app.post("/ask")
async def ask(req: AskRequest, rec: auth.KeyRecord = Depends(auth.require_api_key)):
    check_rate_limit(rec.id, rec.per_minute)

    bullion_hits = grounding.retrieve(req.query)
    # The owner's own portfolio facts: never for a guest (see _answer_events).
    graywind_hits = (graywind_grounding.retrieve(req.query)
                     if rec.scope == "owner" else [])

    context = "\n\n".join(filter(None, [
        grounding.format_context(bullion_hits),
        graywind_grounding.format_context(graywind_hits),
    ])) or None

    # Refuse rather than confabulate. With no context the model answers from
    # general knowledge in exactly the same confident tone, and for a question
    # about the owner's own system that is worse than silence -- he cannot
    # hear the difference, and there are no citations to warn him.
    # A guest asking about the owner's projects is refused even when some
    # unrelated context matched: otherwise the model answers from general
    # knowledge in the same confident tone.
    if graywind_grounding.names_project_internals(req.query) and (
            not context or rec.scope != "owner"):
        return {
            "answer": graywind_grounding.UNGROUNDED,
            "citations": [],
            "grounded": False,
        }

    try:
        await _charge_llm(rec)
    except usage.CapExceeded as exc:
        raise HTTPException(429, guards.TAPPED_OUT) from exc
    except ChargeUnavailable as exc:
        raise HTTPException(503, guards.GENERIC_ERROR) from exc
    try:
        answer = await groq_answer(req.query, context, max_chars=req.max_chars)
    except HTTPException:
        await _refund_llm(rec)
        raise

    return {
        "answer": answer,
        "citations": bullion_hits + graywind_hits,
        "grounded": bool(context),
    }


def _line(**fields) -> str:
    return json.dumps(fields) + "\n"


async def _answer_events(query: str, max_chars: int | None, rec):
    """The spoken answer as event dicts: {"delta"}, then {"done"} or {"error"}.

    Shared by /ask/stream (as NDJSON) and /call (as speech). `rec` is the
    caller's KeyRecord and is required: the paid model call is charged here,
    at the shared layer, so no caller can forget to. Refusals that never
    reach the model cost nothing, and a model failure before the first word
    is refunded.
    """
    # "news debate" is one of Graywind's own gates, not a request for headlines.
    wants_news = (news.is_news_query(query)
                  and not graywind_grounding.names_project_internals(query))
    instruction = None
    if wants_news:
        # Before the fetch, so he is already talking while it runs.
        yield dict(delta=news.random.choice(news.OPENERS) + " ")
        hits = await news.headlines(query)
        context = news.format_context(hits)
        instruction, max_chars = news.INSTRUCTION, news.NEWS_MAX_CHARS
        refusal = None if context else news.UNAVAILABLE
    else:
        bullion_hits = grounding.retrieve(query)
        # Graywind's facts are the owner's own portfolio. A guest never gets
        # them, however the question is worded: the retrieval is skipped, not
        # keyword-filtered.
        graywind_hits = (graywind_grounding.retrieve(query)
                         if rec.scope == "owner" else [])
        hits = bullion_hits + graywind_hits
        context = "\n\n".join(filter(None, [
            grounding.format_context(bullion_hits),
            graywind_grounding.format_context(graywind_hits),
        ])) or None
        refusal = (graywind_grounding.UNGROUNDED
                   if graywind_grounding.names_project_internals(query)
                   and (not context or rec.scope != "owner")
                   else None)
    if refusal:
        yield dict(delta=refusal)
        yield dict(done=True, citations=[], grounded=False)
        return
    try:
        await _charge_llm(rec)
    except usage.CapExceeded:
        yield dict(error=guards.TAPPED_OUT)
        return
    except ChargeUnavailable:
        yield dict(error=guards.GENERIC_ERROR)
        return
    spoke = False
    try:
        async for text in groq_stream(query, context, max_chars=max_chars,
                                      instruction=instruction):
            spoke = True
            yield dict(delta=text)
    except ProviderError as exc:
        _log(f"answer: provider failed: {exc}")    # detail stays server-side
        if not spoke:
            await _refund_llm(rec)
        yield dict(error=guards.GENERIC_ERROR)
        return
    yield dict(done=True, citations=hits, grounded=bool(context))


@app.post("/ask/stream")
async def ask_stream(req: AskRequest, rec: auth.KeyRecord = Depends(auth.require_api_key)):
    """The spoken path: the answer as newline-delimited JSON, as it is written.

    Lines are {"delta": text} while he writes, then one {"done": true,
    "citations": [...], "grounded": bool}. A failure after the response has
    started cannot change the status code, so it arrives as {"error": reason}.

    Same grounding and the same refusal as /ask. Two differences: he answers
    in character, and "what's the news" is answered from headlines fetched
    now rather than from anything the model remembers.
    """
    check_rate_limit(rec.id, rec.per_minute)

    async def body():
        async for event in _answer_events(req.query, req.max_chars, rec):
            yield _line(**event)

    return StreamingResponse(body(), media_type="application/x-ndjson")


# Registered last: call_route imports _answer_events from this module.
import call_route  # noqa: E402

app.include_router(call_route.router)
app.add_middleware(call_route.SecurityHeaders)

from fastapi.staticfiles import StaticFiles  # noqa: E402

# three.js, pinned and served from here rather than a CDN: the page keeps
# the MAVIS key in localStorage, so no third-party script may run on it.
app.mount("/johnny/vendor", StaticFiles(directory=call_route.VENDOR), name="johnny-vendor")

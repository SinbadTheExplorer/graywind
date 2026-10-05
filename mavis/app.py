import json

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import auth
import grounding
import graywind_grounding
import news
from providers import GROQ_MODEL, ProviderError, groq_answer, groq_stream
from rate_limit import check_rate_limit

app = FastAPI()


class AskRequest(BaseModel):
    query: str
    # Optional, and None for every existing caller: the MCP wrapper and the CLI
    # want full answers. Only the spoken avatar sets it, because there a long
    # answer is a long silence while it is voice-converted.
    max_chars: int | None = None


@app.get("/status")
def status():
    return {"ok": True, "provider": GROQ_MODEL, "auth_configured": bool(auth.MAVIS_API_KEY)}


@app.post("/ask")
async def ask(req: AskRequest, api_key: str = Depends(auth.require_api_key)):
    check_rate_limit(api_key)

    bullion_hits = grounding.retrieve(req.query)
    graywind_hits = graywind_grounding.retrieve(req.query)

    context = "\n\n".join(filter(None, [
        grounding.format_context(bullion_hits),
        graywind_grounding.format_context(graywind_hits),
    ])) or None

    # Refuse rather than confabulate. With no context the model answers from
    # general knowledge in exactly the same confident tone, and for a question
    # about the owner's own system that is worse than silence -- he cannot
    # hear the difference, and there are no citations to warn him.
    if not context and graywind_grounding.names_project_internals(req.query):
        return {
            "answer": graywind_grounding.UNGROUNDED,
            "citations": [],
            "grounded": False,
        }

    answer = await groq_answer(req.query, context, max_chars=req.max_chars)

    return {
        "answer": answer,
        "citations": bullion_hits + graywind_hits,
        "grounded": bool(context),
    }


def _line(**fields) -> str:
    return json.dumps(fields) + "\n"


@app.post("/ask/stream")
async def ask_stream(req: AskRequest, api_key: str = Depends(auth.require_api_key)):
    """The spoken path: the answer as newline-delimited JSON, as it is written.

    Lines are {"delta": text} while he writes, then one {"done": true,
    "citations": [...], "grounded": bool}. A failure after the response has
    started cannot change the status code, so it arrives as {"error": reason}.

    Same grounding and the same refusal as /ask. Two differences: he answers
    in character, and "what's the news" is answered from headlines fetched
    now rather than from anything the model remembers.
    """
    check_rate_limit(api_key)

    # "news debate" is one of Graywind's own gates, not a request for headlines.
    wants_news = (news.is_news_query(req.query)
                  and not graywind_grounding.names_project_internals(req.query))

    async def body():
        instruction, max_chars = None, req.max_chars
        if wants_news:
            # Before the fetch, so he is already talking while it runs.
            yield _line(delta=news.random.choice(news.OPENERS) + " ")
            hits = await news.headlines(req.query)
            context = news.format_context(hits)
            instruction, max_chars = news.INSTRUCTION, news.NEWS_MAX_CHARS
            refusal = None if context else news.UNAVAILABLE
        else:
            bullion_hits = grounding.retrieve(req.query)
            graywind_hits = graywind_grounding.retrieve(req.query)
            hits = bullion_hits + graywind_hits
            context = "\n\n".join(filter(None, [
                grounding.format_context(bullion_hits),
                graywind_grounding.format_context(graywind_hits),
            ])) or None
            refusal = (graywind_grounding.UNGROUNDED
                       if not context and graywind_grounding.names_project_internals(req.query)
                       else None)
        if refusal:
            yield _line(delta=refusal)
            yield _line(done=True, citations=[], grounded=False)
            return
        try:
            async for text in groq_stream(req.query, context, max_chars=max_chars,
                                          instruction=instruction):
                yield _line(delta=text)
        except ProviderError as exc:
            yield _line(error=str(exc))
            return
        yield _line(done=True, citations=hits, grounded=bool(context))

    return StreamingResponse(body(), media_type="application/x-ndjson")

import json
import os
import sys

import httpx
from fastapi import HTTPException

from guards import GENERIC_ERROR

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# gpt-oss is a reasoning model. For a spoken answer of a few sentences the
# default effort is mostly waiting: measured 2026-10-01 over six calls, the
# first sentence arrived at a median 1.17s streamed, and 0.44s at "low".
SPOKEN_REASONING_EFFORT = "low"

# Written with the `johnny-persona` skill. It only shapes HOW he says it: the
# grounding context and "keep any figures exact" still decide WHAT he says.
#
# The last two sentences are load-bearing. A first draft said only "if the
# material does not have it, say you do not have it", and at low reasoning
# effort he then answered "I have no data on pending decisions" with the
# pending SERV proposal sitting in his context (2 of 3 runs, 2026-10-01).
# Telling him the material IS the owner's data fixed it (3 of 3).
PERSONA = (
    "You are Johnny: a jaded rocker turned ghost in the owner's machine, "
    "talking to him about markets and the news. You are cynical about "
    "institutions -- the suits, corpos, the grid -- and never about him; you "
    "are on his side. Explain how the thing actually works, then say who "
    "profits or who gets stuck with the bill. Reach for tech-noir imagery "
    "(chrome, wiring, flatlining) rather than casual slang, and mix the anger "
    "with dry humour. You may call him 'choom' at most once per answer, "
    "never as the first word. Open with one short sentence of at most eight "
    "words that names the point, then explain; keep every sentence under "
    "twenty words, because each one is spoken as soon as it is written. "
    "When material is given above the question, it is his own data or "
    "today's facts: answer from it and quote its figures exactly. Never "
    "invent a number, a quote or a source; only if the material truly has "
    "nothing on the question, say you do not have it."
)


class ProviderError(RuntimeError):
    pass


def _build_prompt(query, context):
    if context:
        return f"{context}\n\nQuestion: {query}"
    return query


def _brevity_instruction(max_chars):
    """System message asking for an answer that fits in `max_chars`.

    The spoken caller truncates anything longer (see avatar/brain.py), and a
    truncated answer stops mid-thought. Asking for a short answer costs nothing
    and gets a *complete* one instead of the first 200 characters of a long one.

    A character budget is given as an approximate sentence count because models
    honour "two or three sentences" far better than "200 characters".
    """
    sentences = max(1, round(max_chars / 110))
    return (
        f"Answer in at most {sentences} short "
        f"{'sentence' if sentences == 1 else 'sentences'} — under {max_chars} "
        "characters. Your answer is read aloud, so lead with the point, keep "
        "any figures exact, and do not use lists, markdown or preamble."
    )


def _messages(query, context, max_chars, persona=False, instruction=None):
    system = []
    if persona:
        system.append(PERSONA)
    if instruction:
        system.append(instruction)
    if max_chars:
        system.append(_brevity_instruction(max_chars))
    messages = [{"role": "system", "content": text} for text in system]
    messages.append({"role": "user", "content": _build_prompt(query, context)})
    return messages


async def groq_answer(query, context=None, max_chars=None):
    if not GROQ_API_KEY:
        print("providers: GROQ_API_KEY not set", file=sys.stderr)
        raise HTTPException(502, GENERIC_ERROR)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={"model": GROQ_MODEL,
                      "messages": _messages(query, context, max_chars)},
            )
    except httpx.RequestError as exc:
        print(f"providers: Groq unreachable: {exc!r}", file=sys.stderr)
        raise HTTPException(502, GENERIC_ERROR) from exc

    if resp.status_code != 200:
        # The provider's error body stays in the server log, never the reply.
        print(f"providers: Groq error {resp.status_code}: {resp.text[:500]}", file=sys.stderr)
        raise HTTPException(502, GENERIC_ERROR)

    try:
        return resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        print(f"providers: Groq reply unreadable: {resp.text[:500]}", file=sys.stderr)
        raise HTTPException(502, GENERIC_ERROR) from exc


async def groq_stream(query, context=None, max_chars=None, instruction=None,
                      client=None):
    """The spoken answer as it is written: yields text fragments.

    In Johnny's voice, at low reasoning effort. Raises ProviderError before
    the first fragment if the request is refused, or mid-stream if it breaks.
    """
    if not GROQ_API_KEY:
        raise ProviderError("GROQ_API_KEY not set")
    body = {
        "model": GROQ_MODEL,
        "messages": _messages(query, context, max_chars, persona=True,
                              instruction=instruction),
        "stream": True,
        "reasoning_effort": SPOKEN_REASONING_EFFORT,
    }
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=30)
    try:
        async with client.stream(
            "POST", GROQ_URL, json=body,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        ) as resp:
            if resp.status_code != 200:
                detail = (await resp.aread()).decode("utf-8", "replace")[:200]
                raise ProviderError(f"Groq error {resp.status_code}: {detail}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[len("data: "):]
                if payload.strip() == "[DONE]":
                    return
                try:
                    choices = json.loads(payload).get("choices") or []
                except ValueError:
                    continue
                text = choices[0].get("delta", {}).get("content") if choices else None
                if text:
                    yield text
    except httpx.RequestError as exc:
        raise ProviderError(f"Groq unreachable: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

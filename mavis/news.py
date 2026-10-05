"""Today's headlines, for him to read out and have an opinion about.

Google News RSS: no key, and every item carries the outlet that published it
in a <source> tag, which is what lets him say where a headline came from
instead of reading it as his own knowledge. Fetched on demand and cached for
a few minutes; nothing here runs unless he is asked for the news.

A fetch that fails returns no headlines, and the caller says so out loud. He
must never fall through to the model's memory for "the news": it would recite
old events in the same confident tone, and nobody could hear the difference.
"""
import random
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import httpx

TOP_FEED = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
BUSINESS_FEED = ("https://news.google.com/rss/headlines/section/topic/BUSINESS"
                 "?hl=en-US&gl=US&ceid=US:en")
SEARCH_FEED = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

CACHE_SECONDS = 600
FETCH_TIMEOUT = 6.0
HEADLINES = 5
# Three headlines with a source and a line of commentary each will not fit
# the 200 characters an ordinary spoken answer gets.
NEWS_MAX_CHARS = 700

_NEWS_WORDS = re.compile(r"\b(news|headlines?|happening (today|in the world))\b", re.I)
_BUSINESS_WORDS = re.compile(
    r"\b(market|markets|business|financ\w*|econom\w*|stocks?|wall street|fed)\b", re.I)
# "news about/on X": what follows is the subject to search for.
_ABOUT = re.compile(r"\b(?:news|headlines?)\s+(?:about|on|for|from|regarding)\s+(.+)", re.I)

INSTRUCTION = (
    "He asked for the news. Using ONLY the headlines given, read out three of "
    "them, most important first. For each: say the headline in your own "
    "words, name the outlet it came from, and add one line of your own take. "
    "Do not add any event, figure or detail that is not in the headlines. "
    "Start straight on the first headline: an opening line has already been said."
)
# Said at once, before the feed is even fetched. The headlines take 2-3s to
# fetch and write up (measured 2026-10-01), which tripped the filler line and
# put his first word past 6s; this is spoken in under a second and is long
# enough to cover most of the wait. Must read naturally in front of
# UNAVAILABLE too.
OPENERS = (
    "Alright. Let me pull what the wires are carrying today.",
    "The news. Let me see what they're feeding the grid this morning.",
    "Give me a second, I'm pulling the wires.",
)
UNAVAILABLE = (
    "Can't reach the news feed right now, and I'm not going to recite "
    "yesterday's world from memory. Try me again in a minute."
)

_cache = {}


def is_news_query(query: str) -> bool:
    return bool(_NEWS_WORDS.search(query))


def feed_for(query: str) -> str:
    about = _ABOUT.search(query)
    if about:
        subject = re.sub(r"[^\w\s-]", " ", about.group(1)).strip()
        subject = re.sub(r"^(the|today'?s?)\s+", "", subject, flags=re.I)
        if subject and not re.fullmatch(r"(today|now|world|day)", subject, re.I):
            return SEARCH_FEED.format(query=quote_plus(subject))
    return BUSINESS_FEED if _BUSINESS_WORDS.search(query) else TOP_FEED


def parse_feed(xml_text: str, limit: int = HEADLINES) -> list[dict]:
    """[{title, source, published, link}] from a Google News RSS document."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.findtext("source") or "").strip()
        if not title:
            continue
        # Google appends " - Outlet" to every title; said aloud it would name
        # the outlet twice.
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        published = None
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "").isoformat()
        except (TypeError, ValueError):
            pass
        items.append({"type": "news", "title": title, "source": source or "unknown outlet",
                      "published": published, "link": (item.findtext("link") or "").strip()})
        if len(items) >= limit:
            break
    return items


async def headlines(query: str, *, client: httpx.AsyncClient | None = None,
                    now=time.monotonic) -> list[dict]:
    url = feed_for(query)
    cached = _cache.get(url)
    if cached and now() - cached[0] < CACHE_SECONDS:
        return cached[1]
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True)
    try:
        resp = await client.get(url)
    except httpx.RequestError:
        return []
    finally:
        if owns_client:
            await client.aclose()
    if resp.status_code != 200:
        return []
    items = parse_feed(resp.text)
    if items:
        _cache[url] = (now(), items)
    return items


def format_context(items: list[dict]) -> str | None:
    if not items:
        return None
    lines = ["Today's headlines, fetched just now (the only news you know):"]
    lines += [f"- \"{item['title']}\" -- {item['source']}" for item in items]
    return "\n".join(lines)

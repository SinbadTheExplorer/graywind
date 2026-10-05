"""Headlines: which questions want them, and what he is allowed to read out."""
import httpx
import pytest

import news

FEED = """<?xml version="1.0"?><rss><channel>
<item><title>Bond yields hit a 24-year high - Reuters</title><link>https://example.com/1</link>
<pubDate>Thu, 01 Oct 2026 10:00:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
<item><title>Mortgage rates keep climbing - The New York Times</title><link>https://example.com/2</link>
<pubDate>not a date</pubDate><source url="https://nytimes.com">The New York Times</source></item>
<item><title></title><source>Nobody</source></item>
<item><title>No source on this one</title></item>
</channel></rss>"""


@pytest.fixture(autouse=True)
def clear_cache():
    news._cache.clear()


@pytest.mark.parametrize("query", [
    "what's the news", "read me the headlines", "any news on the Fed?",
    "What is happening in the world today"])
def test_news_questions(query):
    assert news.is_news_query(query)


@pytest.mark.parametrize("query", [
    "what happens to gold when real yields fall", "is this newsworthy",
    "how does the Fed affect mortgage rates"])
def test_ordinary_questions_are_not_news(query):
    assert not news.is_news_query(query)


def test_the_feed_follows_the_question():
    assert news.feed_for("what's the news") == news.TOP_FEED
    assert news.feed_for("what's the news today") == news.TOP_FEED
    assert news.feed_for("what's the news in the markets today") == news.BUSINESS_FEED
    assert "q=oil+prices" in news.feed_for("any news about oil prices?")


def test_titles_lose_the_outlet_suffix_and_keep_the_outlet():
    items = news.parse_feed(FEED)
    assert [(i["title"], i["source"]) for i in items] == [
        ("Bond yields hit a 24-year high", "Reuters"),
        ("Mortgage rates keep climbing", "The New York Times"),
        ("No source on this one", "unknown outlet"),
    ]
    assert items[0]["published"].startswith("2026-10-01")
    assert items[1]["published"] is None


def test_a_document_that_is_not_xml_is_no_headlines():
    assert news.parse_feed("<html>blocked") == []


def test_the_context_names_every_outlet():
    context = news.format_context(news.parse_feed(FEED))
    assert "Reuters" in context and "The New York Times" in context
    assert news.format_context([]) is None


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_headlines_are_cached_between_questions():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text=FEED)

    async with _client(handler) as client:
        first = await news.headlines("what's the news", client=client)
        second = await news.headlines("what's the news", client=client)
    assert first == second and len(first) == 3
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_stale_cache_is_refetched():
    calls, clock = [], [0.0]

    def handler(request):
        calls.append(1)
        return httpx.Response(200, text=FEED)

    async with _client(handler) as client:
        await news.headlines("what's the news", client=client, now=lambda: clock[0])
        clock[0] = news.CACHE_SECONDS + 1
        await news.headlines("what's the news", client=client, now=lambda: clock[0])
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(503), httpx.Response(200, text="<html>")])
async def test_a_failed_fetch_is_no_headlines_and_is_not_cached(response):
    async with _client(lambda request: response) as client:
        assert await news.headlines("what's the news", client=client) == []
    assert news._cache == {}


@pytest.mark.asyncio
async def test_an_unreachable_feed_is_no_headlines():
    def handler(request):
        raise httpx.ConnectError("offline")

    async with _client(handler) as client:
        assert await news.headlines("what's the news", client=client) == []

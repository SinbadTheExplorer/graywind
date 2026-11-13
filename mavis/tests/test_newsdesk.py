"""Tests for mavis.newsdesk."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict

import pytest

import news  # the sibling module; we only need SEARCH_FEED constant
import newsdesk as nd


# --------------------------------------------------------------------------- #
# Helper to build a tiny RSS feed
# --------------------------------------------------------------------------- #
def make_rss(items: list[dict]) -> str:
    """Create a minimal RSS 2.0 document from a list of item dicts."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?><rss><channel>']
    for it in items:
        parts.append("<item>")
        for tag in ("title", "source", "pubDate", "link"):
            if tag in it:
                parts.append(f"<{tag}>{it[tag]}</{tag}>")
        parts.append("</item>")
    parts.append("</channel></rss>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def tmp_json_path(tmp_path: Path, monkeypatch):
    p = tmp_path / "news.json"
    monkeypatch.setenv("MAVIS_NEWS_FILE", str(p))
    return p


@pytest.fixture
def base_now():
    """Fixed ``now`` used for deterministic tests."""
    return datetime(2023, 1, 1, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_items_older_than_48h_are_dropped(tmp_json_path, base_now, monkeypatch):
    old = (base_now - timedelta(hours=49)).strftime("%a, %d %b %Y %H:%M:%S %z")
    recent = (base_now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S %z")
    feed = make_rss(
        [
            {"title": "Old news", "source": "CNBC", "pubDate": old, "link": "u"},
            {"title": "Recent news", "source": "CNBC", "pubDate": recent, "link": "v"},
        ]
    )
    fetch_map = {
        nd.MARKET_FEEDS[0][1]: feed,
    }

    def fetch(url):
        return fetch_map[url]

    envelope = nd.run([], fetch=fetch, now=base_now)
    titles = [i["title"] for i in envelope["items"]]
    assert titles == ["Recent news"]


def test_duplicate_titles_are_merged(tmp_json_path, base_now, monkeypatch):
    dt = (base_now - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S %z")
    feed1 = make_rss([{"title": "Same title", "source": "CNBC", "pubDate": dt, "link": "a"}])
    feed2 = make_rss([{"title": "Same title", "source": "Yahoo Finance", "pubDate": dt, "link": "b"}])
    fetch_map = {
        nd.MARKET_FEEDS[0][1]: feed1,
        nd.MARKET_FEEDS[1][1]: feed2,
    }

    def fetch(url):
        return fetch_map[url]

    envelope = nd.run([], fetch=fetch, now=base_now)
    assert len(envelope["items"]) == 1
    assert envelope["items"][0]["source"] in ("CNBC", "Yahoo Finance")


def test_symbol_tag_matches_whole_word_only(tmp_json_path, base_now, monkeypatch):
    dt = (base_now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S %z")
    feed = make_rss(
        [
            {"title": "AAPL rallies after earnings", "source": "CNBC", "pubDate": dt, "link": "x"},
            {"title": "PINEAPPLE AAPLX deal", "source": "CNBC", "pubDate": dt, "link": "y"},
        ]
    )
    fetch_map = {
        nd.MARKET_FEEDS[0][1]: feed,
        nd.MARKET_FEEDS[1][1]: feed,
        # Symbol search feeds – we don't need them for this test
    }

    def fetch(url):
        if url in fetch_map:
            return fetch_map[url]
        raise RuntimeError("unexpected URL")

    envelope = nd.run(["aapl"], fetch=fetch, now=base_now)
    items = envelope["items"]
    # Only the first item should have the symbol tag
    first, second = sorted(items, key=lambda i: i["title"])
    assert "AAPL" in first["symbols"]
    assert "AAPL" not in second["symbols"]


def test_one_failed_source_is_not_fatal(tmp_json_path, base_now, monkeypatch):
    dt = (base_now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S %z")
    good_feed = make_rss([{"title": "Good", "source": "CNBC", "pubDate": dt, "link": "g"}])
    fetch_map = {
        nd.MARKET_FEEDS[0][1]: good_feed,
        # second market feed will raise
    }

    def fetch(url):
        if url == nd.MARKET_FEEDS[0][1]:
            return good_feed
        raise RuntimeError("boom")

    envelope = nd.run([], fetch=fetch, now=base_now)
    assert envelope["failed_sources"] == [label for label, _ in nd.MARKET_FEEDS[1:]]
    assert envelope["items"]
    assert any(i["title"] == "Good" for i in envelope["items"])


def test_all_sources_failing_raises_and_keeps_old_file(tmp_json_path, base_now, monkeypatch):
    # write a pre‑existing file
    old_content = {"generated_at": "2000-01-01T00:00:00+00:00", "items": []}
    tmp_json_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_json_path.write_text(json.dumps(old_content), encoding="utf-8")

    def fetch(url):
        raise RuntimeError("failed")

    with pytest.raises(nd.NewsError):
        nd.run([], fetch=fetch, now=base_now)

    # file unchanged
    assert json.loads(tmp_json_path.read_text(encoding="utf-8")) == old_content


def test_write_is_atomic(tmp_json_path, base_now, monkeypatch):
    dt = (base_now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S %z")
    feed = make_rss([{"title": "Tmp", "source": "CNBC", "pubDate": dt, "link": "z"}])
    fetch_map = {nd.MARKET_FEEDS[0][1]: feed}

    def fetch(url):
        return fetch_map[url]

    # make json.dump raise after it has written to the temporary file
    original_dump = json.dump

    def bad_dump(obj, fp, *a, **kw):
        original_dump(obj, fp, *a, **kw)
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(json, "dump", bad_dump)

    with pytest.raises(RuntimeError):
        nd.run([], fetch=fetch, now=base_now)

    # No file should exist at the target location
    assert not tmp_json_path.exists()
    # No stray temp files left behind in the directory
    temps = list(tmp_json_path.parent.glob("*.tmp"))
    assert temps == []


def test_symbols_capped_at_8(tmp_json_path, base_now, monkeypatch):
    dt = (base_now - timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S %z")
    feed = make_rss([{"title": "X", "source": "CNBC", "pubDate": dt, "link": "x"}])
    fetch_map = {nd.MARKET_FEEDS[0][1]: feed}

    def fetch(url):
        return fetch_map[url]

    many_symbols = [f"S{i}" for i in range(12)]
    envelope = nd.run(many_symbols, fetch=fetch, now=base_now)
    assert len(envelope["symbols"]) == nd.MAX_SYMBOLS
    assert envelope["symbols"] == many_symbols[: nd.MAX_SYMBOLS]


def test_load_and_age_minutes(tmp_json_path, base_now, monkeypatch):
    dt = (base_now - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S %z")
    feed = make_rss([{"title": "LoadMe", "source": "CNBC", "pubDate": dt, "link": "l"}])
    fetch_map = {nd.MARKET_FEEDS[0][1]: feed}

    def fetch(url):
        return fetch_map[url]

    envelope = nd.run([], fetch=fetch, now=base_now)
    loaded = nd.load()
    assert loaded == envelope

    later = base_now + timedelta(minutes=30)
    age = nd.age_minutes(loaded, later)
    # Approximately 30 minutes (allow small drift)
    assert abs(age - 30) < 1.0

    # Invalid envelope → inf
    assert nd.age_minutes(None, later) == float("inf")

"""Mavis newsdesk – fetch, filter and store market‑related news."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, List, Tuple

import httpx

import jsonfile
import news  # the sibling module that provides `parse_feed` and `SEARCH_FEED`

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

MARKET_FEEDS: List[Tuple[str, str]] = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("Yahoo Finance", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^DJI&region=US&lang=en-US"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("MW Bulletins", "https://feeds.content.dowjones.io/public/rss/mw_bulletins"),
]

MAX_SYMBOLS = 8
MAX_AGE_HOURS = 48
PER_FEED_LIMIT = 30
FETCH_TIMEOUT = 10

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #


def news_path() -> Path:
    """Path to the JSON file that stores the latest news envelope."""
    env_path = os.getenv("MAVIS_NEWS_FILE", "/var/lib/mavis/news.json")
    return Path(env_path)


def default_fetch(url: str) -> str:
    """Retrieve *url* via HTTP GET, raising on non‑200 responses."""
    resp = httpx.get(
        url,
        timeout=FETCH_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "johnny-newsdesk/1.0"},
    )
    resp.raise_for_status()
    return resp.text


class NewsError(RuntimeError):
    """Raised when *all* sources fail to fetch."""


# --------------------------------------------------------------------------- #
# Core logic
# --------------------------------------------------------------------------- #


def _normalise_title(title: str) -> str:
    """Lower‑case, collapse whitespace and strip punctuation."""
    title = re.sub(r"[^\w\s]", " ", title.lower())
    return re.sub(r"\s+", " ", title).strip()


_WORD_REGEX_CACHE: dict[str, re.Pattern] = {}


def _word_regex(sym: str) -> re.Pattern:
    """Compile a whole‑word regex for *sym* (case‑sensitive)."""
    if sym not in _WORD_REGEX_CACHE:
        _WORD_REGEX_CACHE[sym] = re.compile(
            rf"(?<![A-Za-z0-9]){re.escape(sym)}(?![A-Za-z0-9])"
        )
    return _WORD_REGEX_CACHE[sym]


def run(
    symbols: List[str],
    *,
    fetch: Callable[[str], str] | None = None,
    now: datetime | None = None,
) -> dict:
    """
    Fetch news for *symbols* and write the result atomically.

    Returns the envelope that was written.
    """
    fetch = fetch or default_fetch
    now = now or datetime.now(timezone.utc)

    # ------------------------------------------------------------------- #
    # Normalise symbols
    # ------------------------------------------------------------------- #
    seen = set()
    clean_symbols: List[str] = []
    for s in symbols:
        s_up = (s or "").strip().upper()
        if s_up and s_up not in seen:
            seen.add(s_up)
            clean_symbols.append(s_up)
        if len(clean_symbols) >= MAX_SYMBOLS:
            break

    # ------------------------------------------------------------------- #
    # Build source list (label, url, optional symbol)
    # ------------------------------------------------------------------- #
    sources: List[Tuple[str, str, str | None]] = []  # (label, url, symbol_if_search)
    for label, url in MARKET_FEEDS:
        sources.append((label, url, None))

    for sym in clean_symbols:
        label = f"{sym} news"
        query = urllib.parse.quote_plus(f'"{sym}" stock')
        url = news.SEARCH_FEED.format(query=query)
        sources.append((label, url, sym))

    # ------------------------------------------------------------------- #
    # Fetch + parse
    # ------------------------------------------------------------------- #
    all_items: List[dict] = []
    failed_sources: List[str] = []
    any_success = False

    for label, url, origin_sym in sources:
        try:
            txt = fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"newsdesk: {label} failed: {type(exc).__name__}", file=sys.stderr)
            failed_sources.append(label)
            continue

        parsed = news.parse_feed(txt, limit=PER_FEED_LIMIT)
        if not parsed:
            # A dead feed often still answers 200 with an error page: a
            # source counts only when it yields headlines.
            if origin_sym is None:
                print(f"newsdesk: {label} returned no headlines", file=sys.stderr)
                failed_sources.append(label)
            continue
        any_success = True

        # Adjust source for market feeds when needed
        for it in parsed:
            if origin_sym is None and it["source"] == "unknown outlet":
                it["source"] = label

            # stash origin for later symbol‑tagging
            it["__origin_label"] = label
            it["__origin_sym"] = origin_sym
            all_items.append(it)

    if not any_success:
        raise NewsError("All sources failed")

    # ------------------------------------------------------------------- #
    # Filter by age / missing published
    # ------------------------------------------------------------------- #
    def _parse_iso(iso: str | None) -> datetime | None:
        if not iso:
            return None
        try:
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:  # pragma: no cover
            return None

    cutoff = now - timedelta(hours=MAX_AGE_HOURS)
    future_limit = now + timedelta(hours=1)

    filtered: List[dict] = []
    for it in all_items:
        pub_dt = _parse_iso(it.get("published"))
        if pub_dt is None:
            continue
        if pub_dt < cutoff or pub_dt > future_limit:
            continue
        it["_pub_dt"] = pub_dt  # keep for sorting later
        filtered.append(it)

    # ------------------------------------------------------------------- #
    # De‑duplicate by normalised title (keep first encountered)
    # ------------------------------------------------------------------- #
    kept: dict[str, dict] = {}
    deduped: List[dict] = []
    for it in filtered:
        norm = _normalise_title(it["title"])
        if norm in kept:
            # The same story from a symbol search still says which symbol.
            kept[norm].setdefault("__also", set()).add(it.get("__origin_sym"))
            continue
        kept[norm] = it
        deduped.append(it)

    # ------------------------------------------------------------------- #
    # Symbol tagging
    # ------------------------------------------------------------------- #
    for it in deduped:
        title = it["title"]
        symbols_found: List[str] = []

        for sym in clean_symbols:
            if _word_regex(sym).search(title):
                symbols_found.append(sym)

        for origin_sym in {it.get("__origin_sym")} | it.pop("__also", set()):
            if origin_sym and origin_sym not in symbols_found:
                symbols_found.append(origin_sym)

        # Preserve order of `clean_symbols`
        it["symbols"] = [sym for sym in clean_symbols if sym in symbols_found]

        # Clean temporary helpers
        it.pop("__origin_label", None)
        it.pop("__origin_sym", None)

    # ------------------------------------------------------------------- #
    # Final sort (newest first) and envelope creation
    # ------------------------------------------------------------------- #
    deduped.sort(key=lambda i: i["_pub_dt"], reverse=True)
    for it in deduped:
        it.pop("_pub_dt", None)  # not part of the public schema

    envelope = {
        "generated_at": now.isoformat(),
        "symbols": clean_symbols,
        "items": deduped,
        "failed_sources": failed_sources,
    }

    # ------------------------------------------------------------------- #
    # Write atomically
    # ------------------------------------------------------------------- #
    jsonfile.write_atomic(news_path(), envelope, mode=0o644)
    return envelope


def load() -> dict | None:
    """Load the persisted envelope, returning ``None`` on any error."""
    p = news_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "generated_at" in data and "items" in data:
            return data
    except Exception:  # pragma: no cover
        return None
    return None


def age_minutes(envelope: dict | None, now: datetime) -> float:
    """Return minutes elapsed since ``envelope['generated_at']``."""
    if envelope is None:
        return float("inf")
    try:
        gen = datetime.fromisoformat(envelope["generated_at"])
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=timezone.utc)
        diff = now - gen
        return diff.total_seconds() / 60.0
    except Exception:  # pragma: no cover
        return float("inf")

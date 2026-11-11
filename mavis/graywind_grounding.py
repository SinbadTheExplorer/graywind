"""Keyword-retrieval module for Graywind grounding facts.

The facts are a snapshot produced by scripts/extract_graywind_grounding.py
(on the server, every 15 minutes by graywind-sync.timer). The file is
re-read when it changes; a bad or partial file keeps the last good facts.
No live account read happens here.
"""
import json
import os
import sys
import threading

from text_scoring import score_overlap, tokenize

# The server points this at /var/lib/mavis (refreshed by graywind-sync), so
# the code directory can stay read-only for the service.
_GROUNDING_PATH = os.environ.get("MAVIS_GRAYWIND_FACTS") or os.path.join(
    os.path.dirname(__file__), "data", "graywind_grounding.json")

# Fact text is ordinary English prose (e.g. "awaiting manual approval"), so
# a single overlap on a common word is not a real signal -- same reasoning
# as grounding.py's _STRONG_TERMS/MIN_SCORE=2. Tags are the deliberately
# curated match points (symbols, "watchlist", "decision", "pending",
# account names); a tag match counts double, a plain-text-only match once.
# "graywind" is a namespace marker build_facts() adds to every fact
# unconditionally -- a structural certainty, not a data-dependent one --
# so it carries zero discriminating power and is excluded by name. This
# is deliberately NOT "any tag not on every fact" (a document-frequency
# rule considered and rejected): with a single-symbol watchlist, that
# symbol's own tag would legitimately appear on every fact too, and a
# frequency-based rule would wrongly demote the one tag a query about
# that symbol most needs to hit strong on.
_STRUCTURAL_TAGS = {"graywind"}
MIN_SCORE = 2

_FACTS: list[dict] = []
_STRONG_TERMS: set[str] = set()
_lock = threading.Lock()
_loaded_stamp = None    # (mtime_ns, size) of the file behind _FACTS
_bad_stamp = None       # the last file that failed to load (warned once)


def _valid(data) -> bool:
    return (isinstance(data, dict) and isinstance(data.get("facts"), list)
            and all(isinstance(f, dict) and isinstance(f.get("id"), str)
                    and isinstance(f.get("text"), str) and isinstance(f.get("tags"), list)
                    and all(isinstance(t, str) for t in f["tags"])
                    for f in data["facts"]))


def _refresh() -> None:
    """Reload the facts if the file changed; keep the last good ones if not readable."""
    global _FACTS, _STRONG_TERMS, _loaded_stamp, _bad_stamp
    try:
        st = os.stat(_GROUNDING_PATH)
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = "missing"
    with _lock:
        if stamp in (_loaded_stamp, _bad_stamp):
            return
        try:
            if stamp == "missing":
                raise FileNotFoundError(_GROUNDING_PATH)
            with open(_GROUNDING_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if not _valid(data):
                raise ValueError("not a {facts: [{id, text, tags}]} file")
        except (OSError, ValueError) as exc:
            print(f"graywind_grounding: keeping last good facts ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
            _bad_stamp = stamp
            return
        _FACTS = data["facts"]
        _STRONG_TERMS = {tag for fact in _FACTS for tag in fact["tags"]} - _STRUCTURAL_TAGS
        _loaded_stamp, _bad_stamp = stamp, None


_refresh()


def retrieve(query: str, top_k: int = 5) -> list[dict]:
    """Keyword-match the query against Graywind's own decision/pending/
    watchlist facts (built at snapshot time by
    scripts/extract_graywind_grounding.py -- no live account read
    happens here or at request time).
    """
    _refresh()
    with _lock:    # one generation of facts and strong terms, never a mix
        facts, strong_terms = _FACTS, _STRONG_TERMS
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    scored = []
    for fact in facts:
        haystack_tokens = set(fact["tags"]) | tokenize(fact["text"])
        overlap = query_tokens & haystack_tokens
        score = score_overlap(overlap, strong_terms)
        if score >= MIN_SCORE:
            scored.append((score, {
                "type": "graywind_fact",
                "id": fact["id"],
                "text": fact["text"],
            }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for score, item in scored[:top_k]]


def format_context(hits: list[dict]) -> str | None:
    if not hits:
        return None
    header = (
        "Live-ish state from your own Graywind trading bot (snapshot, may "
        "be stale by up to a build cycle -- not a live account read):"
    )
    lines = [header] + [f"- {hit['text']}" for hit in hits]
    return "\n".join(lines)

# Terms that name something only THIS project has. Frequencies were taken from
# the repo itself rather than invented: tier_pools 303, macro_gate 190,
# vix_gate 98, drawdown breaker 30, deflated sharpe 17.
#
# They exist because an ungrounded answer about the owner's OWN trading system
# is worse than no answer, and the failure is invisible: asked "what is the
# macro gate" the model returned a confident description of an electronics
# component, and asked "how much capital does tier 1 get" it returned Basel III
# bank capital ratios -- both with zero citations, in the same tone as a
# correct answer. A person cannot tell those apart by listening.
#
# Deliberately hand-maintained. Deriving it from the corpus would be circular:
# the whole point is to catch questions the corpus CANNOT answer.
PROJECT_TERMS = (
    "macro gate", "macro_gate", "vix gate", "vix_gate", "volatility gate",
    "sentiment gate", "backtest gate", "tier pool", "tier pools", "tier_pools",
    "tier 1", "tier 2", "tier 3", "drawdown breaker", "rolling breaker",
    "kill check", "edge thesis", "deflated sharpe", "position cap",
    "news debate", "trade approval", "graywind",
)

UNGROUNDED = (
    "That's one of mine and I don't have it in what I've been given, so I'd "
    "only be guessing. Nothing in the corpus covers it."
)


def names_project_internals(query: str) -> bool:
    """True if the query asks about something only this project has.

    Used to decide whether an empty retrieval should REFUSE rather than fall
    through to the model's general knowledge. "What is gold" deserves a
    general answer; "what is the macro gate" does not.
    """
    lowered = f" {query.lower()} "
    return any(term in lowered for term in PROJECT_TERMS)

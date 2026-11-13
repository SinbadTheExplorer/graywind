# briefing.py
import asyncio
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Awaitable, Callable, List, Mapping, Optional

import graywind_state
import newsdesk
import push
import providers

CT = ZoneInfo("America/Chicago")


# --------------------------------------------------------------------------- #
# 1. Formatting helpers
# --------------------------------------------------------------------------- #
def fmt_money(x: float) -> str:
    """$99,584 – no cents, commas every three digits."""
    return f"${int(round(x)):,}"


def fmt_price(x: float) -> str:
    """$348.07 – two decimal places, commas."""
    return f"${x:,.2f}"


def fmt_pct(x: float) -> str:
    """0.7% – one decimal place, absolute value."""
    return f"{abs(x):.1f}%"


# --------------------------------------------------------------------------- #
# 2. Fact generation
# --------------------------------------------------------------------------- #
def facts(
    kind: str,
    snap: Optional[Mapping[str, Any]],
    news: Optional[Mapping[str, Any]],
    info_events: List[Mapping[str, Any]],
    now: datetime,
) -> List[str]:
    """Build a list of brief facts for the given kind ('close' or 'night')."""
    today_iso = now.astimezone(CT).date().isoformat()
    out: List[str] = []

    # ----- data availability -------------------------------------------------
    if snap is None or not snap.get("ok", False):
        out.append("Graywind's data is unavailable right now.")
        return out

    # ----- quiet day ---------------------------------------------------------
    decisions_total = sum(
        acct.get("decisions_today", 0) for acct in snap.get("accounts", {}).values()
    )
    if decisions_total == 0:
        out.append("Quiet day: Graywind made no decisions today.")

    # ----- account equity ----------------------------------------------------
    for acct_name, label in (("100k", "100k"), ("small", "Small")):
        acct = snap["accounts"].get(acct_name)
        if not acct:
            continue

        equity = acct.get("equity")
        prev = acct.get("prev_equity")
        equity_day = acct.get("equity_day")
        if equity is not None and prev is not None and equity_day == today_iso:
            change = equity - prev
            if round(abs(change) / prev * 100, 1) == 0:
                out.append(
                    f"{label} account: {fmt_money(equity)}, flat today."
                )
            else:
                pct = abs(change) / prev * 100
                direction = "up" if change > 0 else "down"
                out.append(
                    f"{label} account: {fmt_money(equity)}, {direction} {fmt_pct(pct)} today ({fmt_money(abs(change))})."
                )
        elif equity is not None:
            out.append(f"{label} account: {fmt_money(equity)}, no update for today.")

    # ----- open positions ----------------------------------------------------
    merged: dict[str, Mapping[str, Any]] = {}
    for acct in snap["accounts"].values():
        for pos in acct.get("positions", []):
            sym = pos["symbol"]
            if sym not in merged:
                merged[sym] = pos

    if merged:
        for sym, pos in merged.items():
            levels = [f"{name} {fmt_price(pos[name])}" for name in ("stop", "target")
                      if pos.get(name) is not None]
            # "bought at", not "from": a model read "AAPL from $348.07" as
            # AAPL trading at $348.07.
            entry = f", bought at {fmt_price(pos['entry'])}" if pos.get("entry") is not None else ""
            out.append(f"Holding {sym}{entry}" + (f" ({', '.join(levels)})." if levels else "."))
    else:
        out.append("No open positions.")

    # ----- buys today ---------------------------------------------------------
    buys_seen: List[str] = []
    for acct in snap["accounts"].values():
        for b in acct.get("buys_today", []):
            if b not in buys_seen:
                buys_seen.append(b)

    if buys_seen:
        out.append(f"Bought today: {', '.join(buys_seen)}.")
    else:
        out.append("No new buys today.")

    # ----- info events --------------------------------------------------------
    for ev in info_events[:3]:
        txt = ev.get("text")
        if txt:
            out.append(txt)

    # ----- night‑only news ----------------------------------------------------
    if kind == "night":
        symbols_of_interest = set(merged.keys()) | set(snap.get("watchlist", []))
        if news is None:
            out.append("News feed unavailable.")
        else:
            items = news.get("items", [])
            # First up‑to‑3 headlines that mention a symbol of interest
            matched_symbols = set()
            for item in items:
                item_syms = set(item.get("symbols", []))
                intersect = item_syms & symbols_of_interest
                if intersect:
                    sym = next(iter(intersect))
                    out.append(
                        f'News on {sym}: "{item["title"]}" ({item["source"]}).'
                    )
                    matched_symbols.add(sym)
                    if sum(f.startswith("News on ") for f in out) >= 2:
                        break
            # Then up to 2 more latest headlines (any symbols)
            extra = 0
            for item in items:
                if extra >= 1:
                    break
                # skip if already used
                if any(item["title"] in f for f in out):
                    continue
                out.append(
                    f'Market: "{item["title"]}" ({item["source"]}).'
                )
                extra += 1

    # ----- pending ------------------------------------------------------------
    pending = snap.get("pending", [])
    if pending:
        groups: dict = {}
        for p in pending:
            groups.setdefault((p["symbol"], p["side"]), []).append(f"#{p['issue']}")
        for (sym, side), issues in groups.items():
            what = "proposal" if len(issues) == 1 else f"{len(issues)} proposals"
            out.append(f"Waiting on you: {sym} {side} {what} ({', '.join(issues)}).")
    else:
        # If there is no pending and we haven't already added a fact that implies
        # something urgent, add a generic one.
        out.append("Nothing needs you.")

    return out


# --------------------------------------------------------------------------- #
# 3. Template fallback
# --------------------------------------------------------------------------- #
def template(kind: str, facts_list: List[str]) -> str:
    prefix = "Close wrap: " if kind == "close" else "Night brief: "
    return prefix + " ".join(facts_list)


# --------------------------------------------------------------------------- #
# 4. Guard
# --------------------------------------------------------------------------- #
_number_re = re.compile(r"\d[\d,]*(?:\.\d+)?")
_sentence_re = re.compile(r"[.!?]+(?=\s|$)")


def _extract_numbers(text: str) -> set[str]:
    nums = set()
    for m in _number_re.finditer(text):
        n = m.group(0).replace(",", "")
        if n.endswith(".0"):
            n = n[:-2]
        nums.add(n)
    return nums


def guard_ok(text: str, facts_list: List[str]) -> bool:
    if not text.strip():
        return False
    if len(_sentence_re.findall(text)) > 3:
        return False

    # numbers in the generated text must appear in the facts
    text_nums = _extract_numbers(text)
    facts_nums = set()
    for f in facts_list:
        facts_nums.update(_extract_numbers(f))

    return text_nums.issubset(facts_nums)


# --------------------------------------------------------------------------- #
# 5. Compose (LLM)
# --------------------------------------------------------------------------- #
# Not PERSONA: that one is tuned for spoken answers ("open with a short
# point, then explain") and turns a text into a list of headings.
BRIEF_STYLE = (
    "You are Johnny, the owner's AI fixer: a jaded rocker ghost in the machine "
    "who runs his paper-trading bot while he gets on with life. Text him the "
    "way a calm, competent butler-AI would, with your own dry tech-noir edge: "
    "short, confident, no headings, no lists, no markdown. At most 3 "
    "sentences: first the money, then what moved or what's worth knowing, "
    "then what needs him (or that nothing does). At most one touch of "
    "sarcasm. You may call him 'choom' once. Use ONLY the facts given; you may "
    "leave out the less important ones, but never change, round or invent a "
    "number, name or quote."
)
RETRY_AFTER_SECONDS = 8


async def compose(
    kind: str,
    facts_list: List[str],
    ask: Optional[Callable[[str], Awaitable[str]]] = None,
    *,
    retry_after: float | None = None,
) -> str:
    """Johnny's version of the brief, or the template if he can't be trusted."""
    if ask is None:
        ask = providers.groq_answer
    what = "market-close wrap" if kind == "close" else "night brief"
    prompt = (f"{BRIEF_STYLE}\n\nWrite tonight's {what}.\n\nFacts:\n"
              + "\n".join(f"- {f}" for f in facts_list))
    if retry_after is None:
        retry_after = RETRY_AFTER_SECONDS
    raw = None
    for attempt in range(2):     # once more after a rate limit or a blip
        try:
            raw = (await ask(prompt) or "").strip()
            break
        except Exception:  # noqa: BLE001 -- any failure falls back to the template
            if attempt == 0 and retry_after:
                await asyncio.sleep(retry_after)
    if raw and guard_ok(raw, facts_list):
        return raw
    return template(kind, facts_list)


# --------------------------------------------------------------------------- #
# 6. Run
# --------------------------------------------------------------------------- #
def run(
    kind: str,
    now: Optional[datetime] = None,
    info_events: Optional[List[Mapping[str, Any]]] = None,
    *,
    ask: Optional[Callable[[str], Awaitable[str]]] = None,
    send: Optional[Callable[..., bool]] = None,
    snap: Optional[Mapping[str, Any]] = None,
    news: Optional[Mapping[str, Any]] = None,
) -> str:
    """Orchestrate a brief and (optionally) push it."""
    if now is None:
        now = datetime.now(timezone.utc)

    if snap is None:
        try:
            snap = graywind_state.snapshot(graywind_state.repo_path(), now)
        except Exception:
            snap = None

    if news is None:
        news = newsdesk.load()

    if info_events is None:
        info_events = []

    facts_list = facts(kind, snap, news, info_events, now)

    text = asyncio.run(compose(kind, facts_list, ask=ask))

    title = "Johnny: close wrap" if kind == "close" else "Johnny: night brief"
    dedupe_key = f"brief:{kind}:{now.astimezone(CT).date().isoformat()}"
    if send is None:
        send = push.send
    send(title, text, dedupe=dedupe_key)

    return text

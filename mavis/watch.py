# watch.py
import os
import json
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────
CT = ZoneInfo('America/Chicago')

DROP_PCT = 1.0                     # percent drop that triggers an urgent alert
SILENT_MINUTES = 75                # minutes without a decision that triggers an urgent alert
NEWS_STALE_MINUTES = 65            # minutes after which news is considered stale
MARKET_OPEN = time(8, 30)          # regular market open (CT)
MARKET_CLOSE = time(15, 0)         # regular market close (CT)

MARKET_HOLIDAYS = {
    '2026-11-26', '2026-12-25', '2027-01-01', '2027-01-18',
    '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18',
    '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24',
}
EARLY_CLOSE = {
    '2026-11-27': time(12, 0),
    '2026-12-24': time(12, 0),
}
LABELS = {'100k': '100k', 'small': 'Small'}

# ──────────────────────────────────────────────────────────────────────────────
# Helper imports – these will be monkey‑patched in the test‑suite
# ──────────────────────────────────────────────────────────────────────────────
import graywind_state          # provides snapshot() and repo_path()
import newsdesk                # load() and age_minutes()
import events                  # add()
import reach                   # deliver()
import push                    # PushError, calls_today(), MAX_CALLS_PER_DAY
import jsonfile                # read(), write_atomic(), locked()
from briefing import fmt_money, fmt_pct


# ──────────────────────────────────────────────────────────────────────────────
def watch_path() -> str:
    """Path to the JSON file that stores the last known position snapshot."""
    return os.getenv('MAVIS_WATCH_FILE', '/var/lib/mavis/watch.json')


def market_open_now(now: datetime) -> bool:
    """Return ``True`` if the supplied ``now`` (UTC aware) falls within market
    hours for the Chicago time‑zone, taking holidays and early‑close days into
    account."""
    ct_now = now.astimezone(CT)
    if ct_now.weekday() > 4:                     # Saturday / Sunday
        return False

    date_iso = ct_now.date().isoformat()
    if date_iso in MARKET_HOLIDAYS:
        return False

    open_time = MARKET_OPEN
    close_time = EARLY_CLOSE.get(date_iso, MARKET_CLOSE)

    return open_time <= ct_now.time() < close_time


def run(
    now: datetime | None = None,
    *,
    snap: dict | None = None,
    news: dict | None = None,
    deliver=None,
) -> list[dict]:
    """
    Main entry point.

    Returns a list of event dictionaries that were *created* during this run
    (both urgent and info events).  Urgent events are delivered via the
    ``deliver`` callable; any delivery error is re‑raised after the new
    baseline has been persisted.
    """
    now = now or datetime.now(timezone.utc)
    deliver = reach.deliver if deliver is None else deliver
    ct_now = now.astimezone(CT)
    today_iso = ct_now.date().isoformat()

    # --------------------------------------------------------------------- #
    # 1️⃣  Load snapshot & news (unless caller supplied them)
    # --------------------------------------------------------------------- #
    if snap is None:
        try:
            snap = graywind_state.snapshot(graywind_state.repo_path(), now)
        except Exception:          # any problem reading the state
            snap = None

    if news is None:
        news = newsdesk.load()

    # --------------------------------------------------------------------- #
    # 2️⃣  Load the persisted baseline (may be ``None`` on the very first run)
    # --------------------------------------------------------------------- #
    baseline = jsonfile.read(watch_path(), None)

    # --------------------------------------------------------------------- #
    # 3️⃣  Build the *current* position map from the snapshot (if possible)
    # --------------------------------------------------------------------- #
    current_positions: dict[str, list[str]] = {}
    if snap and snap.get('ok'):
        old = (baseline or {}).get('positions', {})
        for acct, data in snap.get('accounts', {}).items():
            if 'positions.csv' in data.get('missing', []):
                # Unreadable is not "everything closed": keep what we knew.
                current_positions[acct] = old.get(acct, [])
                continue
            current_positions[acct] = [
                pos.get('symbol')
                for pos in data.get('positions', [])
                if isinstance(pos, dict)
            ]
    elif baseline:
        # keep the previous map when we cannot read the state
        current_positions = baseline.get('positions', {})

    # --------------------------------------------------------------------- #
    # 4️⃣  First‑run handling – persist the baseline and exit early
    # --------------------------------------------------------------------- #
    if baseline is None:
        jsonfile.write_atomic(
            watch_path(),
            {'positions': current_positions, 'saved': now.isoformat()},
        )
        return []

    new_events: list[dict] = []

    # --------------------------------------------------------------------- #
    # 5️⃣  Urgent checks
    # --------------------------------------------------------------------- #

    # 5.1  Account‑drop check
    if snap and snap.get('ok'):
        for acct, data in snap.get('accounts', {}).items():
            equity = data.get('equity')
            prev = data.get('prev_equity')
            equity_day = data.get('equity_day')
            if equity is None or prev is None or equity_day != today_iso:
                continue
            change_pct = (equity - prev) / prev * 100
            if change_pct <= -DROP_PCT:
                label = LABELS.get(acct, acct)
                msg = (
                    f"{label} account is down {fmt_pct(change_pct)} today "
                    f"({fmt_money(prev - equity)}), now {fmt_money(equity)}."
                )
                ev = events.add(
                    'drop',
                    'urgent',
                    msg,
                    key=f'drop:{acct}', now=now,
                )
                if ev:
                    new_events.append(ev)

    # 5.2  Silent‑Graywind check (only during market hours)
    if market_open_now(now):
        if snap and snap.get('ok'):
            last = snap.get('last_decision')
            minutes = float('inf') if last is None else (now - last).total_seconds() / 60
            if minutes > SILENT_MINUTES:
                when = 'a while' if last is None else f'{int(minutes)} minutes'
                msg = (
                    f"Graywind has gone quiet: no decision for {when} "
                    "during market hours."
                )
                ev = events.add('silent', 'urgent', msg, key='silent', now=now)
                if ev:
                    new_events.append(ev)

    # 5.3  State‑unavailable check (only during market hours)
    if market_open_now(now) and (snap is None or not snap.get('ok')):
        ev = events.add(
            'state_unavailable',
            'urgent',
            "I can't read Graywind's state right now.",
            key='state_unavailable', now=now,
        )
        if ev:
            new_events.append(ev)

    # 5.4  Stale‑news check
    age = newsdesk.age_minutes(news, now)
    if age > NEWS_STALE_MINUTES:
        msg = 'My news feed is stale'
        if age != float('inf'):
            msg += f' ({int(age)} minutes old)'
        msg += '.'
        ev = events.add('news_stale', 'urgent', msg, key='news_stale', now=now)
        if ev:
            new_events.append(ev)

    # --------------------------------------------------------------------- #
    # 6️⃣  Info check – closed positions
    # --------------------------------------------------------------------- #
    baseline_positions = baseline.get('positions', {})
    for acct, old_syms in baseline_positions.items():
        now_syms = current_positions.get(acct, [])
        for sym in old_syms:
            if sym not in now_syms:
                label = LABELS.get(acct, acct)
                msg = f'{sym} position closed in the {label} account.'
                ev = events.add(
                    'closed',
                    'info',
                    msg,
                    key=f'closed:{acct}:{sym}', now=now,
                )
                if ev:
                    new_events.append(ev)

    # --------------------------------------------------------------------- #
    # 7️⃣  Deliver urgent events (ignore info events)
    # --------------------------------------------------------------------- #
    # Every urgent event not yet delivered, including one a failed push left
    # behind on an earlier run: dedupe stops it being re-added, so this is
    # the only retry it gets.
    first_error = None
    for ev in events.undelivered_urgent(now=now):
        try:
            deliver(ev, now)
        except Exception as exc:          # includes push.PushError
            if first_error is None:
                first_error = exc

    # --------------------------------------------------------------------- #
    # 8️⃣  Persist the new baseline (always!)
    # --------------------------------------------------------------------- #
    jsonfile.write_atomic(
        watch_path(),
        {'positions': current_positions, 'saved': now.isoformat()},
    )

    # --------------------------------------------------------------------- #
    # 9️⃣  Propagate the first delivery error, if any
    # --------------------------------------------------------------------- #
    if first_error:
        raise first_error

    return new_events

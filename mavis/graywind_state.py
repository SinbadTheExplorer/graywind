# graywind_state.py
import csv
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import List, Dict, Any, Tuple, Optional

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
ACCOUNTS: List[Tuple[str, str]] = [
    ("100k", "state"),
    ("small", "state/small"),
]
CT = ZoneInfo("America/Chicago")
EXPECTED_FILES = ("equity_history.csv", "positions.csv", "pending_trades.csv", "decision_log.csv")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _parse_float(value: str) -> Optional[float]:
    """Convert a CSV numeric string to float, treating empty strings as None."""
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _read_csv(path: Path) -> List[Dict[str, str]]:
    """Read a CSV file safely, returning a list of rows as dicts.
    Empty or unreadable files return an empty list.
    """
    if not path.is_file():
        raise FileNotFoundError
    with path.open(newline="") as f:
        try:
            return list(csv.DictReader(f))
        except Exception as exc:
            raise IOError(f"Unable to read CSV {path}: {exc}") from exc


def _read_equity(file_path: Path) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    # Only rows with a day and a number count: a half-written last line
    # must not read as equity (and fake a 99% loss).
    rows = [r for r in _read_csv(file_path)
            if r.get("day") and _parse_float(r.get("equity")) is not None]
    # A last row under half of the one before is a truncated write, not a day.
    if len(rows) >= 2 and _parse_float(rows[-1]["equity"]) < 0.5 * _parse_float(rows[-2]["equity"]):
        rows = rows[:-1]
    if not rows:
        return None, None, None
    last = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else None
    equity = _parse_float(last["equity"])
    prev_equity = _parse_float(prev["equity"]) if prev else None
    return equity, prev_equity, last["day"]


def _read_positions(file_path: Path) -> List[Dict[str, Any]]:
    rows = _read_csv(file_path)
    out = []
    for r in rows:
        if not (r.get("symbol") or "").strip():
            continue
        out.append(
            {
                "symbol": r.get("symbol").strip(),
                "entry": _parse_float(r.get("entry_price")),
                "shares": _parse_float(r.get("shares")),
                "stop": _parse_float(r.get("stop")),
                "target": _parse_float(r.get("target")),
            }
        )
    return out


def _read_pending(file_path: Path) -> List[Dict[str, Any]]:
    rows = _read_csv(file_path)
    out = []
    for r in rows:
        if not (r.get("symbol") or "").strip():
            continue
        out.append(
            {
                "symbol": r.get("symbol").strip(),
                "issue": r.get("issue_number"),
                "side": r.get("side"),
                "qty": _parse_float(r.get("qty")),
                "price": _parse_float(r.get("price_at_proposal")),
            }
        )
    return out


def _read_decisions(
    file_path: Path,
    today_ct: datetime.date,
) -> Tuple[
    List[str],  # buys_today (ordered)
    int,  # blocked_today
    int,  # decisions_today
    set,  # recent_symbols (last 7 days)
    Optional[datetime],  # newest timestamp in this file
]:
    rows = _read_csv(file_path)
    buys_today: List[str] = []
    blocked_today = 0
    decisions_today = 0
    recent_symbols: set = set()
    newest_ts: Optional[datetime] = None

    for r in rows:
        ts_raw = r.get("timestamp")
        symbol = (r.get("symbol") or "").strip()
        if not ts_raw or not symbol:
            continue    # a truncated row
        try:
            ts = datetime.fromisoformat(ts_raw)
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)    # never the server's (Berlin) local time
        # keep global newest
        if newest_ts is None or ts > newest_ts:
            newest_ts = ts

        ts_ct = ts.astimezone(CT)
        ts_date = ts_ct.date()

        # decisions per today (CT)
        if ts_date == today_ct:
            decisions_today += 1
            action = (r.get("action") or "").lower()
            if action == "buy":
                buys_today.append(symbol)
            if action == "blocked":
                blocked_today += 1

        # watchlist (last 7 days, inclusive)
        if ts_date >= today_ct - timedelta(days=6):
            recent_symbols.add(symbol)

    return buys_today, blocked_today, decisions_today, recent_symbols, newest_ts


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def repo_path() -> Path:
    """Return the base repository path for graywind state files."""
    env_path = os.getenv("MAVIS_GRAYWIND_REPO", "/var/lib/mavis/graywind-state")
    return Path(env_path)


def snapshot(repo: Path, now: datetime) -> dict:
    """Collect a snapshot of the graywind state.

    Parameters
    ----------
    repo: Path
        Root of the cloned graywind repository.
    now: datetime
        A timezone‑aware datetime used as “now”. It is converted to
        America/Chicago to decide the “today” date.

    Returns
    -------
    dict
        The snapshot dictionary as described in the specification.
    """
    if now.tzinfo is None:
        raise ValueError("`now` must be timezone‑aware")
    today_ct = now.astimezone(CT).date()

    accounts: Dict[str, dict] = {}
    global_last_decision: Optional[datetime] = None
    watchset: set = set()
    pending_all: List[Dict[str, Any]] = []
    any_file_present = False

    for acct_name, sub_path in ACCOUNTS:
        acct_dir = repo / sub_path
        missing: List[str] = []
        # ---------- equity ----------
        equity_file = acct_dir / "equity_history.csv"
        try:
            equity, prev_equity, equity_day = _read_equity(equity_file)
            any_file_present = True
        except Exception:
            equity = prev_equity = equity_day = None
            missing.append("equity_history.csv")

        # ---------- positions ----------
        positions_file = acct_dir / "positions.csv"
        try:
            positions = _read_positions(positions_file)
            any_file_present = any_file_present or bool(positions)
        except Exception:
            positions = []
            missing.append("positions.csv")

        # ---------- pending trades ----------
        pending_file = acct_dir / "pending_trades.csv"
        try:
            pending = _read_pending(pending_file)
            any_file_present = any_file_present or bool(pending)
        except Exception:
            pending = []
            missing.append("pending_trades.csv")

        # ---------- decision log ----------
        decision_file = acct_dir / "decision_log.csv"
        try:
            (
                buys_today,
                blocked_today,
                decisions_today,
                recent_symbols,
                newest_ts,
            ) = _read_decisions(decision_file, today_ct)
            any_file_present = any_file_present or True
        except Exception:
            buys_today = []
            blocked_today = 0
            decisions_today = 0
            recent_symbols = set()
            newest_ts = None
            missing.append("decision_log.csv")

        # update global structures
        if newest_ts and (global_last_decision is None or newest_ts > global_last_decision):
            global_last_decision = newest_ts
        watchset.update(recent_symbols)
        pending_all.extend(pending)

        accounts[acct_name] = {
            "equity": equity,
            "prev_equity": prev_equity,
            "equity_day": equity_day,
            "positions": positions,
            "buys_today": buys_today,
            "blocked_today": blocked_today,
            "decisions_today": decisions_today,
            "missing": missing,
        }

    # Deduplicate pending trades by issue (keep first occurrence)
    seen_issues = set()
    pending_deduped: List[Dict[str, Any]] = []
    for p in pending_all:
        issue = p.get("issue")
        if issue is None or issue in seen_issues:
            continue
        seen_issues.add(issue)
        pending_deduped.append(p)

    snapshot_dict = {
        "accounts": accounts,
        "last_decision": global_last_decision,
        "watchlist": sorted(watchset),
        "pending": pending_deduped,
        "ok": any_file_present,
    }

    return snapshot_dict

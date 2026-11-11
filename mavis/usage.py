"""Daily spend caps that survive restarts, and the audit log.

Caps count each key's paid work per UTC day (answers, and seconds of audio
transcribed) in SQLite, so a restart never resets them. The audit log records
key ids and a fixed set of fields only -- never keys, audio or transcripts.
"""
import json
import math
import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("llm", "stt_seconds")


def _env_number(name: str, default: float) -> float:
    """A cap from the environment; a bad value falls back loudly, never crashes."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value < 0:
        print(f"usage: bad {name}={raw!r}, using {default}", file=sys.stderr)
        return default
    return value


GLOBAL_DAILY_LLM = _env_number("MAVIS_GLOBAL_DAILY_LLM", 500)
GLOBAL_DAILY_STT_SECONDS = _env_number("MAVIS_GLOBAL_DAILY_STT_SECONDS", 3600)


def db_path() -> Path:
    return Path(os.environ.get("MAVIS_USAGE_DB", "~/.mavis/usage.db")).expanduser()


def audit_path() -> Path:
    return Path(os.environ.get("MAVIS_AUDIT_LOG", "~/.mavis/audit.log")).expanduser()


def _today() -> str:
    """Current UTC date as YYYY-MM-DD."""
    return datetime.now(timezone.utc).date().isoformat()


class CapExceeded(Exception):
    """Adding this amount would pass the key's or everyone's daily cap."""

    def __init__(self, which: str):
        super().__init__(f"daily cap reached: {which}")
        self.which = which


def _create_private(path: Path) -> None:
    """Make the parent dir and an empty 0600 file, safely under races."""
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))


_ready: set = set()
_ready_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    path = db_path()
    with _ready_lock:
        if path not in _ready or not path.exists():
            _create_private(path)
            with sqlite3.connect(path, timeout=5) as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS usage ("
                             "day TEXT, key_id TEXT, kind TEXT, amount REAL, "
                             "PRIMARY KEY (day, key_id, kind))")
                conn.execute("CREATE TABLE IF NOT EXISTS alerts ("
                             "day TEXT, dedupe TEXT, PRIMARY KEY (day, dedupe))")
            _ready.add(path)
    # isolation_level=None: we issue BEGIN IMMEDIATE ourselves.
    return sqlite3.connect(path, timeout=5, isolation_level=None)


def _validate(kind: str, amount) -> float:
    if kind not in KINDS:
        raise ValueError(f"unknown usage kind {kind!r}")
    if (not isinstance(amount, (int, float)) or isinstance(amount, bool)
            or not math.isfinite(amount) or amount < 0):
        # NaN would make every later comparison False and switch the caps off.
        raise ValueError(f"usage amount must be a finite number >= 0, got {amount!r}")
    return float(amount)


def _cap(rec, kind: str) -> float:
    return rec.per_day_llm if kind == "llm" else rec.per_day_stt_seconds


def _global_cap(kind: str) -> float:
    return GLOBAL_DAILY_LLM if kind == "llm" else GLOBAL_DAILY_STT_SECONDS


def _totals(conn, day: str, key_id: str, kind: str) -> tuple[float, float]:
    key_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM usage WHERE day=? AND key_id=? AND kind=?",
        (day, key_id, kind)).fetchone()[0]
    all_total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM usage WHERE day=? AND kind=?",
        (day, kind)).fetchone()[0]
    return key_total, all_total


def _raise_if_over(rec, kind, amount, key_total, all_total) -> None:
    if key_total + amount > _cap(rec, kind):
        raise CapExceeded("key")
    if all_total + amount > _global_cap(kind):
        raise CapExceeded("global")


def check(rec, kind: str, amount: float) -> None:
    """Raise CapExceeded if adding `amount` would pass a cap. Records nothing."""
    amount = _validate(kind, amount)
    conn = _connect()
    try:
        _raise_if_over(rec, kind, amount, *_totals(conn, _today(), rec.id, kind))
    finally:
        conn.close()


def charge(rec, kind: str, amount: float) -> None:
    """Check the caps and record `amount` as one step, or raise CapExceeded.

    BEGIN IMMEDIATE takes SQLite's write lock before reading, so parallel
    requests queue here instead of all passing a check against the same total.
    """
    amount = _validate(kind, amount)
    day = _today()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _raise_if_over(rec, kind, amount, *_totals(conn, day, rec.id, kind))
            conn.execute(
                "INSERT INTO usage (day, key_id, kind, amount) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(day, key_id, kind) DO UPDATE SET amount = amount + excluded.amount",
                (day, rec.id, kind, amount))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def record(rec, kind: str, amount: float) -> None:
    """Record `amount` without checking (for work already done)."""
    amount = _validate(kind, amount)
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO usage (day, key_id, kind, amount) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(day, key_id, kind) DO UPDATE SET amount = amount + excluded.amount",
            (_today(), rec.id, kind, amount))
    finally:
        conn.close()


def refund(rec, kind: str, amount: float) -> None:
    """Give back a charge for work that failed (never below zero)."""
    amount = _validate(kind, amount)
    conn = _connect()
    try:
        conn.execute("UPDATE usage SET amount = MAX(0, amount - ?) "
                     "WHERE day=? AND key_id=? AND kind=?",
                     (amount, _today(), rec.id, kind))
    finally:
        conn.close()


def alert_sent_today(dedupe: str) -> bool:
    conn = _connect()
    try:
        return conn.execute("SELECT 1 FROM alerts WHERE day=? AND dedupe=?",
                            (_today(), str(dedupe)[:_MAX_DEDUPE_CHARS])).fetchone() is not None
    finally:
        conn.close()


def alerts_sent_today() -> int:
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM alerts WHERE day=?", (_today(),)).fetchone()[0]
    finally:
        conn.close()


def record_alert(dedupe: str) -> None:
    """Mark an alert sent today; older days' rows are dropped."""
    day = _today()
    conn = _connect()
    try:
        conn.execute("DELETE FROM alerts WHERE day < ?", (day,))
        conn.execute("INSERT OR IGNORE INTO alerts (day, dedupe) VALUES (?, ?)",
                     (day, str(dedupe)[:_MAX_DEDUPE_CHARS]))
    finally:
        conn.close()


_MAX_DEDUPE_CHARS = 200


def today_totals(key_id: str | None = None) -> dict[str, float]:
    """Today's totals per kind, for one key or (None) for everyone."""
    sql = "SELECT kind, SUM(amount) FROM usage WHERE day=?"
    args = [_today()]
    if key_id is not None:
        sql += " AND key_id=?"
        args.append(key_id)
    conn = _connect()
    try:
        rows = conn.execute(sql + " GROUP BY kind", args).fetchall()
    finally:
        conn.close()
    totals = {kind: 0.0 for kind in KINDS}
    totals.update({kind: amount for kind, amount in rows})
    return totals


# The only fields an audit line may carry besides ts/event/key_id. Anything
# else is dropped, so a careless caller cannot log a transcript or a key.
AUDIT_FIELDS = frozenset({
    "seconds", "ms", "kind", "amount", "which", "reason", "code",
    "scope", "ident", "path", "count",
})
_MAX_FIELD_CHARS = 120
_audit_lock = threading.Lock()


def _clean(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else str(value)
    return str(value)[:_MAX_FIELD_CHARS]


def audit(event: str, key_id: str | None, **fields) -> None:
    """Append one JSON line. Only AUDIT_FIELDS are kept; long values are cut."""
    entry = {name: _clean(value) for name, value in fields.items() if name in AUDIT_FIELDS}
    dropped = sorted(set(fields) - AUDIT_FIELDS)
    if dropped:
        entry["dropped"] = dropped    # names only, never values
    entry.update(ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 event=str(event)[:_MAX_FIELD_CHARS],
                 key_id=None if key_id is None else str(key_id)[:_MAX_FIELD_CHARS])
    line = json.dumps(entry) + "\n"
    path = audit_path()
    with _audit_lock:
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(line)

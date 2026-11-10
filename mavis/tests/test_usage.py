import json
import importlib
import os
from pathlib import Path

import pytest

from keys import KeyRecord
import usage


@pytest.fixture(autouse=True)
def set_env_and_paths(tmp_path, monkeypatch):
    db_path = tmp_path / "usage.db"
    audit_path = tmp_path / "audit.log"
    monkeypatch.setenv("MAVIS_USAGE_DB", str(db_path))
    monkeypatch.setenv("MAVIS_AUDIT_LOG", str(audit_path))
    # ensure fresh files for each test
    if db_path.exists():
        db_path.unlink()
    if audit_path.exists():
        audit_path.unlink()
    yield
    # cleanup (optional)
    if db_path.exists():
        db_path.unlink()
    if audit_path.exists():
        audit_path.unlink()


def rec(id_: str = "a", llm: int = 3, stt: float = 10.0) -> KeyRecord:
    return KeyRecord(id_, "guest", 10, llm, stt)


def test_under_cap_passes_and_records():
    r = rec()
    usage.check(r, "llm", 1)  # should not raise
    usage.record(r, "llm", 1)
    totals = usage.today_totals("a")
    assert totals["llm"] == 1
    usage.check(r, "llm", 2)  # still under per‑key cap (3)


def test_check_raises_key_cap_at_limit():
    r = rec(llm=3)
    usage.record(r, "llm", 3)
    with pytest.raises(usage.CapExceeded) as exc:
        usage.check(r, "llm", 1)
    assert exc.value.which == "key"

    # zero amount never exceeds cap
    usage.check(r, "llm", 0)


def test_global_cap_counts_all_keys(monkeypatch):
    monkeypatch.setattr(usage, "GLOBAL_DAILY_LLM", 4, raising=False)

    a = rec("a", llm=10)
    b = rec("b", llm=10)
    c = rec("c", llm=10)

    usage.record(a, "llm", 2)
    usage.record(b, "llm", 2)

    with pytest.raises(usage.CapExceeded) as exc:
        usage.check(c, "llm", 1)
    assert exc.value.which == "global"


def test_stt_seconds_are_fractional():
    r = rec(stt=10.0)
    usage.record(r, "stt_seconds", 9.5)

    usage.check(r, "stt_seconds", 0.4)  # ok
    with pytest.raises(usage.CapExceeded) as exc:
        usage.check(r, "stt_seconds", 0.6)
    assert exc.value.which == "key"


def test_over_cap_key_still_refused_after_restart():
    # Review Focus 4: a fresh process must still refuse an over-cap key.
    owner = KeyRecord("o", "owner", 20, 300, 1800)
    usage.record(owner, "llm", 300)
    reloaded = importlib.reload(usage)
    with pytest.raises(reloaded.CapExceeded) as exc:
        reloaded.charge(owner, "llm", 1)
    assert exc.value.which == "key"
    assert reloaded.today_totals("o")["llm"] == 300


def test_new_utc_day_resets(monkeypatch):
    # first day
    monkeypatch.setattr(usage, "_today", lambda: "2026-11-10", raising=False)
    r = rec()
    usage.record(r, "llm", 3)  # reaches per‑key cap

    # next day
    monkeypatch.setattr(usage, "_today", lambda: "2026-11-11", raising=False)
    usage.check(r, "llm", 1)  # should be allowed again


def test_today_totals_per_key_and_all():
    a = rec("a")
    b = rec("b")
    usage.record(a, "llm", 1)
    usage.record(b, "llm", 2)

    tot_a = usage.today_totals("a")
    tot_all = usage.today_totals()

    assert tot_a["llm"] == 1
    assert tot_all["llm"] == 3


def test_audit_writes_json_lines(monkeypatch):
    audit_file = Path(os.getenv("MAVIS_AUDIT_LOG"))
    usage.audit("event1", "a", seconds=1)
    usage.audit("event2", None, reason="x")

    lines = audit_file.read_text().strip().splitlines()
    assert len(lines) == 2

    ev1 = json.loads(lines[0])
    ev2 = json.loads(lines[1])

    assert ev1["event"] == "event1"
    assert ev1["key_id"] == "a"
    assert ev1["seconds"] == 1
    assert "ts" in ev1
    assert ev1["ts"].endswith("Z") or ev1["ts"].endswith("+00:00")

    assert ev2["event"] == "event2"
    assert ev2["key_id"] is None
    assert ev2["reason"] == "x"
    assert "ts" in ev2
    assert ev2["ts"].endswith("Z") or ev2["ts"].endswith("+00:00")


def test_audit_never_writes_key_or_transcript(monkeypatch, tmp_path):
    import keys
    monkeypatch.setenv("MAVIS_KEYS_FILE", str(tmp_path / "keys.json"))
    key = keys.add("friend", "guest")
    usage.audit("call_start", "friend", seconds=1.5, key=key,
                text="what is in my portfolio", headers={"X-API-Key": key})
    content = Path(os.getenv("MAVIS_AUDIT_LOG")).read_text()
    assert key not in content
    assert "portfolio" not in content
    line = json.loads(content)
    assert line["seconds"] == 1.5 and line["key_id"] == "friend"
    assert line["dropped"] == ["headers", "key", "text"]


def test_audit_fields_cannot_overwrite_fixed_ones():
    # event/key_id can't be passed twice (Python refuses); ts is not allowed.
    usage.audit("real", "a", ts="1999-01-01", reason="r" * 500)
    line = json.loads(Path(os.getenv("MAVIS_AUDIT_LOG")).read_text())
    assert (line["event"], line["key_id"]) == ("real", "a")
    assert line["ts"] != "1999-01-01" and line["dropped"] == ["ts"]
    assert len(line["reason"]) == 120


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, "3", True, None])
def test_bad_amounts_rejected_and_never_recorded(bad):
    r = rec()
    for fn in (usage.check, usage.charge, usage.record):
        with pytest.raises(ValueError):
            fn(r, "llm", bad)
    assert usage.today_totals("a")["llm"] == 0


def test_charge_over_cap_records_nothing():
    r = rec(llm=3)
    usage.charge(r, "llm", 3)
    with pytest.raises(usage.CapExceeded):
        usage.charge(r, "llm", 1)
    assert usage.today_totals("a")["llm"] == 3


def test_parallel_charges_never_pass_the_cap():
    import threading
    r = rec(llm=5)
    results = []

    def go():
        try:
            usage.charge(r, "llm", 1)
            results.append("ok")
        except usage.CapExceeded:
            results.append("capped")

    threads = [threading.Thread(target=go) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 5
    assert usage.today_totals("a")["llm"] == 5


def test_bad_env_cap_falls_back_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("MAVIS_GLOBAL_DAILY_LLM", "lots")
    assert usage._env_number("MAVIS_GLOBAL_DAILY_LLM", 500) == 500
    monkeypatch.setenv("MAVIS_GLOBAL_DAILY_LLM", "nan")
    assert usage._env_number("MAVIS_GLOBAL_DAILY_LLM", 500) == 500
    monkeypatch.setenv("MAVIS_GLOBAL_DAILY_LLM", "120")
    assert usage._env_number("MAVIS_GLOBAL_DAILY_LLM", 500) == 120


def test_unknown_kind_in_db_does_not_crash_totals():
    import sqlite3
    usage.record(rec(), "llm", 1)
    with sqlite3.connect(usage.db_path()) as conn:
        conn.execute("INSERT INTO usage VALUES (?, 'a', 'future', 2)", (usage._today(),))
    assert usage.today_totals("a")["llm"] == 1

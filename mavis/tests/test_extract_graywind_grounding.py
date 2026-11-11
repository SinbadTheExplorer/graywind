import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from extract_graywind_grounding import (
    build_facts,
    extract_watchlist,
    latest_decision_per_symbol,
    read_pending_trades,
)


def write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n")


def test_latest_decision_per_symbol_keeps_last_row_per_symbol(tmp_path: Path):
    csv_path = tmp_path / "decision_log.csv"
    header = "timestamp,symbol,action,reason,rsi,sma_fast,sma_slow,vix,sentiment,days_to_earnings,macro_breaches,sector_gates"
    rows = [
        "2026-09-13T10:00:00-04:00,AAPL,hold,initial check,50,100,105,20,neutral,5,0,0",
        "2026-09-14T11:00:00-04:00,AAPL,buy,all checks passed,55,101,106,18,positive,4,0,0",
        "2026-09-14T12:00:00-04:00,SERV,hold,waiting for data,45,99,104,22,neutral,6,1,0",
    ]
    write_csv(csv_path, header, rows)

    result = latest_decision_per_symbol(csv_path)

    assert set(result.keys()) == {"AAPL", "SERV"}
    aapl = result["AAPL"]
    assert aapl["action"] == "buy"
    assert aapl["reason"] == "all checks passed"


def test_latest_decision_per_symbol_raises_when_file_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        latest_decision_per_symbol(tmp_path / "does_not_exist.csv")


def test_read_pending_trades_returns_empty_list_when_file_missing(tmp_path: Path):
    assert read_pending_trades(tmp_path / "does_not_exist.csv") == []


def test_read_pending_trades_parses_rows(tmp_path: Path):
    csv_path = tmp_path / "pending_trades.csv"
    header = "symbol,issue_number,side,qty,price_at_proposal,stop_price,target_price,tier,proposed_date"
    rows = [
        "AAPL,13,buy,78.7532,332.835,326.18,342.82,2,2026-09-14",
    ]
    write_csv(csv_path, header, rows)

    rows_parsed = read_pending_trades(csv_path)

    assert len(rows_parsed) == 1
    row = rows_parsed[0]
    assert row["symbol"] == "AAPL"
    assert row["issue_number"] == "13"


def test_extract_watchlist_parses_the_assignment(tmp_path: Path):
    file_path = tmp_path / "live_loop.py"
    file_path.write_text('SOME_OTHER = 1\nWATCHLIST = ["AAPL", "SERV"]\nMORE = 2\n')

    assert extract_watchlist(file_path) == ["AAPL", "SERV"]


def test_extract_watchlist_raises_when_missing(tmp_path: Path):
    file_path = tmp_path / "live_loop.py"
    file_path.write_text("NOT_HERE = 1\n")

    with pytest.raises(ValueError):
        extract_watchlist(file_path)


def test_extract_watchlist_parses_a_multiline_assignment(tmp_path: Path):
    file_path = tmp_path / "live_loop.py"
    file_path.write_text(
        'SOME_OTHER = 1\n'
        'WATCHLIST = [\n'
        '    "AAPL",\n'
        '    "SERV",\n'
        ']\n'
        'MORE = 2\n'
    )

    assert extract_watchlist(file_path) == ["AAPL", "SERV"]


def test_build_facts_includes_watchlist_decisions_and_pending():
    latest_decisions = {
        "AAPL": {
            "action": "buy",
            "reason": "all checks passed",
            "timestamp": "2026-09-14T11:00:00-04:00",
        },
    }
    pending_trades = [
        {
            "symbol": "AAPL", "issue_number": "13", "side": "buy",
            "qty": "78.7532", "tier": "2", "proposed_date": "2026-09-14",
        },
    ]

    facts = build_facts([("100k", latest_decisions, pending_trades)], ["AAPL", "SERV"])

    ids = {f["id"] for f in facts}
    assert "watchlist" in ids
    assert "decision-100k-AAPL" in ids
    assert "pending-100k-13" in ids

    decision_fact = next(f for f in facts if f["id"] == "decision-100k-AAPL")
    assert "buy" in decision_fact["text"]
    assert "all checks passed" in decision_fact["text"]

    pending_fact = next(f for f in facts if f["id"] == "pending-100k-13")
    assert "78.7532" in pending_fact["text"]


def test_extractor_honours_repo_and_out_args(tmp_path: Path):
    import json
    from extract_graywind_grounding import main
    repo = tmp_path / "gw"
    header = ("timestamp,symbol,action,reason,rsi,sma_fast,sma_slow,vix,sentiment,"
              "days_to_earnings,macro_breaches,sector_gates")
    for d in (repo / "state", repo / "state" / "small"):
        d.mkdir(parents=True)
        write_csv(d / "decision_log.csv", header,
                  ["2026-11-11T10:00:00-05:00,NVDA,hold,waiting,50,1,2,20,neutral,5,0,0"])
    (repo / "live_loop.py").write_text('WATCHLIST = ["NVDA"]\n')
    out = tmp_path / "out" / "facts.json"
    assert main(["--repo", str(repo), "--out", str(out)]) == 0
    facts = json.loads(out.read_text())["facts"]
    assert any("NVDA" in f["text"] for f in facts)
    assert [p.name for p in out.parent.iterdir()] == ["facts.json"]    # no temp left

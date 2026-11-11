"""Build-time snapshot of Graywind grounding data.

This script creates `mavis/data/graywind_grounding.json` from Graywind's
CSV state files. It deliberately excludes `tier_pools.csv` because the
100k account's pool balances are known-wrong as of 2026-09-15.
"""
import argparse
import ast
import csv
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "graywind_grounding.json"
# (account name, its state folder relative to the Graywind checkout)
ACCOUNTS = [
    ("100k", Path("state")),
    ("small", Path("state") / "small"),
]


def latest_decision_per_symbol(csv_path: Path) -> dict[str, dict]:
    """Return the most recent decision row per symbol from a decision log.

    Unlike read_pending_trades, a missing file is not a normal empty state
    here -- it means the account/path is misconfigured -- so this
    deliberately does not guard against it and lets FileNotFoundError
    propagate.
    """
    decisions: dict[str, dict] = {}
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row["symbol"]
            decisions[symbol] = row
    return decisions


def read_pending_trades(csv_path: Path) -> list[dict]:
    """Read pending trades CSV; return empty list if the file does not exist."""
    if not csv_path.is_file():
        return []
    with csv_path.open(newline="") as f:
        return list(csv.DictReader(f))


def extract_watchlist(live_loop_path: Path) -> list[str]:
    """Extract the WATCHLIST assignment from a live_loop.py file.

    Non-greedy up to the first "]" -- correct as long as no ticker symbol
    or inline comment before the list's real closing bracket contains a
    literal "]". live_loop.py is this same project's own source, not
    adversarial input, so that holds in practice.
    """
    text = live_loop_path.read_text()
    match = re.search(r"^WATCHLIST\s*=\s*(\[.*?\])", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError(f"WATCHLIST assignment not found in {live_loop_path}")
    return ast.literal_eval(match.group(1))


def build_facts(accounts_data: list[tuple[str, dict, list[dict]]], watchlist: list[str]) -> list[dict]:
    """Compose fact dictionaries from account decisions, pending trades and the watchlist."""
    facts: list[dict] = []

    watchlist_tags = ["watchlist", "graywind"] + [s.lower() for s in watchlist]
    facts.append(
        {
            "id": "watchlist",
            "tags": watchlist_tags,
            "text": f"Graywind's active trading watchlist is {', '.join(watchlist)}.",
        }
    )

    for account_name, latest_decisions, pending_trades in accounts_data:
        for symbol in sorted(latest_decisions):
            row = latest_decisions[symbol]
            fact_id = f"decision-{account_name}-{symbol}"
            tags = ["decision", "graywind", account_name.lower(), symbol.lower()]
            text = (
                f"[Graywind, {account_name} account] Most recent decision for {symbol}: "
                f"{row['action']} — \"{row['reason']}\" (as of {row['timestamp']})."
            )
            facts.append({"id": fact_id, "tags": tags, "text": text})

        for row in pending_trades:
            fact_id = f"pending-{account_name}-{row['issue_number']}"
            tags = ["pending", "graywind", account_name.lower(), row["symbol"].lower()]
            qty = float(row["qty"])
            text = (
                f"[Graywind, {account_name} account] Pending trade proposal: {row['side']} "
                f"{qty:.4f} shares of {row['symbol']} (tier {row['tier']}), proposed "
                f"{row['proposed_date']}, GitHub issue #{row['issue_number']} — awaiting manual approval."
            )
            facts.append({"id": fact_id, "tags": tags, "text": text})

    return facts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=REPO_ROOT,
                        help="Graywind checkout holding state/ and live_loop.py")
    parser.add_argument("--out", type=Path, default=OUT_PATH,
                        help="where to write the facts JSON")
    args = parser.parse_args(argv)
    repo, out = args.repo, args.out

    accounts_data = []
    for account_name, rel in ACCOUNTS:
        state_dir = repo / rel
        latest_decisions = latest_decision_per_symbol(state_dir / "decision_log.csv")
        pending_trades = read_pending_trades(state_dir / "pending_trades.csv")
        accounts_data.append((account_name, latest_decisions, pending_trades))

    watchlist = extract_watchlist(repo / "live_loop.py")
    facts = build_facts(accounts_data, watchlist)

    # Written to a temp file and renamed into place, so the server's reload
    # never sees a half-written file.
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=out.parent,
                                         delete=False, suffix=".tmp") as tf:
            tmp_path = tf.name
            json.dump({"facts": facts}, tf, indent=2)
            tf.write("\n")
            tf.flush()
            os.fsync(tf.fileno())
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, out)
    except BaseException:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    print(f"wrote {len(facts)} facts to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

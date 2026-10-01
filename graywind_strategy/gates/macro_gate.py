"""Bullion macro-gate: blocks new trades when a vote-count of macro stress
signals (NFCI, HY OAS, yield curve slope), sourced from Bullion's public
daily-cron data.json, meets a configured breach threshold. Fails closed --
any fetch, parse, or staleness failure raises MacroDataUnavailable, which
the caller (pipeline.py) must treat as a blocked trade, never as a skipped
gate. Additive alongside vix_gate.py, which keeps its own direct FRED call
unchanged.

vix is still fetched into the snapshot (Bullion publishes it, and the
staleness-checked fetch walk treats it like any other field) but is
deliberately excluded from the vote: evaluate_vix_gate already blocks
outright on the identical FRED VIXCLS series at the identical 25.0
threshold earlier in decide_trade, so counting it here too could only ever
fire when it's wrong -- Bullion's forward-filled value reads stale-high
while live FRED is actually fine.
"""
from datetime import datetime

import requests

NFCI_THRESHOLD = 0.0
HY_OAS_THRESHOLD = 5.0
CURVE_SLOPE_THRESHOLD = 0.0


class MacroDataUnavailable(Exception):
    pass


BULLION_DATA_URL = "https://sinbadtheexplorer.github.io/claudekit/bullion-live-map/data.json"
DAILY_STALENESS_CEILING_DAYS = 7
WEEKLY_STALENESS_CEILING_DAYS = 14

_FIELD_CEILINGS = {
    "vix": DAILY_STALENESS_CEILING_DAYS,
    "hy_oas": DAILY_STALENESS_CEILING_DAYS,
    "us10y": DAILY_STALENESS_CEILING_DAYS,
    "us2y": DAILY_STALENESS_CEILING_DAYS,
    "nfci": WEEKLY_STALENESS_CEILING_DAYS,
}


def count_macro_breaches(snapshot):
    breaches = 0
    if snapshot["nfci"] >= NFCI_THRESHOLD:
        breaches += 1
    if snapshot["hy_oas"] >= HY_OAS_THRESHOLD:
        breaches += 1
    if snapshot["curve_slope"] < CURVE_SLOPE_THRESHOLD:
        breaches += 1
    return breaches


def macro_gate(snapshot, required_breaches=2):
    """Bare-bool wrapper around count_macro_breaches().

    Not called by pipeline.py -- decide_trade() calls count_macro_breaches()
    directly (see evaluate_macro_gate() in pipeline.py) so it can attach a
    breach count to gate_readings, which a plain bool can't carry. This
    function is kept as a tested, reusable pure predicate (its is True/
    is False return behavior is deliberately pinned by tests/test_macro_gate.py)
    even though nothing in production currently calls it.
    """
    return count_macro_breaches(snapshot) < required_breaches


def _most_recent_value_before(history, field, as_of_date, ceiling_days):
    for date_str in sorted(history.keys(), reverse=True):
        record_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if record_date >= as_of_date:
            continue
        record = history[date_str]
        if field not in record:
            continue
        if (as_of_date - record_date).days > ceiling_days:
            raise MacroDataUnavailable(
                f"no fresh value for '{field}': most recent is {record_date}, "
                f"older than the {ceiling_days}-day staleness ceiling"
            )
        return record[field]
    raise MacroDataUnavailable(f"no value found for '{field}' in history before {as_of_date}")


def fetch_bullion_macro_snapshot(as_of_date, session=requests):
    try:
        response = session.get(BULLION_DATA_URL, timeout=10)
        response.raise_for_status()
        history = response.json()["history"]

        values = {
            field: _most_recent_value_before(history, field, as_of_date, ceiling)
            for field, ceiling in _FIELD_CEILINGS.items()
        }

        return {
            "vix": float(values["vix"]),
            "nfci": float(values["nfci"]),
            "hy_oas": float(values["hy_oas"]),
            "curve_slope": float(values["us10y"]) - float(values["us2y"]),
        }
    except MacroDataUnavailable:
        raise
    except Exception as exc:
        raise MacroDataUnavailable(str(exc)) from exc

"""The jobs Johnny's timers run on the server.

    python jobs.py news                 hourly: fetch headlines
    python jobs.py watch                every 15 min: look for trouble, push urgent events
    python jobs.py brief close|night    15:15 and 21:00 CT, Mon-Fri
    python jobs.py test-event [--at ISO] [--text TEXT]
                                        push a fake urgent event now (as if at --at),
                                        to check text-vs-call by hand

Exit status is 1 on failure, so systemd's OnFailure pages the owner.
"""
import argparse
import sys
from datetime import datetime, timezone

import briefing
import events
import graywind_state
import jsonfile
import newsdesk
import reach
import watch

CT = briefing.CT
NEWS_FAILURES_BEFORE_PAGE = 2
TEST_TEXT = "Test: AAPL position closed (entry $348.07, stop $343.96)."


def _symbols(now) -> list:
    """Held symbols first (they matter most), then the recent watchlist."""
    try:
        snap = graywind_state.snapshot(graywind_state.repo_path(), now)
    except Exception:  # noqa: BLE001 -- market news is still worth fetching
        return []
    held = [p["symbol"] for a in snap["accounts"].values() for p in a["positions"]]
    return list(dict.fromkeys(held + snap["watchlist"]))


def news_job(now=None) -> None:
    """Fetch headlines. One failed run is only logged; the second in a row
    fails the unit, and systemd's OnFailure pages the owner (once a day)."""
    now = now or datetime.now(timezone.utc)
    failures = newsdesk.news_path().with_name("news.failures")
    try:
        newsdesk.run(_symbols(now), now=now)
    except Exception as exc:
        count = int(jsonfile.read(failures, 0) or 0) + 1
        jsonfile.write_atomic(failures, count)
        if count >= NEWS_FAILURES_BEFORE_PAGE:
            raise
        print(f"jobs: news failed once ({type(exc).__name__}); retrying next hour", file=sys.stderr)
        return
    if failures.exists():
        failures.unlink()


def brief_job(kind: str, now=None) -> str:
    # Only what the brief can show (facts() takes 3); the rest waits for the next one.
    info = events.pending_info()[:3]
    text = briefing.run(kind, now=now, info_events=info)
    events.mark([e["id"] for e in info], "brief")
    return text


def test_event(at=None, text=TEST_TEXT) -> str:
    """A real push of a fake urgent event, decided as if it were `at`."""
    now = datetime.now(timezone.utc)
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=CT)          # a bare time means Chicago, not the server's Berlin
    ev = events.add("test", "urgent", text, key=f"test:{now.isoformat()}", now=now)
    return reach.deliver(ev, now, decide_at=at)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="jobs.py")
    sub = parser.add_subparsers(dest="job", required=True)
    sub.add_parser("news")
    sub.add_parser("watch")
    brief = sub.add_parser("brief")
    brief.add_argument("kind", choices=("close", "night"))
    test = sub.add_parser("test-event")
    test.add_argument("--at", type=datetime.fromisoformat,
                      help="decide as if it were this time (ISO, with offset)")
    test.add_argument("--text", default=TEST_TEXT)
    argv = list(sys.argv[1:] if argv is None else argv)
    # systemd instance names can't hold a space: "brief-close" = "brief close".
    if argv and argv[0].startswith("brief-"):
        argv = ["brief", argv[0][len("brief-"):]] + argv[1:]
    args = parser.parse_args(argv)
    try:
        if args.job == "news":
            news_job()
        elif args.job == "watch":
            watch.run()
        elif args.job == "brief":
            print(brief_job(args.kind))
        else:
            print(test_event(args.at, args.text))
    except Exception as exc:  # noqa: BLE001 -- one line in the journal, then exit 1
        print(f"jobs: {args.job} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Johnny Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Johnny reads hourly news and Graywind's state on the VPS, sends a close wrap and a night brief, and pushes urgent events as a text or a "Johnny is calling" alert depending on the owner's schedule.

**Architecture:** Small flat modules in `mavis/` driven by a CLI (`jobs.py`) that systemd timers run as user `mavis`. JSON files in `/var/lib/mavis` carry state between runs. A synchronous ntfy sender (`push.py`) delivers; Groq rewrites briefs in Johnny's voice behind a number guard.

**Tech Stack:** Python 3.12, httpx, stdlib `zoneinfo`/`csv`/`xml.etree`, pytest, systemd timers, ntfy.

**Spec:** `docs/superpowers/specs/2026-11-13-johnny-reports-design.md`

## Global Constraints

- All schedules and "today" use `ZoneInfo("America/Chicago")`; the server clock is Europe/Berlin.
- Busy windows Mon & Wed 08:40–12:00 and 14:30–16:00; quiet hours 22:00–07:00; market hours 08:30–15:00 CT, Mon–Fri.
- Briefs ≤ 3 sentences; every number in a model-written brief must appear in the facts (commas ignored), else the template is sent.
- Max 3 call pushes per CT day; urgent kinds at most once per (kind, account) per CT day.
- Pushes contain no keys, logins, IPs; Graywind numbers are fine (public repo, paper money).
- Paths come from env with server defaults: `MAVIS_NEWS_FILE`, `MAVIS_EVENTS_FILE`, `MAVIS_WATCH_FILE`, `MAVIS_SCHEDULE_FILE`, `MAVIS_PUSH_FILE` (push dedupe log), `MAVIS_GRAYWIND_REPO` (default `/var/lib/mavis/graywind-state`), `MAVIS_PUBLIC_URL` (default `https://johnny.tail4beff0.ts.net`).
- Non-security code is drafted with `delegate`, reviewed with code-review medium. `call.py`/`call_route.py`/`web/call.js` changes are written by Claude.

## Review Focus

1. A missing/empty/half-written state CSV or news file → the job reports "data unavailable" (and the brief says so) instead of crashing or claiming zero P&L. Test in Tasks 2 and 4.
2. ntfy down or non-2xx → `push.send` raises, the job exits non-zero, and the dedupe log is NOT written (so the next run retries). Test in Task 3.
3. Running the same job twice (systemd retry, manual rerun) sends nothing twice. Test in Tasks 3 and 5.
4. A brief on a holiday/weekend-adjacent day where `equity_history.csv` has no row for today → "quiet day", never a P&L computed against the wrong day. Test in Task 4.
5. `?event=` with an unknown, stale (>24 h) or guest-held id → an ordinary call, no event text leaked. Test in Task 7.

---

### Task 1: News desk

**Files:** Create `mavis/newsdesk.py`, `mavis/tests/test_newsdesk.py`; modify `mavis/conftest.py` (add env redirects for all new paths + delete `MAVIS_NTFY_TOPIC` already covered).

**Interfaces:**
- Produces: `run(symbols: list[str], *, fetch=None, now=None) -> dict` (writes `news_path()`; returns the envelope `{"generated_at": iso, "items": [{"title","source","link","published","symbols": [..]}]}`); `news_path() -> Path`; `load() -> dict | None`; `age_minutes(envelope, now) -> float`.
- Consumes: `news.parse_feed(xml, limit)` and `news.SEARCH_FEED`; the four market feed URLs copied from `bullion-live-map/fetch_bullion_news.py` (cnbc, yahoo_dji, marketwatch, mw_bulletins).

- [ ] Tests: `test_items_older_than_48h_are_dropped`, `test_duplicate_titles_are_merged`, `test_symbol_tag_matches_whole_word_only` ("AAPL" tags "AAPL rallies", not "PINEAPPLE"), `test_one_failed_source_is_not_fatal`, `test_all_sources_failing_raises_and_keeps_old_file`, `test_write_is_atomic` (old file intact if serialising fails), `test_symbols_capped_at_8`. `fetch` is an injected `callable(url) -> str`.
- [ ] Implement; per-symbol query is `f'"{sym}" stock'`.
- [ ] `pytest tests/test_newsdesk.py` passes; commit.

### Task 2: Graywind state reader

**Files:** Create `mavis/graywind_state.py`, `mavis/tests/test_graywind_state.py` (fixtures written to tmp dirs).

**Interfaces:**
- Produces: `snapshot(repo: Path, now: datetime) -> dict` with `{"accounts": {"100k": Acct, "small": Acct}, "last_decision": datetime|None, "watchlist": [str], "pending": [{"symbol","issue","side","qty","price"}]}`; `Acct = {"equity": float|None, "prev_equity": float|None, "equity_day": "YYYY-MM-DD"|None, "positions": [{"symbol","entry","shares","stop","target"}], "buys_today": [str], "blocked_today": int, "decisions_today": int}`; `ACCOUNTS = [("100k","state"),("small","state/small")]`.
- Watchlist = symbols seen in `decision_log.csv` in the last 7 days (no parsing of live_loop.py).

- [ ] Tests: `test_day_change_uses_last_two_rows`, `test_no_row_for_today_means_equity_day_is_not_today`, `test_missing_file_gives_none_not_crash`, `test_decision_counts_are_per_ct_day` (a row at 23:30 UTC on the 12th is CT the 12th), `test_pending_dedupes_issue_across_accounts`.
- [ ] Implement; commit.

### Task 3: Push sender

**Files:** Create `mavis/push.py`, `mavis/tests/test_push.py`.

**Interfaces:**
- Produces: `send(title: str, message: str, *, dedupe: str, call_url: str | None = None, client=None) -> bool` — False if already sent (dedupe) or no topic; raises `PushError` if ntfy fails. With `call_url`: headers `Priority: 5`, `Tags: telephone_receiver`, `Click: call_url`, and it counts toward `calls_today()`; `calls_today(now=None) -> int`; `MAX_CALLS_PER_DAY = 3`.
- Dedupe log: JSON `{dedupe: iso_sent}` in `MAVIS_PUSH_FILE`, entries older than 7 days pruned; written only after a 2xx.

- [ ] Tests (fake client): `test_sends_once_per_dedupe`, `test_failed_send_raises_and_is_not_recorded`, `test_no_topic_sends_nothing`, `test_call_push_sets_priority_and_click`, `test_title_is_ascii_safe`.
- [ ] Implement (reuse `alerts._topic()` / `alerts._server()`); commit.

### Task 4: Briefs

**Files:** Create `mavis/briefing.py`, `mavis/tests/test_briefing.py`.

**Interfaces:**
- Consumes: `graywind_state.snapshot`, `newsdesk.load`, `events.pending_info()` (Task 5 — until then pass `[]`), `push.send`.
- Produces: `facts(kind: "close"|"night", snap, news, info_events, now) -> list[str]` (spoken-formatted lines, e.g. `"100k account: $99,584, down 0.7% today"`), `template(kind, facts) -> str`, `guard_ok(text, facts) -> bool`, `async compose(kind, facts, ask=providers.groq_answer) -> str`, `run(kind, now=None) -> str` (composes and sends with dedupe `f"brief:{kind}:{ct_date}"`, marks info events delivered).
- Night facts add ≤ 3 headlines tagged with held/watched symbols, then ≤ 2 market headlines; and "Waiting on you: SPY buy proposal (#123)" or "Nothing needs you."

- [ ] Tests: `test_guard_rejects_invented_number`, `test_guard_ignores_commas_and_accepts_reworded`, `test_guard_rejects_four_sentences`, `test_template_used_when_model_fails` (ask raises), `test_template_used_when_guard_fails`, `test_quiet_day_when_no_decisions_today`, `test_missing_state_says_data_unavailable`, `test_nothing_needs_you_only_when_no_pending_and_no_urgent`.
- [ ] Implement; Groq prompt: Johnny voice, ≤ 3 sentences, use only the facts, keep figures exactly as written, one touch of sarcasm at most. Commit.

### Task 5: Watch + reach

**Files:** Create `mavis/watch.py`, `mavis/reach.py`, `mavis/events.py`, tests for each.

**Interfaces:**
- `events.py`: `add(kind, urgency, text, *, key) -> dict|None` (None if `key` already seen today), `get(event_id) -> dict|None`, `pending_info() -> list`, `mark(ids, delivery)`; event = `{"id": 12-hex, "kind", "urgency": "urgent"|"info", "text", "created": iso, "delivery": None|"text"|"call"|"brief"}`.
- `reach.py`: `load_schedule() -> dict` (defaults from spec when the file is missing), `is_busy(now, sched) -> bool`, `is_quiet(now, sched) -> bool`, `deliver(event, now=None) -> str` ("call"|"text") using `push.send`; call when urgent and not busy and not quiet and `push.calls_today() < 3`; call URL `f"{PUBLIC_URL}/johnny?event={id}"`.
- `watch.py`: `run(now=None) -> list[dict]` — loads snapshot + saved baseline, emits per spec (≥1 % equity drop per account; Graywind silent > 75 min in market hours; news older than 65 min; info: position closed, new buy, new pending issue, held/watched symbol in news since last run), delivers urgent ones via `reach.deliver`, saves baseline. First run saves baseline only.

- [ ] Tests: `test_first_run_only_saves_baseline`, `test_one_percent_drop_is_urgent_once_a_day`, `test_silent_graywind_only_in_market_hours`, `test_stale_news_is_urgent_once_a_day`, `test_closed_position_is_info`, `test_busy_window_texts`, `test_quiet_hours_text`, `test_free_time_calls_with_event_url`, `test_fourth_call_of_the_day_becomes_text`, `test_wednesday_1500_is_busy_and_tuesday_1500_is_not`.
- [ ] Implement; commit.

### Task 6: CLI, units, deploy

**Files:** Create `mavis/jobs.py`, `deploy/johnny-news.{service,timer}`, `deploy/johnny-watch.{service,timer}`, `deploy/johnny-brief@.service`, `deploy/johnny-brief-close.timer`, `deploy/johnny-brief-night.timer`; modify `deploy/deploy.sh` (install + `enable --now` the timers); `mavis/tests/test_jobs.py`, `tests/test_server_deploy.py` if imports change.

- `jobs.py` subcommands: `news`, `watch`, `brief {close,night}`, `test-event [--at ISO]` (adds an urgent `test` event "Test: AAPL position closed (entry $348.07, stop $343.96)" and delivers it). Exit 1 on failure. News job keeps a failure counter in `/var/lib/mavis/news.failures` and pushes once at 2 in a row.
- Timers: news `OnCalendar=hourly` + `Persistent=true`; watch `OnCalendar=*:0/15`; close `OnCalendar=Mon..Fri 15:15 America/Chicago`; night `OnCalendar=Mon..Fri 21:00 America/Chicago`. Services: `User=mavis`, `EnvironmentFile=/var/lib/mavis/env`, `OnFailure=mavis-alert@%n.service`, the hardening lines from `mavis-alert@.service`, `WorkingDirectory=/opt/mavis/mavis`.
- [ ] Test: `test_cli_dispatches_each_subcommand`, `test_news_failure_counter_pages_at_two`.
- [ ] Full suite green; commit. (Deploy happens after the owner's look.)

### Task 7: Incoming-call screen (cut first if short of time)

**Files:** Modify `mavis/web/call.html`, `mavis/web/call.js`, `mavis/call.py`, `mavis/call_route.py`; tests in `mavis/tests/test_call.py`, `mavis/tests/test_call_route.py`.

- Page: with `?event=<id>` show "Johnny is calling" + Answer (Call button relabelled), send `{"type":"hello","key":..., "event": id}`.
- Server: `CallDeps.opening: str | None = None`; `run_call` after the greeting runs one text turn (`_answer_turn(text, deps, ws)`, the post-transcribe half of `_turn`) with `f"You called the owner about this alert: {event_text} Explain it in two sentences and ask what he wants to do."`. `call_ws` sets `opening` only when `rec.scope == "owner"` and `events.get(id)` exists and is ≤ 24 h old; ids must match `[0-9a-f]{12}`.
- [ ] Tests: `test_owner_with_valid_event_hears_opening_first`, `test_guest_with_event_gets_ordinary_call`, `test_unknown_or_stale_event_gets_ordinary_call`, `test_bad_event_id_format_is_ignored`.
- [ ] Headless probe: `?event=` shows the incoming screen; zero CSP violations. Commit.

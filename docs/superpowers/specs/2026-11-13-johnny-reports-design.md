# Johnny Reports — Design (step 1 of the "Jarvis" direction)

**Date:** 2026-11-13 · **Budget:** 2 days (owner) · **Branch:** `feat/mavis-avatar`

## Intent

The owner's north star is a reel of an assistant ("Jarvis") that runs things
while you're away and only interrupts when it matters: one short update every
night, a call for the big one, a recommendation drawn from your own history,
and a plain "nothing needs you" when that's true. The feel comes from manner,
not a face or a voice: restraint, initiative, brevity, context.

Step 1 gives Johnny that manner over what he can already see: Graywind's
state (paper trading) and market news. He reports twice a day, decides on his
own whether an event is worth a call or just a text, and never fails silently.

Later steps (not this one): telling him work shifts by voice, real phone
calls (Twilio), trade ideas + paper trades by spoken OK, options analysis,
more world sources (the parked Bullion Global idea), a prediction scorecard.

## Goals

1. **Hourly news cycle on the VPS.** Fresh market headlines plus headlines
   about the symbols Graywind holds or watches, saved for Johnny to read.
   Reading, not retraining: the model gets today's news at the moment it
   writes.
2. **Two briefs a day (Mon–Fri, America/Chicago):**
   - **15:15 — close wrap:** what Graywind did today, day P&L, what's open.
   - **21:00 — night brief:** the day plus the news that matters for what he
     holds or watches, anything waiting on the owner, "nothing needs you"
     when nothing does.
   Each ≤ 3 sentences, Johnny's voice (facts first, a little flair).
3. **Text or call, Johnny's call.** Events are graded urgent or info. Info
   waits for the next brief. Urgent: during class windows or quiet hours →
   a text ("Hey choom, ..."); otherwise → a **"Johnny is calling"** push that
   opens the app on an incoming-call screen; answering starts a call where
   Johnny opens by explaining the event.
4. **No silent failure.** A news cycle that stops, or Graywind going quiet in
   market hours, reaches the owner's phone.

## Non-goals (this step)

- Placing or cancelling trades; trade ideas; options.
- A real ringing phone call / SMS (Twilio) — the ntfy push stands in.
- Learning the owner's schedule by voice (work shifts vary; later).
- Any new paid service.

## Anti-goals (would be a failure even if it "works")

- Johnny pestering: more than a few pushes on a normal day, or a call for
  something that could wait for the brief.
- A brief that states a number Graywind's state doesn't contain (the model
  inventing P&L). Numbers come from the data or the brief isn't sent in
  that form.
- A job that dies quietly and leaves Johnny reading stale news as current.
- Leaking anything new: the ntfy topic is guessable, so a push may contain
  only what is already public (Graywind's state repo is public; paper money).
  No keys, logins, IPs.

## Constraints

- Server: Contabo VPS, Ubuntu 24.04, Python 3.12, systemd. Server clock is
  Europe/Berlin — every schedule pins `America/Chicago` explicitly.
- Data: `/var/lib/mavis/graywind-state` (public repo clone, refreshed every
  15 min by `graywind-sync`), accounts `state/` (100k) and `state/small/`.
  Files used: `equity_history.csv`, `positions.csv`, `decision_log.csv`,
  `pending_trades.csv`. Not `tier_pools.csv` (known wrong).
- Brain: Groq (existing key in `/var/lib/mavis/env`), free tier.
- Delivery: ntfy (existing topic `MAVIS_NTFY_TOPIC`); priority, click URL and
  tags are plain ntfy headers.
- Owner's fixed busy windows (America/Chicago): Mon & Wed 08:40–12:00 and
  14:30–16:00. Quiet hours 22:00–07:00. Kept in a small JSON file on the
  server (`/var/lib/mavis/schedule.json`) so they can change without a deploy.
- Security posture from the cloud-security spec holds: jobs run as user
  `mavis`, no localhost access (`IPAddressDeny=localhost`), read-only code.
- Owner workflow: delegate non-security code, code-review medium after each
  piece, explain in plain words.

## Decided (by the owner, in conversation 2026-11-13)

- Paper only, for years. No real money.
- Johnny decides call vs text; sarcasm "just a bit".
- Briefs at market close **and** 21:00.
- News refresh hourly.
- Bullion's news is in scope (it is the news source).
- Budget 2 days.

## How (Claude's calls — the builder may adjust within the goals)

**Modules (flat, like the rest of `mavis/`):**
- `newsdesk.py` — fetch Bullion's four market feeds (CNBC, Yahoo ^DJI,
  MarketWatch top stories, MW bulletins) plus Google News search per symbol
  (held + watchlist, capped at 8). Keep the last 48 h, deduped, each item
  tagged with the symbols it mentions. Atomic write to
  `/var/lib/mavis/news.json` with `generated_at`. A failed source is logged,
  not fatal; all sources failing is a failed run.
- `graywind_state.py` — read the state CSVs into a plain snapshot: per
  account equity today/yesterday, open positions, today's buys/blocked
  counts, pending proposals, last state update time.
- `watch.py` — compare the current snapshot with the last one saved
  (`/var/lib/mavis/watch.json`) and emit events. Grading was checked by
  replaying 10/26–11/12 history: "every close and every proposal is urgent"
  gave 1–5 pushes per account per trading day (pestering); the rules below
  give about one a week, each one a real problem:
  - an account's equity down ≥ 1 % on the day vs the previous day's close →
    **urgent** ("trade bust"; happened once in 3 weeks, the 10/30 SPY
    stop-out), at most once per account per day;
  - Graywind silent (newest `decision_log.csv` timestamp — every cycle writes
    a row, even holds — older than 75 min) during market hours
    08:30–15:00 CT → **urgent**, at most once a day (fired on 4 real stalls
    in that window; normal gaps are 15–60 min);
  - news file older than 65 min → **urgent**, at most once a day;
  - position closed, new buy, new pending proposal (deduped by
    `issue_number` across accounts), held/watched symbol in the news →
    **info**, folded into the next brief.
  First run (no saved snapshot) only saves a baseline. Events are appended
  to `/var/lib/mavis/events.json` (id, kind, urgency, text, created,
  delivery). Runs on its own 15-min timer, not as part of `graywind-sync`
  (so a failed sync can't stop the staleness checks).
- `reach.py` — decides delivery for urgent events: busy window or quiet
  hours → text; else call push. At most 3 call pushes a day (then text).
  Text = ntfy default priority; call = ntfy priority 5, tag
  `telephone_receiver`, title "Johnny is calling", click URL
  `<MAVIS_PUBLIC_URL>/johnny?event=<id>`.
- `briefing.py` — builds the facts block, writes a deterministic template
  brief, then asks Groq to say the same thing in Johnny's voice in ≤ 3
  sentences. **Number guard:** every number in the model's version must
  appear in the facts block, and it must be ≤ 3 sentences; otherwise the
  template is sent. Facts carry numbers already spoken-formatted ("$656",
  "-0.7%") and the guard ignores commas, so normal rewording passes. Info
  events since the last brief are folded in and marked delivered. A day
  with no Graywind decisions (holiday) is reported as a quiet day.
- **Sending:** a new synchronous ntfy sender (`push.py`) for briefs and
  events, separate from `alerts.notify()` — that one sends from a daemon
  thread a oneshot job would kill before the POST, and shares the
  10-a-day security-alert budget an attacker could exhaust. `push.py`
  returns only after ntfy accepts (non-zero exit otherwise, so systemd's
  `OnFailure` pages), with its own dedupe (`brief:<kind>:<CT date>`,
  event id) and a cap of 3 call pushes a day.
- **Test isolation:** every new path has an env override (`MAVIS_NEWS_FILE`,
  `MAVIS_EVENTS_FILE`, `MAVIS_WATCH_FILE`, `MAVIS_SCHEDULE_FILE`) that
  `conftest.py` points at a temp dir, and conftest blocks `push.py`'s
  network send like it blocks ntfy today.
- Per-symbol headlines reuse `news.py`'s Google News search feed.
- `jobs.py` — CLI the timers call: `news`, `watch`, `brief close|night`,
  `test-event` (injects a fake "position closed" event, optionally at a
  given time, to check criterion 3).

**Call opening (security-relevant — written by Claude, not delegated):**
the call page reads `?event=<id>`, shows an incoming-call screen with an
Answer button (a tap is required anyway for mic and audio), and sends the id
in the `hello`. The server accepts it only for the owner scope, only for an
id that exists in `events.json` and is under 24 h old, and then, after the
greeting, answers a synthetic opening ("explain this alert in two sentences
and ask what he wants to do") through the normal answer pipeline. Guests and
unknown ids get an ordinary call.

**Order of work (calendar-driven):** today is Fri 11/13; criterion 1 needs
two consecutive trading days, so briefs must be live by Mon 11/16 15:15 CT.
Build: news desk → state reader → push sender → briefs → timers → watch +
text-or-call → incoming-call screen with `hello{event}` last (first cut if
time runs short; `test-event` can exercise criterion 3 any day). Check
timers on the VPS with `systemd-analyze calendar` and confirm `deploy.sh`
installs and enables new units.

**Systemd (deploy/):** `johnny-news.timer` (hourly), `johnny-watch.timer`
(every 15 min), `johnny-brief@close.timer` (`Mon..Fri 15:15 America/Chicago`),
`johnny-brief@night.timer` (`Mon..Fri 21:00 America/Chicago`). All
`User=mavis`, `EnvironmentFile=/var/lib/mavis/env`, `OnFailure=mavis-alert@%n`.
News job pages the owner after 2 failures in a row (graywind-sync pattern).

## Done criteria (stage-2 rule: checkable by someone else)

1. On two trading days in a row, both briefs arrive on time (±5 min), each
   ≤ 3 sentences, and every number in them matches the Graywind dashboard.
2. Over a full day, `news.json`'s `generated_at` is never more than 65 min
   old; if the cycle breaks, an alert reaches the phone.
3. A test "position closed" event during a class window arrives as a text;
   the same event outside one arrives as "Johnny is calling", and answering
   starts a call where Johnny explains the event first.

## Left to the builder

Exact wording of templates and prompts, ntfy emoji tags, file layouts beyond
the fields named, test structure.

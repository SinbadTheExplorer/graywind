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
  (`/var/lib/mavis/watch.json`) and emit events:
  - position closed (symbol gone from positions) → **urgent** ("trade bust"
    in the owner's words; the text gives entry/stop/target, never a guessed
    exit price);
  - new pending proposal (Graywind wants a decision) → **urgent**;
  - Graywind state older than 45 min during market hours → **urgent**,
    at most once a day;
  - news file older than 65 min → **urgent**, at most once a day;
  - a new buy, or a held/watched symbol in the news → **info**.
  Events are appended to `/var/lib/mavis/events.json` (id, kind, urgency,
  text, created, delivery). Runs every 15 min after `graywind-sync`.
- `reach.py` — decides delivery for urgent events: busy window or quiet
  hours → text; else call push. At most 3 call pushes a day (then text).
  Text = ntfy default priority; call = ntfy priority 5, tag
  `telephone_receiver`, title "Johnny is calling", click URL
  `<MAVIS_PUBLIC_URL>/johnny?event=<id>`.
- `briefing.py` — builds the facts block, writes a deterministic template
  brief, then asks Groq to say the same thing in Johnny's voice in ≤ 3
  sentences. **Number guard:** every number in the model's version must
  appear in the facts block, and it must be ≤ 3 sentences; otherwise the
  template is sent. Info events since the last brief are folded in and
  marked delivered.
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

**Systemd (deploy/):** `johnny-news.timer` (hourly), `johnny-watch` run as
`ExecStartPost` of `graywind-sync.service` (so it sees fresh state),
`johnny-brief@close.timer` (`Mon..Fri 15:15 America/Chicago`),
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

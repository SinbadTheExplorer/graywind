# Johnny v1.0: the hub that watches Bullion and Graywind for you

## Context
Johnny began as a sci-fi avatar that reads your projects, reports to you and answers questions. Since then, most of the effort has gone into his visuals for social media, and the original purpose was left behind. This plan puts that purpose first. Johnny becomes the face of the whole system:
- He watches **Bullion** and **Graywind** so you never have to open Alpaca or GitHub.
- He briefs you, raises alarms and answers questions.
- He looks good doing it.

The agent-council and VPS idea is **separate and later** (someday list, by your choice). This plan uses the normal workflow: the `delegate` skill writes code first, and Claude reviews and explains each change.

**Budget:** done by **2026-10-22** (11 working days from 10/11). The phases are ordered by value, so if time runs out, the visual phases are the ones that get cut, not the purpose.

### What already exists (worktree `~/Projects/graywind-johnny`, branch `feat/mavis-avatar`, 31+ commits unpushed)
- **Panda3D avatar:** keanu/Johnny, mech and Spartan models. Kokoro voice, Groq Whisper speech-to-text, the "wake up johnny" wake word, lip sync.
- **Portal mode** (`MAVIS_PORTAL=1`): full screen, webcam head tracking, off-axis parallax (the reel effect). Head and eyes follow you (`_Look` in `avatar/scene.py`).
  - Open from the 10/7 handoff: tracker drops to about 1 fps while he talks, and nothing has been verified live yet.
- **Brain:** local FastAPI backend (`mavis/app.py`). `/ask` and `/ask/stream` use **Groq only** (`providers.py`), with no fallback. Grounding is **static snapshots**: `data/bullion_grounding.json` from 9/14 and `data/graywind_grounding.json` from 9/15.
- **Live signals already published** (public raw GitHub URLs):
  - Graywind `dashboard-data/status.csv` (`last_cycle_timestamp` heartbeat, equity, today_pnl, action, reason). Also `trade_log.csv`, `state/pending_trades.csv`, and the `small/` copies for the $2k account.
  - Bullion `data.json` (29 fields, each with `published` and `cadence`) and `news.json` (`sources{}` with ok/error/fresh).
  - Alarms exist only as labelled GitHub issues: graywind `pipeline-alarm`, `macro-alarm`, `tier-pool-alarm`, `pending-trade`; claudekit `pipeline-alarm`, `news-pipeline-stale`, `baseline-alarm`.
  - ntfy push exists only for trade approvals (`graywind_strategy/trade_approval.py` `notify_ntfy`).
  - **Gap:** missed scheduled runs are recorded nowhere, so they can only be detected from heartbeat age.

## Done criteria (checkable by someone else)
1. **Reports and alarms.**
   - "Johnny, report" gets a spoken briefing of at most 60 seconds, quoting *current* numbers: Graywind equity and P&L for both accounts, minutes since the last cycle, pending trades, Bullion data/news freshness, and open alarm issues.
   - A simulated failure (stale heartbeat fixture, or an open alarm issue) produces a spoken alarm plus a phone push within 15 minutes, and does **not** repeat once it has been acknowledged.
2. **Free-model brain.**
   - With `GROQ_API_KEY` deliberately broken, Johnny still answers out loud through the fallback chain, and `/status` names the provider that answered.
   - Questions like "how's Graywind doing" use live data, not the September snapshot.
3. **Looks and window.**
   - A compact window (always on top, resizable, draggable, remembers its position) and the full-screen portal switch with one key.
   - His head and eyes follow you in both modes. The tracker stays at **≥12 fps while he talks**.
   - Parallax runs in full screen only (your choice).
   - Verified live with screenshots you have seen.

**End state:** tag `johnny-v1.0` plus a changelog entry (what it does and doesn't do), then push on your say-so, then a panel feedback session (stage 5).

## Phases (in order; each is small and ends in a commit with tests)

### P0: Handoff and housekeeping (day 1, 10/11)
- Write the **"everything" handoff** with the `writing-handoff-docs` skill: `docs/superpowers/graywind-johnny-hub-v1-handoff.md` in the worktree. It records:
  - the 3-project picture: Johnny as the hub; Bullion released and moved to maintenance; Graywind on autopilot, reported through Johnny;
  - the agent-council and VPS idea with its phased path (Jules first, then VPS writer/reviewer pairs and Claude routine check-ins, then hourly GPU rental for a Qwen fine-tune once data exists), parked on the someday list;
  - this week's non-Johnny actions: run the Bullion panel checklist in `~/.claude/feedback/`, set `DEEPSEEK_API_KEY` and do one test run of the trade-approval advisor, decide which project leaves the active slot;
  - this plan and its done criteria.
- Copy the done criteria to `docs/superpowers/specs/2026-10-11-johnny-hub-v1-done-criteria.md`.
- Confirm `mavis/.venv/bin/python -m pytest -q` is green (382 expected) before any change.
- Save a memory pointer.

### P1: Reports and alarms, requirement 1 (days 2–5), the core purpose
- **New `mavis/health.py`**, made of pure functions tested with fixture files:
  - `fetch_signals()` downloads the raw URLs above plus open issues per label through the GitHub REST API (public repos; optional `GITHUB_TOKEN` in `~/.mavis/env` for rate limits). Each fetch has a 10s timeout, and a failed fetch is itself a signal.
  - `evaluate(signals, now) -> Digest` returns ok/warn/alarm items:
    - Graywind heartbeat age, aware of market hours (weekdays 13–20 UTC; more than 40 minutes during market hours = alarm). This closes the missed-runs gap.
    - Bullion fields older than their cadence.
    - `news.json` sources that are not ok or not fresh.
    - Each open alarm issue.
    - New trades since the last report, and pending trades.
- **Backend:**
  - `GET /health` returns the Digest as JSON.
  - `GET /briefing` turns the digest into a Johnny-voiced script with the LLM chain (P2). If every LLM is down, a **template fallback** is used, so a briefing never fails silently.
  - The live digest is also injected as context into `/ask` and `/ask/stream`, which fixes "answers off the mark" for Graywind questions.
- **Avatar:**
  - A "report" intent (keyword match on the transcript, in `avatar/states.py`).
  - An automatic briefing on the first wake of each day.
  - A background alarm watcher (every 10 minutes) diffs the digest against `~/.mavis/alarms.json`. On a new alarm it speaks (if awake) and sends a push.
- **Push:** reuse ntfy, following the `notify_ntfy` pattern in `trade_approval.py`, with an `NTFY_TOPIC` in `~/.mavis/env`.
- Pending trades already get pushed by Graywind, so they are only spoken, not pushed again.

### P2: Free-model brain, requirement 2 (days 5–6)
- In `mavis/providers.py`, turn `groq_answer`/`groq_stream` into a **provider chain** behind one interface: `answer(...)` and `stream(...)` iterate providers and fail over on error, timeout or 429. The order is:
  1. **Groq** (`openai/gpt-oss-120b`)
  2. **Gemini API free key** (Google AI Studio; this is separate from your Gemini subscription, so get a free key)
  3. **Cerebras** or **OpenRouter free models**, as a third option
- Keys go in `~/.mavis/env`. Missing keys are skipped. `/status` reports the last provider used and per-provider health.
- Tests use fake providers (first raises → second answers; all raise → clean error). The persona prompt is shared across providers.
- **Not in scope:** model "council" debate, and any Anthropic API path (see the Fable-credit memory).

### P3: Compact window, requirement 5 (days 7–8)
- In `avatar/app.py`, a new mode `MAVIS_WINDOW=compact|portal` plus a hotkey (`F`) to switch at runtime:
  - **Compact:**
    - undecorated, transparent overlay (the existing overlay path at `app.py:498-504`);
    - default size about 360×420 in the bottom-right corner, resizable (corner drag zone) and movable (drag);
    - position and size saved in `~/.mavis/window.json`;
    - **always on top**;
    - head tracking stays on (look-at only); off-axis parallax is turned off (a plain perspective camera).
  - **Portal:** the existing full-screen path, unchanged.
- **Spike first (half a day):** check whether Panda3D 1.11-dev's `WindowProperties.set_z_order(Z_top)` keeps the window above other apps on macOS. If not, set the window level through PyObjC (`NSFloatingWindowLevel`) on the native handle.
- "Toolbar" is read as an always-on-top corner widget. A menu-bar icon (show/hide) is **optional and cut first** if time is short.

### P4: Tracking while talking, requirement 3 (day 9)
This finishes the 10/7 handoff's criteria 4 and 5:
1. Fix `talkprobe` (wrap the worker in try/except and print the traceback).
2. Measure the variants, one per run: GIL switch interval, ORT `allow_spinning=0`, `MAVIS_KOKORO_THREADS=2`, lip sync off, audio playback replaced by a sleep.
3. Ship the smallest fix that keeps the tracker at 12 fps or more while he talks (`avatar/headtrack.py`, `avatar/tts.py`, `avatar/app.py`).
4. Verify live with screenshots shown to you.

Pose pacing and the idle loop (animation 3/10) get one bounded pass only if time remains.

### P5: Parallax polish, requirement 4 (day 10), first to be cut
- Compare portal mode with the reel (`~/Downloads/ScreenRecording_10-04-2026 13-52-10_1.MP4`): frame-grab the reel, take screenshots of portal mode, and set them side by side.
- **Stop rule:** you rate it, and it passes at 7/10 or above, or once 1 day is spent.
- Techno-vibe styling stays out of scope.

### P6: Release (day 11, 10/22)
- Full test run, then a live walkthrough against the 3 done criteria with you.
- Tag `johnny-v1.0`, write the changelog, push only on your go-ahead (the repo is public).
- Update the handoff and memory, then schedule the feedback panel session.

## Critical files
`mavis/providers.py`, `mavis/app.py` (backend endpoints), **new** `mavis/health.py`, `mavis/avatar/app.py` (window modes, watcher thread), `mavis/avatar/states.py` (report intent), `mavis/avatar/headtrack.py`, `mavis/avatar/tts.py`, `mavis/avatar/scene.py` (camera mode switch). Tests go in `mavis/tests/`.
Reuse: `graywind_strategy/trade_approval.py:notify_ntfy` (push pattern), `avatar/brain.py` (backend client), `tools/render_portal.py` (offscreen checks).
Leave alone: Graywind trading code, the main checkout on `integrate-approval`, and the gitignored model assets.

## Verification
- **Unit:** `cd ~/Projects/graywind-johnny/mavis && .venv/bin/python -m pytest -q` stays green. New tests:
  - `health.evaluate` on fixtures (fresh, stale heartbeat in and out of market hours, stale Bullion field, source down, open alarm issue);
  - alarm dedupe;
  - provider failover;
  - briefing template fallback.
- **Live backend:** `curl localhost:8000/health` and `/briefing` against the real URLs. Then break `GROQ_API_KEY` and confirm `/status` shows the fallback provider.
- **Alarm end to end:** point the watcher at a stale fixture, then confirm he speaks, the ntfy push arrives on your phone, and it does not repeat.
- **App:** run with `set -a; . ~/.mavis/env; set +a; .venv/bin/python -m avatar.app` (not through Johnny.app, which loses stderr). Check compact and portal, the F toggle, and always-on-top over Chrome. Take timed screenshots and show them to you.
- **Tracker:** use the talkprobe numbers (≥12 fps while speaking). Don't trust implementer claims; re-run the probes independently.

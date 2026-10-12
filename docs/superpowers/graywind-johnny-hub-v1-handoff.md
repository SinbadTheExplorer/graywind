# Johnny Hub v1 (and the bigger picture): Session Handoff

**Written:** 2026-10-11 · **For:** the next Claude Code session on the owner's Mac. It starts **P1 (reports and alarms)** of the Johnny Hub v1 plan. This doc also records the strategy conversation that produced the plan.

This **supersedes** `graywind-johnny-look-tracking-handoff.md` for *direction*. That file is still the reference for tracker-while-talking (P4): its probe idioms and its open criteria 4 and 5.

## Goal

The owner realized Johnny drifted away from his original purpose. He was meant to be a sci-fi avatar that **reads Bullion and Graywind, reports, raises alarms and answers questions**. Instead, most of the effort went into visuals for social media. The new direction treats the three projects as **one system**:

```
            OWNER
             ↑  talk / briefings / alarms (spoken + phone push)
          JOHNNY  (the hub)
             ↑
     ┌───────┴────────┐
  BULLION          GRAYWIND
  (market data)    (paper trading, on autopilot)
```

Owner requirements (10/11):
1. Reads Bullion and Graywind data and gives reports, alarms and failures.
2. Has a brain made of free-model API keys, so the owner asks and he answers.
3. Looks good and tracks the owner's movement with his head.
4. Parallax "rising out of the screen" illusion, like the @ojrgb Instagram reel.
5. Lives as a small, resizable, always-on-top avatar that can go full screen.

- **Done criteria (owner-approved):** `docs/superpowers/specs/2026-10-11-johnny-hub-v1-done-criteria.md`. Budget: **2026-10-22**.
- **Plan:** `docs/superpowers/plans/2026-10-11-johnny-hub-v1.md` (phases P0–P6, cut from the bottom).
- **Ledger:** none. The plan's phase list, plus `git log`, is the record.

Owner choices (10/11, via questions):
- 2-week budget.
- Parallax in **full screen only** (compact mode keeps look-at tracking without parallax).
- Alarms are **spoken plus pushed to the phone (ntfy)**.
- The agent-council idea is **separate and later** (see below).

## How to resume (do this first)

1. Re-orient:
   ```
   cd ~/Projects/graywind-johnny            # worktree, branch feat/mavis-avatar
   git log --oneline -3                     # expect this handoff's docs commit on top of b8f3f2d
   git status --short                       # expect clean
   ```
   The branch is **31+ commits ahead of `origin/feat/mavis-avatar`, and NOTHING is pushed.** The repo is PUBLIC, so pushing is the owner's call.
2. Tests: `cd mavis && .venv/bin/python -m pytest -q` → **382 passed** (checked 10/11 before any P1 work).
3. Workflow (global CLAUDE.md): use the **`delegate` skill first** for implementation, then review it yourself and explain what changed in plain language before the owner accepts it. Use TDD.
4. **Immediate next action:** start P1. Write `mavis/health.py` (`fetch_signals`, `evaluate(signals, now) -> Digest`) test-first against fixture copies of the real files listed under "Live signals" below.

## Current state (active files)

**Branch:** `feat/mavis-avatar`, at `b8f3f2d` plus this session's docs commit.

**Created this session (docs only, no code):**
- `docs/superpowers/specs/2026-10-11-johnny-hub-v1-done-criteria.md`: the 3 done criteria and the budget
- `docs/superpowers/plans/2026-10-11-johnny-hub-v1.md`: the full phased plan
- this handoff

**Files P1–P4 will modify (untouched so far):**
- **new** `mavis/health.py`: signal fetch and evaluation into a Digest
- `mavis/app.py`: new `GET /health` and `GET /briefing`; inject the digest into `/ask` and `/ask/stream`
- `mavis/providers.py`: Groq only today (`groq_answer` :84, `groq_stream` :103, model `openai/gpt-oss-120b`, persona :24). This becomes a provider chain in P2.
- `mavis/avatar/states.py`: "report" intent
- `mavis/avatar/app.py`:
  - alarm watcher thread
  - window modes. Overlay path :498-504 is undecorated and transparent. Portal path :509-513 is full screen. Nothing sets z-order, size or origin today.
- `mavis/avatar/headtrack.py`, `mavis/avatar/tts.py`: tracker starvation while talking (P4)
- `mavis/avatar/scene.py`: plain perspective camera for compact mode (portal uses `off_axis`, `portal.py:125-139`)

**Live signals Johnny will read** (public, no auth; `raw.githubusercontent.com/SinbadTheExplorer/<repo>/main/<path>`):
- **graywind**
  - `dashboard-data/status.csv` (+ `small/`): `last_cycle_timestamp` is the heartbeat. `index.html` calls it live under 20 min, stale at 20–240, dead beyond.
  - `dashboard-data/equity_curve.csv`, `dashboard-data/trade_log.csv`
  - `state/pending_trades.csv`, `state/decision_log.csv` (`macro_breaches=unavailable` when the Bullion feed is down)
  - Cycles: Actions cron `7,37 13-20 * * 1-5`, plus the Cloudflare worker `*/15 13-20 * * 1-5`.
- **claudekit/bullion-live-map**
  - `data.json`: 29 fields, each with `value, published, cadence, source`. Daily at 10:07 UTC.
  - `news.json`: `generated_at`, `headlines[]`, and `sources{cnbc, marketwatch, mw_bulletins, yahoo_dji}` each with `ok, error, fresh, newest`. Hourly 13–21 UTC on weekdays.
- **Alarm issues** (GitHub REST; filter open issues by label):
  - graywind: `pipeline-alarm`, `macro-alarm`, `tier-pool-alarm`, `pending-trade`
  - claudekit: `pipeline-alarm`, `news-pipeline-stale`, `baseline-alarm`
- **Push:** ntfy already exists for trade approvals. Copy the pattern from `graywind_strategy/trade_approval.py` `notify_ntfy` (in the graywind repo `origin/main`, not this worktree's `mavis/`).

**Scratch / traps:**
- ⚠️ **Missed scheduled runs are recorded nowhere.** GitHub has dropped about 7 of 9 Bullion news slots a day, and the cron worker silently stopped after the account rename. Johnny must detect them from **heartbeat age vs. schedule**. Don't wait for an issue.
- ⚠️ `data.json` has no per-source ok/error field, so a failed fetch only shows as an old `published` date.
- ⚠️ The current Q&A grounding is **static**: `data/bullion_grounding.json` (9/14) and `data/graywind_grounding.json` (9/15, 6 facts). Johnny's "answers off the mark" complaint (script 4/10) traces partly to this. Don't rebuild the Bullion corpus (it was re-verified identical on 9/25); add the live digest instead.
- ⚠️ `mavis/.venv` is this worktree's **own** venv (Panda3D 1.11.0.dev3895, the only build with Retina on macOS). Don't relink it to the main checkout.
- ⚠️ Johnny.app sends stderr nowhere. Debug with `.venv/bin/python -m avatar.app` after `set -a; . ~/.mavis/env; set +a`.
- ⚠️ A small window would break portal parallax: `off_axis` assumes the window covers the whole physical screen (`MAVIS_SCREEN_CM`). That's why compact mode uses a plain camera.

**Not mine, leave alone:**
- the main checkout `~/Projects/graywind` (on `integrate-approval`, with its own dirty files)
- all Graywind trading code
- gitignored franchise model assets (Spartan, Hulkbuster)
- the worktrees under `graywind/.claude/worktrees/`

## What has changed

- **No code changed this session.** Only the docs listed above. Tests: 382 passed before and after.
- **Strategy decisions this session** (owner conversation, 10/8–10/11), recorded here because no other file has them:
  1. **Johnny becomes the hub** for the three projects (diagram above). Graywind's "too lazy to check Alpaca daily" problem gets solved by Johnny checking for the owner. Bullion becomes a data source for Johnny.
  2. **Bullion should be Released** (tag plus changelog) and moved to the maintenance slot. Its real gap is **people, not code**:
     - The one Reddit post got 0 engagement, which is one data point, not a verdict.
     - **The stage-5 feedback panel has never been run.** The checklist is in `~/.claude/feedback/`; read `~/.claude/feedback/bullion-launch-handoff.md` first.
  3. **Graywind runs on autopilot.** Its "noteworthy achievement" is reframed as quant discipline plus an honest paper-trading record plus the trading course, not profit.
     - Quick win: the trade-approval advisor only needs the `DEEPSEEK_API_KEY` repo secret and one manual `workflow_dispatch` dry run.
  4. **WIP cap:** the owner must decide which project leaves the active slot. The proposal: Bullion → maintenance; Johnny (plus Graywind reporting) active.
- **The 24/7 agent-council idea: PARKED (someday list, the owner chose "separate later").** The discussion concluded:
  - The owner's instincts are sound and match industry practice: cheap workers checked by a strong reviewer (as the existing `delegate` skill already does), cross-provider review, guardrails over trust, distilling into a small fine-tuned model. The flaw was the **build order**, not the direction.
  - Phased path when it resumes:
    1. Phase 1: **Jules** (comes with the owner's free 1-year Gemini/Google AI Pro subscription; check the actual entitlements first) plus Gemini CLI headless, running small tasks with real executable checks on a branch. Success means 3 or more of 10 PRs worth merging. Cost $0.
    2. Phase 2: about a $5–12/mo VPS (Hetzner/DO) running writer and reviewer models from different providers, with tests as the referee, plus **Claude scheduled routines checking in about twice a day** rather than a 24/7 Claude. Advance only after 2 weeks with no silent failures.
    3. Phase 3: fine-tune Qwen with **hourly GPU rental** (RunPod/Vast, about $5–20 a run) or free Kaggle/Colab GPUs, **only once a narrow repeated task plus 500 or more examples exist** (for example, from council logs). A cheap VPS can't fine-tune, so this is hardware gate 1.
  - Rules agreed in discussion:
    - Use one free tier per *provider*. **Never** make several accounts on one provider to rotate keys (it breaks the terms of service and risks a ban).
    - Unconstrained model debate amplifies errors and burns quota, so use fixed roles with tests as the arbiter.
    - Agents work branch-only: no main, no deploy, no secrets, never Graywind trading logic.
    - Use limits on change size and on attempts per task, plus a heartbeat alarm.
  - It counts as a **project** for the WIP cap, even though the owner framed it as infrastructure.

## What has failed / risks / caveats

- **Nothing has failed this session** (planning only).
- **Still open from 10/7** (they become P4): tracker criterion 5 (drops to about 1 fps while talking; the in-app `talkprobe` printed nothing) and criterion 4 (nothing verified live). See the look-tracking handoff.
- **UNVERIFIED assumptions in the plan:**
  - Whether Panda3D 1.11-dev's `set_z_order(Z_top)` works on macOS. P3 starts with a half-day spike; the fallback is PyObjC `NSFloatingWindowLevel`.
  - Whether the Gemini **API** free key (AI Studio) works for `/ask/stream` streaming. The consumer Gemini subscription is **not** API credit; the same lesson as the Fable credit.
- **Budget risk:** 11 days for 6 phases. If it slips, cut **P5 (parallax polish) first**, then the optional menu-bar icon, then the animation pass. Never cut P1 or P2; they are the purpose.
- **Owner feedback carried forward:**
  - Animation 3/10 (pose pacing, idle loop). Model and filler lines are good, so do not change them.
  - Voice "will do".
  - The mech's framing went about 17% smaller on 10/7, and the owner hasn't seen it yet.
- **Rule:** an LLM briefing must never fail silently. If every provider is down, use the template fallback text.

## What's next (ordered)

1. **P1 (days 2–5): reports and alarms.**
   1. `mavis/health.py` written test-first. Fixtures: fresh; heartbeat stale inside vs. outside market hours; stale Bullion field; news source down; open alarm issue; fetch failure.
   2. Backend `/health` and `/briefing`, with the template fallback.
   3. Inject the digest into `/ask` and `/ask/stream`.
   4. Avatar "report" intent plus a briefing on the first wake of the day.
   5. Alarm watcher every 10 min, deduped via `~/.mavis/alarms.json`, sending ntfy using `NTFY_TOPIC` in `~/.mavis/env`.
2. **P2 (days 5–6): provider chain** in `providers.py`: Groq → Gemini → Cerebras/OpenRouter, failing over on error, timeout or 429; `/status` names the provider. The owner needs to create the free keys and put them in `~/.mavis/env`.
3. **P3 (days 7–8): compact window.** `MAVIS_WINDOW=compact|portal`, `F` toggles, always-on-top, resize, drag, position saved to `~/.mavis/window.json`.
4. **P4 (day 9): tracker ≥12 fps while talking**, plus live screenshots (see the look-tracking handoff's "What's next").
5. **P5 (day 10): reel comparison.** Stop when the owner rates it 7/10 or higher, or after 1 day.
6. **P6 (10/22): release.** Tag `johnny-v1.0` and write the changelog; push on the owner's say-so; then the feedback panel.
7. **Outside Johnny, for the owner this week:**
   - send the Bullion panel checklist;
   - set `DEEPSEEK_API_KEY` and dry-run the advisor;
   - pick which project leaves the active slot;
   - (still pending from 10/1) `npx wrangler deploy` the cron-trigger worker if not done.

## Verification idioms used in this project (for the resuming session)

- **Tests:** `cd mavis && .venv/bin/python -m pytest -q` (382 as of 10/11). Mutation-test behavioural fixes. Clear bytecode before mutate/restore runs: `find . -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +`.
- **Live backend:** run it via `scripts/mavis-backend.sh` (uvicorn on :8000, sources `~/.mavis/env`). Then `curl -H "X-API-Key: $MAVIS_API_KEY" localhost:8000/status` (and `/health` and `/briefing` once they exist).
- **Real signal check:** `curl -s https://raw.githubusercontent.com/SinbadTheExplorer/graywind/main/dashboard-data/status.csv`. Open issues: `gh issue list -R SinbadTheExplorer/graywind --label pipeline-alarm --state open`.
- **App, live:** `set -a; . ~/.mavis/env; set +a; .venv/bin/python -m avatar.app`. If the launch agent is running, run `launchctl bootout gui/$UID/com.mavis.avatar` first. The app opens on screen and speaks out loud, so warn the owner.
- **Offscreen look:** `.venv/bin/python -m tools.render_portal --avatar mech-bust --frame 308 --out x.png`. Read the PNG yourself before asking the owner.
- **Never trust implementer (delegate or subagent) verification claims.** Re-run the probe or test yourself.

# Johnny Call Mode — Session Handoff

**Written:** 2026-11-09 · **For:** a fresh session continuing Johnny Call Mode at **step 3 (Tailscale → first real phone call)**, then criteria testing.

## Goal

Johnny appeared at the wrong times, or not at all. Three things caused it:
- **Wake word:** the model was never trained (`mavis/assets/wakeword/` is empty), so only the W key woke him.
- **Window glitches:** hiding and re-showing the 3D window glitched.
- **Leaving:** dismissal was spoken-only.

The owner replaced all of that with a **Sesame-style call**. On phone or laptop, open a web page, tap **Call**, and the 3D Johnny picks up. You talk, he answers, and you tap **End**. This is a scope change to Johnny Hub v1, not a new project.
- Spec / done criteria: `docs/superpowers/specs/2026-11-09-johnny-call-mode-done-criteria.md` (6 criteria; **built by Mon 11/16, done by Mon 11/23**; cut #5 first if late)
- Plan: `docs/superpowers/plans/2026-11-09-johnny-call-mode.md`
- Prior handoff (Hub v1, still the parent effort): `docs/superpowers/graywind-johnny-hub-v1-handoff.md`. Read it only if you need Hub v1 context.

## How to resume (do this first)

1. Work in the worktree `~/Projects/graywind-johnny` on branch `feat/mavis-avatar`. Run `git log --oneline ed846eb0..HEAD`: there should be 7 commits, ending `8343adab`.
2. Read the criteria and the plan. Steps 1 and 2 of the plan are DONE. The owner's global workflow (`~/.claude/CLAUDE.md`) applies. Implementation goes through the `delegate` skill first. Claude reviews it, runs `code-review`, and explains the change in plain language. The owner must approve before each commit.
3. Trust git and these docs over memory.
4. **Immediate next action:** step 3, Tailscale.
   - Guide the owner to install Tailscale on the Mac and the phone, both signed into the same account. This is a manual step for the owner.
   - Start the backend with the call voice warm.
   - Expose it with `tailscale serve` over HTTPS.
   - The owner opens `https://<mac>.<tailnet>.ts.net/johnny` on the phone and places the **first real-voice call**.

## Current state (active files)

**Branch:** `feat/mavis-avatar`, 39 commits ahead of `origin/feat/mavis-avatar` (all unpushed). **The repo is public. Push only when the owner says so.**

**Call Mode commits:** `75dfab6c` → `6d6c3f38` → `74a13983` → `110b34be` (docs), `2a0e96c1` (step 1), `c891db63` (step 2), `8343adab` (docs).

**Files created / changed:**
- `mavis/call.py`: the call itself, with no I/O of its own. It has one receive loop running alongside each turn, so End cancels a turn instantly. It plays one filler if the answer is slow, and handles the half-duplex turn flow and the timing log (`call: first audio N ms`).
- `mavis/call_route.py`: the server side.
  - `/call` WebSocket. The first message must be `{"type":"hello","key":...}`. Close code 4401 means wrong key, 4400 means a bad or missing hello, 1011 means the server key is unset.
  - `GET /johnny` serves the page.
  - `GET /johnny/model.glb` serves the model and needs the key (`Cache-Control: private, no-cache`).
  - `GET /johnny/check` is the key check.
  - It plugs in Groq STT (`stt.transcribe_wav`), `app._answer_events`, Kokoro, and the canned lines. Rate limiting counts per utterance, before the paid STT call.
- `mavis/app.py`: `/ask/stream`'s body was extracted to `_answer_events()`, which `/call` shares. There's a lifespan hook for voice warm-up, the call router is included, and three.js is mounted at `/johnny/vendor`.
- `mavis/auth.py`: new `key_matches()`. `mavis/avatar/stt.py`: new `transcribe_wav()`.
- `mavis/web/call.html`: the page. It has three screens (key, idle, call), a 3D Keanu with idle/smoking/dismiss clips, a jaw driven by playback level, blinks, a mic AudioWorklet with an energy voice-activity detector (16 kHz WAV upload), a playback queue, Mute and End, a wake lock, and an orb fallback. Debug hooks are on `window.__johnny`: `setMouth`, `setBlink`, `play`, `vad`, `jawAxis`, `V`. Add `?debug=1` for an fps counter.
- `mavis/web/vendor/three/`: three.js r160, MIT licensed, vendored deliberately so that no third-party script runs next to the key saved in localStorage.
- Tests: `mavis/tests/test_call.py` (14), `mavis/tests/test_call_route.py` (10). The full suite has **406 passing**.

**Not in git (on purpose):** `mavis/assets/avatar/keanu-web.glb` (6.4 MB). It is built from the owner's local Keanu rip, which is © CD Projekt Red, gitignored, and never published. The rebuild recipe is in the plan, step 2:
- Source: `~/Downloads/Keanu 3D model.rar`.
- Clips: `~/Documents/{Breathing Idle,Smoking,Dismissing Gesture,Angry,Offensive Idle}.fbx`.
- Run Blender `tools/retarget_anim.py`, then `gltf-transform optimize` with the flags listed in the plan.

**Scratch / traps:**
- ⚠️ `/private/tmp/claude-501/.../scratchpad/` from the 11/9 session holds the probe scripts (`call/probe*.mjs`, `probe.py`) and renders. They're temporary and may be gone. Don't rely on them.
- ⚠️ Another backend may already be running on **port 8000** (PID was 1108 on 11/9, the LaunchAgent `scripts/mavis-backend.sh`). It runs **old code without `/call`**. For testing, either restart it with the new code or run a second one on another port (11/9 tests used 8765 with `MAVIS_API_KEY=probe-key`).
- ⚠️ Voice warm-up is **opt-in**: `MAVIS_CALL_WARM=1`. Without it, the first call after a restart waits several seconds for Kokoro to load.

**Not mine — leave alone:** `.DS_Store`. Leave all Graywind trading code alone as well.

## What has changed

- **Step 1** (`2a0e96c1`): the `/call` WebSocket. Live-measured against the real Groq, Kokoro and brain: pick-up 18 ms, first answer audio 2.0–2.7 s, End → bye 30 ms.
- **Step 2** (`c891db63`): the call page with the 3D Keanu. Verified in headless Chrome at 390×844:
  - The model loads in about 1 s, and the bones and the 5 clips are found.
  - Jaw and blink were checked visually.
  - A full call through the page worked: injected speech, real STT, answer, captions, jaw up to 0.85.
  - End call releases the mic, socket and audio.
  - A second call started with a double tap works.
- Both steps had a delegate draft, Claude's fixes, and a `code-review` pass with all findings fixed. The owner approved and asked for both commits.
- `~/.local/bin/delegate`: the output cap was raised to 16384 tokens (`DELEGATE_MAX_OUTPUT_TOKENS`), and it now warns when output is truncated. Groq had been silently cutting off at 3072. A backup is in the session scratchpad.

## What has failed / risks / caveats

- **Nothing is broken in the committed code.**
- **UNVERIFIED, real microphone:** no real voice has gone through the page yet. Headless Chrome's fake mic only delivered silence, so tests fed frames straight into `__johnny.vad`. The voice-detection thresholds are untuned guesses: start above max(0.012, 3× floor), end after 700 ms of quiet. Expect to tune them on the phone.
- **UNVERIFIED on iPhone Safari:** audio unlock on the Call tap, AudioWorklet support, wake lock, and real frame rate on a phone GPU (criterion: 24 fps or better). The headless 10 fps comes from CPU rendering and means nothing.
- **Latency risk:** answers take about 2.5 s with the server alone, but **about 6 s when the same Mac also renders Johnny** (CPU contention with Kokoro). The phone renders on its own GPU, so it should be fine. Calling from the **laptop browser** may miss criterion #2 (3 s).
- **"Graywind" heard as "Greywind"** by STT with the macOS `say` voice. Johnny then says he has no data. This bug predates call mode. Check it with the owner's real voice before acting.
- **Jaw tuning:** the axis is `(0,0,-1)` at 9°, and the lids use the same axis at −22°. These were found by rendering. GLTFLoader strips `.` from bone names, so the page sanitizes names via `PropertyBinding.sanitizeNodeName`.
- **Decisions carried forward (they override earlier plan text):**
  - The model is **Keanu** (owner's choice), not mech-bust and not `jonny_fixed`. It is local-only and must never be on a public URL. That matters for the cloud decision.
  - The server stays on the laptop until #1–#3 pass. After that the options are about $5/month for a VPS, or Oracle Pay-As-You-Go. Free Oracle is ruled out because it reclaims idle servers. A public cloud host conflicts with Keanu's licence, so raise this with the owner then.
  - No talking over Johnny in v1 (it's half-duplex). No new animation here, because animation is the owner's claude.ai lane.
  - The desktop wake-word app is untouched. The call page is a new front door, not a rewrite.

## What's next (ordered)

1. **Step 3: Tailscale.**
   - The owner installs it on the Mac (`brew install --cask tailscale` or the App Store) and the iPhone, then signs in on both.
   - Run `tailscale serve --bg 8000` (or the port the backend uses) and get the URL from `tailscale serve status`.
   - Start the backend from `mavis/` with the new code: `MAVIS_CALL_WARM=1 MAVIS_API_KEY=<owner's key> .venv/bin/python -m uvicorn app:app --port 8000`, or restart the LaunchAgent and add `MAVIS_CALL_WARM=1` to it.
   - Write the URL into this doc.
2. **First real call from the phone.** Watch the server log for the `call:` timing lines. Tune the voice detector in `web/call.html` (`MIN_THRESHOLD`, `END_FRAMES`) if it cuts the owner off or never triggers.
3. **Step 4, alarm push (criterion #5, cut first):** an alarm inbox `data/alarms/*.json`, a `--test-alarm` command, and an ntfy push linking to `/johnny?alarm=<id>`.
4. **Owner runs the criteria checks:**
   - #1: 10 calls each on phone wifi, phone cellular and laptop.
   - #2 and #3: timings from the log.
   - #4: one idle day.
   - #6: one other person; this triggers the `~/.claude/feedback/` panel.
5. Then decide the cloud host and tag a release, per the workflow's Released/Buried rule.

## Verification idioms used in this project

- Tests: `cd mavis && .venv/bin/python -m pytest -q` (expect 406 or more passing).
- Live server probe: run uvicorn on a spare port with a throwaway `MAVIS_API_KEY`. Connect with `websockets` from `.venv`, send hello plus a 16-bit 16 kHz WAV (make one with `say -o q.wav --data-format=LEI16@16000 "..."`, then **rewrite it with Python's `wave` module**, because `say` adds a JUNK chunk), and time the messages.
- Page in headless Chrome: use the `headless-chrome-verification` skill's CDP template at `--window-size=390,844`. Set `localStorage['johnny.key']`, wait for `__johnny.modelLoaded`, and screenshot. To test a call, detach the fake device (`__johnny.S.micNode.port.onmessage = null`) and feed 320-sample frames to `__johnny.vad` at 20 ms intervals.
- Never claim audio is audible from automation. Real sound needs the owner's ears.

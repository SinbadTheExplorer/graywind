# Johnny Call Mode: Plan

Criteria: `docs/superpowers/specs/2026-11-09-johnny-call-mode-done-criteria.md`. Branch: `feat/mavis-avatar`.

## What exists already
- `mavis/app.py`: the FastAPI brain, with `/ask`, `/ask/stream` and API-key auth (`auth.py`).
- `avatar/stt.py`: Groq Whisper speech-to-text, in the cloud.
- `avatar/tts.py`: Kokoro voice, local on the laptop, about 0.4x realtime on CPU.
- `avatar/dismiss.py`, `avatar/canned.py`: dismissal phrases and canned greeting/filler lines. Reuse these.

The desktop wake-word flow (`avatar/app.py`, `wake.py`) is left as is. The call page is a new front door, not a rewrite of the desktop app.

## Steps

1. **Call endpoint (server, test-first)**
   - Add a WebSocket `/call` to `mavis/app.py`, behind the existing API key.
   - Per turn: receive one utterance of audio from the browser → Groq STT → `/ask/stream` logic → Kokoro sentence by sentence → stream audio back.
   - Send the canned greeting on connect.
   - If the answer is slow, send filler (the same 3 s rule as the desktop).
   - A spoken "that's all" ends the call too.
   - The server cancels all work the moment the socket closes. That gives End call its 1 s limit.

2. **Call page (one static HTML file, served by FastAPI)**
   - Sesame-style layout: a Johnny card, Call button, then the call screen with **3D Johnny**, timer, Mute and End call.
   - three.js (pinned version from a CDN) loads `jonny_fixed.glb`. His mouth follows his voice's volume, the same idea as `lipsync.py`. Listening/thinking/speaking play the existing clips named in the scene config.
   - Check the phone frame rate; if it's under 24 fps, shrink the model's textures. If it still fails, fall back to the orb.
   - Browser mic with voice-activity detection to cut utterances, so only finished speech is sent and silence is never uploaded.
   - The API key is entered once and saved on that device.
   - Mobile-first layout; check it on iPhone Safari specifically, which is strict about audio autoplay and the mic.

3. **Tailscale**
   - The owner installs Tailscale on the laptop and phone (a one-time manual step, guided).
   - `tailscale serve` exposes the FastAPI port over HTTPS on the private network only.
   - Write the URL into the handoff doc.

4. **Alarm push (#5, cut first)**
   - Alarm inbox `data/alarms/*.json` plus a `--test-alarm` command.
   - A new alarm sends an ntfy push whose link opens the call page with `?alarm=<id>`.
   - Johnny opens the call by speaking it, and the alarm is removed only after it has been spoken.

5. **Timing log**
   - The server logs call→greeting, question-end→first-audio and close→silent times.
   - The owner's 10/10 checks for #1–#3 read these numbers.

## Order and cut line
Build 1→2→3, which covers criteria #1–#4 and #6. Then step 5 (the timing log, small, folded into step 1). Step 4 is last and is the first thing cut.

## How each criterion gets checked
- **#1, #3:** 10 calls on each device or network, plus the timing log.
- **#2:** the timing log.
- **#4:** idle day; the log shows no `/call` sessions the owner didn't open.
- **#5:** `--test-alarm`, then tap the push.
- **#6:** one other person, no instructions.

## Risks
- **iPhone audio:** Safari blocks audio that doesn't follow a tap. The Call tap must unlock playback.
- **Kokoro speed:** the laptop's CPU sets the speed. If the 3 s target fails, fall back to a cloud voice.
- **Model weight on phones:** the avatar folder is 53 MB in total; check the size of `jonny_fixed.glb` itself and compress it (e.g. gltf-transform) if it loads slowly.
- **Laptop asleep:** calls fail in v1. Cloud move decided after #1–#3 pass. Keep config in environment variables so it can move.

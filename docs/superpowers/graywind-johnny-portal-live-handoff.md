# Johnny Portal Mode — First Live Session Handoff

**Written:** 2026-10-04 (late) · **Supersedes** `graywind-johnny-portal-terminal-handoff.md`
for what's next; that file is still the reference for how portal mode is built.

## How to resume

1. `cd ~/Projects/graywind-johnny` — branch `feat/mavis-avatar`, local commits
   `d0bb9e8`..`e9fc070` on top of `3bd3033`, **none pushed**.
2. `cd mavis && .venv/bin/python -m pytest -q` → **373 passed**.
3. ⚠️ `mavis/.venv` is now this worktree's OWN venv on **Panda3D
   1.11.0.dev3895** (no longer a symlink to the main checkout's 1.10 venv).
4. ⚠️ Johnny.app's stderr goes nowhere. Debug by stopping the launch agent
   (`launchctl bootout gui/$UID/com.mavis.avatar`) and running
   `set -a; . ~/.mavis/env; set +a; .venv/bin/python -m avatar.app`.
   Two Johnnys at once fight over full screen and one quits. Re-enable with
   `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.mavis.avatar.plist`.

## Done this session

- Merged the cloud portal branch onto the Kokoro fast-voice work (`b9fa3d0`).
- Glow buffers fixed for macOS (`ecf9dd0`); the window used to be blank and stuttering.
- He stays visible while asleep in portal mode (`a53339e`).
- The mech's eyes stay inside the glass (`cb3fef2`): framing 1.45 / rise -0.04,
  `portal_still` holds frame 0, pinned by `tests/test_portal_eyes_in_view.py`.
- Retina rendering with Panda 1.11 + dpi-aware: 2940x1912 (`e1362c5`).
- 30fps cap (`e9fc070`): measured 27.5fps mean, but p95 frame time is 51ms,
  so the pacing is uneven. Check that it's smooth.
- spartan + hulkbuster rebuilt locally from the owner's raw Sketchfab GLBs.
- `~/.mavis/env`: MAVIS_PORTAL=1, MAVIS_SCREEN_CM=29.0x18.9 (backup: env.bak-pre-portal).
- Verified by an automated spoken exchange (scratch probe; shape below):
  mech first word 1.77s, keanu 1.55s, spartan 2.05s. Jaw (mech, keanu) and
  nod (spartan) move with speech, and he stays visible after dismissal.

## Owner's list (2026-10-04), in priority order

1. **Mech animation back ("shaking"), the owner trusts us on this.** The reel
   is "animated fbx". Remove `portal_still`, play `anim`, and extend
   `test_portal_eyes_in_view` to sample poses ACROSS the clip (not frame 0),
   then refit framing so the eyes never clip at any frame.
2. **Head and eyes track the viewer, for both the mech and Johnny** (owner's
   last words). Today only the whole pivot turns ±9°/±10°. Drive the head/neck
   joints (and keanu's `LeftEye`/`RightEye`) toward the tracked eye, layered
   on top of the clip.
3. **Webcam drops to ~1fps while he talks** (HUD showed `cam 1fps`
   mid-answer). Kokoro synthesis (4 threads) starves the tracker thread.
4. **Mech = separate character: "caged predator"** (low, menacing, patient,
   "it could get you if not for the glass"), with its own Kokoro voice
   (deep and slow). Switching models with M switches persona and voice.
   Persona lives in `providers.py` PERSONA; it needs a per-model choice sent
   with `/ask/stream`. Re-run the grounding check after any persona edit
   (see the comment above PERSONA).
5. **Johnny's dog tag doesn't line up** (owner saw it live). Not yet investigated.
6. **keanu probe run ended early** after his first sentence. Not yet investigated
   (the last rerun printed nothing past "SAY speech-0").
7. Johnny's voice: owner HATES Kokoro and loved the old cloned voice, but
   chose "keep Kokoro for now". Options when revisited: ElevenLabs clone
   (needs the voice actor's consent + an account) or local chunked VC (~5-6s).
8. "Techno vibe" (gold binary / neon lines) is NOT in the reel. Style unchosen.
9. Room walls still show at the right edge from typical seats; the reel never
   shows corners.

## How to replicate the reel (told to owner)

Caption: "virtual shadow + off axis projection + animated fbx". We have the
first two; animation is item 1. The reel is filmed through ONE phone lens
while the tracker follows the person holding that phone. To record a clip that
looks the same, hold the phone next to your eye.

## Probe idioms (scratch, not committed)

- Live state: wrap `ShowBase.run` to add a `doMethodLater` task that logs
  `win.get_fb_x_size()`, the actor's `is_hidden()` and `globalClock` fps, and
  calls `win.save_screenshot(...)`.
- Spoken exchange: monkeypatch `capture.record_utterance` to return
  `say -o q.wav --data-format=LEI16@16000` audio, force the first
  `Runtime.wait_for_wake`, and wrap `AvatarScene.set_mouth`/`show_caption`/`hide`.
  Only quit on `hide()` AFTER the question; the machine hides once at startup.

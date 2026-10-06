# Johnny Portal Mode — First Live Session — Session Handoff

**Written:** 2026-10-05 · **For:** the next Claude Code session on the owner's
Mac, continuing Johnny's portal mode from its first live run: bring the mech's
animation back, make head and eyes track the viewer, give the mech its own
persona, and fix the bugs the owner found.

This **supersedes** `graywind-johnny-portal-terminal-handoff.md` for state and
next steps. That file, and `graywind-johnny-portal-handoff.md` before it, are
still the reference for **how portal mode is built**: modules, tools, the model
drop-in format, and the dead ends already tried. Read this file first. Open
those only when you need the architecture detail.

---

## Goal

Johnny is a talking 3D character (MAVIS backend, Groq answers grounded in
Bullion and Graywind data). Portal mode turns the Mac's screen into a
**window**: the webcam tracks the viewer's eyes, the scene is drawn from that
eye through an off-axis frustum, and the character stands behind the glass in
a dark room and casts a shadow. The target is the Instagram reel by **@ojrgb**,
captioned *"Virtual shadow + off axis projection + animated fbx = scary mech
that looks like it could %!?# you up if not for that thin layer between
you"*. The owner judges by eye against that reel: "the quality of that reel
or better". Their copy is at
`~/Downloads/ScreenRecording_10-04-2026 13-52-10_1.MP4`.

Several characters share the window and **M** switches between them: the
reel's **mech** (default), **Johnny** (`keanu`, the CDPR model) and the
**Spartan**. The owner's latest direction is that **each one is a different
character with its own voice and personality**, and that **every one must
talk**.

- Done criteria (older, overall release): `docs/superpowers/specs/2026-09-28-johnny-done-criteria.md`.
  The owner never explicitly OK'd its 10/1 rewording.
- Portal architecture: `docs/superpowers/graywind-johnny-portal-terminal-handoff.md`
- Model drop-in format and licences: `mavis/assets/avatar/ATTRIBUTION.md`
- There is no plan doc or ledger for this work. **Git log + this file are the record.**

## How to resume (do this first)

1. Re-orient:
   ```
   cd ~/Projects/graywind-johnny          # worktree, branch feat/mavis-avatar
   git log --oneline -12                  # expect ed66855 or later on top
   git status --short                     # expect clean
   ```
   The branch is **28 commits ahead of `origin/feat/mavis-avatar`. NOTHING is
   pushed.** The owner decides on pushing; the repo is PUBLIC.
2. Tests: `cd mavis && .venv/bin/python -m pytest -q` → **373 passed**.
3. ⚠️ **`mavis/.venv` is this worktree's OWN venv on Panda3D
   1.11.0.dev3895.** It is no longer a symlink to `~/Projects/graywind/mavis/.venv`,
   which is still on 1.10.16. Do not "fix" it back: 1.10 cannot render Retina
   on macOS.
4. Before running Johnny yourself, stop the launch agent. Two Johnnys fight
   over full screen and one of them quits:
   ```
   launchctl bootout gui/$UID/com.mavis.avatar
   # ... your runs: set -a; . ~/.mavis/env; set +a; .venv/bin/python -m avatar.app
   launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.mavis.avatar.plist   # restore after
   ```
5. **Immediate next action:** work item 1 of "What's next", the mech's animation
   back with its eyes still in frame. The owner explicitly said "i trust you to
   do that". Item 2 (head and eyes track the viewer) was the owner's last
   request before signing off ("one thing i really liked is that let the camera
   track me through the head and eyes movement for both the mech and johnny").

## Current state (active files)

**Branch:** `feat/mavis-avatar` at `ed66855`, 28 commits ahead of
`origin/feat/mavis-avatar` (`f3f4771`). This session's commits, oldest first:

| sha | what |
|---|---|
| `d0bb9e8` | Saved the 10/1 Kokoro fast-voice + streamed answers + news work, which had been uncommitted for 3 days |
| `b9fa3d0` | Merged `origin/feat/johnny-portal` (the cloud session's portal mode) on top |
| `ecf9dd0` | Glow buffers request float colour: macOS was rejecting them, which made the window blank and stuttering |
| `a53339e` | In portal mode he stays visible while asleep (the overlay used to hide him until W) |
| `cb3fef2` | Mech's eyes stay inside the glass; film look toned down |
| `e1362c5` | Retina rendering: Panda 1.11 + `dpi-aware`, own venv, MSAA chosen by density |
| `e9fc070` | 30fps cap in portal mode |
| `ed66855` | Short version of this handoff (now replaced by this file) |

**Files created / changed this session (all committed):**
- `mavis/avatar/look.py` — `Bloom.stage()` passes `FrameBufferProperties`
  (float_color, rgba 16): **the macOS blank-window fix**. Grade LUT: S-curve 0.45→0.25,
  saturation no longer held back.
- `mavis/avatar/scene.py`:
  - `hide()` and `_build()` keep actor + credit visible when `self.portal` is set.
  - New `portal_still` config key (in `_EXTRA_KEYS`). Behind the glass it holds the
    clip at frame 0 by setting `self.animated = False` after posing.
  - `_portal_msaa()`: 0 at Retina density, 4 otherwise.
  - `PORTAL_EXPOSURE` is still 0.35 (tried 0.6, reverted: it washed the wall).
- `mavis/avatar/app.py`:
  - In `main()`, when portal mode is on: `loadPrcFileData` sets `dpi-aware #t`
    and `clock-mode limited` / `clock-frame-rate 30`.
  - Merge resolution: `Runtime(..., speaker=, tracker=)`. `voice_client` stays deleted.
- `mavis/avatar/stage.py` — `GRAIN_ALPHA` 0.07→0.0, `VIGNETTE_ALPHA` 0.92→0.55,
  key light ×1.5 (`6.6, 6.45, 6.2`), `CONCRETE_RGB` darkened to `(0.028, 0.035, 0.057)`.
- `mavis/assets/avatar/extra/mech-bust/avatar.json` (**tracked**):
  `portal_framing 1.45`, `portal_rise -0.04`, `portal_still true`, `sway 1.5`.
- `mavis/tests/test_portal_eyes_in_view.py` (**new**) — projects every mech glow
  vertex in the head's upper ¾ through the glass from 27 viewer positions:
  - x: −0.20, 0, +0.20 m
  - y: −0.45, −0.60, −0.85 m
  - z: −0.15, 0, +0.10 m

  The pivot is turned fully to each viewer, and every point must clear each edge
  by 6% of the screen height. It runs on two screens, `air-13` (0.290×0.189)
  and `default`.
- `mavis/tests/test_scene_portal.py` — `test_asleep_behind_the_glass_he_stays_in_view`;
  the breathing test's mech config strips `portal_still`.
- `mavis/tests/test_mech_bust.py` — framing 1.45, and not animated behind the glass.
- `mavis/requirements.txt`:
  - `--extra-index-url https://archive.panda3d.org/simple/` + `panda3d==1.11.0.dev3895`.
  - `kokoro-onnx` and `opencv-python-headless` both kept (merge).
  - ⚠️ **Pillow is NOT listed** but is installed and needed by
    `tools/fix_sketchfab_glb` and `gloss_by_colour`.

**Outside the repo (not in git):**
- `~/.mavis/env` appends `MAVIS_PORTAL=1`, `MAVIS_SCREEN_CM=29.0x18.9`
  (M2 Air: 2560×1664 px at 224 ppi; the full-screen window covers the notch rows).
  The backup from before portal mode is at `~/.mavis/env.bak-pre-portal`.
- `mavis/assets/avatar/extra/spartan/` and `hulkbuster/` (gitignored; franchise IP,
  **never commit**):
  - Rebuilt from the owner's raw downloads `~/Downloads/spartan_mkv_halo_reach_26mb.glb`
    and `~/Downloads/hulkbuster_helmet_compressed.glb`, using exactly the
    `ATTRIBUTION.md` recipes. Neither was meshopt-compressed, so no `dequantize`.
  - Their `avatar.json` files were written by hand from the recorded values:
    - spartan: nod 2.5°, sway 2, glow 6.
    - hulkbuster: dormant, framing 1.7, rise 0.02.
- `zbrush-mech` is **missing**. It needs its Sketchfab source zip
  ("zbrush-for-concept-mech-design…"), and its licence is unconfirmed. Optional.
- `~/Applications/Johnny.app` was rebuilt by `scripts/build_app_bundle.sh`, so it
  asks for the camera too. The owner has granted the camera.

**Files later work will modify (untouched so far):**
- `mavis/providers.py` — `PERSONA` is the single Johnny prompt. The mech persona needs
  a per-model choice here plus a field on `POST /ask/stream`. ⚠️ Re-run the grounding
  check described in the comment above `PERSONA` after any persona edit (a bad wording
  once made him deny context he had, 2 of 3 runs).
- `mavis/avatar/tts.py` — `Speaker` / Kokoro voice is global (`MAVIS_KOKORO_VOICE`).
  It needs a per-model voice.
- `mavis/avatar/canned.py`, `scripts/pregen_lines.py` — canned lines (greeting,
  filler, dismissal) are per *voice* in `assets/voice-<name>/`. The mech needs its own
  set in its own voice and words.
- `mavis/avatar/headtrack.py` — the tracker thread that starves while Kokoro speaks.
- `mavis/avatar/scene.py` `look_from` / `idle` — today gaze only rotates the whole
  pivot. Head/eye joints are untouched.

**Scratch workspace / traps:**
- ⚠️ **Johnny.app's stdout/stderr go nowhere.** `~/Library/Logs/mavis-avatar.log` stays
  empty because the launch agent runs `open -W -a Johnny.app`. An empty log means
  nothing. Run `.venv/bin/python -m avatar.app` directly to see errors.
- ⚠️ `tools/render_portal` renders offscreen, frame 0 only, at 1x, with no webcam. It
  **cannot show**:
  - the blank-window bug (it rendered fine while the live window was blank);
  - animation-driven clipping;
  - Retina sharpness;
  - the hide-while-asleep bug.

  Verify visual work **live**, using the probe idioms below.
- ⚠️ `AvatarApp.__init__` calls `scene.hide()` once at startup. A probe that hooks
  `hide()` must ignore that first call.
- ⚠️ `win.save_screenshot()` at 2940×1912 stalls 2–4s. Ignore fps samples taken
  around a screenshot.
- ⚠️ `mavis/assets/voice/` still holds the 28 old cloned-voice canned lines. Nothing
  reads them. **Keep them**: the owner may want that voice back.
- Scratch probes from this session live in this session's scratchpad (temporary). Their
  shapes are written out under "Verification idioms" below, so rebuild them as needed.

**Not mine — leave alone:**
- Everything outside `mavis/` and `docs/superpowers/`.
- The main checkout `~/Projects/graywind` (on `integrate-approval`, with its own
  uncommitted `dashboard-data/` and `.claude/` files).
- The Graywind trading code.

## What has changed

- **Portal mode runs live on the Mac for the first time.** Verified by live screenshots:
  - the mech in the room with glowing eyes, at 2940×1912;
  - the HUD shows `JOHNNY // LOCKED`;
  - tracking works (the eye position moves with the viewer).
- **Blank and stuttering window, root-caused and fixed (`ecf9dd0`):**
  - **Cause:** three glow buffers were `FRAMEBUFFER_INCOMPLETE_ATTACHMENT` on macOS,
    plus `GL error 0x506` every frame. The float textures sat on FilterManager's
    default 8-bit buffers. The cloud box's Mesa tolerated that; macOS does not.
  - **After the fix:** zero GL errors, and the glow works (red eyes bloom).
- **"No model on screen" (`a53339e`):** the live probe showed `hidden=True`. The
  overlay's "vanish while asleep" rule was carried into portal mode. Now he is always
  visible behind the glass.
- **Mech eyes clipping (`cb3fef2`):**
  - **Cause:** framing 1.15 / rise 0 left the eye lights 1.7cm past the top edge
    when seen from close and high. On top of that, the `anim` clip swings the head
    further.
  - **Choosing the fix:** a search over framing × rise found 1.45 / −0.04 to be
    the largest framing that passes. Others that passed: 1.55/−0.02, 1.7/0.
  - **Test:** `test_portal_eyes_in_view` failed before the fix and passes after.
- **Quality (`e1362c5`):** Panda 1.10.16 renders at point resolution (1470×956) on
  Retina, whatever `dpi-aware` says (tested). 1.11.0.dev3895 gives 2940×1912:
  - the mech's Japanese decals, scratches and rust are now visible in screenshots;
  - all 373 tests pass on 1.11;
  - live fps by MSAA setting: 4× = 45.6, 2× = 50.7, 0 = 59.3. 0 was chosen at Retina,
    and a 1:1 crop shows clean edges.
- **30fps cap (`e9fc070`):** measured 27.5fps mean, p95 frame 51ms, worst 83ms. See caveats.
- **Talking verified end to end in portal mode** (automated probe, real
  STT/Groq/Kokoro):

  | model | first word after question | mouth |
  |---|---|---|
  | mech | 1.77s | jaw `jaw_07` moved (692 distinct poses, max amount 1.0) |
  | keanu | 1.55s | jaw moved (197 distinct poses) |
  | spartan | 2.05s | nod (175 distinct pitches) |

  For the mech the run also confirmed:
  - "Warming up his voice..." clears;
  - the news headlines are read with outlets named;
  - the dismissal ("that's all") works, and he stays visible afterwards.

## What has failed / risks / caveats

- **Nothing is failing in the test suite** (373 passed). Open problems, all seen live:
- **Webcam tracking drops to ~1fps while he talks.** The HUD read `cam 1fps` in a
  mid-answer screenshot (15fps when idle). Likely Kokoro synthesis (capped at 4
  threads) starving the tracker thread. During answers the window effect freezes and
  then jumps, which is part of what the owner called "glitchy". Not yet investigated.
- **30fps pacing is uneven:** p95 51ms means frames regularly take twice the 33ms
  budget. `clock-mode limited` sleeps coarsely. Consider `sync-video` with a frame
  divisor, or measure whether the GPU is the limit.
- **The webcam runs at only 15fps when idle**, probably auto-exposure in a dim room.
  Tracking is coarse until there's more light on the face.
- **keanu's probe run ended early** right after his first sentence (no dismissal
  logged). A rerun printed nothing past "SAY speech-0". **Not investigated.** It could
  be the probe (the owner was at the keyboard) or a real crash in keanu's
  portal/clip path. Reproduce before assuming either.
- **Johnny's dog tag doesn't line up** (owner saw it live in portal mode). Not
  investigated. Suspects: the tag mesh is skinned to a joint the retargeted clips
  move differently, or it is a separate node not parented to the skeleton. Get a
  live screenshot first.
- **UNVERIFIED:**
  - eye clipping for keanu, spartan and hulkbuster. The eye test only knows the
    mech's glow meshes. keanu has `LeftEye`/`RightEye` joints; the spartan's visor is
    `Helmet_Spartan_Helmet_Mat_0`.
  - The `anim` clip across its full length. Today it's off in portal mode.
  - The owner's own ratings (presence / lag / stability). Never given.
- **Room walls still show at the right edge** from typical seats. The live resting eye
  was about x −0.05, z −0.08. The reel never shows corners.
- **Decisions carried forward (the owner's words, 2026-10-04):**
  - **Mech gets its animation back** ("we can add the animation of it shaking, i trust
    you to do that"). The reel is literally "animated fbx". `portal_still` was a
    stopgap; the eyes-in-glass requirement still stands ("make no mistakes, it
    clipped too much").
  - **Head AND eyes follow the viewer, for the mech and Johnny.**
  - **The mech is a separate character: "caged predator".** Low, menacing, patient,
    toys with you; "it could get you if not for the glass". A deep, slow voice with
    grit. M switches persona *and* voice. Johnny stays Johnny.
  - **Johnny's voice:** the owner **hates Kokoro** ("Johnny voice before was perfect,
    i hate this new voice even if it's faster") but chose **"Keep Kokoro for now"**.
    Do not switch voices without asking. Options when they revisit:
    - an ElevenLabs clone (~1–2s; needs an account AND the consent of the voice actor
      behind `actor_sample.wav`, which is still unanswered);
    - local chunked VC (~5–6s, heavy on the 8GB Mac).
  - **GPU:** the owner said the load was "embarrassing" and chose **cap at 30fps**,
    keeping full Retina. The other levers (1.5× render scale, shadow map 2048→1024,
    bloom at lower resolution) were not chosen. Ask before trading sharpness.
  - **"Techno vibe"** (orange/gold binary-number lines, neon render lines) — the owner
    asked for it, but **it is not in the reel** (checked frame by frame). Style
    options (a) scrolling gold binary on the back wall, (b) circuit traces that pulse
    with speech, (c) both, (d) a reference. **Unanswered; don't build until chosen.**
- **Honest limit, already told to the owner:** the reel looks perfect because it's
  filmed through one phone lens while the tracker follows the person holding it. Two
  human eyes always see less depth. To record a clip like the reel, hold the phone
  next to your eye.
- **The owner works late, is learning as they go, wants plain language, and asked
  to be challenged rather than agreed with.** The user's global workflow
  (`~/.claude/CLAUDE.md`) wants done criteria before code and a finite bug list.
  "Like the reel" has no stopping point, so propose 3–4 checkable criteria. For
  example:
  - no room corners ever;
  - the figure fills the frame and its eyes never crop;
  - every model talks visibly with first word ≤3s;
  - ≥28fps with smooth pacing.

## What's next (ordered)

1. **Mech animation back, eyes still in the glass.**
   1. Remove `"portal_still": true` from `mavis/assets/avatar/extra/mech-bust/avatar.json`
      (or keep the key and make it false).
   2. Extend `tests/test_portal_eyes_in_view.py` to sample the `anim` clip across its
      length. For example, `sc.actor.pose("anim", f)` for ~12 frames over
      `getNumFrames("anim")`, then `bundle.forceUpdate()` and re-read glow vertices
      with `animate_vertices`.
   3. Refit framing/rise using the same search loop as before (shape under
      Verification idioms).
   4. Verify **live** with timed screenshots across the clip.
   5. Update `test_mech_bust.py`.

   Alternative if the clip's head swing needs too small a framing: play the clip
   and override the head/neck joint toward the viewer (overlaps item 2). Tell the
   owner about the trade-off.
2. **Head and eyes track the viewer — mech and Johnny.**
   - Today `look_from` sets `self.gaze`/`self.gaze_p` and `idle()` eases the whole
     **pivot** (±9° heading, ±10° pitch).
   - Add per-model `look_joints` config (neck/head, plus eyes where they exist:
     keanu `LeftEye`/`RightEye`; the mech's joint names via `tools.inspect_model`) and
     drive them toward the eye, layered on top of the clip.
   - Use `controlJoint` + `forceUpdate()`. Remember: `controlJoint` detaches a joint
     from the clip.
   - Keep it model-agnostic (static models still use the pivot).
   - Then re-run the eye-clipping check with the new head range.
3. **Tracker starvation while talking.**
   - Instrument `headtrack.py`: frames per second actually processed, and its
     thread's wait time, while `SpeechStream` synthesises.
   - Try fewer Kokoro threads, a higher priority for the tracker thread, or running
     the face detector on a downscaled frame.
   - Target: ≥12fps of tracking during an answer.
4. **Mech persona "caged predator" + its own voice.**
   - Per-model persona prompt (`providers.py`) selected by a field on `/ask/stream`
     (sent by `brain.py` from the current model).
   - Per-model Kokoro voice (pick a deep, slow stock voice or blend; render samples to
     `.wav` and **let the owner listen** before committing).
   - Per-model canned lines in the persona's words. Use the `johnny-persona` skill for
     Johnny only; the mech needs new writing.
   - After the persona edits, re-run the grounding check above `PERSONA`.
   - After editing backend files: `launchctl kickstart -k gui/$UID/com.mavis.backend`.
5. **keanu early exit** — reproduce with the talking probe (`MAVIS_AVATAR=keanu`),
   capturing the whole stderr.
6. **Johnny's dog tag misalignment** — live screenshot of keanu in portal, find
   the tag mesh and what it's skinned or parented to (`tools.inspect_model`).
7. **Smooth the 30fps pacing** and recheck GPU load. Also the room corners at the
   right edge.
8. Eye-in-glass checks for keanu and spartan (local script; their files are
   gitignored, so skip them in pytest when missing).
9. Ask the owner for: ratings, the techno-style choice, and later the Johnny
   voice decision. Then propose done criteria and get a yes.
10. When the owner signs off: decide on pushing `feat/mavis-avatar` (owner's call),
    and remove the stale `origin/feat/johnny-portal` question (it's merged locally).

## Verification idioms used in this project (for the resuming session)

- **Tests:** `cd mavis && .venv/bin/python -m pytest -q` (373 at handoff).
  Mutation-test behavioural fixes. Before mutate/restore runs, clear stale bytecode:
  `find . -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +`.
- **Offscreen look check** (frame 0, 1x, no webcam; good for lighting and framing
  only):
  `.venv/bin/python -m tools.render_portal --avatar mech-bust --out x.png` gives a
  6-tile sheet from 6 eye positions. Then *Read the PNG yourself*.
- **Live probe (the real check):** a script that monkeypatches `ShowBase.run`
  before calling `avatar.app.main()`. With env sourced (`set -a; . ~/.mavis/env; set +a`)
  and the launch agent booted out, it adds `taskMgr.doMethodLater` tasks that:
  - log `win.get_fb_x_size()`, the eye passed to `AvatarScene.look_from`, camera
    pos, lens film/focal/offset, `actor.is_hidden()` and
    `globalClock.get_average_frame_rate()`;
  - call `win.save_screenshot(path)` at fixed times;
  - `sys.exit(0)` after ~18s.
- **FPS probe:** collect `globalClock.get_dt()` for 10s after a 4s warm-up and report
  mean fps, p95 and worst. Override MSAA by wrapping `simplepbr.init` (`msaa_samples`).
- **Talking probe:**
  1. Make the audio: `say -o q.wav --data-format=LEI16@16000 "What's the news today?"`,
     plus a "That's all, thanks." clip.
  2. Monkeypatch `capture.record_utterance` to return those clips as float32 /32768,
     sleeping for their length, then block.
  3. Let the first `Runtime.wait_for_wake` call return immediately.
  4. Wrap `Runtime.say` (log latency since the question ended), `AvatarScene.set_mouth`
     (record the amount, `self.mouth._joint.get_hpr()` and `actor.get_p()`),
     `show_caption` (screenshot 0.6s after the first captions), `show_notice` and
     `hide` (quit only after the question).
  5. Choose the model with `MAVIS_AVATAR=keanu|spartan`.
- **Framing search** (for refitting after clip/head changes): build
  `AvatarScene(base, "mech-bust", portal=Screen, registry=dict(reg, **{"mech-bust": cfg}))`
  over a grid of `portal_framing` × `portal_rise`. Score each by the test's
  worst-case slack (as a fraction of screen height) across both screens, and pick
  the largest framing that reaches ≥ 0.06.
- **Panda 1.11 Retina check:** with `dpi-aware #t`, a full-screen window reports
  `get_fb_x_size()` = 2940 on this Air. 1470 means you are on 1.10.
- **Reel frames for comparison:**
  `ffmpeg -ss <t> -i "~/Downloads/ScreenRecording_10-04-2026 13-52-10_1.MP4" -frames:v 1 -vf "crop=1320:1100:0:180,scale=900:-1" f.png`
- **Backend restart** after `app.py`/`providers.py`/`news.py` edits:
  `launchctl kickstart -k gui/$UID/com.mavis.backend`.
- **Rebuild local drop-in models:** `ATTRIBUTION.md` recipes. `pip install pillow` is
  needed for the tools; `npx -y @gltf-transform/cli@4 prune` finishes each one.

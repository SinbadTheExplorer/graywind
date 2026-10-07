# Johnny Portal Mode — Head & Eye Tracking — Session Handoff

**Written:** 2026-10-07 · **For:** the next Claude Code session on the owner's
Mac. Its job is to finish the "every model tracks you like the reel" pass: two
of the five agreed criteria are still open, the camera lag while he talks
and a live verification.

This **supersedes** `graywind-johnny-portal-live-handoff.md` for state and
next steps. Go to that file (and `graywind-johnny-portal-terminal-handoff.md`)
only for portal architecture, the model drop-in format, the probe idioms and
the older open items (persona/voice, dog tag, keanu early exit, techno vibe).

## Goal

The owner asked: *"make all the models in johnny like the mech, johnny track
eyes and move with me creating illusion like in the original instagram
video"* (the @ojrgb reel; their copy is at
`~/Downloads/ScreenRecording_10-04-2026 13-52-10_1.MP4`). Behind the glass,
each rigged model (mech, Johnny/keanu, Spartan) must keep playing its own
animation while its neck and head turn toward the tracked viewer and its
eyes land on them.

**Done criteria, agreed by the owner on 2026-10-07 (stop when all five pass):**
1. Mech, Johnny and Spartan keep their idle animation, and the head/neck turns toward the tracked eye *on top of* it. ✅
2. The eyes aim at the viewer wherever the model has real eye joints. ✅ (Johnny only; see caveats)
3. No eye or visor leaves the glass. This is checked by a test across clip frames × 27 viewer positions × the full look range. ✅
4. Verified **live** on the Mac with screenshots, not only offscreen. ❌ **NOT DONE**
5. Camera tracking stays at **≥12 fps while he talks**. Today it drops to about 1 fps mid-answer, which freezes the window illusion. ❌ **NOT DONE (investigation started)**

Owner decision this session: **Johnny's lenses made see-through-ish** (alpha 0.54 → 0.30) so his eyes can be seen following you.

- There is no spec, plan or ledger doc. **The git log and this file are the record.**

## How to resume (do this first)

1. Re-orient:
   ```
   cd ~/Projects/graywind-johnny          # worktree, branch feat/mavis-avatar
   git log --oneline -3                   # expect 62ed084 (+ this handoff's commit) on top
   git status --short                     # expect clean
   ```
   The branch is **31 commits ahead of `origin/feat/mavis-avatar`. NOTHING is pushed.**
   The repo is PUBLIC; pushing is the owner's call.
2. Tests: `cd mavis && .venv/bin/python -m pytest -q` → **382 passed**. The Spartan and
   Johnny cases of the eyes test are skipped on machines without those gitignored models; here they run.
3. ⚠️ `mavis/.venv` is this worktree's OWN venv, on Panda3D 1.11.0.dev3895. Don't relink it.
4. **Immediate next action:** finish criterion 5. Rerun the talking probe below and get its
   `PROBE` lines to actually print (the last run printed nothing; see caveats). Then compare
   variants.

## Current state (active files)

**Branch:** `feat/mavis-avatar`, at `62ed084` before this handoff's own docs commit.

**Changed this session (committed in `62ed084`):**
- `mavis/avatar/scene.py`
  - New `_Look` class plus a `_parent_of()` helper. For each driven joint it calls `controlJoint`, and each frame:
    1. rebuilds the joint's local matrix from the clips' own `AnimChannelMatrixXfmTable` values, weighted by `bundle.get_control_effect`;
    2. turns it by a world-axis rotation, converted into the parent joint's frame through an `exposeJoint` follower of the parent.
  - Config is `look: {pivot, joints:[[name, share]…], eyes:[…], heading, pitch}`. The eye joints get the share left over, so head plus eyes always add up to the full angle.
  - New `AvatarScene.face(heading, elevation)` splits the turn between the pivot and the `_Look`. `idle()` now eases `self._facing` toward `gaze`/`gaze_p` and calls `face()`.
  - **Pitch sign bug fixed.** The pivot used to get `+gaze_p`, which tipped his face UP and away from a seated viewer below him. It now gets `-elevation`.
  - `look_from` uses each look model's own limits (25° heading / 15° pitch). It measures pitch from `_pivot_z0`, so breathing doesn't shake it.
  - After `loop()` in `_build`, `set_control_effect(idle, 1.0)` is set explicitly so the look can read the blend weights.
  - keanu: `look` (pivot 0.15, Neck1 0.3, Head1 0.35, eyes LeftEye/RightEye), `portal_rise 0.18`, lens `alpha_scale 0.3`.
  - `"look"` added to `_EXTRA_KEYS`.
- `mavis/assets/avatar/extra/mech-bust/avatar.json`
  - `portal_still` removed, so **the shake is back**.
  - `look` set to pivot 0.3, neck_3_04 0.2, neck_4_05 0.2, head_06 0.3.
  - **Framing changed from 1.45/−0.04 to 1.75/+0.07**, so the mech is about 17% smaller on screen. This is the tightest framing that clears with the clip playing. Tell the owner.
- `mavis/tests/test_portal_eyes_in_view.py` — rewritten:
  - covers all 3 models across every clip (8 frames each) × 27 seats × 2 screens, with `face()` applied;
  - checks the mech's glow, keanu's `eyes` mesh, and a band of the Spartan's visor;
  - `worst_slack()` is reusable for framing searches.
- `mavis/tests/test_scene_portal.py`
  - The gaze-easing test is rewritten for the shared turn.
  - New `test_his_face_points_at_the_viewer`: the head is within 5° of the viewer and tilts the right way. Mutation-tested against the old sign: it fails.
- `mavis/tests/test_mech_bust.py`
  - Asserts the mech is animated, its driven joints, and framing 1.75.
  - New `test_the_look_rides_on_top_of_the_shake`. Mutation-tested: it fails if the clip value is ignored.
- `mavis/tools/render_portal.py` — new `--frame N`. It now poses the idle clip and calls `face()` per eye. Previous renders never showed the turn at all.

**Outside git (gitignored, franchise IP, never commit):**
- `mavis/assets/avatar/extra/spartan/avatar.json` now has `look` (pivot 0.2, Neck_05 0.35,
  Head_06 0.45), `portal_framing 2.1`, `portal_rise 0.12`. **No `idle_anim` on purpose:**
  its `Take 001` clip opens in a T-pose and tears the chest and neck armour by frame 60
  (seen in a render). The look runs on the rest pose.

**Files later work will modify:**
- `mavis/avatar/headtrack.py` — the tracker thread (criterion 5).
- `mavis/avatar/tts.py` `KokoroVoice.start()` — `ort.SessionOptions`. Candidate fixes are
  `session.intra_op.allow_spinning=0` and fewer threads (`MAVIS_KOKORO_THREADS`, default 4).
- `mavis/avatar/app.py` — `Runtime.say` uses `sounddevice`, and `_tick` drives the mouth and `idle` on the render thread.

**Scratch / traps:**
- ⚠️ This session's probe scripts are in the session scratchpad, which is temporary:
  `aim.py`, `animprobe.py`, `fit.py`, `face.py`, `camprobe.py`, `talkprobe.py`. Their
  shapes are written out under "Verification idioms" below; rebuild them from there.
- ⚠️ `render_portal` still renders offscreen with no webcam, at 1x, one instant per tile.
  It cannot show the easing, the tracking lag, or Retina sharpness.
- ⚠️ `_Look` reads the parent joint's orientation one frame late. Static checks must call
  `face()` **twice** to settle (the tests do). Live, this is invisible.

**Not mine — leave alone:** everything outside `mavis/` and `docs/superpowers/`; the main
checkout `~/Projects/graywind` (on `integrate-approval`, with its own dirty files); the Graywind trading code.

## What has changed

- **Joint probe (why the design looks the way it does):** every clip moves the neck/head
  joints of the mech and keanu (mech head ±5°, neck up to ±10°; keanu Head1 up to 43° in
  smoking/stance). A plain `controlJoint` would have frozen the shake, hence the
  replay-then-turn approach. keanu's `LeftEye`/`RightEye` aren't moved by any clip. keanu's
  `head_tilt_*_GRP` are not in the neck→head chain (they are leaves), so there is no free
  joint to piggyback on.
- **Aim measured by vectors:** after the turn, the mech's head points within 1–3° of the
  viewer, keanu's head within 3°, and keanu's eyes within about 1.5°.
- **Renders checked by eye:** all three turn toward each viewer. The Spartan is clean on
  its rest pose. Lens tint 0.54 / 0.30 / 0.15 compared on a close-up; 0.30 shows the irises
  and still reads as red aviators.
- **Framing search results** (slack as a fraction of screen height; the pass mark is ≥0.06):
  - mech: 1.75/+0.07 → 0.067 (chosen); 1.45/−0.04 → −0.064.
  - keanu: 2.1/0.18 → 0.076.
  - Spartan: 2.1/0.12 → 0.126.
- **Criterion 5, first measurement:** webcam + real tracker + Kokoro synthesizing back to
  back, with **no Panda window**, gave **24.2 fps idle and 23.8 fps while synthesizing**
  (worst gap 0.18s). **So Kokoro's CPU load alone does not starve the tracker.** The cause
  needs the full app: the render loop, sounddevice playback, and lip sync on the render thread.

## What has failed / risks / caveats

- **The in-app talking probe printed nothing.** `talkprobe.py` ran the real app (exit 0),
  but no `PROBE …` lines appeared in the log. The last visible line was OpenCV's
  `setPreferableTarget` warning. Not investigated; the owner paused the session there.
  Suspects:
  - the worker thread dies on an exception in the daemon thread, which is swallowed;
  - `self.tracker` is None (no camera) and `tracker_rate` raises;
  - the window was closed early.

  Wrap the worker body in `try/except` and print the traceback first.
- **UNVERIFIED live** (criterion 4). Nothing from this session has been seen in the real
  full-screen window. In particular, it's unknown whether:
  - the easing feels right;
  - the clip and the turn together look natural on keanu during smoking/stance (head swings up to 43°);
  - the per-frame `forceUpdate()` in `_Look.apply` costs visible fps at Retina.
- **The mech is about 17% smaller** than the framing the owner saw on 10/4. This is the price of
  the shake plus a correct downward look. Alternatives if the owner dislikes it: lower the
  mech's `look.pitch` limit or its neck shares, then refit.
- **Mech "eyes" are glow lamps.** It has `eye_center_*` joints, but rotating a glowing disc
  shows nothing, so the mech tracks with its head only. That is criterion 2 as worded ("where
  the model has real eye joints").
- **Hulkbuster** is static and dormant: it still turns as one piece on the pivot. Not in scope.
- **The Spartan's clip is unusable** (T-pose, tears the armour). If the owner wants him animated, he needs a different clip.
- In the old `render_portal` "high" tile (eye z=+0.18, above the tested range) the tops of the
  mech and keanu are cut off. That seat is outside `VIEW_Z`, so the tests don't cover it.
- Carried forward from the 10/5 handoff and still open: mech persona/voice, the keanu early
  exit, the dog tag, 30fps pacing, room corners, the techno-vibe choice, the Johnny voice decision.

## What's next (ordered)

1. **Criterion 5: tracker starvation while talking.**
   1. Fix `talkprobe.py`: add a try/except around the worker, print the traceback, assert the
      tracker is present. Rerun until you get idle and speaking tracker rates, plus render fps.
   2. Compare variants, one per run, using env `PROBE_VARIANT`:
      - baseline;
      - `sys.setswitchinterval(0.001)` (GIL contention);
      - ORT `allow_spinning=0`;
      - `MAVIS_KOKORO_THREADS=2`;
      - lip sync off;
      - `sd.play` replaced by a sleep (audio callback cost).
   3. Ship the smallest fix that reaches ≥12 fps while speaking. Keep the test-first habit:
      a unit test where possible, a probe number otherwise.
2. **Criterion 4: live verification.**
   - Run `set -a; . ~/.mavis/env; set +a; .venv/bin/python -m avatar.app`. The avatar launch
     agent wasn't running this session; if it is, `launchctl bootout gui/$UID/com.mavis.avatar` first.
   - Take timed screenshots of each model (M to switch) from left, right and low seats, and
     during an answer.
   - Show the owner. Ask about the mech's smaller framing and whether the keanu eyes read.
3. Then report criteria 1–5 to the owner and ask whether this pass is done, so it can be
   **Released** (tag plus changelog) in the sense of the global workflow.
4. Push only on the owner's say-so.

## Verification idioms used in this project (for the resuming session)

- **Tests:** `cd mavis && .venv/bin/python -m pytest -q` (382). Mutation-test behavioural
  fixes. Clear bytecode before mutate/restore runs:
  `find . -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +`.
- **Offscreen look:** `.venv/bin/python -m tools.render_portal --avatar mech-bust --frame 308 --out x.png`
  (with `~/.mavis/env` sourced). It turns the model to each of 6 eyes. *Read the PNG yourself.*
- **Aim check (aim.py):**
  1. Expose the head joint.
  2. `face(0,0)` twice, then record `forward_local = invert(head.get_quat(render)).xform(Vec3(0,-1,0))`.
  3. For each eye: `look_from`, `face(gaze, gaze_p)` twice.
  4. Measure the angle between `head.get_quat(render).xform(forward_local)` and `eye - head_pos`.
- **Framing search (fit.py):**
  - Import `tests/test_portal_eyes_in_view.py` as a module.
  - For each framing × rise, build `AvatarScene(base, name, portal=screen,
    registry=dict(reg, **{name: dict(cfg, portal_framing=f, portal_rise=r)}))`.
  - Score it as `min(worst_slack(...)[0] / screen.height)` over `SCREENS`.
  - Pick the smallest framing that scores ≥0.06. Each evaluation takes about 4s, so run the models in parallel.
- **Joint/clip probe (animprobe.py):** `exposeJoint(..., localTransform=True)` per joint,
  `actor.pose(clip, f)` + `bundle.forceUpdate()` over 12 frames, and the HPR range per joint.
  A range of 0 means the clip doesn't touch that joint.
- **Tracker-only rate (camprobe.py):**
  1. `headtrack.open_camera()` on the main thread, then `HeadTracker(...).start()`.
  2. Count the distinct `tracker.latest()` timestamps per second. Don't trust `tracker.fps`:
     it only refreshes when a frame arrives.
  3. Run `KokoroVoice(threads=N).synth_samples` in a loop on another thread.
- **In-app talking probe (talkprobe.py):**
  1. Monkeypatch `avatar.app.Runtime.start` to start a worker that waits 6s and measures the tracker for 5s.
  2. Feed 4 sentences into a `speech.SpeechStream(self.speaker, tmpdir)`, `close()` it, and
     play each with `self.say(path)` while measuring for 9s.
  3. Print `PROBE …` lines, then `os._exit(0)`.
  4. Call `avatar.app.main()`.

  It opens Johnny full screen and speaks out loud, so warn the owner first.

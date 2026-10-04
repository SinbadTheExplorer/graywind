# Johnny — Portal Mode (head-tracked window + virtual shadow) — Session Handoff

**Written:** 2026-10-04 · **Branch:** `feat/johnny-portal`, cut from
`feat/mavis-avatar` at `f3f4771`. Builds the owner's long-standing vision for
Johnny, from a reel (@ojrgb, "Virtual shadow + off axis projection"): the
monitor stops being a picture and becomes a **window** he stands behind.

## Goal

Johnny should look physically present *inside* the screen. Three parts:

1. **Off-axis projection** — every frame, draw the scene from where the
   viewer's eye actually is, through a frustum whose edges are the physical
   screen's edges (Kooima's generalised perspective projection).
2. **Head tracking** — webcam + OpenCV's YuNet face model gives both eye
   centres; the gap between them gives distance.
3. **A room and a virtual shadow** — parallax needs things at different
   depths to slide past each other; his shadow on the back wall is the
   strongest "he is really in there" cue.

## How to run it (owner, on the Mac)

```
cd ~/Projects/graywind-johnny && git fetch && git checkout feat/johnny-portal
cd mavis && .venv/bin/pip install -r requirements.txt   # adds opencv-python-headless
scripts/build_app_bundle.sh                              # adds the camera permission
echo 'MAVIS_PORTAL=1' >> ~/.mavis/env
echo 'MAVIS_SCREEN_CM=30.2x19.6' >> ~/.mavis/env         # MEASURE YOURS, see below
.venv/bin/python -m avatar.app                           # or relaunch Johnny.app
```

- **T** pauses/resumes tracking (A/B the effect). **M** switches model. **W** wakes him. **Esc** quits.
- **Measure the lit screen area with a ruler** (width x height, cm). The effect
  is only as correct as these two numbers. On a notched MacBook in full
  screen, measure the area *below* the notch.
- If the room swings the WRONG way when you lean, set `MAVIS_WEBCAM_MIRRORED=1`
  (a virtual camera such as Continuity Camera or OBS can hand over a mirrored
  feed). `MAVIS_WEBCAM_HFOV` (default 62) tunes how far the view moves per
  centimetre of head movement.
- Remove `MAVIS_PORTAL=1` to get the original transparent desktop overlay
  back, unchanged.

## Current state

**New files**
- `mavis/avatar/portal.py` — pure maths: screen config from env, eye position
  from two eye landmarks, off-axis lens settings, gaze angle, 1-euro filter,
  `EyeSmoother` (holds 0.8s through a blink, glides home over 1.5s when the
  face is gone, re-acquires without a jump).
- `mavis/avatar/headtrack.py` — webcam thread. Camera is **opened on the main
  thread** (macOS's AVFoundation permission prompt needs the main run loop);
  frames are read on a daemon thread. Every failure becomes an on-screen
  notice and a centred, still view — never a crash.
- `mavis/avatar/stage.py` — the room (procedural grid walls, no new art
  asset), key Spotlight with a 2048² shadow map, red rim light, low fill.
- `mavis/assets/headtrack/` — YuNet ONNX (232 KB, MIT, committed) + ATTRIBUTION.
- `mavis/tools/render_portal.py` — renders six eye positions into one contact
  sheet. Run under `xvfb-run` on Linux, directly on the Mac.

**Changed**
- `avatar/scene.py` — `AvatarScene(base, avatar, portal=None)`. With a
  `portal.Screen` he is placed `PORTAL_DEPTH` (0.30 m) behind the glass,
  scaled so the nominal eye sees the same torso framing as the overlay, on a
  pivot through his head; `look_from(eye)` drives the lens and a small
  (clamped 9°, eased) turn toward the viewer. `_frame_head`'s measuring was
  extracted to `_measure_head` with no behaviour change. Shadows are enabled in
  simplepbr only in portal mode.
- `avatar/app.py` — `MAVIS_PORTAL=1` → full screen, opaque, tracker started,
  `Runtime._follow_eye()` each frame, **T** toggle.
- `scripts/build_app_bundle.sh` — `NSCameraUsageDescription`.
- `requirements.txt` — `opencv-python-headless==5.0.0.93` (cp37-abi3 wheel;
  verified a `macosx_13_0_arm64` wheel exists for Python 3.14).

**Tests:** `cd mavis && .venv/bin/python -m pytest -q` → **220 passed** after the look pass (217 before it) in the
Linux cloud box (was 179 there; 38 new). The 6 that fail there are
environment-only and failed before this work: `say` is macOS-only, and five
need the gitignored `keanu.bam`. Expect the full count on the Mac.
Mutation-checked: flipping the mirror sign, the film-offset sign, the glide
timing, the re-acquire reseed and a wall's facing each fails a test.

## What was tried and failed (don't repeat)

- **A room exactly the size of the screen.** He stands 30 cm back, where the
  window reveals ~1.5x its own height; framed to fill it, he was taller than
  the box and the ceiling sliced his head off. The room is now sized to what
  the window reveals at his depth.
- **Near-black walls** swallowed his shadow entirely. Walls are mid-dark grey
  with red grid lines; the shadow reads as a hole in the key light's pool.
- **The glass-edge outline cast a shadow** (a thin diagonal line across the
  left wall). It is now hidden from the key light's shadow camera via
  `stage.SHADOW_BIT`.
- **MediaPipe** was rejected up front: its wheels trail new Python releases and
  the avatar runs on Homebrew's Python 3.14.

## Look pass (2026-10-04, second commit) — matched to the reel

The owner asked for the reel's quality. Frame-by-frame, the reel (a
TouchDesigner project) differs from v1 in LOOK, not tracking, so this pass
changed only the set:

| Reel | v1 | Now |
|---|---|---|
| Low-key: hard top light, metal highlights, black corners | Flat, evenly lit | Hard top Spotlight + red rim + cool kicker, near-zero fill |
| Dim navy concrete wall | Bright pink grid box | Procedural Perlin concrete, navy, no visible pattern |
| Subject big, close, cropped by the screen | Small torso, 30cm back | `PORTAL_FRAMING` 2.1 head heights, `PORTAL_DEPTH` 0.18m |
| Grain, vignette | Clean CG | `stage.FilmFinish`: vignette + per-frame grain, under the text |
| Flat UI on the glass (depth reference) | None | `show_hud`: `JOHNNY // LOCKED  eye 0.61m ...` top-left |

Also MSAA x4 in portal mode only. Tried and rejected during this pass:
- **simplepbr fog** — it is exponential in distance from the CAMERA, and
  everything is 0.7-1.0m away, so it dims the frame uniformly instead of
  separating depths.
- **A tight key cone** — simplepbr ignores the spot exponent and cuts the
  cone off hard: a crisp stage-spotlight disc on the wall. The cone is now
  wide (edge off-screen) and the falloff comes from the vignette.
- **Mirror-wrapped concrete** — hides the seam but folds the noise into an
  obvious Rorschach blot. Repeat-wrapped at 0.75m tiles instead.
- **`PORTAL_RISE` 0.24** clipped his crown by 1.3mm; now 0.21 (pinned by
  `test_head_is_visible_through_the_window_from_the_nominal_eye`).

**The biggest remaining gap is the asset, not the code.** The reel's mech is a
high-end hard-surface model with metal PBR materials; `jonny` (the only model
in the cloud box) is a Ready Player Me export in a T-pose. The owner's local
`keanu` model is much closer — every look decision above should be re-judged
on it, on the Mac.

## Model switching (third commit) — press M

- **M** cycles through every model on disk: built-ins (`keanu`, `jonny`), then
  drop-ins from `mavis/assets/avatar/extra/<name>/` (model + `avatar.json`,
  gitignored; format and licence notes in `assets/avatar/ATTRIBUTION.md`).
- `tools/inspect_model.py <model>` prints a starter `avatar.json` (head mesh,
  mouth morph/jaw, idle clip). Checked against `jonny`: it reproduces the
  hand-written config exactly.
- `AvatarScene` is now split: `__init__` = once per window (shader, camera,
  film, credit node); `_build(name)` = per model; `_teardown()`; `swap(name)`
  restores the previous model and re-raises if the new one fails to load.
- The runtime defers the swap one frame (`doMethodLater(0.05)`) so the cut to
  black and "// switching to X" are drawn before the load blocks the render
  thread. Repeated M presses during a pending swap are ignored.
- Tests: `tests/test_avatar_swap.py` + 3 runtime tests, 234 passing. Mutation
  checked: uncleared lights, leftover room, no restore on failure, an asleep
  model shown, a stale credit — each fails a test.
- Rendered a portal swap sequence (jonny → copy → jonny): one room, four
  lights after two swaps.
- **Caveat:** Panda3D's ModelPool keeps every loaded model in RAM. On the 8GB
  M2, cycling through many large models adds up.

## The mech is the default; the free Johnny is gone (2026-10-04)

At the owner's request ("remove the old johnny model, focus on the mech"):

- **Removed:** `assets/avatar/jonny.glb` (Stuxed, CC BY), its `AVATARS`
  entry, its ATTRIBUTION section and unignore line, and `tools/repair_gltf.py`
  + its tests, which existed only to repair that one file.
- **Default is now `mech-bust`** (`PREFERENCE = ("mech-bust", "keanu")`). The
  DeviantArt `keanu` is still loaded with M or `MAVIS_AVATAR=keanu` on the Mac.
- **Tests moved onto the mech** (the only rigged committed model). Assertions
  are from measurement: 54 joints, jaw opens ~11k of 53k head vertices.
- **Lost coverage, on purpose:** the `slider` (morph-target) mouth driver no
  longer has a committed model. Neither remaining model uses it.
- **Two latent bugs found by the move, both fixed and mutation-checked:**
  - `_IdleMotion` counted ABSENT joints as driven: `controlJoint` returns a
    dummy node rather than failing. The old test only passed because the free
    model had no idle channels. Now checked with `bundle.find_child`.
  - Default portal framing let a DEEP head poke out of the window top (the
    mech's crest by 2.8mm): `_keep_head_in_window` lowers him until every
    corner of the head is inside from the nominal eye. Skipped when a model
    sets `portal_rise` (the mech crops on purpose, as the reel does).

## UNVERIFIED (needs the owner, on the Mac)

- **Everything with a real webcam.** The cloud box has no camera. The maths is
  pinned by tests and the look was checked from rendered eye positions, but
  latency, jitter and "does it feel real" can only be judged live.
- **The CDPR `keanu` model in portal mode** — only `jonny` exists here. Watch
  for the cigarette prop and the clips' shadow.
- **Performance.** Portal mode adds a second render of the model (the shadow
  pass) at full-screen Retina resolution. If it stutters, the first lever is
  the 2048² shadow map in `stage.light_room`.
- **The camera permission dialog** naming "Johnny".

## Honest limits of the effect

- It is correct for **one eye**. A phone camera (one lens) sees it perfectly,
  which is why the reel looks so good; your two eyes still see a flat screen,
  so in person it reads as strong parallax, not true 3D.
- **One viewer.** Anyone beside you sees a sheared room.
- Turning your head (not moving it) shrinks the eye gap and reads as leaning
  back: a known, accepted error of the eye-gap depth estimate.

## What's next (ordered)

1. Owner runs it, measures the screen, and rates it like the earlier
   ratings (animation 3/10 etc.): presence, latency, stability.
2. Tune by eye: `PORTAL_DEPTH`, `stage.BACK_GAP`, light colours/positions,
   `EyeSmoother.HOLD/RETURN`, the 1-euro `min_cutoff`/`beta`.
3. Asleep state: the room stays lit and empty while he is hidden. Consider
   dimming it, so waking him ("Wake up, Johnny") turns the lights on.
4. Merge into `feat/mavis-avatar` once the owner signs off.

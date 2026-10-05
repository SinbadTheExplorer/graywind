# Johnny Portal Mode — Handoff to the Local Terminal Session

**Written:** 2026-10-05 · **From:** a cloud session (Linux, no webcam, no Mac) ·
**For:** a Claude Code session in the owner's terminal **on the Mac**, where
Johnny actually runs. This file is self-contained: you do not need the chat
it came from.

**Supersedes** `graywind-johnny-portal-handoff.md` (a running log of the same
work; keep it for history, act from THIS file). The older MAVIS queue in
`graywind-mavis-animation-and-grounding-handoff.md` is still open and is
listed under "Older queue" below.

---

## Goal

The owner's long-standing vision for Johnny, from a reel by **@ojrgb**
(TouchDesigner, "Virtual shadow + off axis projection"): the monitor becomes a
**window** a character stands behind. A webcam tracks the viewer's eyes, the
scene is redrawn from that eye every frame through a frustum whose edges are
the physical screen's edges, and the character casts a shadow on the wall
behind it. The owner wants the quality of that reel **or better**, on every
model, and judges it by eye.

## How to resume (do this first)

1. Where Johnny runs on this Mac: `~/Projects/graywind-johnny` (a worktree;
   per the older handoff it was pinned to `feat/mavis-avatar`).
   ```
   cd ~/Projects/graywind-johnny
   git fetch origin && git checkout feat/johnny-portal && git pull
   git log --oneline -1        # expect be236cc or later
   ```
   `feat/johnny-portal` was cut from `feat/mavis-avatar` at `f3f4771` and is
   **13 commits ahead of it, pushed, tree clean**. Nothing is merged.
2. Dependencies (new: OpenCV for the webcam):
   `cd mavis && .venv/bin/pip install -r requirements.txt`
3. Rebuild the app bundle — it now asks for the **camera** as well as the mic:
   `scripts/build_app_bundle.sh`
4. Local-only models (NOT in git, by design — see "Models"). The owner was
   sent zips; they must be unzipped into `mavis/assets/avatar/extra/`:
   `johnny-spartan.zip` (latest, gold visor) and `johnny-extra-models.zip`
   (hulkbuster + zbrush-mech). Check: `ls mavis/assets/avatar/extra/` should
   show `mech-bust hulkbuster spartan zbrush-mech`. If any are missing, ASK
   the owner for the zip — do not try to regenerate them without the source.
5. Tests: `cd mavis && .venv/bin/python -m pytest -q`. In the cloud box:
   **243 passed**, with 6 failing only for environment reasons (`say` is
   macOS-only; five need `keanu.bam`, which only exists on this Mac). **On
   the Mac expect all of them to pass** — if the keanu tests fail here, that
   is real and new.
6. Then go to "What's next" item 1. It needs the owner at the keyboard.

## How to run portal mode

Add to `~/.mavis/env` (read by `scripts/mavis-avatar.sh`):
```
MAVIS_PORTAL=1
MAVIS_SCREEN_CM=30.2x19.6     # MEASURE the lit screen area with a ruler (w x h, cm).
                              # Notched MacBook in full screen: measure BELOW the notch.
# MAVIS_WEBCAM_MIRRORED=1     # only if the room swings the WRONG way when leaning
# MAVIS_WEBCAM_HFOV=62        # tunes how far the view moves per cm of head movement
```
Run: `cd mavis && .venv/bin/python -m avatar.app` (or relaunch Johnny.app).

Keys: **W** wake · **M** next model · **T** pause/resume head tracking (A/B the
effect) · **Esc** quit. Top-left of the glass: `JOHNNY // LOCKED  eye 0.61m
x+0.04 z+0.02  cam 30fps` — LOCKED / SEARCHING / PAUSED / NO CAMERA. Remove
`MAVIS_PORTAL=1` to get the original transparent desktop overlay, unchanged.

## Current state — what exists

**Portal mode (all in `mavis/avatar/`)**
- `portal.py` — pure maths: screen config from env, eye position from two
  eye landmarks (depth from the eye gap), off-axis lens, gaze heading AND
  pitch, 1-euro filter, `EyeSmoother` (holds 0.8 s through a blink, glides
  home over 1.5 s when the face is lost, re-acquires without a jump).
- `headtrack.py` — webcam thread, OpenCV YuNet face model
  (`assets/headtrack/`, MIT, committed). Camera is **opened on the main
  thread** (macOS's permission prompt needs the main run loop). Every failure
  → on-screen notice + centred still view, never a crash.
- `stage.py` — the room (procedural navy concrete; sized so that from
  straight on NO wall is visible, walls appear as you lean), low-key light
  rig (key Spotlight high-in-front with a 2048² shadow map, red rim + cool
  kicker BEHIND as edge lights, low fill; ceiling takes no direct light),
  generated studio env map (overhead softbox) so PBR metal reads as metal,
  `FilmFinish` (vignette + per-frame grain, under the text).
- `look.py` — patches into simplepbr: **soft shadows** (16-tap Poisson),
  **glow/bloom** (bright-pass on strongest channel, threshold 1.3, two-pass
  blur, added in HDR inside a copy of simplepbr's tonemap), **colour grade**
  (33³ LUT: S-curve, −12% saturation, navy shadows, warm highlights), and a
  fix so simplepbr's LUT shader compiles under GLSL 1.20. Each patch refuses
  and falls back to stock simplepbr if simplepbr's source text changes.
- `scene.py` — `AvatarScene(base, avatar, portal=None, registry=None)`:
  once-per-window setup vs per-model `_build`/`_teardown`/`swap`; portal
  placement with per-model framing; head kept inside the window; gaze
  (turn ±9°, tilt ±10° to the viewer's eye height, eased); breathing bob for
  models without a working clip; per-model emissive `glow` (copied materials,
  never compounds through the model cache); exposure +0.35 stops.
- `app.py` — `MAVIS_PORTAL=1` → full screen, tracker, `_follow_eye` per
  frame, HUD, **M** swaps on a LATER frame (cut to black + notice first,
  because loading blocks the render thread).

**Models** (`mavis/assets/avatar/`; rules in `ATTRIBUTION.md`)
| name | where | licence / status | motion |
|---|---|---|---|
| `mech-bust` (DEFAULT) | committed, `extra/mech-bust/` | "Mech bust", Just8, CC BY 4.0 — the reel's own model, modified (changes recorded) | own clip `anim`; jaw `jaw_07` axis r 18°; glow 16; framing 1.15 / rise 0 |
| `keanu` | this Mac only, gitignored | KonnieGFX port of CDPR's character — never commit | real clips + jaw; **untested in portal** |
| `spartan` | local only | McCarthy3D, CC BY 4.0, but Halo IP → never commit | clip DISABLED (see failures); sway 2, breathing, nod 2.5°; glow 6; gold-mirror visor |
| `zbrush-mech` | local only | licence UNCONFIRMED → never commit until confirmed | static; breathing, nod; glow 4; head_fraction 0.5 |
| `hulkbuster` | local only, **dormant** | el_robotto, CC BY 4.0, but Marvel IP → never commit | static; skipped by M; `MAVIS_AVATAR=hulkbuster` still loads it |

The free Stuxed "Jonny Silverhand" model was **removed at the owner's
request** — do not bring it back.

**Tools** (`mavis/tools/`, run as `.venv/bin/python -m tools.<name>`)
- `inspect_model <file>` — prints a starter `avatar.json`: biggest head/helmet
  mesh, mouth (morph, or jaw with its hinge axis measured), idle clip — and
  REFUSES a clip that inflates the model when played.
- `fix_sketchfab_glb in out [--drop MESH ...] [--max-texture 2048]` — WebP →
  JPEG/PNG, merges skins sharing a root, groups bones+meshes under one
  Armature, drops display floors, caps textures. Meshopt-compressed input
  must first go through `npx -y @gltf-transform/cli@4 dequantize`; finish
  with `npx -y @gltf-transform/cli@4 prune`.
- `collada_to_glb model.dae textures/ out.glb` — Sketchfab "source" zips
  (needs `pip install trimesh pycollada pillow`).
- `gloss_by_colour in out --material M --hue LO HI ...` — make a colour-picked
  region metallic/mirror (the Spartan's visor). `--preview` writes the mask.
- `render_portal --avatar NAME --out x.png` — six eye positions in one sheet.
  **The way to judge any visual change without a webcam.**
- Drop-in model format (`extra/<name>/avatar.json`, keys `model`, `credit`,
  `head_mesh`|`head_fraction`, `mouth`, `idle_anim`, `glow`, `sway`,
  `portal_framing`, `portal_rise`, `dormant`): `ATTRIBUTION.md`.

## What was tried and failed (don't repeat)

- **Screen-sized room box** — ceiling sliced the head. **Room sized to the
  subject's depth** — walls visible from straight on, read as a diorama.
  Now sized to what the window shows at the BACK wall.
- **simplepbr fog** — camera-distance based; just dims everything. **Tight
  spot cone** — simplepbr ignores the spot exponent: hard disc on the wall.
- **Mirror-wrapped concrete** — Rorschach blot. Repeat-wrapped at 0.75 m.
- **Bloom threshold 0.85 on luminance** — a white blob at the top of the
  frame (the softbox reflecting off the mech's crest just out of frame), and
  pure-red eyes never glowed (luminance weights red 0.21). Now 1.3 on the
  strongest channel. The blob was NOT the ceiling — found by hiding things
  one at a time; render emission-only with lights set to BLACK (removing
  every light makes simplepbr draw everything unlit at full brightness).
- **Spartan's clip "Take 001"** — balloons the arms into wings (posed size
  ×2.6). Frame-0 values equal the rest pose, yet it deforms: the export's
  bind vs rest poses disagree and panda3d-gltf applies the difference twice.
  Root cause NOT fixed; the clip is off. The inspector now catches this.
- **Bytecode trap in this repo's habit of mutation-testing:** a same-length
  edit within the same second reuses a stale `.pyc`. Always
  `find . -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +`
  between mutate/restore runs.

## UNVERIFIED — none of this has been seen on the Mac

Everything was verified by tests and by offscreen renders in a Linux box
(Xvfb + Mesa). **Nobody has seen it live.** Specifically unknown:
- **Frame rate on the 8 GB M2.** Portal mode now costs: PBR + a 2048² shadow
  pass + 16-tap soft shadows + 3 bloom passes + LUT + MSAA ×4, at full-screen
  Retina. If it stutters, cheapest levers first: MSAA 4→0 (`scene._init_shader`),
  shadow map 2048→1024 (`stage.light_room`), bloom off (`look.Bloom`), soft
  shadow taps 16→8 (`look._soft_shadow_source`).
- The webcam (latency, jitter, mirrored or not, the camera permission dialog
  naming "Johnny"), and whether the illusion actually lands for two eyes.
- **`keanu` in portal mode** — framing, the cigarette prop, its clips under
  the new lighting. Expect to tune its framing; compare with `render_portal`.
- The mech's jaw moving with REAL speech (only test renders so far).
- Shader compile on macOS: macOS uses a core profile (GLSL 330 path), the
  cloud box used 1.20. The patches were written for both; watch stderr for
  "glow unavailable", "soft shadows unavailable", "colour grade may not
  compile" on first launch.

## Honest limits (tell the owner, don't oversell)

- Correct for **one eye**. The reel looks perfect because a phone camera has
  one lens; two eyes still see a flat screen. One viewer only.
- Turning the head (vs moving it) reads as leaning back — eye-gap depth.
- The models set the ceiling: zbrush-mech is ~5.7k triangles.
- Only `mech-bust` and `keanu` truly animate; the rest sway/breathe/nod.

## What's next (ordered)

1. **Live test with the owner (blocking everything else).** Pull, unzip the
   models, set the env (measure the screen!), launch, then:
   - read the HUD's `cam NNfps` and note the render frame rate;
   - lean left/right/up: walls should appear as you lean, NONE straight on;
     if the room swings the wrong way → `MAVIS_WEBCAM_MIRRORED=1`;
   - **T** to A/B tracking; **M** through every model;
   - wake him (W), talk, watch the mech's jaw and the nod on the others;
   - get the owner's ratings out of 10 (presence, lag, stability, per model),
     the way earlier work was rated (animation 3/10 etc.).
   Fix what this turns up before adding anything.
2. **Make the illusion breathtaking (owner already agreed this is the
   direction):** (a) a **"Wake up, Johnny" power-on** — room dark, eyes
   flicker on, light floods in, gaze lifts to the viewer — on all models;
   (b) **voice-reactive glow** — emissive pulses with the speech envelope
   (`avatar/lipsync.py` already computes it; `scene.set_mouth` gets the
   amount every frame); (c) **idle glances** — occasional look-away and snap
   back to the viewer. All three work on static models, which need them most.
3. **Spartan real animation:** fix the bind/rest mismatch (rewrite joint
   node TRS from the inverse bind matrices in a converter step, then
   re-test with `inspect_model`'s deform check), then try Mixamo clips — its
   skeleton is `mixamorig:` already.
4. **`keanu` portal tuning** (framing, rim colour vs his skin, cigarette).
5. If `zbrush-mech`'s source is found, confirm licence; if CC BY and not a
   franchise design, it may be committed (follow `ATTRIBUTION.md`).
6. Owner sign-off → merge `feat/johnny-portal` into `feat/mavis-avatar`.

**Older queue (from `graywind-mavis-animation-and-grounding-handoff.md`,
still open):** instrument spoken-answer latency; fill the Graywind grounding
corpus (needs the owner's decision on which docs are authoritative); blinking
(now partly moot for helmeted models); train the "wake up johnny" model (owner
present, saved Colab copy); rotate the Groq API key.

## Working conventions in this project

- Small work stays inline; no spec/plan doc unless the owner asks.
- **Render it and look** before claiming a visual change works
  (`tools/render_portal.py`; Xvfb not needed on the Mac).
- **Mutation-test** every behavioural fix: break it, confirm a test fails,
  restore (mind the `.pyc` trap above).
- **Never commit** a model whose licence is unconfirmed or that depicts a
  franchise design (Marvel, Halo, CDPR), whatever its Sketchfab licence. The
  repo is public. `assets/avatar/extra/*` is ignored by default for this.
- Commit messages explain WHY; push to `feat/johnny-portal`.
- The owner is a business student, learning as they go, works late, and
  asked to be challenged rather than agreed with. Plain language; short TLDR.

# MAVIS / Johnny — Face Pass (Blink, Lenses, Brows) — Session Handoff

**Written:** 2026-09-29 · **For:** whoever resumes Johnny, to continue the
quality-8/10 pass. Next up: the talking-gesture clip, which needs the owner's
Mixamo download first.

This **supersedes** `graywind-mavis-animation-and-grounding-handoff.md` for
current state. That file is still the authority on the mic/TCC diagnosis, the
wake-word Colab repairs and the ungrounded-answer guard. Read it only if one of
those comes up.

## Goal

On 2026-09-28 the owner asked how an animation/avatar expert would rate Johnny.
Answer: functionality 5, quality 4, usage 3. Two decisions followed: **take
quality to 8/10**, and **accept usage option A**. Johnny stays personal-only,
because the CDPR model and the character's voice can't legally go to anyone
else. **Done criteria were written before any code** (the owner's workflow
requires that), with a budget ending **2026-10-12**:

- **Done criteria (the authority):** `docs/superpowers/specs/2026-09-28-johnny-done-criteria.md`
  1. He looks alive at the LIVE framing: brows, head and hands move while he
     speaks, blinks are visible, the chrome arm is shaded metal, and there are
     no see-through holes in the arm or hair.
  2. First spoken word within 6s of the end of the question. **Chunked voice
     conversion (VC) is owner-APPROVED** (2026-09-28), overriding the voice
     spec's "audio finished before animating" rule.
  3. "Wake up, Johnny" wakes him on at least 4 of 5 tries, with no false wakes
     in 30 minutes.
- Avatar spec: `docs/superpowers/specs/2026-09-19-mavis-avatar-design.md`
- Avatar plan: `docs/superpowers/plans/2026-09-19-mavis-avatar.md`. ⚠️ Its
  checkboxes under-report; trust `git log`.

**Out of scope, by decision:** usage beyond the owner (no installer, no
shareable persona); filling the Graywind grounding corpus; the voice timbre
and filler lines, which the owner has approved.

## How to resume (do this first)

1. `cd ~/Projects/graywind-johnny`: a dedicated worktree pinned to
   `feat/mavis-avatar`, which is where Johnny runs from. **Not**
   `~/Projects/graywind`.
2. `git log --oneline -4` should show `f31a009`, `5d5047e`, `f3f4771`,
   `6f6bf26`. **`5d5047e` and `f31a009` are NOT pushed.** Only the owner
   decides whether to push.
3. `cd mavis && .venv/bin/python -m pytest -q` should report **222 passed**.
4. **Immediate next action:** ask the owner whether the Mixamo talking clips
   are in `~/Downloads`: 2-3 of "Talking" / "Standing Arguing" / "Explaining",
   FBX Binary, Without Skin. If they are, retarget them (see What's next #1).
   If not, do #2 (chunked VC), which needs nothing from him.

## Current state (active files)

**Branch:** `feat/mavis-avatar`, 58 commits ahead of base `bde13f3`, 2 ahead
of `origin`.

**Committed this session:**
- `5d5047e`:
  - `mavis/avatar/blink.py` (new): pure `BlinkSchedule`, with random 2-6s
    gaps, about 12% double blinks, and no replay after a pause.
  - `avatar/scene.py`: `_Lids` plus the `"blink"` and `"lens"` config on
    keanu, and `_tint_lenses()`.
  - `tests/test_blink.py` (new), plus scene tests.
  - The done-criteria spec.
- `f31a009`:
  - `avatar/lipsync.py`: `emphasis(env)`, the brow track.
  - `avatar/scene.py`: `_Brows`, `set_brows()` and the `"brows"` config.
  - `avatar/app.py`: `_mouth` is now `(env, brows, start)`; `_tick` drives
    and resets the brows.
  - Tests in `test_lipsync.py`, `test_app_runtime.py` and `test_scene.py`.

**Files later work will modify:**
- `mavis/tools/retarget_anim.py`: add the talking clips as extra `name=<fbx>`
  arguments.
- `scene.AVATARS["keanu"]["anims"]` and `["poses"]["speaking"]`: currently
  `"idle"`, which should become the talking clip.
- `mavis/avatar/app.py` `say()` / `voice_client.py`: where chunked VC goes.
- `mavis/assets/wakeword/`: still EMPTY; `wake_up_johnny.onnx` goes here.

**Scratch workspace / traps:**
- ⚠️ **Calling `delegate` from a tool shell: always add `< /dev/null`.** When
  stdin isn't a terminal, delegate reads it as piped input. A shell whose stdin
  is left open then blocks forever *before any request is sent*. That cost a
  9-hour hang this session, and it looks exactly like a Groq outage. The
  session also added `--max-time` to both provider calls in
  `~/.local/bin/delegate`: `DELEGATE_TIMEOUT`, default 90s, owner-approved.
  That file isn't in this repo.
- ⚠️ `mavis/.venv` and the gitignored assets are symlinks into
  `~/Projects/graywind/mavis/`. Don't delete the main checkout's copies.
- ⚠️ The Groq API key still hasn't been rotated (it leaked into a transcript
  on 2026-09-25).

**Not mine — leave alone:** `.DS_Store`, `.claude/`, and the untracked
`dashboard-data/*performance_report.json`.

## What has changed

- **He blinks** (`5d5047e`). He rotates `[lr]_J_eye_lid_up_root_[12]_JNT` on
  **`r`, negative**. Found by rendering: +r opens him wide-eyed and h does
  nothing; -22° meets the lower lid, while -35° pushes through it. The other
  lid joints are siblings under `face_root_JNT`, not children of the roots;
  the edge rows carry the lashes, which is what reads as a blink.
  `forceUpdate()` is skipped when the value is unchanged.
- **The lenses are see-through** (`5d5047e`). The owner chose this over
  keeping them opaque or taking them off. The texture alpha is a flat 0.93,
  the tint strength for the game's glass shader. At that opacity his eyes, and
  every blink, were invisible at the live framing. The alpha scale is now
  0.54 (about 0.5 effective). `glass_outer` is deliberately untouched: it's a
  cutout for the frame, not the lens.
- **Brows rise on emphasis** (`f31a009`). They fire when the fast loudness
  average beats 1.7× the 2s average, rise over 0.12s and fall over 0.35s,
  travelling 4mm up the face frame. **Tuned on his real recorded lines:** the
  drafted 1.15/0.5 had the brows up 48% of the time (44 raises a minute),
  because pauses drag the average down. The tuned values give 12%, about 21 a
  minute. All 26 brow joints hang off `face_root_JNT`. Lowering the brows only
  tucks them behind the glasses frame, so there is no frown channel.
- **222 tests** (from 193). Every behavioural change was mutation-tested:
  - lids with no `forceUpdate`
  - triple blinks
  - untinted lenses
  - no blinking from `idle()`
  - brows moving down
  - the tick skipping the brows
  - the brows left raised after an answer

## What has failed / risks / caveats

- **Delegate hung twice** (see the trap above). It's fixed, and the root cause
  is understood.
- **UNVERIFIED in the live window. The owner hasn't seen any of this yet.**
  All checks so far used offscreen renders at 1200×900. The real window size
  was never checked.
- **The brow raise is subtle at the live framing:** about 5px in a still
  frame. It may need 5mm (`"metres"` in the keanu config). That's the owner's
  call after seeing it move.
- **The brows snap to 0 when an answer ends** instead of easing down.
  Accepted for now; watch for a visible pop.
- **The chrome arm and hair render with see-through holes offscreen.** This
  may partly be the white render background, since the live window is
  transparent. It isn't diagnosed yet and is part of criterion 1. The
  2026-09-19 memory trap applies: arm alpha is a spec mask, so **never
  blanket-blend** it.
- **Eye darts / gaze: not built.** Now that the lenses are see-through they
  would show. They're optional under the criteria wording.
- The wake word is still untrained. The Colab copy with 5 repairs is linked
  in the previous handoff. Free Colab reaps idle sessions, so the owner must
  be present for the run.

## What's next (ordered)

1. **Talking-gesture clip**, which needs the owner's Mixamo FBX files. Run
   `/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python mavis/tools/retarget_anim.py -- <keanu.fbx> <texdir> <out.glb> idle=… smoking=… dismiss=… angry=… stance=… talk=<Talking.fbx>`.
   The rebuild steps are in `mavis/assets/avatar/ATTRIBUTION.md`. Then add
   `"talk"` to `anims` and set `poses["speaking"] = "talk"`. **Don't
   `controlJoint` Head1/Neck1** for head motion; that detaches them from every
   clip. Render with `tools/render_pose.py --clip talk` to check it.
2. **Chunked VC for criterion 2** (≤6s to first word). It's approved.
   ChatterboxVC runs at 0.67x realtime, faster than playback, so
   sentence-by-sentence conversion accumulates no deficit. Caveat:
   `voice_worker._normalise` scales each clip to `TARGET_PEAK`, so
   per-sentence chunks would jump in loudness. Normalise across chunks
   instead. The `emphasis()`/envelope are also computed per wav, so decide
   whether the brows run per chunk.
3. **Diagnose the arm/hair holes**: render against a dark background first,
   to separate "render background" from "real transparency bug".
4. **Wake word** (owner present), then a hands-free test: 4 of 5 wakes, 30
   minutes with no false wake.
5. Owner re-rates → tag a release → `superpowers:finishing-a-development-branch`.
   Rotate the Groq key.

## Verification idioms used in this project (for the resuming session)

- **Suite:** `cd mavis && .venv/bin/python -m pytest -q` should report 222.
  The keanu tests run only where the gitignored model exists; they did here.
- **Mutation-test every behavioural change:** break it, confirm the right test
  fails, restore it.
- **Render and look; the pixels are the evidence.** `tools/render_pose.py`
  works for body clips. For face work, write a probe that:
  - builds `scene.AvatarScene(base, "keanu")`;
  - sets `set_control_effect` so idle is 1 and everything else is 0, then
    calls `pose("idle", 0)`;
  - moves joints with `controlJoint` and calls `forceUpdate()`;
  - steps `taskMgr` 3-4 times, then `win.save_screenshot`.

  Camera at `face_root + (0, -0.22, 0)` for close-ups. The default camera,
  left untouched, gives the live framing. Tile images with Panda3D's
  `PNMImage` (no PIL in the venv).
- **Hide the glasses to see the eyes in a probe:** `actor.find("**/glass").hide()`.
- **Shared keanu fixture:** it's module-scoped and a clip keeps playing. To
  compare vertices, freeze with `pose("idle", 0)` and call
  `_bundle.forceUpdate()` explicitly. Drivers skip no-op updates, so an
  unchanged `set()` won't refresh the pose.
- **zsh gotcha:** `"$VAR:r"` and `"$VAR:h"` are filename modifiers. Write
  `"${VAR}:r"`.
- **Start him live:** `launchctl kickstart -k gui/$UID/com.mavis.avatar`.

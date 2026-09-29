# MAVIS / Johnny — Chunked Voice Conversion — Session Handoff

**Written:** 2026-09-29 · **For:** whoever resumes Johnny's quality-8/10 pass.
Criterion 2 (first word ≤6s) is built but **fails on battery at the default
voice settings**. It needs two owner inputs: a mains-power measurement and an
ear test of 6 CFM steps.

This **supersedes** `graywind-mavis-face-blink-brows-handoff.md` for current
state. That file is still the authority on the blink/lens/brow work and on the
talking-clip plan (What's next #1 there is still open).

## Goal

Hit done-criterion 2: from the end of a question to his first spoken word in
≤6s, down from 15.8s measured 2026-09-25. Chunked voice conversion was
owner-approved 2026-09-28.
- Done criteria (the authority): `docs/superpowers/specs/2026-09-28-johnny-done-criteria.md`
- Avatar spec: `docs/superpowers/specs/2026-09-19-mavis-avatar-design.md`
- There is no plan doc for this piece. The design is in the module docstrings
  of `avatar/chunks.py` and `avatar/voice_stream.py`, plus the constants'
  comments in `scripts/voice_worker.py`.

## How to resume (do this first)

1. `cd ~/Projects/graywind-johnny`: the pinned worktree on `feat/mavis-avatar`.
   `git log --oneline -3` should show this session's two commits (the chunked
   VC commit and its code-review fixes) on top of `7fb1b73`.
2. `cd mavis && .venv/bin/python -m pytest -q` should report **273 passed**.
3. Ask the owner the two questions in What's next #1 and #2. Nothing else on
   criterion 2 moves without them.
4. **Immediate next action:** have the owner plug in, turn Low Power Mode off,
   stop the avatar, and run `tools/latency_probe.py` (instructions are in its
   docstring).

## Current state (active files)

**Branch:** `feat/mavis-avatar`. This session's work is in ONE local commit on
top of `7fb1b73`. **Not pushed**; only the owner decides whether to push.
`5d5047e`, `f31a009` and `7fb1b73` are also still unpushed.

**Files created / changed:**
- `mavis/avatar/chunks.py` (new): sentence splitter (abbreviation-safe), the
  greedy chunk planner, `predicted_gaps()`, and the **gap guard**. If any
  predicted gap between chunks exceeds `MAX_GAP_SECONDS = 1.0`, it falls back
  to ONE chunk, i.e. the pre-chunking behaviour.
- `mavis/avatar/voice_stream.py` (new): `VoiceStream`, a producer thread that
  voices chunk 0 first and writes later `say` scaffolds ahead on a second
  thread. A failed chunk degrades to its scaffold, and conversion is not
  retried for the rest of the answer.
- `mavis/avatar/voice_client.py`:
  - `convert(..., gain=)` and `last_gain`;
  - a live cost model: `fit_cost()` (Theil-Sen, clamped) and `cost_model()`,
    fed by the worker's warm-call timings and its startup calibration;
  - `DEFAULT_COST = (2.5, 1.2)`, which is deliberately pessimistic so an
    uncalibrated planner voices the answer whole;
  - `READY_TIMEOUT` raised from 90 to 240s.
- `mavis/scripts/voice_worker.py`:
  - 5s prompt window (`MAVIS_VC_PROMPT_SECONDS=5`, `MAVIS_VC_PROMPT_START=5`);
  - `MAVIS_VC_STEPS` (default **10**, unchanged);
  - shape bucketing `BUCKETS = (1,2,3,4,6,8,12,16)`, with every bucket
    prewarmed before `ready`;
  - `torch.mps.empty_cache()` after each call;
  - an optional `gain` in the request; replies now carry `gain`,
    `audio_seconds` and `cold`, and `ready` carries `calibration`.
- `mavis/avatar/app.py`: `_voice()` returns a started `VoiceStream`, planned
  with the voice's live cost model. `_answer()` returns
  `(first_wav, stream, text)` as soon as chunk 0 is voiced. `_speak()` plays
  the chunks back to back, and `_discard()` cancels the stream and removes its
  files.
- `mavis/tools/latency_probe.py` (new): the criterion-2 harness. It uses the
  real `Runtime._voice` and the live backend, simulates playback including the
  worst filler (4.51s), and reports both boundaries (A = from `/ask`,
  B = from end of speech) plus the gaps.
- Tests: `test_chunks.py`, `test_voice_stream.py` (new), plus additions to
  `test_voice_client.py` and `test_app_runtime.py`.

**Files later work will modify:**
- `~/.mavis/env`: where `MAVIS_VC_STEPS=6` goes if the owner approves it. The
  avatar wrapper exports the whole file, so the worker inherits it.
- `mavis/assets/wakeword/`: still EMPTY.

**Scratch workspace / traps:**
- ⚠️ **Nothing is live until the avatar restarts.** The launch agent runs this
  worktree's files from disk, so the next login or kickstart picks this up.
  Expect **~110s of "Warming up his voice..."** on battery (every bucket is
  compiled) and **~3.9GB resident** for the worker. Both are bounded.
- ⚠️ **Don't run the probe while the avatar is up.** Two workers on 8GB
  thrashes swap, and the numbers become swap, not VC.
- ⚠️ `delegate` truncates at exactly 3072 completion tokens (no
  `max_completion_tokens` is sent). Ask it for one file per call.
- ⚠️ Voice A/B/C clips are in `~/.mavis/voice-ab/`, outside the repo on
  purpose: it's the actor's voice. Its `README.txt` says what each is.

**Not mine — leave alone:** `.DS_Store`, `.claude/`, and the untracked
`dashboard-data/*performance_report.json`.

## What has changed

The measured facts matter more than the code. Each one overturns an earlier
note.

1. **Every VC call pays a fixed cost.** s3gen prepends the reference prompt's
   mel (10s by default) to every conversion, so a two-word clip cost ~6s. The
   earlier "0.67x realtime, so chunking has no stall risk" was a 9/25
   measurement under those power conditions and ignored this cost.
   - Fix: keep a 5s prompt window. The speaker embedding still comes from the
     full reference.
   - Speaker similarity: tail-5s median 0.735 vs full 0.687.
   - Whisper WER is equal (0.18 vs 0.22 on matched sentences).
2. **PyTorch-MPS compiles and keeps a graph per input shape.**
   - The unbucketed worker grew ~180MB per call. It reached 8GB and was what
     pushed this Mac into a 10GB+ swap storm.
   - A cold bucket costs +5-10s, which explains every "mystery" spike,
     including a 10s mid-answer gap.
   - With bucketing plus full prewarm, memory is flat and the gaps are 0.
3. **Low Power Mode on battery makes VC ~3x slower.** `pmset -g` showed
   `lowpowermode 1`. The cost model is therefore measured live per session,
   not hard-coded. `say -v Tom` has a ~1.1s startup floor per call, whatever
   the text length.
4. **Numbers, battery plus Low Power Mode, 5 questions of 105-191 chars:**

   | Setting | A median (from `/ask`) | A worst | Gaps |
   |---|---|---|---|
   | Before this session | 15.8s (9/25, other conditions) | | |
   | 10 steps (default) | 15.8s | 17.2s | 0 |
   | `MAVIS_VC_STEPS=6` | **6.0s** | 13.3s | 0.6s total |

   B (from the literal end of speech) adds ~1.6-2s: 1.2s of trailing silence
   plus STT.
5. Suite 222 → **273**. Mutation-tested:
   - the break-even merge;
   - the abbreviation fix (the delegate draft never matched "U.S.");
   - the cost-model wiring in `_voice`.

6. **Code-review fixes (second commit).**
   - The planner and cost model now price a chunk at its padded bucket, not
     its real length. A 4.1s chunk costs a 6s conversion, and the old pricing
     under-predicted gaps.
   - Calibration is timed through `_convert` itself.
   - A failed chunk 0 keeps its "voice degraded" notice. The settle used to
     wipe it, both before and after this work.
   - A reference clip shorter than 10s gets a clamped prompt window instead of
     an empty one.
   - When the first sentence is too short to cover the next conversion
     ("Look, choom."), the planner grows the first chunk sentence by sentence
     instead of voicing the whole answer.

## What has failed / risks / caveats

- **Criterion 2 FAILS on battery at 10 steps.** Don't claim otherwise. The
  mains-power figure has **not been measured**, and it shouldn't be
  extrapolated.
- **UNVERIFIED in the live window.** No one has heard a chunked answer through
  the real app. The probe drives the real `_voice`/`VoiceStream`/worker, but
  not `sounddevice` playback or the mouth across chunk boundaries (the mouth
  closes briefly between chunks).
- **Worst case stays long even at 6 steps (13.3s).** It happens when the first
  sentence is long and the guard refuses a clause split. Next levers, in order:
  - a smarter first cut;
  - an in-process `say` replacement (~1s);
  - streaming the first sentence from Groq.
- **Shared gain mostly hits the 0.99 clip guard**, which is close to per-chunk
  peak normalisation (see the `voice_stream.py` docstring). It isn't a
  regression, but it isn't a true loudness match either.
- **The 110s warm-up delays the first possible wake after login.** `_serve`
  waits for the voice before listening.
- **Groq rate-limits Whisper under bursts** (a 429 during the WER check). This
  doesn't matter for normal use.

## What's next (ordered)

1. **Owner: measure on mains.** Plug in, turn Low Power Mode off, and press
   Escape on Johnny. Then, from `mavis/`, run
   `set -a; . ~/.mavis/env; set +a; .venv/bin/python tools/latency_probe.py`.
   Record the A/B medians and worst cases. If A's median is ≤6s at 10 steps on
   mains, criterion 2 passes in the owner's normal state (ask which state is
   normal for them).
2. **Owner: ear test.** In `~/.mavis/voice-ab/`, compare B (the new default)
   with C (6 steps). If C is acceptable, put `MAVIS_VC_STEPS=6` in
   `~/.mavis/env` and kickstart. That is what gets battery to ~6s median.
3. Restart him (`launchctl kickstart -k gui/$UID/com.mavis.avatar`) and have
   the owner ask 3 questions. Listen for the join between chunks and watch the
   mouth.
4. Talking-gesture clip (needs the owner's Mixamo FBX), the arm/hair holes
   diagnosis and the wake word are unchanged from the previous handoff.
5. When all 3 criteria pass: the owner re-rates → tag a release →
   `superpowers:finishing-a-development-branch`. Rotate the Groq key.

## Verification idioms used in this project (for the resuming session)

- **Suite:** `cd mavis && .venv/bin/python -m pytest -q` should report 273.
- **Real worker without the app:** construct `avatar.voice_client.VoiceClient()`,
  then `.start()`, `.convert(src, out)`, `.cost_model()`. Sample memory with
  `top -l 1 -pid <pid> -stats mem`. Run with the avatar stopped.
- **Criterion 2:** `tools/latency_probe.py`. Always note the power state with
  `pmset -g | grep lowpower` and `pmset -g batt`.
- **Voice quality without ears:**
  - Speaker similarity: cosine of `model.s3gen.speaker_encoder.inference(16k)`
    against `ref_dict["embedding"]`.
  - Intelligibility: Groq Whisper WER against the source text. Space the calls
    to avoid 429s.
- **Mutation-test every behavioural change** (break it, see the right test
  fail, restore it).

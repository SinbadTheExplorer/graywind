# MAVIS / Johnny — Fast Voice, Streaming Answers, News — Session Handoff

**Written:** 2026-10-01 · **For:** whoever resumes Johnny's release push. The
owner's deadline is **2026-10-03**. Speed and news are built and measured;
"lively" and the wake phrase are the open work.

This **supersedes** `graywind-mavis-chunked-vc-handoff.md`: the chunked voice
conversion it describes was deleted this session.
`graywind-mavis-face-blink-brows-handoff.md` is still the authority on the
face work and the talking-clip plan.

## Goal

Ship Johnny against the four criteria the owner set on 2026-10-01: responsive,
lively, useful, light on the Mac. The owner traded the character's cloned voice
for speed, because local voice conversion could not get under 6s on an 8GB M2.
- Done criteria (the authority): `docs/superpowers/specs/2026-09-28-johnny-done-criteria.md`
- Avatar spec: `docs/superpowers/specs/2026-09-19-mavis-avatar-design.md`
- There is no plan doc. The design is in the module docstrings of
  `avatar/tts.py`, `avatar/speech.py`, `avatar/capture.py` and `news.py`.

## How to resume (do this first)

1. `cd ~/Projects/graywind-johnny` (worktree on `feat/mavis-avatar`).
   `git status --short` should show this session's work as **uncommitted**
   changes (33 paths) on top of `2d86010`, unless the owner has since said to
   commit.
2. `cd mavis && .venv/bin/python -m pytest -q` should report **305 passed**.
3. Read the done-criteria doc. Trust it and git over this file.
4. **Immediate next action:** ask the owner for the three things only they can
   give: a listen to the new voice (run him, press W), whether the Mixamo
   talking clips are in `~/Downloads`, and whether the voice actor behind
   `actor_sample.wav` agreed to cloning (see caveats).

## Current state (active files)

**Branch:** `feat/mavis-avatar`. This session's work is **not committed**.
Earlier commits `5d5047e`..`2d86010` are still unpushed; only the owner decides
whether to push.

**Files created:**
- `mavis/avatar/tts.py` — the voices: Kokoro (local, default), ElevenLabs,
  `say`. `Speaker` wraps one and falls back to `say`, marking itself degraded.
- `mavis/avatar/speech.py` — `SentenceCutter` (streamed text to whole
  sentences; cuts a long FIRST sentence at a clause) and `SpeechStream`
  (sentence to wav, in order, while the answer is still being written).
- `mavis/news.py` — Google News RSS, cached 10 minutes, with the outlet name
  on every headline.
- `mavis/tests/test_tts.py`, `test_speech.py`, `test_news.py`, `test_capture.py`.

**Files changed:**
- `mavis/app.py` — new `POST /ask/stream` (newline-delimited JSON). `/ask` is
  unchanged for the MCP tool and the CLI.
- `mavis/providers.py` — `groq_stream` (streaming, `reasoning_effort: low`,
  the Johnny persona prompt). `groq_answer` behaves as before.
- `mavis/avatar/brain.py` — `fragments()` / `sentences()` replace `ask()`.
- `mavis/avatar/app.py` — `Runtime` takes `speaker=`; `_answer` returns as
  soon as the first sentence is voiced; the caption follows the sentence being
  spoken; the filler line plays only if the first sentence is not ready in
  `FILLER_AFTER_SECONDS = 2.0`.
- `mavis/avatar/capture.py` — Silero voice-activity detection; the trailing
  silence he waits out dropped from 1.2s to 0.7s. Falls back to the old
  loudness threshold and 1.2s if the model file is missing.
- `mavis/avatar/stt.py` — one reused HTTP client, and a vocabulary prompt so
  Whisper spells "Graywind".
- `mavis/avatar/canned.py`, `mavis/scripts/pregen_lines.py` — canned lines are
  rendered per voice into `assets/voice-<name>/` by the runtime venv.
- `mavis/tools/latency_probe.py` — rewritten for the new path.
- `mavis/requirements.txt`, `mavis/.gitignore`, `mavis/avatar/lines.py`.

**Files deleted (staged):** `avatar/voice_client.py`, `avatar/voice_stream.py`,
`avatar/chunks.py`, `scripts/voice_worker.py`, `scripts/scaffold_speaker.swift`
and their four test files. `split_sentences` moved into `avatar/speech.py`.

**Outside the repo:**
- `~/.mavis/models/`: `kokoro-v1.0.onnx`, `voices-v1.0.bin`, `silero_vad.onnx`.
  Also `kokoro-v1.0.int8.onnx`, which is unused (measured slower) and can go.
- `mavis/assets/voice-kokoro/` — 28 canned lines in the new voice (gitignored).
- `kokoro-onnx` was pip-installed. ⚠️ `graywind-johnny/mavis/.venv` is a
  symlink to `graywind/mavis/.venv`, so it landed in the main checkout's venv.

**Scratch workspace / traps:**
- ⚠️ `mavis/assets/voice/` still holds the 28 lines in the old cloned voice.
  Nothing reads it now. Left in place on purpose; do not overwrite.
- ⚠️ The backend runs under launchd from this worktree. After editing
  `app.py`, `providers.py` or `news.py`:
  `launchctl kickstart -k gui/$UID/com.mavis.backend`.
- ⚠️ `assets/wakeword/wake_up_johnny.onnx` **does not exist**. He starts with
  "Press W in the window to wake him."

**Not mine — leave alone:** everything outside `mavis/` and the criteria doc.

## What has changed

- Time from the end of a question to the first word of the answer: **2.3s
  median, 2.4s worst** over five questions including news and two Graywind
  questions, on mains power, with the filler line charged where it would play
  (`tools/latency_probe.py`, 2026-10-01). It was 15.8s on 2026-09-25.
- No mid-answer gaps in any measured run.
- "What's the news" reads headlines fetched at that moment, names each outlet,
  and comments in character. He says an opening line at once while the feed is
  fetched.
- The avatar process idles at about 10% CPU and 280-390MB with the voice
  loaded; the voice plus detection peaked at 721MB under synthesis. The
  separate torch worker is gone.
- Tests: 305 passed (293 before the session).

## What has failed / risks / caveats

- **Nothing is failing**, but much is unverified:
- **UNVERIFIED — a real conversation.** The window was launched once and
  started cleanly; nobody pressed W. Greeting, answer, lip-sync and whether
  the animation hitches while a sentence is synthesised (Kokoro is capped at 4
  threads for that reason) have not been seen.
- **UNVERIFIED — the voice itself.** Nobody has listened to it. It is a blend
  of two stock Kokoro voices (`MAVIS_KOKORO_VOICE`), not the character.
- **UNVERIFIED — the 0.7s cut-off on a human voice.** Tested only on `say`
  speech followed by digital silence. If he cuts questions off, set
  `MAVIS_ENDPOINT_SECONDS=1.0` in `~/.mavis/env`.
- **UNVERIFIED — the ElevenLabs voice.** Tested against a mock only.
- **NOT DONE — "lively" (criterion 2).** No animation work this session.
- **NOT DONE — the wake phrase (criterion 1).** The model has never been
  trained; that is an owner task on openWakeWord's Colab notebook.
- **NOT DONE — the 30-minute memory session (criterion 4).**
- **The four criteria in the doc are the assistant's wording.** The owner
  replied only with the deadline. Get an explicit yes.
- **Whose voice is `actor_sample.wav`?** `assets/voice/ATTRIBUTION.md` says "a
  hired voice actor's voice". If that actor agreed to cloning, ElevenLabs could
  legally carry the original voice at full speed. If not, it cannot.
- **Groq's free tier is 8,000 tokens a minute.** A burst of news questions hit
  a 429 during testing. He reports it on screen and keeps listening.
- **Grounded answers depend on the prompt wording.** With the first persona
  draft he denied having the pending SERV proposal that was in his context (2
  of 3 runs). The comment above `PERSONA` in `providers.py` records the fix
  (15 of 15 afterwards). Re-run that check after any persona edit.
- "What is Graywind waiting on me to approve" retrieves nothing and is refused.
  That is the retrieval and corpus limit, out of scope for this release.

## What's next (ordered)

1. Owner runs him and listens: `launchctl kickstart gui/$UID/com.mavis.avatar`,
   press W, ask a market question, "what's the news", and a Graywind question.
   Canned lines to preview the voice: `afplay mavis/assets/voice-kokoro/greeting-*.wav`.
2. If the owner approves the changes, commit locally on `feat/mavis-avatar`.
3. Lively: retarget the Mixamo talking clips if they are in `~/Downloads`
   (What's next #1 in the face handoff), then check the 60-second idle rule.
4. Owner trains the wake-word model; then run the 4-of-5 and 30-minute checks.
5. 30-minute session with Activity Monitor's memory pressure graph open.
6. When all four criteria pass: owner re-rates, tag a release, write the
   changelog.

## Verification idioms used in this project (for the resuming session)

- Tests: `cd mavis && .venv/bin/python -m pytest -q`.
- Timing: `set -a; . ~/.mavis/env; set +a; .venv/bin/python tools/latency_probe.py ["question" ...]`.
  Note mains or battery (`pmset -g batt`). Leave 60s between runs or Groq
  rate-limits.
- One answer by hand:
  `curl -s -N -X POST localhost:8000/ask/stream -H "X-API-Key: $MAVIS_API_KEY" -H 'content-type: application/json' -d '{"query": "what is on the graywind watchlist", "max_chars": 200}'`
- Re-render canned lines after changing the voice: `.venv/bin/python scripts/pregen_lines.py`.

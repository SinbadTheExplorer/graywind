# Johnny Call Mode: Plan

Criteria: `docs/superpowers/specs/2026-11-09-johnny-call-mode-done-criteria.md`. Branch: `feat/mavis-avatar`.

## What changes, in plain terms
Today, `app.py`'s `_serve` loop blocks on `wait_for_wake()` (the wake word or the W key). It then runs `_conversation()` until a spoken dismissal or a long silence, and `states.py` hides the scene while he's asleep. Call mode swaps the wake word for buttons and stops hiding the scene.

## Steps (test-first where the logic is pure)

1. **State machine (`states.py`)**
   - Add `IDLE` (the call screen) and `RINGING` states, plus `on_call()`, `on_pick_up()` and `on_hang_up()`.
   - `on_hang_up()` is accepted from **any** state.
   - Idle never calls `scene.hide()`. The scene stays up and shows the call screen. This targets criterion #1.
   - Unit tests cover every transition, including hang-up during THINKING and SPEAKING.

2. **Call screen + buttons (`scene.py`)**
   - Add Call and Hang-up buttons drawn in the existing overlay layer (Panda3D DirectGui), plus a "ringing..." label.
   - Keyboard backups: `C` for call, `H` or `Esc` for hang up (Esc currently quits; quitting moves to `Q`).
   - Verify by rendering offscreen to PNG and checking it before asking the owner.

3. **Cancellable conversation (`app.py`)**
   - Replace `wait_for_wake()` with a wait on a call event.
   - Run `_conversation()` as a task that hang-up **cancels**.
   - To meet the 1 s limit, recording (`capture.record_utterance`) and playback (`say`/`_speak`) must also check a stop flag between audio blocks, so a thread blocked on the mic or speaker exits quickly.
   - Remove the "gone quiet = dismissed" path. A long silence leaves the call open on the call screen.
   - Spoken "that's all" stays as a backup hang-up.

4. **Wake word off by default**
   - `wake.py` stays in the repo but is no longer started (flag to re-enable).
   - This targets criterion #4: no microphone listening while idle.

5. **Incoming call on alarm**
   - Add a tiny alarm inbox: a file `data/alarms/*.json`, plus a `--test-alarm` command that writes one.
   - A new alarm makes him ring. Picking up speaks it, and the alarm is removed only after he has spoken it.
   - Hub v1 P1 `health.py` will write into the same inbox later.

6. **Timing log**
   - Log call→pick-up, question-end→first-audio and hang-up→silent times to stderr.
   - The owner's 10/10 checks for #1–#3 use these numbers instead of guessing.

## Order and cut line
Build 1→2→3→4 first: that covers criteria #1–#4 and #6. Step 5 is last and is the first thing cut if time runs out. Step 6 is folded into step 3.

## How each criterion gets checked
- **#1, #3:** the owner runs 10 calls and 10 hang-ups; the timing log plus watching or recording.
- **#2:** the timing log.
- **#4:** run idle for a day; the log shows zero call events without a button press or alarm.
- **#5:** `--test-alarm`, then pick up.
- **#6:** one other person, no instructions.

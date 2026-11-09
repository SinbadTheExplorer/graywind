# Johnny Call Mode: Done Criteria

**Agreed:** 2026-11-09 by the owner. **Built by:** Wed 2026-11-11. **Done by:** Mon 2026-11-16.
**Scope change to** Johnny Hub v1 (`2026-10-11-johnny-hub-v1-done-criteria.md`), which is past its 10/22 budget. This change replaces how Johnny is summoned. It does not add a new project.

**Why:** Johnny appearing at the wrong times, or not appearing at all, comes from three parts:
- the wake word ("Wake up, Johnny") misfires
- hiding and re-showing the 3D scene glitches
- dismissal is spoken-only

Sesame-style calling replaces all three with explicit buttons:
- tap **Call**
- he rings and picks up
- you talk
- tap **Hang up**

## Criteria (stop when all six pass)

1. **Connects cleanly.** 10 of 10 calls connect with no visual glitch: no black flash, no frozen frame, no window jump. The owner checks this live or from a screen recording.
2. **Responsive.**
   - He picks up within **2 s** of tapping Call.
   - He starts answering within **3 s** of the owner finishing a question.
3. **Hang up works.** 10 of 10 hang-ups end the call within **1 s**, including mid-sentence and mid-recording.
4. **No ghost calls.** Over one full idle day, he never picks up or speaks unless the owner called or an alarm fired.
5. **He calls you on an alarm.**
   - A test alarm makes him ring.
   - Picking up gets a spoken line naming that alarm.
   - Declining or ignoring the call doesn't stop the alarm from being kept. It is still there on the next call.
   - Out of scope: real Graywind/Bullion alarm detection. That stays Hub v1 P1 (`health.py`, not built yet).
6. **Someone else can use it.** One person who isn't the owner places a call, asks a question and hangs up, with no instructions. This triggers a stage-5 feedback session (`~/.claude/feedback/`).

**Rule:** if 11/16 passes and the work isn't done, cut #5 first rather than extend.

## Out of scope (someday list)
- Interrupting him mid-sentence by talking (Sesame's full-duplex barge-in)
- Any new pick-up or hang-up animation. The owner does animation work in claude.ai chat, not here.

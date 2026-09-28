# Johnny — Done Criteria

**Written:** 2026-09-28, agreed with the owner before the work starts.
**Target:** quality 8/10 (from 4/10). **Usage is deliberately capped** — see below.
**Time budget:** ~4 sessions, finish by **2026-10-12**. Past that, cut scope or bury.

## Done means all three of these hold

1. **He looks alive, face and arm included.** Judged at the live window's own
   framing, not a close-up, because only what is visible there counts. While
   he speaks: his brows visibly move and his head and hands move with the
   speech, not just the idle loop. At rest: blinks are visible (at least 5 in
   30 seconds) if the eyes can be seen through the lenses. The chrome arm
   renders as shaded metal and neither the arm nor his hair shows see-through
   holes. Checkable frame by frame from a render sequence or a screen
   recording.
   *(Reworded the same day it was written: the first draft counted eye
   movements, which turned out to be hidden behind his sunglasses at the
   live framing and so could pass without anyone seeing them.)*
2. **He starts talking within 6 seconds.** For an answer of 170-180 characters,
   the time from the end of the question to his first spoken word is 6s or
   less (measured 15.8s on 2026-09-25). Chunked voice conversion is **approved
   by the owner** (2026-09-28) to get there, and it replaces the voice spec's
   "audio is finished before the renderer animates" rule.
3. **He wakes hands-free.** Saying "Wake up, Johnny" at normal volume from the
   desk chair wakes him on at least 4 of 5 tries, with no false wake in 30
   minutes of ordinary room noise. The W key stays only as a fallback.

When all three pass: the owner re-rates him, then tag a release with a short
changelog of what he does and doesn't do.

## Deliberately out of scope

- **Usage beyond the owner (option A, chosen 2026-09-28).** The CDPR model and
  the character's voice cannot legally go to anyone else, so Johnny stays a
  personal app. No installer, no shareable persona, no other users. A
  shareable version would be a new project and goes on the someday list.
- **Filling the Graywind corpus** (script 4/10). It still needs an owner
  decision on which docs are authoritative, and it isn't on this list. The
  honest-refusal guard (`9f21df2`) covers it meanwhile.
- Voice timbre and the filler lines. Both were approved; don't touch them.

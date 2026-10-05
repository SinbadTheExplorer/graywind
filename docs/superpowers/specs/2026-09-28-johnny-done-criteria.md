# Johnny — Done Criteria

**Written:** 2026-09-28. **Rewritten 2026-10-01** as an owner-ordered scope
change: four objectives instead of three, and the voice is traded for speed.
**Target:** quality 8/10 (from 4/10). **Usage is deliberately capped** — see below.
**Time budget:** finish by **2026-10-03** (owner's deadline, set 2026-10-01).
Past that, cut scope or bury.
**Who writes the code:** Opus writes Johnny's code directly until the release
tag. The delegate-first rule is suspended for this project only.

## Done means all four of these hold

1. **He is responsive.** On mains power, the time from the end of the question
   to his first spoken word is 3s or less (it was 15.8s on 2026-09-25, and the
   6s target of the previous version failed on battery). Saying "Wake up,
   Johnny" at normal volume from the desk chair wakes him on at least 4 of 5
   tries, with no false wake in 30 minutes of ordinary room noise. The W key
   stays only as a fallback.
2. **He looks alive, face and arm included.** Judged at the live window's own
   framing, not a close-up, because only what is visible there counts. While
   he speaks: his brows visibly move and his head and hands move with the
   speech, not just the idle loop. At rest: blinks are visible (at least 5 in
   30 seconds) if the eyes can be seen through the lenses, and no idle loop
   visibly repeats within 60 seconds. The chrome arm renders as shaded metal
   and neither the arm nor his hair shows see-through holes. Checkable frame
   by frame from a render sequence or a screen recording.
3. **He is useful.** Asked "what's the news", he reads today's headlines, names
   where each came from, and adds his own commentary in character. Asked about
   Graywind, he quotes a real figure from the data he was given or says he
   doesn't have it. Advice from the owner's data stays limited to what the
   grounding snapshot holds until the owner decides which docs are
   authoritative; that decision is not part of this release.
4. **He is light on the Mac.** Across a 30-minute session with ordinary use,
   memory pressure never goes red and other apps stay usable while he answers.

When all four pass: the owner re-rates him, then tag a release with a short
changelog of what he does and doesn't do.

## Decisions that changed on 2026-10-01

- **The voice is traded for speed.** Local voice conversion into the
  character's voice ran at about 1.5x realtime on this 8GB M2 and could not
  get under 6s. Live answers now use a fast text-to-speech voice instead:
  a local one, or a cloud voice if the owner prefers it by ear. This
  overrides the earlier "voice timbre: don't touch" line.
- **No cloning of someone's voice on a cloud service without their consent.**
  ElevenLabs' prohibited-use policy forbids replicating another person's
  voice "without consent or legal right", and forbids using its output to
  train other models (read 2026-10-01). `assets/voice/ATTRIBUTION.md` calls
  the reference clip "a hired voice actor's voice"; whether that actor agreed
  to cloning is the owner's to answer. Without that, a designed or library
  voice is the allowed route.
- **Chunked voice conversion is retired** with the voice it served.

## Deliberately out of scope

- **Usage beyond the owner (option A, chosen 2026-09-28).** The CDPR model
  cannot legally go to anyone else, so Johnny stays a personal app. No
  installer, no shareable persona, no other users. A shareable version would
  be a new project and goes on the someday list.
- **Choosing the authoritative Graywind docs** (script 4/10). Still an owner
  decision. The honest-refusal guard (`9f21df2`) covers it meanwhile.
- **Interrupting him mid-sentence.** Next release.

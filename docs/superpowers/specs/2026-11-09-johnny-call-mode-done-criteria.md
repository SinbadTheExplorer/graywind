# Johnny Call Mode: Done Criteria

**Agreed:** 2026-11-09 by the owner. **Built by:** Fri 2026-11-13. **Done by:** Fri 2026-11-20.
**Scope change to** Johnny Hub v1 (`2026-10-11-johnny-hub-v1-done-criteria.md`), which is past its 10/22 budget. This change replaces how Johnny is summoned. It does not add a new project.

**Why:** Johnny appearing at the wrong times, or not appearing at all, comes from three parts:
- the wake word ("Wake up, Johnny") misfires
- hiding and re-showing the 3D scene glitches
- dismissal is spoken-only

Sesame-style calling replaces all three with explicit buttons, in a web page that works on phone and laptop:
- tap **Call**
- he picks up
- you talk
- tap **End call**

## What it is
- **Call page:** a single web page modeled on Sesame's voice demo. It has a voice-reactive orb in Johnny's colours, a call timer, Call / End call / Mute, and no face.
- **Where it runs:** the page is served by the owner's laptop. The phone reaches it over Tailscale, which gives one private HTTPS address that works on home wifi and away. HTTPS is required for browser mic access.
- **The 3D mech:** stays a laptop-only extra and is not part of the call.
- **Limitation:** calls work only while the laptop is awake and Johnny is running.

## Criteria (stop when all six pass)

1. **Connects cleanly.** 10 of 10 calls connect on each of the following, with no glitch (no stuck "connecting", no broken audio, no frozen orb):
   - phone on home wifi
   - phone on cellular away from home
   - laptop browser
2. **Responsive.**
   - He picks up within **2 s** of tapping Call.
   - He starts answering within **3 s** of the owner finishing a question, on home wifi.
   - Away from home: within **4 s**.
3. **End call works.** 10 of 10 End calls stop his voice and the mic within **1 s**, including mid-sentence.
4. **No ghost calls.** Over one full idle day, he never speaks, and the mic is never live, unless a call is open.
5. **He calls you on an alarm.**
   - A test alarm sends an ntfy push to the phone.
   - Tapping it opens the call page, and Johnny picks up and names that alarm.
   - Ignoring the push keeps the alarm. It is still spoken on the next call.
   - Out of scope: real Graywind/Bullion alarm detection. That stays Hub v1 P1 (`health.py`, not built yet).
6. **Someone else can use it.** One person who isn't the owner places a call on the owner's phone or laptop, asks a question and ends the call, with no instructions. This triggers a stage-5 feedback session (`~/.claude/feedback/`).

**Rule:** if 11/20 passes and the work isn't done, cut #5 first rather than extend.

## Out of scope (someday list)
- Interrupting him mid-sentence by talking (Sesame's full-duplex barge-in). This is the first upgrade if calls feel stiff.
- A native phone app, or real ringing while the page is closed
- Hosting Johnny off the laptop so he works when it's asleep
- Any face or new animation on the call page. The owner does animation work in claude.ai chat, not here.

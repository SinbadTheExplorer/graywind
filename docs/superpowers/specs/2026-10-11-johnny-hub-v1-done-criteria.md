# Johnny Hub v1: Done Criteria

**Agreed:** 2026-10-11 by the owner, who approved the plan. **Budget:** finish by **2026-10-22**.
**Supersedes** `2026-09-28-johnny-done-criteria.md` as the definition of finished Johnny.

Johnny returns to his original purpose. He reads Bullion and Graywind, reports to the owner, raises alarms, and answers questions. Looking good is still part of the job.

## Criteria (stop when all three pass)

1. **Reports and alarms**
   - When the owner says "Johnny, report", he gives a spoken briefing of at most 60 seconds. It quotes current numbers:
     - Graywind equity and P&L for both accounts ($100k and $2k)
     - minutes since the last trading cycle
     - pending trades
     - Bullion data and news freshness
     - open alarm issues
   - A simulated failure must trigger a spoken alarm and a phone push (ntfy) within 15 minutes. Use either a stale heartbeat fixture or an open alarm issue. Once acknowledged, the alarm must not repeat.

2. **Free-model brain**
   - With `GROQ_API_KEY` deliberately broken, Johnny still answers out loud through the fallback chain (Groq → Gemini free key → Cerebras/OpenRouter free). `/status` names the provider that answered.
   - Questions about how Graywind is doing are answered from live data, not the 2026-09-15 snapshot.

3. **Looks and window**
   - A compact window and the full-screen portal swap with one key. The compact window stays on top, can be resized and dragged, and remembers its position.
   - Head and eyes follow the viewer in both modes.
   - The tracker stays at **12 fps or more while he talks**.
   - Parallax runs in full-screen portal mode only (owner's choice).
   - Each of the above is verified live, with screenshots the owner has seen.

## End state
Tag `johnny-v1.0` and write a changelog entry covering what he does and doesn't do. Push only when the owner says so (the repo is public). Then run a feedback panel session (`~/.claude/feedback/`).

## Phase order (cut from the bottom)
- P0 handoff
- P1 reports/alarms
- P2 provider chain
- P3 compact window
- P4 tracker while talking
- P5 parallax polish (stop at a 7/10 owner rating, or after 1 day)
- P6 release

Full plan: `docs/superpowers/plans/2026-10-11-johnny-hub-v1.md`.

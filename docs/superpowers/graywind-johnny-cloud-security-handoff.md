# Johnny Cloud + Security — Session Handoff

**Written:** 2026-11-11 · **For:** a fresh session finishing Task 9 (owner phone checks, Mac cut-over) and then the voice decision.

## Goal

Move Johnny (MAVIS call mode) off the owner's 8 GB laptop onto a Contabo VPS that is private to the owner's Tailscale tailnet, harden it against abuse ("seasoned developers and hackers"), and make everything except the 3D model ready for future guest users (owner keeps the Keanu model; guests get a public model later). Owner dates: **built by 11/12 (met), done by 11/14.**
- Spec: `docs/superpowers/specs/2026-11-10-johnny-cloud-security-design.md`
- Plan: `docs/superpowers/plans/2026-11-10-johnny-cloud-security.md` (Tasks 1–9)
- Previous handoff (call mode, steps 1–2): `docs/superpowers/graywind-johnny-call-mode-handoff.md`

## How to resume (do this first)

1. `cd ~/Projects/graywind-johnny && git log --oneline 14f88bb9..HEAD` — expect 11 commits ending `8222942b`. Branch `feat/mavis-avatar`, **51 commits ahead of origin, NOT pushed** (repo is public; push only on owner's word).
2. `ssh johnny 'systemctl is-active mavis graywind-sync.timer'` → `active active`. (`~/.ssh/config` has `Host johnny` → the tailnet IP, root, `~/.ssh/johnny_vps`.)
3. Workflow rules (owner's CLAUDE.md): delegate non-security code to `delegate`; write security code yourself; run `code-review` at medium after each step; explain in plain language; **owner approval before every commit.**
4. **Immediate next action:** ask the owner whether they've done the 10 phone calls from the installed app with the Mac lid closed (criteria 1 + 4). Until they confirm, **do not** cut over the Mac (step 8 of Task 9).

## Current state (active files)

**Branch:** `feat/mavis-avatar`, 11 commits since `14f88bb9` (all committed, tree clean except `.DS_Store`).

**Live service:** `https://johnny.tail4beff0.ts.net/johnny` (tailnet only; installable as an app — Share → Add to Home Screen).

**Files created / changed (by commit):**
- `74c4afea` spec + plan.
- `ea50c8a5` `mavis/keys.py` (hashed per-person keys, scopes, CLI `add|link|unlink|revoke|list`), `mavis/auth.py` (returns `KeyRecord`), `mavis/conftest.py` (isolates keys/usage/audit/lockout/ntfy in tests).
- `7516ef44` `mavis/usage.py` — SQLite daily caps (BEGIN IMMEDIATE), refunds, allowlisted JSONL audit log, alert dedupe table.
- `36d095f7` `mavis/guards.py` (WAV normalisation, generic errors), `app.py` (docs off, input limits, charge/refund), `providers.py`.
- `c554928b` `mavis/call.py`, `call_route.py` — call slots (owner always gets in), 15 min / 2 min idle, origin check, guest scope wall (no Graywind retrieval, refusal line, no Keanu), audit call start/end.
- `3a45e48e` failed-key lockout (5 in 10 min → 10 min; owner key passes; identity = Tailscale login from loopback, else IP).
- `b5b7c0a5` CSP: script moved to `web/call.js`, mic worklet `web/worklet.js`, import map allowed by per-request sha256; `SecurityHeaders` ASGI middleware.
- `219b2f91` `mavis/alerts.py` — ntfy, once/day/kind, ≤10/day, marked sent only on 2xx.
- `f51dd36e` `deploy/` (bootstrap.sh, deploy.sh, mavis.service, mavis-alert@.service, graywind-sync.{service,timer,sh}, tailnet-acl.hujson), `mavis/requirements-server.txt`, live-reloading `graywind_grounding.py`, extractor `--repo/--out`.
- `48cee8d8` installable app: `web/manifest.webmanifest`, `web/icons/*` (Viego seal "J", from the Graywind dashboard's Viego reskin), `web/fonts/johnny-title.woff2` + `OFL.txt` (Ma Shan Zheng subset, J-o-h-n-y only).
- `8222942b` sign-in by Tailscale login (no key on owner devices); side jobs denied localhost.

**Server layout (VPS, Ubuntu 24.04, Python 3.12, 4 vCPU / 8 GB, Contabo France (IPs in `~/.ssh/config` and the Contabo panel, kept out of this public repo), tagged `tag:johnny`):**
- Code `/opt/mavis/mavis` (root-owned, read-only to service), venv `.venv`, deploy files `/opt/mavis/deploy`.
- Models `/opt/mavis/models` (root:mavis 0640): kokoro-v1.0.onnx, voices-v1.0.bin, keanu-web.glb.
- State `/var/lib/mavis` (mavis, 0700): `env` (GROQ_API_KEY, MAVIS_API_KEY, MAVIS_NTFY_TOPIC, MAVIS_OWNER_LOGINS), `alert.env` (topic only), keys.json, usage.db, audit.log, graywind-state/ (public repo clone), graywind_grounding.json.
- `tailscale serve` 443 → 127.0.0.1:8000. ufw: deny all incoming except `tailscale0`. sshd: keys only (`00-hardening.conf` + `00-mavis.conf`).

**Scratch workspace / traps:**
- ⚠️ Scratchpad probes (not committed): `abuse_probe.py`, `latency_probe.py`, `csp_probe.mjs`, `pwa_probe.mjs` under the session scratchpad — the session dir may be gone; rewrite rather than hunt.
- ⚠️ `deploy/deploy.sh` ships **HEAD only** (`git archive`), not uncommitted edits. Commit before deploying.
- ⚠️ macOS `rsync` is openrsync (no `--chown`/`--from0`) — that's why deploy uses tar over ssh.
- ⚠️ The ntfy topic the owner chose (set from `JOHNNY_NTFY_TOPIC` into the server env, not in git) is guessable; alerts deliberately never name anyone. Suggest a random topic if they care.
- ⚠️ The Mac backend (`com.mavis.backend` LaunchAgent, `tailscale serve` on the Mac) is **still running** on purpose until the owner confirms the VPS works on the phone.

**Not mine — leave alone:** `.DS_Store`; all Graywind trading code; `mavis/assets/voice/` and `assets/voice-kokoro/` (gitignored generated audio; voice-kokoro is shipped by deploy.sh).

## What has changed

- Security Tasks 1–8 built, each reviewed (code-review medium, all findings fixed), owner-approved, committed. Test suite: **593 passed** (`cd mavis && .venv/bin/python -m pytest -q`).
- Task 9 so far:
  - bootstrap + deploy done.
  - Owner pasted the tailnet ACL and tagged the VPS.
  - HTTPS serve enabled.
- **Criterion 1:**
  - `nmap -Pn -p-` of the public IP: **0 open ports**. Port 113 showed "closed", likely the owner's router.
  - Phone call with the Mac asleep: **NOT yet done by owner.**
- **Criterion 2 PASS:**
  - Abuse probes made zero STT requests and only the one deliberately allowed LLM call: no key / wrong key 401, docs 404, 2 MB → 1009, non-WAV → generic error, 31 s → "too long".
  - The guest cap held across a restart.
  - Lockout fired, with identity `ts:<login>`.
  - Both ntfy alerts arrived on the owner's phone.
- **Criterion 3 PASS:**
  - Guest model fetch 404 (no public model), owner 200.
  - A guest asking about Graywind got the refusal line, `grounded: false`.
  - After revoke, the next request was 401.
- **Criterion 4:**
  - Automated: server-side `first audio` median **2.5 s** (2.2–3.0) PASS. Mac-side 3.3 s; tailnet RTT to France ~190 ms (direct, not DERP).
  - Owner's 10 phone calls: **NOT yet done.**
- Verified live: `tailscale serve` **overwrites a forged Tailscale-User-Login** (test 2026-11-11) — basis for login sign-in.

## What has failed / risks / caveats

- **Nothing deployed is failing.** All services are active and the health check returns `{"ok": true}`.
- **Chatterbox on the VPS: RULED OUT.**
  - On CPU, ChatterboxTTS ran at about **20× slower than realtime** (64 s for a 3 s sentence), and ChatterboxVC at about 12×. Load took 126 s.
  - The bench folder and the copy of the actor sample were deleted from the VPS.
- **Voice:**
  - The owner says the current voice "is not like the Johnny imitation voice actor I hired." It's the Kokoro blend `am_onyx:0.6,am_fenrir:0.4`, the same one the Mac has used since 2026-10-01, when the owner traded the cloned voice for speed. Nothing degraded in the move.
  - The actor sample is at `~/minhthanh0403/claude-projects/claudekit/bullion-live-map/audio/voice_sample/actor_sample.wav`.
  - Canned lines in the actor's voice: `mavis/assets/voice/` (28 wavs).
  - **Consent for AI cloning is unconfirmed.** Ask before any cloning.
- **UNVERIFIED on a real phone:** installing the app (manifest and iOS tags), the 3D model appearing at iOS 16+, `connect-src` on Safari.
- **Known limit:** the CSP needs `'wasm-unsafe-eval'`, so the model needs iOS 16 or later. Older devices get the orb.
- **Decisions that override the plan:**
  - **Lockout lets the owner key through.** A guest sharing the owner's identity can't lock the owner out.
  - **SSH isn't bound to the tailnet IP.** On Ubuntu 24.04, `ListenAddress` can stop sshd at boot, so ufw does the blocking.
  - **The VPS is tagged in the admin UI,** not with `tailscale up --advertise-tags`.
  - **A guest with no public model gets 404, not 403.**
  - **Login sign-in is opt-in** via `MAVIS_TAILSCALE_SIGNIN=1`, which only `mavis.service` sets.
- `KeyExpiry` still shows 2027-05-09 on the tagged node. Tagging normally disables expiry, so confirm it's off in the admin page (Machines → johnny).

## What's next (ordered)

1. **Owner:**
   - Install the app on the iPhone (Safari → Share → Add to Home Screen). It should open with **no key** thanks to Tailscale sign-in.
   - Make 10 calls with the Mac lid closed.
   - Then compute the median: `ssh johnny 'journalctl -u mavis --since "-1h" | grep -oE "first audio [0-9]+ ms"'`. It must be 3000 ms or less, and the owner's feel decides whether to move to a US Central server.
2. **Task 9, step 8 — Mac cut-over (only after step 1 passes):**
   - `launchctl bootout gui/$(id -u)/com.mavis.backend`
   - Remove `MAVIS_CALL_WARM=1` from `~/.mavis/env`
   - `tailscale serve reset` on the Mac.
   - Check first whether the desktop avatar (`com.mavis.avatar`) depends on the local backend; if so, point `MAVIS_URL` at the VPS instead.
3. **Voice decision (owner):** the leading option is the ElevenLabs **free plan**: a premade or Voice-Design voice (no cloning), about 10k credits/month, Kokoro as automatic fallback.
   - The owner creates the account and sends the voice ID.
   - The API key goes into `/var/lib/mavis/env` **without** passing through the chat.
   - Set `MAVIS_TTS=elevenlabs`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_API_KEY` there.
   - Fix the fallback first: `avatar/tts.py` falls back to macOS `say`, which **doesn't exist on Linux**. Make it fall back to Kokoro.
   - Regenerate the canned lines in the new voice.
   - Starter ($6/mo) would enable cloning the actor, but only if consent is confirmed.
4. **Owner-requested UI change (not built):** hide Keanu until the call connects. The idle screen should show only the seal and the "Johnny" title on black, with Keanu fading in on connect. Memory says the owner handles *animation* in claude.ai chat; this is call-flow UI, so confirm scope with the owner first.
5. Queued from before:
   - three-brain fallback (Groq → Cerebras → Gemini, hedged), spec §7
   - voice smoothness fixes and the owner's listening test (0.25/0.35/0.5 s sentence gaps), spec §8
   - optional Sesame CSM-1B test (needs a GPU; likely moot after the Chatterbox result)
6. Release per the owner's workflow when the criteria are met: tag and changelog. Update memory `project-johnny-hub-v1.md`.

## Verification idioms used in this project (for the resuming session)

- **Tests:** `cd mavis && .venv/bin/python -m pytest -q`. The suite should pass fully; `conftest.py` isolates all state and blocks real ntfy.
- **Server import gate:** `tests/test_server_deploy.py` imports the app with every package outside `requirements-server.txt` blocked. Run it after touching dependencies.
- **Deploy:** commit, then `JOHNNY_NTFY_TOPIC=<topic> deploy/deploy.sh`. It ends by printing `{"ok":true}` plus the serve status. Without the variable on later runs, the existing env stays as it is.
- **Live checks:**
  - `curl -s -o /dev/null -w "%{http_code}" https://johnny.tail4beff0.ts.net/johnny/check` → 200 from an owner device (login sign-in).
  - Server logs: `ssh johnny 'journalctl -u mavis -n 50'`
  - Audit log: `ssh johnny 'tail /var/lib/mavis/audit.log'`
- **Keys on the server:** `ssh johnny 'cd /opt/mavis/mavis && runuser -u mavis -- env MAVIS_KEYS_FILE=/var/lib/mavis/keys.json .venv/bin/python keys.py list'`
- **Browser check of the page:** headless Chrome via the `headless-chrome-verification` skill template.
  - Load at 390×844 with fake media flags.
  - Feed 16 kHz frames through `__johnny.vad(f)`; the fake-mic file flag is silent in headless.
  - Assert `__johnny.modelLoaded`, a "heard" caption, and zero `securitypolicyviolation` events.
- **Secrets:** never print them. Copy the owner key to the clipboard with `grep MAVIS_API_KEY ~/.mavis/env | … | pbcopy`.

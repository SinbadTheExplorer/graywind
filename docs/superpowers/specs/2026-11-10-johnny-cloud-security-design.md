# Johnny on a cloud server, hardened for future users — design

**Written:** 2026-11-10 · **Parent:** Johnny Call Mode (`2026-11-09-johnny-call-mode-done-criteria.md`), itself a scope change of Johnny Hub v1.
**Status:** APPROVED by owner 2026-11-10 (dates set by owner).

## Why

- **The laptop can't be the server.** The owner says the laptop can't handle it. Measured on 11/9: answers take about 2.5 s when the Mac only runs the server, and about 6 s when it also renders Johnny. Calls only work while the lid is open, too.
- **Other people will use Johnny later.** Today only the owner calls Johnny. Everything except the 3D model must be ready for other users, so that opening it up is a switch rather than a rebuild.
- **The model splits by user.** Other users will get a legal public model, and the owner keeps the real (Keanu) Johnny.
- **Seasoned attackers are the bar.** The owner asked what experienced developers and attackers could exploit. Section 3 answers that from the actual code, and this design closes those holes.

## Goals / non-goals / anti-goals

**Goals**
- Johnny runs 24/7 on a Contabo VPS. The owner is paying for the small plan.
- Phone and laptop calls reach it over Tailscale HTTPS. The laptop stops being a server.
- Every hole in §3 is closed, or explicitly deferred with a reason.
- The server is ready for multiple users: per-person keys, per-person limits, scopes, revocation, spend caps and an audit log.

**Non-goals (now)**
- Public access (Tailscale Funnel)
- Sign-up pages, passwords, payments
- Picking the public model
- New animation (that's the owner's claude.ai lane)
- Talking over Johnny mid-answer

**Anti-goals** (failures even if it "works")
- A guest hears the owner's Graywind data: positions, pending trades, tiers, account names.
- The Keanu file is ever reachable without the owner's key, or committed to git. The repo is public.
- A leaked key, a bug or a script runs up a Groq bill with nobody noticing. Per the silent-failure rule, a cap hit must alert, not just quietly stop.
- The VPS ever holds trading credentials (Alpaca), or can reach the owner's Mac or phone.

## 1. Done criteria (checkable by someone else)

1. **Nothing public.**
   - A port scan of the VPS's public IP from outside the tailnet shows **zero open ports**.
   - The owner completes a phone call to `https://<vps>.<tailnet>.ts.net/johnny`, with the Mac asleep.
2. **Abuse costs nothing.** Each probe below causes **zero Groq requests**, shown by the audit log and the automated tests:
   - no key
   - wrong key
   - oversized audio
   - non-WAV audio
   - audio longer than 30 s
   - an over-limit key
   - a key past the daily cap

   Also, the daily spend cap still holds after `systemctl restart`.
3. **Guests are walled off.**
   - A guest key gets **403** on the Keanu model.
   - Asked about the Graywind watchlist or pending trades, a guest gets the refusal line, never data.
   - A revoked key fails on its very next request.
4. **The move doesn't make it slower.** The time from the end of an utterance to the first audio, measured in the VPS log, has a **median of 3 s or less** over 10 owner calls. This is call-mode criterion #2, re-measured on the VPS.

**Time budget (owner-set 2026-11-10):** **built by Thu 11/12, done by Sat 11/14.** This supersedes call mode's 11/16 / 11/23 dates.
- Critical path: the owner must buy the VPS on 11/10–11/11, because nothing deploys without it.
- Cut order if late:
  1. ntfy alerts (log-only instead)
  2. the Graywind freshness timer (manual `scp` of the snapshot instead)
  3. P1 #11, the CSP/page refactor. Low risk while the server is tailnet-only.

  P0 is never cut.

## 2. Architecture

```
iPhone / laptop browser ──HTTPS (Tailscale serve, tailnet only)──▶ Contabo VPS
                                                                   ├─ tailscaled  (serve :443 → 127.0.0.1:8000)
                                                                   ├─ mavis.service (uvicorn, user `mavis`, 127.0.0.1 only)
                                                                   ├─ /var/lib/mavis/{env,keys.json,usage.db,audit.log}
                                                                   └─ graywind-sync.timer (public repo pull → snapshot)
Outbound only: Groq (STT + LLM), Google News RSS, GitHub (public Graywind repo), ntfy.
```

- **OS:** Ubuntu 24.04 LTS on the smallest Contabo Cloud VPS.
- **Python:** 3.12, using a new server-only `requirements-server.txt`. The current `requirements.txt` won't install on Linux 3.12+ (openwakeword/tflite), and the server doesn't need panda3d, opencv, sounddevice or the wake word.
- **Model files:** Kokoro and Keanu are copied over with `scp` and never go through git.

## 3. Findings: what an attacker could exploit today

Found by reading `app.py`, `auth.py`, `call.py`, `call_route.py`, `rate_limit.py`, `avatar/stt.py`, `providers.py` and `web/call.html` on 2026-11-10. The current key is 40 characters and random, so guessing it is not realistic. The holes are elsewhere.

### P0: fix before the VPS goes live (even while private)

| # | Hole | Exploit | Fix |
|---|---|---|---|
| 1 | **Guest data scope doesn't exist.** `_answer_events` always loads `graywind_grounding` (pending trades, positions, tiers). | Any future key asks "what's pending in Graywind?" and hears the owner's portfolio. | Each key gets a **scope**. `owner` gets Graywind + Bullion + news. `guest` gets Bullion + news only, and Graywind questions get the existing `UNGROUNDED` refusal. |
| 2 | **Unbounded audio.** Uvicorn's default WebSocket message cap is 16 MiB, and the server never inspects the WAV. | One 16 MiB "utterance" is about 8 min of paid Whisper for one rate-limit slot. Before auth, junk bytes can also be pushed at the server. | Start uvicorn with `--ws-max-size 1048576`. Before the rate limit and before Groq, parse the WAV header: RIFF/PCM16, mono, 16 kHz, **≤ 30 s**. Reject otherwise. |
| 3 | **Unbounded text input** on `/ask` and `/ask/stream`. `query` has no length cap, and `max_chars` is client-chosen and unclamped. | Huge prompts, or answers asked to be 100k characters long, burn tokens. | Cap `query` at 500 characters. Clamp `max_chars` to 50–600. |
| 4 | **No daily or global spend cap.** The limit is 20/min per key, and it lives in memory. | A leaked key gets about 28,800 STT + LLM calls a day, and a restart resets the count. | A persistent daily cap in SQLite, per key and global, counting STT seconds and LLM calls. A cap hit gives a spoken "tapped out for today" line plus **one ntfy alert per day**. The owner also sets a spend limit in the Groq console if their tier has one. That limit is the only backstop if the VPS itself is compromised. |
| 5 | **No concurrency or duration limits.** Kokoro synth is CPU-heavy, and calls have no time limit. | A few parallel calls freeze the small VPS. An idle open call holds resources forever. | At most **2 concurrent calls globally and 1 per key**. A call ends after **15 min**, or after **2 min with no utterance**. Synthesis goes through the existing single lock. |
| 6 | **Internal errors are sent to clients.** These include `Groq error: {resp.text}` and `f"{type(exc).__name__}: {exc}"`. | Exposes the provider's error bodies, file paths and stack details, which helps an attacker map the system. | Clients get generic messages ("Johnny's line dropped, try again"). The detail goes to the server log only. |
| 7 | **Discovery routes are open.** `/docs`, `/redoc` and `/openapi.json` are on by default, and `/status` shows the model name and whether auth is configured. | A free map of every endpoint. | Turn off the docs routes. `/status` returns `{"ok": true}` only. |
| 8 | **The VPS could be a pivot.** On the tailnet, a compromised VPS could reach the Mac and phone. | Server takeover, then lateral movement to the owner's devices. | A tailnet ACL tags the VPS `tag:johnny`. It may receive :443/:22 from the owner's devices and **can't initiate connections to any of them**. The VPS also never holds Alpaca or other trading credentials. |

### P1: before a second key exists

| # | Hole | Fix |
|---|---|---|
| 9 | **One shared, permanent key** with no revocation and no per-person identity. | `~/.mavis/keys.json` stores **SHA-256 hashes**, never the keys themselves. Each record holds `id`, `scope`, `per_minute`, `per_day` and `revoked`. A CLI (`keys.py add/revoke/list`) prints a new key once. The current `MAVIS_API_KEY` stays valid as an `owner` key so nothing breaks. Logs record the key **id**, never the key. |
| 10 | **No throttle on failed key attempts** (`/johnny/check`, `/call` hello, `/ask`). | Failed attempts are counted per caller identity: the `Tailscale-User-Login` header if serve sends it (to verify), otherwise the client address. 5 failures in 10 min lock that identity out for 10 min (owner set 5 on 11/10). Every lockout is logged and alerted. |
| 11 | **XSS = key theft.** The key sits in localStorage, the page has inline scripts, there's no CSP, and the page can be framed. | Add a strict CSP: `default-src 'self'`, no inline script, `frame-ancestors 'none'`. Also `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `Permissions-Policy: microphone=(self), camera=(), geolocation=()`. Move the inline module and the AudioWorklet to static files, so `blob:` and `'unsafe-inline'` aren't needed. Hash the importmap or remove it. |
| 12 | **No WebSocket origin check.** Not exploitable today, because the key isn't a cookie, but it's cheap defence in depth. | Reject `/call` when `Origin` doesn't match the host. |
| 13 | **The model goes to any valid key.** | `/johnny/model.glb` serves Keanu to `owner` keys only. `guest` keys get `MAVIS_PUBLIC_MODEL`, or a 404, in which case the page shows the orb. |
| 14 | **No audit trail.** | `audit.log` is JSON lines: time, key id, event (call start/end, utterance seconds, LLM call, refusal, auth fail, cap hit, lockout). **No transcripts or audio** (my call: guests' words are their privacy; the owner can change this). |

### VPS hardening (the server itself)

- **SSH:** the SSH key is added when the server is ordered. Password login is off and root login is off (Contabo images often have both on, so check).
- **Network:** SSH listens only on the Tailscale interface. `ufw` denies all inbound except the `tailscale0` interface.
- **Updates:** `unattended-upgrades` installs security patches automatically.
- **Service:**
  - It runs as the non-root user `mavis` under systemd, with `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome` (except its own dir), `PrivateTmp` and `MemoryMax`.
  - uvicorn binds to `127.0.0.1` only, and `Restart=on-failure`.
  - Secrets are in `env`, chmod 600, owned by `mavis`.
- **Monitoring:** ntfy alerts on a service restart loop, a cap hit or a lockout.

## 4. Graywind data on the server

- **Today:** `graywind_grounding.json` is a snapshot built from Graywind's CSV state files, and the GitHub Actions cycles commit those CSVs to the public repo.
- **On the VPS:** a systemd timer runs every 15 min. It shallow-pulls the **public** Graywind repo with no credentials, re-runs `extract_graywind_grounding.py`, and the server reloads the JSON when its modification time changes.
- **Failure handling:** if the pull fails 3 times in a row, an alert goes out (silent-failure rule).

## 5. The owner's manual steps

1. Finish the Tailscale sign-in on the Mac (it showed "Logged out" on 11/10). It's in the menu-bar icon, under Log in.
2. Buy the smallest Contabo Cloud VPS with **Ubuntu 24.04**, and add an SSH public key during checkout. Claude will create the key and give the owner the text to paste.
3. In the Groq console, check the tier and set a monthly spend limit if one is offered.
4. Paste the tailnet ACL that Claude writes into the Tailscale admin console.
5. Give the ntfy topic for alerts. Graywind's existing one is fine if the owner wants a single channel.

## 6. Decided by the owner / left to the builder

**Owner decided:**
- Private only for now, and future-user ready except for the model.
- Keanu stays for the owner, and the public model gets swapped in later.
- The laptop isn't the server.
- Contabo, small paid plan.

**Claude's calls (owner can override):**
- Ubuntu 24.04
- The limits: 30 s per utterance, 2 concurrent calls, 15 min per call, 500-character query, failed-attempt lockout
- No transcripts in the log
- Keys stored as hashes in a file, not a database
- SQLite for usage counts
- 15-min Graywind sync
- The current key becomes the first `owner` key

**Left to the builder:**
- Exact numbers for the default daily caps. Start from today's real usage, about 30 calls/day, and give it 3× headroom.
- How the CSP handles the importmap.
- Whether `Tailscale-User-Login` is available, and the fallback if it isn't.

**After cutover:**
- Unload the Mac's `com.mavis.backend` LaunchAgent and remove `MAVIS_CALL_WARM=1` from `~/.mavis/env`.
- The desktop avatar points at the VPS, or stays off. It's untouched otherwise.

## 7. Next, after this ships: three brains (owner-approved 2026-11-10)

This fills Hub v1 done-criterion #2, which was never built. It doesn't move the 11/12 / 11/14 dates.

- **Chain:** Groq (primary) → Cerebras (plan B: same gpt-oss-120b, so the persona doesn't drift; confirm the free tier still exists) → Gemini free tier (plan C: a different vendor). No aggregators (OpenRouter etc.).
- **Hedged "dual brain":**
  - Ask Groq first. If no first token arrives within ~0.8 s, also ask Cerebras, and speak whichever starts first. Cancel the other.
  - Don't race every question. That would spend two free allowances each time.
- **On failure:** fall back only before the first token. If every brain fails, Johnny says so out loud and an alert fires. `/status` names the brain that answered.
- **What stays the same:** speech-to-text stays Groq-only. Each brain's use counts against the same `llm` daily caps.
- **Owner notes:**
  - The Gemini free tier may use conversations to improve Google's products. The owner accepted this on 11/10.
  - Everything stays on free tiers. The owner is to confirm there's no card on Groq.

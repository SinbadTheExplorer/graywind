# Johnny Cloud + Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Owner workflow applies: draft each task through the `delegate` skill first, Claude reviews and fixes, explains in plain language, and the owner approves before each commit.

**Goal:** Move Johnny's backend to a Contabo VPS that is reachable only over Tailscale, and close every hole in the design's §3. Per-user keys, scopes, caps and an audit log mean outside users can be added later without a rebuild.

**Architecture:** Three new focused modules sit in front of the existing call and answer paths:
- `keys.py`: who you are and what you may see
- `usage.py`: persistent spend caps and the audit log
- `guards.py`: input validation, call slots and the failed-key lockout

`auth.require_api_key` returns a `KeyRecord` instead of a string, and every route reads its scope from it. Deployment is rsync plus systemd plus `tailscale serve` on Ubuntu 24.04, with no public ports.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, sqlite3 (stdlib), pytest, systemd, ufw, Tailscale, ntfy.

**Spec:** `docs/superpowers/specs/2026-11-10-johnny-cloud-security-design.md`

## Global Constraints

- Deadline: **built Thu 11/12, done Sat 11/14**. Cut order if late: ntfy alerts, then the sync timer, then Task 6 (CSP). P0 items are never cut.
- Never commit `keys.json`, `usage.db`, `audit.log`, `env`, or any `.glb`/Kokoro model file. The repo is public.
- Never store a key in plaintext on the server, and never write a key or transcript to a log. Logs carry `key_id` only.
- The existing `MAVIS_API_KEY` env key keeps working as an `owner` key with id `owner-env`. The desktop avatar must not break.
- Clients never see exception text. Generic message: `"Johnny's line dropped. Try again."`
- Limits (env-overridable):

  | Env var | Default |
  |---|---|
  | `MAVIS_MAX_UTTERANCE_SECONDS` | 30 |
  | `MAVIS_WS_MAX_BYTES` | 1048576 |
  | `MAVIS_MAX_QUERY_CHARS` | 500 |
  | `max_chars` clamp | 50–600 |
  | `MAVIS_MAX_CALLS` | 2 global, 1 per key |
  | `MAVIS_CALL_MAX_SECONDS` | 900 |
  | `MAVIS_CALL_IDLE_SECONDS` | 120 |
  | lockout | 5 failures / 600 s → 600 s lock |

- Daily caps (UTC day, persisted):

  | Who | LLM calls | STT seconds |
  |---|---|---|
  | owner | 300 | 1800 |
  | guest | 50 | 300 |
  | global | 500 | 3600 |

  Env: `MAVIS_GLOBAL_DAILY_LLM`, `MAVIS_GLOBAL_DAILY_STT_SECONDS`.
- The server never imports panda3d, openwakeword, sounddevice or opencv. `requirements-server.txt` is the server's only dependency list.
- The VPS never holds Alpaca or any trading credential.

## Review Focus

1. **A WAV whose header lies about its size** (header says 1 s, payload is 1 MB). Duration must come from the actual byte count, so it's rejected. Test in Task 3.
2. **A guest asks about the owner's data without saying "Graywind"** ("what's pending?", "what am I holding?"). The guest must get no Graywind facts whatever the wording, because the scope removes the retrieval rather than keyword-filtering it. Test in Task 4.
3. **The cap is reached mid-answer.** The current answer finishes, and the *next* utterance gets the tapped-out line. The count never exceeds the cap by more than one turn. Test in Task 2/4.
4. **A server restart.** Daily counts and revocations survive, so a fresh process still refuses an over-cap key. Test in Task 2.
5. **The desktop avatar's old `/ask/stream` calls with the env key** still succeed with owner scope after Tasks 1–3. Test in Task 1.

---

### Task 1: Key store with scopes (`keys.py`) and `auth` returning a `KeyRecord`

**Files:**
- Create: `mavis/keys.py`
- Modify: `mavis/auth.py`
- Modify: `mavis/app.py` (routes use `rec.id` for rate limiting)
- Modify: `mavis/call_route.py` (`/johnny/check`, `/johnny/model.glb` take a `KeyRecord`)
- Test: `mavis/tests/test_keys.py`, update `mavis/tests/test_auth.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) KeyRecord(id: str, scope: Literal["owner","guest"], per_minute: int, per_day_llm: int, per_day_stt_seconds: int, revoked: bool = False)`
  - `auth.lookup(candidate) -> KeyRecord | None` (env key first, then `keys.lookup_file`), plus `auth.still_valid(rec)` re-checked per utterance; `keys.lookup_file`: compares the SHA-256 hex with `hmac.compare_digest` against every record. Returns `None` for unknown or revoked keys. The env `MAVIS_API_KEY` matches as `KeyRecord("owner-env", "owner", 20, 300, 1800)`.
  - `keys.add(key_id: str, scope: str) -> str`: returns the new key, `secrets.token_urlsafe(32)`. Stores the hash only and applies the scope's default caps.
  - `keys.revoke(key_id: str) -> None`
  - `keys.list_records() -> list[KeyRecord]`
  - The CLI is `python keys.py add <id> <owner|guest> | revoke <id> | list`.
  - The store path is `MAVIS_KEYS_FILE` (default `~/.mavis/keys.json`). The file is written chmod 600 via write-to-temp-then-rename. It's re-read whenever its modification time changes, so a revoke takes effect on the next request without a restart.
  - `auth.require_api_key(...) -> KeyRecord`: 401 for unknown or revoked keys; 500 if neither the env key nor the keys file exists.

- [ ] **Step 1: Write failing tests** in `test_keys.py`:
  - `test_add_returns_key_that_looks_up_with_scope`
  - `test_file_holds_hash_not_key` (the raw key string is not in the file bytes)
  - `test_revoked_key_fails_next_lookup_without_restart`
  - `test_env_key_is_owner_env_record`
  - `test_unknown_and_none_return_none`
  - `test_file_mode_is_600`

  In `test_auth.py`:
  - `test_require_api_key_returns_record`
  - `test_ask_stream_with_env_key_still_200` (Review Focus 5)

- [ ] **Step 2: Run** `cd mavis && .venv/bin/python -m pytest tests/test_keys.py tests/test_auth.py -q`. Expected: FAIL (no module `keys`).
- [ ] **Step 3: Implement** `keys.py`, then switch `auth.require_api_key` and the routes in `app.py` and `call_route.py` to `KeyRecord`. `check_rate_limit` is called with `rec.id` and `rec.per_minute`; add an optional `limit` parameter to `rate_limit.check_rate_limit`.
- [ ] **Step 4: Run** the full suite, `.venv/bin/python -m pytest -q`. Expected: all pass (406 + new).
- [ ] **Step 5: Commit** after owner approval: `feat(mavis): per-user keys with scopes, hashed at rest`.

### Task 2: Persistent daily caps and audit log (`usage.py`)

**Files:**
- Create: `mavis/usage.py`
- Test: `mavis/tests/test_usage.py`

**Interfaces:**
- Consumes: `KeyRecord` (Task 1).
- Produces:
  - `class CapExceeded(Exception)` with attribute `.which: Literal["key","global"]`
  - `usage.check(rec: KeyRecord, kind: Literal["llm","stt_seconds"], amount: float) -> None`: raises `CapExceeded` if adding `amount` would pass the key's or the global daily cap.
  - `usage.record(rec: KeyRecord, kind, amount: float) -> None`
  - `usage.today_totals(key_id: str | None = None) -> dict[str, float]`
  - `usage.audit(event: str, key_id: str | None, **fields) -> None`: appends one JSON line `{"ts": ISO-8601 UTC, "event", "key_id", ...fields}` to `MAVIS_AUDIT_LOG` (default `~/.mavis/audit.log`).
  - The database is `MAVIS_USAGE_DB` (default `~/.mavis/usage.db`), with table `usage(day TEXT, key_id TEXT, kind TEXT, amount REAL, PRIMARY KEY(day,key_id,kind))`. Add amounts with an upsert. The day is the UTC date.

- [ ] **Step 1: Write failing tests:**
  - `test_check_raises_key_cap_at_limit` (owner llm: 300 recorded → `check(...,1)` raises `.which=="key"`)
  - `test_global_cap_counts_all_keys`
  - `test_counts_survive_new_connection` (Review Focus 4: re-import or re-open the database and the totals are unchanged)
  - `test_new_utc_day_resets`, with the clock injected through a module-level `_today()` monkeypatched in tests
  - `test_audit_line_has_no_key_material` (the audit text doesn't contain the key)
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_usage.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `usage.py` with the stdlib `sqlite3`. Open a short-lived connection per call; the volume is tiny.
- [ ] **Step 4: Run** the full suite. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(mavis): persistent daily spend caps and audit log`.

### Task 3: Input guards, quiet errors, hidden discovery routes

**Files:**
- Create: `mavis/guards.py`
- Modify: `mavis/app.py`:
  - `AskRequest` gets `Field(max_length=MAX_QUERY_CHARS)`, and a validator clamps `max_chars` to 50–600.
  - `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`
  - `/status` returns `{"ok": True}` only.
  - Before each LLM call: `usage.check` + `usage.record(rec,"llm",1)`; a `CapExceeded` returns 429 `"Johnny's tapped out for today."`
  - `groq_answer` failures return 502 `"Johnny's line dropped. Try again."`, and the detail is logged.
- Modify: `mavis/providers.py`: the `HTTPException(502, f"Groq error: {resp.text}")` detail becomes generic; log `resp.text` to stderr.
- Test: `mavis/tests/test_guards.py`, extend `tests/test_app.py`

**Interfaces:**
- Produces:
  - `class BadAudio(ValueError)`
  - `guards.wav_seconds(data: bytes, max_seconds: float = MAX_UTTERANCE_SECONDS) -> float`. It parses the RIFF chunks itself and accepts only PCM format 1, 1 channel, 16000 Hz, 16-bit. Duration is `len(actual data chunk bytes present) / 32000`, never the header's size field. Raise `BadAudio` on anything else, or if the result is over `max_seconds` or 0.
  - `guards.GENERIC_ERROR = "Johnny's line dropped. Try again."`
  - `guards.TAPPED_OUT = "I'm tapped out for today, choom. Call me tomorrow."`

- [ ] **Step 1: Write failing tests:**
  - `test_valid_16k_mono_wav_seconds` (1.0 s of silence → 1.0)
  - `test_rejects_stereo`, `test_rejects_44k`, `test_rejects_not_riff`, `test_rejects_over_30s`
  - `test_lying_header_uses_real_bytes` (Review Focus 1: header data size 32000 but 1 MB of data actually present → `BadAudio` for over 30 s)
  - `test_ask_rejects_501_char_query_422`
  - `test_max_chars_clamped_to_600`
  - `test_docs_and_openapi_404`
  - `test_status_has_only_ok`
  - `test_groq_error_body_not_in_response`
  - `test_ask_over_cap_429_and_no_groq_call` (Groq monkeypatched to fail the test if called)
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_guards.py tests/test_app.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `guards.py` and the `app.py`/`providers.py` changes.
- [ ] **Step 4: Run** the full suite. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(mavis): input limits, quiet errors, no discovery routes`.

### Task 4: Harden the call path (scope, caps, slots, timeouts, origin, model by scope)

**Files:**
- Modify: `mavis/app.py`:
  - `_answer_events(query, max_chars, scope="owner")`. When `scope != "owner"`, skip `graywind_grounding.retrieve` entirely (empty hits). If `names_project_internals(query)`, return `UNGROUNDED`.
  - `/ask` and `/ask/stream` pass `rec.scope`.
- Modify: `mavis/call_route.py`:
  - `hello` → `auth.lookup`.
  - Origin check: when the `Origin` header is present and its host differs from `Host`, close 4403.
  - Slots: `guards.CallSlots.acquire(rec.id)`. When busy, send `{"type":"error","message":"Johnny's on another call."}` and close 4429.
  - `_call_transcribe`: `wav_seconds` → `usage.check(rec,"stt_seconds",secs)` → `check_rate_limit` → STT → `usage.record`.
  - Answer: `usage.check/record(rec,"llm",1)`. `CapExceeded` → `call.AnswerError(TAPPED_OUT)`, and `usage.audit("cap_hit", ...)`.
  - Audit `call_start`, `call_end` (with `seconds`) and `utterance` (with `seconds`).
  - `/johnny/model.glb`: an owner gets `MODEL`. A guest gets `MAVIS_PUBLIC_MODEL` if it is set and exists, **403 if the path requested is the Keanu model**, otherwise 404.
- Modify: `mavis/call.py`:
  - `CallDeps` gets `max_seconds: float = 900`, `idle_seconds: float = 120`.
  - `run_call` sends `{"type":"bye","reason":"time"}` and returns when either limit passes. The idle clock resets on each received utterance.
  - Every client-bound error message becomes `GENERIC_ERROR`, except `AnswerError` messages, which are deliberate copy. Details go to `deps.log`.
- Modify: `mavis/guards.py`: `class CallSlots(max_total: int, max_per_key: int = 1)` with `acquire(key_id) -> bool` and `release(key_id) -> None`. It's process-wide; the module instance is `SLOTS`.
- Modify: uvicorn launch (`scripts/mavis-backend.sh` and the Task 8 systemd unit): `--ws-max-size ${MAVIS_WS_MAX_BYTES:-1048576}`.
- Test: extend `tests/test_call.py` and `tests/test_call_route.py`

- [ ] **Step 1: Write failing tests:**
  - `test_guest_never_gets_graywind_context` (Review Focus 2: "what's pending?" and "what am I holding?" with guest scope → `graywind_grounding.retrieve` is never called, monkeypatched to raise)
  - `test_guest_model_403_owner_200`
  - `test_bad_origin_closed_4403`
  - `test_second_concurrent_call_same_key_4429`
  - `test_oversized_wav_no_stt_call`
  - `test_non_wav_no_stt_call`
  - `test_over_stt_cap_no_stt_call_and_tapped_out_error`
  - `test_cap_hit_mid_answer_finishes_then_refuses_next` (Review Focus 3)
  - `test_call_ends_after_idle_seconds`
  - `test_call_ends_after_max_seconds` (fake clock)
  - `test_internal_exception_text_not_sent_to_client`
  - `test_revoked_key_hello_4401`
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_call.py tests/test_call_route.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** The slot release goes in a `finally` around `run_call`.
- [ ] **Step 4: Run** the full suite, plus a live probe: uvicorn on :8765 with a throwaway key, then a `websockets` client sends a 2 MB message (expect the connection closed by the size limit) and a valid 2 s WAV (expect `heard`). Check that `audit.log` shows the events.
- [ ] **Step 5: Commit**: `feat(mavis): call path scopes, caps, slots, timeouts and origin check`.

### Task 5: Failed-key lockout

**Files:**
- Modify: `mavis/guards.py`
- Modify: `mavis/auth.py` (`require_api_key` takes a `Request`)
- Modify: `mavis/call_route.py` (hello path)
- Test: `mavis/tests/test_guards.py`, `tests/test_call_route.py`

**Interfaces:**
- Produces:
  - `guards.identity(headers: Mapping[str,str], client_host: str | None) -> str`: returns `"ts:" + Tailscale-User-Login` if present, else `"ip:" + client_host`.
  - `guards.LOCKOUT.locked(ident) -> bool` and `guards.LOCKOUT.fail(ident) -> bool`, which returns True when this failure triggers a lock. The policy is 5 failures in 600 s → locked for 600 s.
  - While locked, every attempt returns 429 (HTTP) or close 4429 (WS) **without checking the key**. A trigger writes `usage.audit("lockout", None, ident=...)` and calls `alerts.notify` (Task 7; a no-op until then).

- [ ] **Step 1: Write failing tests:**
  - `test_five_failures_lock_identity`
  - `test_locked_identity_rejected_even_with_right_key`
  - `test_lock_expires_after_600s` (fake clock)
  - `test_identity_prefers_tailscale_header`
  - `test_ws_hello_failures_count`
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full suite. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(mavis): lock out repeated wrong-key attempts`.

### Task 6: Page hardening (CSP and security headers)

**Files:**
- Create: `mavis/web/call.js` (the body of the current `<script type="module">`, moved)
- Create: `mavis/web/worklet.js` (the `WORKLET` string, moved; the page loads it with `audioWorklet.addModule('/johnny/worklet.js')`)
- Modify: `mavis/web/call.html` (`<script type="module" src="/johnny/call.js">`; the importmap is replaced by relative imports of `/johnny/vendor/three/...` inside `call.js`)
- Modify: `mavis/call_route.py`: serve `call.js` and `worklet.js` with `Cache-Control: no-cache`, plus a middleware adding headers on `/johnny*`:
  - `Content-Security-Policy: default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: no-referrer`
  - `Permissions-Policy: microphone=(self), camera=(), geolocation=()`
- Test: `tests/test_call_route.py`

- [ ] **Step 1: Write failing tests:**
  - `test_johnny_page_has_csp_and_headers`
  - `test_page_has_no_inline_script` (no `<script>` tag without `src` in `call.html`)
  - `test_call_js_and_worklet_served`
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** the move. Keep `window.__johnny` debug hooks working.
- [ ] **Step 4: Verify** with the full suite, then the `headless-chrome-verification` skill at 390×844:
  - no CSP violations in the console
  - `__johnny.modelLoaded === true`
  - a fed-frames call reaches `heard`

  Also check that `connect-src 'self'` allows `wss:` same-origin in Chrome. If Safari later blocks it, add the explicit `wss://<host>`.
- [ ] **Step 5: Commit**: `feat(mavis): strict CSP, no inline script on the call page`.

### Task 7: Alerts (ntfy)

**Files:**
- Create: `mavis/alerts.py`
- Modify: the `cap_hit` and `lockout` sites from Tasks 4–5
- Test: `mavis/tests/test_alerts.py`

**Interfaces:**
- Produces: `alerts.notify(title: str, message: str, dedupe: str) -> None`.
  - It POSTs to `https://ntfy.sh/$MAVIS_NTFY_TOPIC` in a background thread with a 5 s timeout.
  - At most once per `dedupe` key per UTC day, tracked in `usage.db` table `alerts(day, dedupe)`.
  - It's a no-op if the topic is unset, and it never raises.

- [ ] **Step 1: Write failing tests:**
  - `test_notify_posts_once_per_day_per_dedupe` (the httpx call is monkeypatched)
  - `test_notify_noop_without_topic`
  - `test_notify_swallows_network_error`
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement**, and wire it to `cap_hit` (dedupe `cap:<which>`) and `lockout` (dedupe `lockout:<ident>`).
- [ ] **Step 4: Run** the full suite. Expected: PASS.
- [ ] **Step 5: Commit**: `feat(mavis): ntfy alerts on cap hits and lockouts`.

### Task 8: Fresh Graywind data and the server deploy kit

**Files:**
- Modify: `mavis/scripts/extract_graywind_grounding.py`: `main(argv)` accepts `--repo PATH` (default: the current `REPO_ROOT`) and `--out PATH`.
- Modify: `mavis/graywind_grounding.py`: `_facts()` reloads the JSON when its modification time changes (replacing the import-time load). A bad or partial file keeps the last good facts and logs once.
- Create: `mavis/requirements-server.txt`: fastapi, uvicorn[standard], httpx, numpy, scipy and kokoro-onnx, pinned to the versions in `requirements.txt` or the current venv. Plus `onnxruntime` if kokoro-onnx doesn't pull it in.
- Create `deploy/` with:

  | File | Contents |
  |---|---|
  | `mavis.service` | User=mavis, `WorkingDirectory=/opt/mavis/mavis`, `EnvironmentFile=/var/lib/mavis/env`, `ExecStart=.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --ws-max-size 1048576`, `Restart=on-failure`, `NoNewPrivileges=yes`, `ProtectSystem=strict`, `StateDirectory=mavis` (= `/var/lib/mavis`), `ProtectHome=yes`, `ReadWritePaths=/opt/mavis/mavis/data`, env sets `MAVIS_KEYS_FILE`/`MAVIS_USAGE_DB`/`MAVIS_AUDIT_LOG` under `/var/lib/mavis`, `PrivateTmp=yes`, `MemoryMax=3G`, `OnFailure=mavis-alert@%n.service` |
  | `mavis-alert@.service` | sends an ntfy alert on unit failure |
  | `graywind-sync.service` + `graywind-sync.timer` | every 15 min: `git -C /opt/graywind-state fetch --depth 1 origin main && git reset --hard origin/main`, then run the extractor with `--repo /opt/graywind-state --out /opt/mavis/mavis/data/graywind_grounding.json`. Three consecutive failures send an alert. |
  | `bootstrap.sh` | run once as root over SSH; idempotent; see the list below |
  | `deploy.sh` | runs on the Mac. rsyncs the repo's `mavis/` to `/opt/mavis/mavis` (excluding `.venv`, `__pycache__`, `tests`, `assets/avatar/*.glb`), scps `keanu-web.glb` and the `~/.mavis/models/` Kokoro files once, installs `requirements-server.txt` into the venv, and restarts the service |
  | `tailnet-acl.hujson` | ACL snippet: `tag:johnny` owned by the owner; owner devices → `tag:johnny:443,22`; **no rule lets `tag:johnny` reach anything** |

  `bootstrap.sh` does the following:
  - `apt install python3.12-venv espeak-ng ufw unattended-upgrades git rsync`
  - creates user `mavis`
  - `ufw default deny incoming; ufw allow in on tailscale0; ufw enable`
  - sshd: `PasswordAuthentication no`, `PermitRootLogin prohibit-password`, `ListenAddress <tailscale IP>` (applied only after Tailscale is up, so the session isn't locked out)
  - installs Tailscale, `tailscale up --advertise-tags=tag:johnny --ssh=false`
  - `tailscale serve --bg 8000`
  - `dpkg-reconfigure -f noninteractive unattended-upgrades`
- Test: extend `tests/test_extract_graywind_grounding.py` and `tests/test_graywind_grounding.py`

- [ ] **Step 1: Write failing tests:**
  - `test_extractor_honours_repo_and_out_args`
  - `test_facts_reload_on_mtime_change`
  - `test_corrupt_file_keeps_last_good_facts`
  - `test_requirements_server_has_no_desktop_deps` (no panda3d, openwakeword, sounddevice or opencv)
  - `test_server_imports_without_desktop_deps` (a subprocess import of `app` with those modules blocked through a `sys.meta_path` finder succeeds)
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Run `bash -n` and `shellcheck` (if installed) on every script.
- [ ] **Step 4: Run** the full suite. If Docker is available, also run `docker run --rm -v $PWD/mavis:/m ubuntu:24.04` to install `requirements-server.txt` and import `app`. Otherwise, this check moves to Task 9 on the real VPS.
- [ ] **Step 5: Commit**: `feat(mavis): server deploy kit and live Graywind snapshot`.

### Task 9: Provision, cut over, verify the done criteria (owner steps interleaved)

- [ ] **Step 1 (owner):** finish the Tailscale login on the Mac. Buy the smallest Contabo Cloud VPS with Ubuntu 24.04, pasting `~/.ssh/johnny_vps.pub` at checkout. Send Claude the public IP. Set a Groq spend limit if the tier allows one. Paste `deploy/tailnet-acl.hujson` into the Tailscale admin.
- [ ] **Step 2:** `ssh -i ~/.ssh/johnny_vps root@<ip> 'bash -s' < deploy/bootstrap.sh`. The owner approves the Tailscale auth link it prints.
- [ ] **Step 3:** run `deploy/deploy.sh`, write `/var/lib/mavis/env` (chmod 600, with the Groq key, the env owner key, `MAVIS_CALL_WARM=1` and the ntfy topic), and start the service and the timer.
- [ ] **Step 4: verify criterion 1.**
  - From the Mac with Tailscale **off**: `nmap -Pn -p- <public ip>` shows 0 open ports.
  - The owner calls `https://<vps>.<tailnet>.ts.net/johnny` from the phone with the Mac lid closed.
- [ ] **Step 5: verify criterion 2.** Run the abuse probe script, saved in the scratchpad (not committed), against the VPS:
  - no key
  - wrong key
  - a 2 MB message
  - non-WAV bytes
  - a 35 s WAV
  - 6 bad keys (expect a lockout)
  - an over-cap guest, after temporarily setting its cap to 1

  `audit.log` must show zero Groq requests for all of them. Then `systemctl restart mavis` and confirm the over-cap guest is still refused.
- [ ] **Step 6: verify criterion 3.**
  - `keys.py add tester guest`: the guest's model fetch gets 403.
  - Ask "what's pending in Graywind?" over `/ask/stream` with the guest key: the reply is the refusal line.
  - `keys.py revoke tester`: the next request gets 401.
- [ ] **Step 7: verify criterion 4.** The owner places 10 calls. Compute the median of the `call: first audio N ms` lines from `journalctl -u mavis`; it must be 3000 ms or less. If Contabo's CPU is too slow for Kokoro, report the numbers. Don't quietly change voices.
- [ ] **Step 8: cut over the Mac.** Run `launchctl bootout gui/$(id -u)/com.mavis.backend`, remove `MAVIS_CALL_WARM=1` from `~/.mavis/env`, and run `tailscale serve reset` on the Mac.
- [ ] **Step 9:** update the call-mode handoff with the VPS URL and the results, and update memory. Push only if the owner says so.

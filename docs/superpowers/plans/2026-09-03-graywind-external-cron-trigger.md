# External Cron Trigger for Graywind Live Trading

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple the live trading cycle's trigger from GitHub Actions' own `schedule:` event, which was empirically confirmed to have collapsed from ~11 firings/day to 1-3/day starting 2026-08-26 (individual runs still complete in ~60-90s, ruling out a workflow-side backlog — this is GitHub silently not creating the scheduled run, matching GitHub's own documented "scheduled workflows may be delayed... high load times include the start of every hour" behavior).

**Architecture:** A Cloudflare Worker (`cron-trigger/`) with its own Cron Trigger — a separate, more reliable scheduling primitive than GitHub Actions' `schedule:` event — calls GitHub's `workflow_dispatch` REST endpoint for `live-trading.yml` on the same market-hours cadence. `workflow_dispatch` is a plain synchronous REST call, not subject to the delay/drop behavior GitHub documents specifically for the `schedule:` event type, so this only requires Cloudflare's own cron to be reliable (it's core scheduled-compute infra there, not a bolted-on git feature).

**Tech Stack:** Cloudflare Workers (free tier — Cron Triggers included), `wrangler` CLI, vanilla JS (no framework, no dependencies beyond `wrangler` itself).

**Spec:** No separate spec doc — this plan's own "Architecture" section is the full design; it was settled in conversation, not written up separately, same precedent as other small Graywind decisions that skip a dedicated spec (see `graywind-tactical-diversification-handoff.md`'s "Authorities" section for that precedent).

## Global Constraints

- No secret value (Cloudflare API token, GitHub PAT) may ever be typed into a Claude Code session — every command that touches a real credential value must be run by the owner directly in their own terminal, outside this tool. This applies to every step below marked **(run this yourself)**.
- The Worker must not gain any permission beyond what it needs: `Account > Workers Scripts > Edit` on the Cloudflare side, `Actions: Read and write` scoped to the `graywind` repo only on the GitHub side. No KV, no zone/route permissions, no repo-wide GitHub scope.
- This is additive infrastructure — it must not modify `live_loop.py`, `tier_config.py`, or any other trading-logic file. It only decides *when* the existing workflow runs.
- Leave `live-trading.yml`'s own `schedule:` trigger in place as a redundant fallback until the Worker's reliability is confirmed over real market days — removing it is a separate, later decision requiring the owner's sign-off, not part of this plan.

---

### Task 1: Cloudflare Worker that dispatches the live-trading workflow on schedule

**Files:**
- Create: `cron-trigger/wrangler.toml` — Worker config, cron trigger, non-secret vars (owner/repo/workflow filename)
- Create: `cron-trigger/src/index.js` — `scheduled()` handler (the real trigger) + a `fetch()` GET handler for manual on-demand testing
- Create: `cron-trigger/package.json` — `wrangler` devDependency, `deploy`/`dev` scripts

**Interfaces:**
- Consumes: three Worker environment bindings — `env.GITHUB_OWNER`, `env.GITHUB_REPO`, `env.GITHUB_WORKFLOW_FILE` (all non-secret, set in `wrangler.toml`'s `[vars]`) and `env.GITHUB_PAT` (secret, set via `wrangler secret put`, never committed).
- Produces: `triggerGraywindCycle(env)` → `{ ok, status, bodyText }`, called from both `scheduled()` and the manual `fetch()` GET handler.

- [x] **Step 1: Write `wrangler.toml`** — done this session. Cron set to `*/15 13-20 * * 1-5` (full cadence restored, since Cloudflare's own Cron Triggers don't share GitHub Actions' documented `schedule:`-event reliability problem).

- [x] **Step 2: Write `src/index.js`** — done this session. `scheduled()` calls `triggerGraywindCycle` via `ctx.waitUntil()`; the `fetch()` GET handler exposes the same call at the Worker's `*.workers.dev` URL for on-demand manual testing without waiting for the next cron tick.

- [x] **Step 3: Write `package.json`** — done this session, `wrangler` pinned as a devDependency.

- [ ] **Step 4: Install dependencies**

Run: `cd cron-trigger && npm install`

Expected: `node_modules/.bin/wrangler` exists; `npx wrangler --version` prints a version.

- [ ] **Step 5: Authenticate wrangler (run this yourself, in your own terminal — not through Claude Code)**

Either:
```bash
cd cron-trigger
npx wrangler login
```
(opens a browser OAuth flow — approve it there), or, if you generated a Cloudflare API token instead (scoped to `Account > Workers Scripts > Edit` only, per the earlier permission spec):
```bash
export CLOUDFLARE_API_TOKEN="<paste the token here, in your own terminal>"
```

Expected: `npx wrangler whoami` (safe to run either way, prints no secret) shows your Cloudflare account.

- [ ] **Step 6: Deploy the Worker (run this yourself)**

```bash
cd cron-trigger
npx wrangler deploy
```

Expected: output includes a `*.workers.dev` URL and confirms the cron trigger (`*/15 13-20 * * 1-5`) is attached.

- [ ] **Step 7: Set the GitHub PAT secret (run this yourself — this is the one step where a real credential value must never appear in a Claude Code session)**

```bash
cd cron-trigger
npx wrangler secret put GITHUB_PAT
```

This prompts interactively for the value — paste the fine-grained PAT (repo: `graywind` only, `Actions: Read and write`, per the earlier permission spec) there, not anywhere in a Claude Code conversation.

- [ ] **Step 8: Manually verify the trigger actually fires a workflow run**

Hit the Worker's `*.workers.dev` URL from Step 6 with a plain GET (browser, or `curl <url>` — this one is safe to run through Claude Code, it contains no secret). Expected response body: `dispatched`.

Then check GitHub Actions run history for `live-trading.yml` and confirm a new run appears with `"event": "workflow_dispatch"` within a minute or two:

```bash
curl -s "https://api.github.com/repos/SinbadTheExplorer/graywind/actions/workflows/334898521/runs?per_page=3&event=workflow_dispatch" | python3 -c "
import json,sys
d = json.load(sys.stdin)
for r in d['workflow_runs']:
    print(r['run_number'], r['status'], r['conclusion'], r['created_at'])
"
```

Expected: the newest run's `created_at` is within ~2 minutes of when the GET was sent.

- [ ] **Step 9: Commit the Worker source (not secrets — nothing in this diff is a credential)**

```bash
git add cron-trigger/wrangler.toml cron-trigger/src/index.js cron-trigger/package.json
git commit -m "$(cat <<'EOF'
Add Cloudflare Worker cron trigger for live-trading.yml

GitHub Actions' own schedule: event was empirically confirmed to have
collapsed from ~11 firings/day to 1-3/day since 2026-08-26 (individual
runs still complete in ~60-90s, so it's not a workflow-side backlog --
GitHub is silently not creating the scheduled run, matching its own
documented high-load delay/drop behavior for frequent schedules).
workflow_dispatch is a plain REST call, not subject to that same
behavior, so triggering it from Cloudflare's own Cron Triggers (a more
reliable scheduling primitive) restores the intended cadence without
touching any trading logic.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014zxa4aam7zKTRUR3GCUGkr
EOF
)"
```

- [ ] **Step 10: Monitor for a real market week, then decide on `live-trading.yml`'s own `schedule:` trigger**

After ~1 week of real market days, re-run the same day-by-day run-count check used to diagnose the original problem (group `workflow_runs` by day and event type) and confirm the Worker-triggered cadence is actually landing close to every 15 minutes. Only once that's confirmed should removing the now-redundant `schedule:` trigger in `live-trading.yml` be considered — a separate, later decision, not part of this plan.

---

## Self-Review Notes

- **Spec coverage:** The "Architecture" section's one deliverable (Worker calls `workflow_dispatch` on a Cloudflare-native schedule) is fully covered by Task 1; there's no second subsystem.
- **Placeholder scan:** No TBD/TODO. Steps 1-3 are already complete (code written this session); steps 4-10 are concrete commands with expected output stated, not vague instructions.
- **Type consistency:** `triggerGraywindCycle(env)`'s return shape (`{ ok, status, bodyText }`) is used identically by both callers (`scheduled()` and the `fetch()` GET handler) in the one file that defines it.

## Explicitly out of scope for this plan

- Removing `live-trading.yml`'s own `schedule:` trigger — deliberately deferred to Step 10, after real-world confirmation.
- Any change to `live_loop.py` or trading logic — this plan only changes *when* the existing workflow is invoked, never what it does.
- The staggered/widened `*/15` → `7,37 13-20 * * 1-5` change to `live-trading.yml` itself — that was a separate, already-applied mitigation (see that file's top-of-file comment), independent of and prior to this plan.

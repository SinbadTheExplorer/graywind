#!/bin/bash
# Ship Johnny to the VPS from the Mac, over the tailnet. Safe to re-run.
#
#     deploy/deploy.sh                 # host "johnny" (MagicDNS)
#     JOHNNY_HOST=100.x.y.z deploy/deploy.sh
#
# Sends only what is committed at HEAD (plus the generated canned voice
# lines), so nothing local-only -- keys.json, usage.db, env files, other
# models, half-finished edits -- can ride along. Files deleted from git are
# deleted on the server. The first run also creates the server's env file from the
# two keys it needs in ~/.mavis/env; values are piped, never printed.
set -euo pipefail

HOST="${JOHNNY_HOST:-johnny}"
SSH="ssh -o BatchMode=yes root@$HOST"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS="${MAVIS_MODEL_DIR:-$HOME/.mavis/models}"
cd "$ROOT"

say() { printf '\n== %s\n' "$*"; }

say "Code (committed files at HEAD, tests left behind) and canned voice lines"
if [ -n "$(git status --porcelain -- mavis deploy ':!mavis/tests')" ]; then
    echo "note: uncommitted changes in mavis/ or deploy/ are NOT deployed (HEAD only)"
fi
STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
git archive HEAD mavis deploy ':(exclude)mavis/tests' | tar -xf - -C "$STAGE"
mkdir -p "$STAGE/mavis/assets"
cp -R mavis/assets/voice-kokoro "$STAGE/mavis/assets/"
# Unpacked to a staging folder, then mirrored with --delete, so a file
# removed from git is removed from the server too. The venv is kept.
COPYFILE_DISABLE=1 tar -czf - -C "$STAGE" mavis deploy |
    $SSH 'set -e; rm -rf /opt/mavis/.stage; mkdir -p /opt/mavis/.stage
          tar -xzf - -C /opt/mavis/.stage --no-same-owner --no-same-permissions
          rsync -a --delete --exclude=/.venv/ /opt/mavis/.stage/mavis/ /opt/mavis/mavis/
          rsync -a --delete /opt/mavis/.stage/deploy/ /opt/mavis/deploy/
          rm -rf /opt/mavis/.stage
          chown -R root:root /opt/mavis/mavis /opt/mavis/deploy
          chmod -R u=rwX,go=rX /opt/mavis/deploy
          find /opt/mavis/mavis -path /opt/mavis/mavis/.venv -prune -o -exec chmod u=rwX,go=rX {} +
          chmod 755 /opt/mavis/deploy/*.sh'

say "Voice model and Keanu (sent only when the size differs; service-readable only)"
for f in "$MODELS/kokoro-v1.0.onnx" "$MODELS/voices-v1.0.bin" mavis/assets/avatar/keanu-web.glb; do
    name=$(basename "$f")
    local_size=$(stat -f %z "$f")
    remote_size=$($SSH "stat -c %s /opt/mavis/models/$name 2>/dev/null || echo 0")
    if [ "$local_size" != "$remote_size" ]; then
        echo "sending $name ($((local_size / 1048576)) MB)"
        scp -q "$f" "root@$HOST:/opt/mavis/models/$name.part"
        $SSH "mv /opt/mavis/models/$name.part /opt/mavis/models/$name"
    fi
done
$SSH 'chown root:mavis /opt/mavis/models/*; chmod 640 /opt/mavis/models/*'

say "Server env files"
if $SSH test -s /var/lib/mavis/env; then
    echo "env exists, left as is (edit on the server: /var/lib/mavis/env)"
else
    {
        grep -E '^(export )?(GROQ_API_KEY|MAVIS_API_KEY)=' "$HOME/.mavis/env" | sed 's/^export //'
        if [ -n "${JOHNNY_NTFY_TOPIC:-}" ]; then echo "MAVIS_NTFY_TOPIC=$JOHNNY_NTFY_TOPIC"; fi
    } | $SSH 'set -e; f=/var/lib/mavis/env
              install -m 600 -o mavis -g mavis /dev/stdin "$f.new"
              for k in GROQ_API_KEY MAVIS_API_KEY; do
                  [ "$(grep -c "^$k=." "$f.new")" = 1 ] || { rm -f "$f.new"; echo "need exactly one $k" >&2; exit 1; }
              done
              mv "$f.new" "$f"' ||
        { echo "env not created: ~/.mavis/env needs one GROQ_API_KEY and one MAVIS_API_KEY line" >&2; exit 1; }
    echo "env created with GROQ_API_KEY, MAVIS_API_KEY${JOHNNY_NTFY_TOPIC:+, MAVIS_NTFY_TOPIC}"
fi
# The alert-only copy for graywind-sync and mavis-alert@: just the topic.
$SSH 'set -e; grep -E "^MAVIS_NTFY_TOPIC=" /var/lib/mavis/env > /var/lib/mavis/alert.env.new || true
      chown mavis:mavis /var/lib/mavis/alert.env.new; chmod 600 /var/lib/mavis/alert.env.new
      mv /var/lib/mavis/alert.env.new /var/lib/mavis/alert.env'

say "Python packages"
$SSH 'set -e; cd /opt/mavis/mavis
      [ -x .venv/bin/python ] || python3 -m venv .venv
      .venv/bin/pip install -q --upgrade pip
      .venv/bin/pip install -q -r requirements-server.txt'

say "Services"
$SSH 'set -e
      install -m 644 /opt/mavis/deploy/mavis.service /opt/mavis/deploy/mavis-alert@.service \
          /opt/mavis/deploy/graywind-sync.service /opt/mavis/deploy/graywind-sync.timer \
          /etc/systemd/system/
      systemctl daemon-reload
      systemctl enable --now graywind-sync.timer >/dev/null
      systemctl start graywind-sync.service || echo "graywind-sync failed; see journalctl -u graywind-sync"
      systemctl enable mavis.service >/dev/null
      systemctl restart mavis.service'

say "Health"
for _ in $(seq 1 60); do
    if $SSH 'curl -fsS -m 2 http://127.0.0.1:8000/status' 2>/dev/null; then
        echo; $SSH 'tailscale serve status'; exit 0
    fi
    sleep 2
done
echo "mavis did not come up; see: ssh root@$HOST journalctl -u mavis -n 50" >&2
exit 1

#!/bin/bash
# One-time (and safe to re-run) hardening of the Johnny VPS. Run as root,
# over the TAILNET, never the public IP:
#
#     ssh root@johnny 'bash -s' < deploy/bootstrap.sh
#
# After this the public internet sees no open port at all: the firewall
# admits traffic only on tailscale0, so SSH and Johnny are reachable only
# from your own tailnet devices. If Tailscale ever breaks, use Contabo's
# web VNC console (root password) to get back in.
set -euo pipefail

say() { printf '\n== %s\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }

say "Checking Tailscale is up (the firewall step below depends on it)"
command -v tailscale >/dev/null || { echo "install Tailscale first: curl -fsSL https://tailscale.com/install.sh | sh" >&2; exit 1; }
TS_IP=$(tailscale ip -4 2>/dev/null | head -n1)
[ -n "$TS_IP" ] || { echo "tailscale is not up: run 'tailscale up' first" >&2; exit 1; }
# Lock-out guard: refuse if this session did not come in over the tailnet.
SSH_DEST=$(awk '{print $3}' <<<"${SSH_CONNECTION:-}")
if [ -n "$SSH_DEST" ] && [ "$SSH_DEST" != "$TS_IP" ] && [ "${I_HAVE_CONSOLE:-}" != 1 ]; then
    echo "You are connected via $SSH_DEST, not the tailnet ($TS_IP)." >&2
    echo "Reconnect with: ssh root@$TS_IP   (or set I_HAVE_CONSOLE=1)" >&2
    exit 1
fi

say "Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip espeak-ng ufw unattended-upgrades \
    git rsync curl ca-certificates >/dev/null

say "Service user and folders"
id mavis >/dev/null 2>&1 || useradd --system --home-dir /var/lib/mavis --no-create-home \
    --shell /usr/sbin/nologin mavis
install -d -m 755 -o root -g root /opt/mavis /opt/mavis/mavis /opt/mavis/deploy
install -d -m 750 -o root -g mavis /opt/mavis/models      # Keanu: not world-readable
install -d -m 700 -o mavis -g mavis /var/lib/mavis

say "Firewall: nothing in from the internet, everything in from the tailnet"
ufw --force delete allow OpenSSH >/dev/null 2>&1 || true
ufw --force delete allow 22/tcp >/dev/null 2>&1 || true
ufw --force delete allow 22 >/dev/null 2>&1 || true
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow in on tailscale0 comment 'tailnet only' >/dev/null
ufw --force enable >/dev/null
ufw status verbose

say "SSH: keys only"
# 00- so it wins: sshd keeps the FIRST value it reads, and cloud images ship
# a 50-cloud-init.conf that may turn passwords back on.
cat > /etc/ssh/sshd_config.d/00-mavis.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PermitEmptyPasswords no
X11Forwarding no
MaxAuthTries 3
CONF
sshd -t
systemctl reload ssh 2>/dev/null || systemctl reload sshd

say "Automatic security updates (reboots at 09:30 UTC only if a patch needs it)"
cat > /etc/apt/apt.conf.d/52mavis-unattended <<'CONF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "09:30";
CONF
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
systemctl enable --now unattended-upgrades >/dev/null

say "Tailscale serve: https://<this machine>.<tailnet>.ts.net -> 127.0.0.1:8000"
tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale serve status

say "Done. Next, from the Mac: deploy/deploy.sh"

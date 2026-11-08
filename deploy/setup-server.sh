#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 server. Run by deploy/setup.sh, which prepends the variables:
#   FW_HOST (this server), FW_HTTPS_PORT, FW_SITE (the Vercel address), OPENROUTER_API_KEY
set -euo pipefail

# No service restarts after installs: one of them may be the SSH tunnel this script runs through.
apt="sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get"
$apt update -q
$apt install -yq python3-venv python3-dev build-essential rsync curl gpg debian-keyring debian-archive-keyring apt-transport-https
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  $apt update -q && $apt install -yq caddy
fi

# Oracle's Ubuntu images reject everything but SSH in the server's own firewall, on top of the cloud one.
if ! sudo iptables -C INPUT -p tcp -m multiport --dports 80,443,8443 -j ACCEPT 2>/dev/null; then
  sudo iptables -I INPUT 1 -p tcp -m multiport --dports 80,443,8443 -j ACCEPT
  if command -v netfilter-persistent >/dev/null; then sudo netfilter-persistent save; fi
fi

# Headroom for the spread forecast's numpy work; the backend alone uses about 800 MB.
if [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

sudo mkdir -p /srv/firewatch/backend/data/cache /etc/firewatch
sudo chown -R ubuntu:ubuntu /srv/firewatch

# Text-message links and the Twilio signature check use the Vercel address, which is what people and Twilio see.
# Caddy only lets the Vercel site in, so the visitor IP it forwards can be trusted for the rate limits.
if [ ! -f /srv/firewatch/.env ]; then
  cat > /srv/firewatch/.env <<EOF
MODE=sample
API_TOKEN=$(openssl rand -hex 24)
MESH_GATEWAY=off
SENSOR_SIM=true
PUBLIC_BASE_URL=$FW_SITE
FORWARDED_IP_HEADER=x-firewatch-client-ip
OPENROUTER_API_KEY=$OPENROUTER_API_KEY
EOF
  chmod 600 /srv/firewatch/.env
fi

if [ ! -f /etc/firewatch/caddy.env ]; then
  sudo tee /etc/firewatch/caddy.env >/dev/null <<EOF
FW_HOST=$FW_HOST
FW_BACKEND=127.0.0.1:8000
FW_HTTPS_PORT=$FW_HTTPS_PORT
FW_PROXY_SECRET=$(openssl rand -hex 32)
EOF
  sudo chmod 640 /etc/firewatch/caddy.env && sudo chown root:caddy /etc/firewatch/caddy.env
fi

sudo mkdir -p /etc/systemd/system/caddy.service.d
printf '[Service]\nEnvironmentFile=/etc/firewatch/caddy.env\n' | sudo tee /etc/systemd/system/caddy.service.d/firewatch.conf >/dev/null
sudo systemctl daemon-reload
echo "server ready"

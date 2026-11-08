#!/usr/bin/env bash
# Push the backend to the API server and restart it. The pages go to Vercel with deploy/vercel-deploy.sh.
#   deploy/deploy.sh ubuntu@<host>        (FW_SSH_KEY=path/to/key to pick the SSH key)
set -euo pipefail
target=${1:?usage: deploy/deploy.sh ubuntu@host}
repo=$(cd "$(dirname "$0")/.." && pwd)
ssh_cmd="ssh -o StrictHostKeyChecking=accept-new ${FW_SSH_KEY:+-i $FW_SSH_KEY}"

# --delete keeps the code in step with this checkout; excluded paths (the server's .env, database, venv and
# tile cache) are never deleted.
rsync -az --delete -e "$ssh_cmd" --exclude-from="$repo/deploy/rsync-exclude" "$repo/" "$target:/srv/firewatch/"
# Map and fuel tiles the spread forecast reads; copying them means no forecast waits on a download. A checkout
# without them (GitHub Actions) leaves the server's copy alone.
if [ -d "$repo/backend/data/cache" ]; then
  rsync -az -e "$ssh_cmd" "$repo/backend/data/cache/" "$target:/srv/firewatch/backend/data/cache/"
fi

$ssh_cmd "$target" 'bash -s' <<'EOF'
set -euo pipefail
cd /srv/firewatch/backend
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
sudo cp /srv/firewatch/deploy/firewatch.service /etc/systemd/system/firewatch.service
sudo cp /srv/firewatch/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl daemon-reload
sudo systemctl enable -q firewatch caddy
sudo systemctl restart firewatch caddy
for i in $(seq 1 60); do curl -sf -o /dev/null http://127.0.0.1:8000/api/health && break; sleep 2; done
curl -sf -o /dev/null http://127.0.0.1:8000/api/health && echo "api up" || { echo "api did not come up"; sudo journalctl -u firewatch -n 40 --no-pager; exit 1; }
EOF

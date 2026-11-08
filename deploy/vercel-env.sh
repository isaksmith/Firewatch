#!/usr/bin/env bash
# Give the Vercel project the console login and the way to the API server. Run once after provision.sh, and again
# to change the password. The API token and proxy secret are read from the server; nothing is printed.
#   FW_PASSWORD=... [FW_USER=firewatch] FW_SSH_KEY=~/.ssh/firewatch_lightsail deploy/vercel-env.sh ubuntu@<ip>
set -euo pipefail
target=${1:?usage: deploy/vercel-env.sh ubuntu@host}
repo=$(cd "$(dirname "$0")/.." && pwd)
: "${FW_PASSWORD:?set FW_PASSWORD for the console login}"
ssh_cmd="ssh -o StrictHostKeyChecking=accept-new ${FW_SSH_KEY:+-i $FW_SSH_KEY}"

remote() { $ssh_cmd "$target" "sudo sed -n 's/^$1=//p' $2"; }
put() { printf %s "$2" | vercel env add "$1" production --force --sensitive --yes --cwd "$repo" >/dev/null; }

port=$(remote FW_HTTPS_PORT /etc/firewatch/caddy.env)
put FW_API_ORIGIN "https://$(remote FW_HOST /etc/firewatch/caddy.env):${port:-443}"
put FW_PROXY_SECRET "$(remote FW_PROXY_SECRET /etc/firewatch/caddy.env)"
put FW_API_TOKEN "$(remote API_TOKEN /srv/firewatch/.env)"
put FW_USER "${FW_USER:-firewatch}"
put FW_PASSWORD "$FW_PASSWORD"
echo "vercel settings saved; run deploy/vercel-deploy.sh"

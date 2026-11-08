#!/usr/bin/env bash
# One-time setup of an existing Ubuntu 24.04 server (Oracle Cloud, Lightsail, anything with SSH) as the API server.
#   FW_SITE=https://<project>.vercel.app FW_SSH_KEY=~/.ssh/firewatch_oracle deploy/setup.sh ubuntu@<ip>
# The API address is https://<ip with dashes>.sslip.io unless FW_HOST is set.
set -euo pipefail
target=${1:?usage: deploy/setup.sh ubuntu@host}
repo=$(cd "$(dirname "$0")/.." && pwd)
: "${FW_SITE:?set FW_SITE to the Vercel address, e.g. https://firewatch-abc.vercel.app}"
ip=${target#*@}
host=${FW_HOST:-${ip//./-}.sslip.io}
port=${FW_HTTPS_PORT:-443}
ssh_cmd="ssh -o StrictHostKeyChecking=accept-new ${FW_SSH_KEY:+-i $FW_SSH_KEY}"

openrouter=$(sed -n 's/^OPENROUTER_API_KEY=//p' "$repo/.env" 2>/dev/null || true)
{ printf 'FW_HOST=%q\nFW_HTTPS_PORT=%q\nFW_SITE=%q\nOPENROUTER_API_KEY=%q\n' "$host" "$port" "$FW_SITE" "$openrouter"
  cat "$repo/deploy/setup-server.sh"; } | $ssh_cmd "$target" 'bash -s'

echo "server: $target"
echo "api:    https://$host:$port"

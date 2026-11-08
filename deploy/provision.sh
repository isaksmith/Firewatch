#!/usr/bin/env bash
# Create the Lightsail API server once: SSH key, instance, static IP, firewall, then the one-time server setup.
#   FW_SITE=https://<project>.vercel.app deploy/provision.sh
# On a network that blocks SSH (it connects, then times out "during banner exchange"), add FW_SSH_OVER_TLS=1:
# SSH then goes inside TLS on port 443 and the API moves to port 8443 (deploy/ssh-over-tls.sh).
# Prints the server address; then run deploy/deploy.sh ubuntu@<ip>.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
name=${FW_NAME:-firewatch}
region=${AWS_REGION:-us-east-2}
zone=${FW_ZONE:-${region}a}
bundle=${FW_BUNDLE:-micro_3_0}   # $7/mo: 2 vCPU, 1 GB plus 2 GB swap; small_3_0 ($12) for 2 GB
key=${FW_SSH_KEY:-$HOME/.ssh/firewatch_lightsail}
: "${FW_SITE:?set FW_SITE to the Vercel address, e.g. https://firewatch-abc.vercel.app}"
lsl() { aws lightsail --region "$region" "$@"; }

https_port=443 launch=()
if [ -n "${FW_SSH_OVER_TLS:-}" ]; then https_port=8443 launch=(--user-data "file://$repo/deploy/ssh-over-tls.sh"); fi

[ -f "$key" ] || ssh-keygen -q -t rsa -b 4096 -N '' -C "$name" -f "$key"
lsl get-key-pair --key-pair-name "$name-key" >/dev/null 2>&1 ||
  lsl import-key-pair --key-pair-name "$name-key" --public-key-base64 "$(cat "$key.pub")" >/dev/null

if ! lsl get-instance --instance-name "$name" >/dev/null 2>&1; then
  lsl create-instances --instance-names "$name" --availability-zone "$zone" --blueprint-id ubuntu_24_04 \
    --bundle-id "$bundle" --key-pair-name "$name-key" ${launch[@]+"${launch[@]}"} >/dev/null
fi
until [ "$(lsl get-instance-state --instance-name "$name" --query state.name --output text)" = running ]; do sleep 5; done

lsl get-static-ip --static-ip-name "$name-ip" >/dev/null 2>&1 || lsl allocate-static-ip --static-ip-name "$name-ip" >/dev/null
[ "$(lsl get-static-ip --static-ip-name "$name-ip" --query staticIp.isAttached --output text)" = True ] ||
  lsl attach-static-ip --static-ip-name "$name-ip" --instance-name "$name" >/dev/null
ip=$(lsl get-static-ip --static-ip-name "$name-ip" --query staticIp.ipAddress --output text)

# SSH takes only the key, so it is open like the web ports; a network's SSH address can differ from its web one.
lsl put-instance-public-ports --instance-name "$name" --port-infos "fromPort=22,toPort=22,protocol=tcp" \
  "fromPort=80,toPort=80,protocol=tcp" "fromPort=443,toPort=443,protocol=tcp" "fromPort=8443,toPort=8443,protocol=tcp" >/dev/null

if [ -n "${FW_SSH_OVER_TLS:-}" ] && ! grep -q "^Host $ip\$" ~/.ssh/config 2>/dev/null; then
  printf '\n# %s: SSH inside TLS on port 443 (deploy/ssh-over-tls.sh)\nHost %s\n  IdentityFile %s\n  ProxyCommand openssl s_client -quiet -connect %%h:443 -servername firewatch-ssh 2>/dev/null\n' \
    "$name" "$ip" "$key" >> ~/.ssh/config
fi
until ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -i "$key" "ubuntu@$ip" true 2>/dev/null; do sleep 5; done
FW_HTTPS_PORT=$https_port FW_SSH_KEY=$key "$repo/deploy/setup.sh" "ubuntu@$ip"

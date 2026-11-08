#!/usr/bin/env bash
# Create the API server on Oracle Cloud's Always Free tier: network, firewall, an Arm machine (2 OCPUs, 12 GB), then
# the one-time server setup. Safe to rerun: it reuses what already exists by name.
#   FW_SITE=https://<project>.vercel.app deploy/oracle.sh
# Needs the oci CLI with an API key profile (OCI_CLI_PROFILE, default FIREWATCH) whose region is the home region.
# Free Arm machines are often all taken; it keeps trying each availability domain until one has room.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
: "${FW_SITE:?set FW_SITE to the Vercel address, e.g. https://firewatch-abc.vercel.app}"
export OCI_CLI_PROFILE=${OCI_CLI_PROFILE:-FIREWATCH} SUPPRESS_LABEL_WARNING=True
name=${FW_NAME:-firewatch}
key=${FW_SSH_KEY:-$HOME/.ssh/firewatch_oracle}
tenancy=$(sed -n "/^\[$OCI_CLI_PROFILE\]/,/^\[/s/^tenancy=//p" ~/.oci/config)
c="--compartment-id $tenancy"
# A lookup that matches nothing prints nothing and succeeds; any error stops the script (set -e), so a failed lookup
# is never mistaken for "not there yet" and duplicated.
q() { oci "$@" --raw-output; }

[ -f "$key" ] || ssh-keygen -q -t ed25519 -N '' -C "$name" -f "$key"

vcn=$(q network vcn list $c --display-name "$name" --query 'data[0].id')
[ -n "$vcn" ] || vcn=$(q network vcn create $c --display-name "$name" --cidr-blocks '["10.0.0.0/16"]' \
  --dns-label fw --wait-for-state AVAILABLE --query 'data.id')

igw=$(q network internet-gateway list $c --vcn-id "$vcn" --query 'data[0].id')
[ -n "$igw" ] || igw=$(q network internet-gateway create $c --vcn-id "$vcn" --display-name "$name" --is-enabled true \
  --wait-for-state AVAILABLE --query 'data.id')
rt=$(q network vcn get --vcn-id "$vcn" --query 'data."default-route-table-id"')
oci network route-table update --rt-id "$rt" --force \
  --route-rules "[{\"destination\":\"0.0.0.0/0\",\"networkEntityId\":\"$igw\"}]" >/dev/null

# SSH only from this computer's address; the web ports from anywhere.
me=$(curl -s https://checkip.amazonaws.com)/32
sl=$(q network vcn get --vcn-id "$vcn" --query 'data."default-security-list-id"')
oci network security-list update --security-list-id "$sl" --force \
  --egress-security-rules '[{"destination":"0.0.0.0/0","protocol":"all"}]' \
  --ingress-security-rules "[
    {\"source\":\"$me\",\"protocol\":\"6\",\"tcpOptions\":{\"destinationPortRange\":{\"min\":22,\"max\":22}}},
    {\"source\":\"0.0.0.0/0\",\"protocol\":\"6\",\"tcpOptions\":{\"destinationPortRange\":{\"min\":80,\"max\":80}}},
    {\"source\":\"0.0.0.0/0\",\"protocol\":\"6\",\"tcpOptions\":{\"destinationPortRange\":{\"min\":443,\"max\":443}}},
    {\"source\":\"0.0.0.0/0\",\"protocol\":\"1\",\"icmpOptions\":{\"type\":3,\"code\":4}}]" >/dev/null

subnet=$(q network subnet list $c --vcn-id "$vcn" --query 'data[0].id')
[ -n "$subnet" ] || subnet=$(q network subnet create $c --vcn-id "$vcn" --display-name "$name" \
  --cidr-block 10.0.0.0/24 --dns-label api --wait-for-state AVAILABLE --query 'data.id')

image=$(q compute image list $c --operating-system "Canonical Ubuntu" --operating-system-version 24.04 \
  --shape VM.Standard.A1.Flex --sort-by TIMECREATED --sort-order DESC --limit 1 --query 'data[0].id')
# When the free Arm machines are taken, Oracle answers 500 "Out of host capacity", and 429 or even 401 to quick
# retries, so the CLI's own retries are off and each round waits. The smaller size is often available sooner and
# is still several times what the backend needs.
inst=$(q compute instance list $c --display-name "$name" --lifecycle-state RUNNING --query 'data[0].id')
ads=$(q iam availability-domain list $c --query "join(' ', data[].name)")
until [ -n "$inst" ]; do
  for size in '{"ocpus":2,"memoryInGBs":12}' '{"ocpus":1,"memoryInGBs":6}'; do
    for ad in $ads; do
      if out=$(oci compute instance launch $c --availability-domain "$ad" --display-name "$name" --no-retry \
          --shape VM.Standard.A1.Flex --shape-config "$size" --image-id "$image" \
          --subnet-id "$subnet" --assign-public-ip true --ssh-authorized-keys-file "$key.pub" \
          --wait-for-state RUNNING --query 'data.id' --raw-output 2>&1); then
        inst=$(echo "$out" | tail -1); echo "launched $size in $ad"; break 2
      fi
      echo "$out" | grep -qiE 'capacity|TooManyRequests|InternalError|NotAuthenticated' || { echo "$out" >&2; exit 1; }
      echo "$(date +%H:%M) $ad $size: $(echo "$out" | grep -oE '"message": "[^"]*"' | head -1)"
      sleep 10
    done
  done
  [ -n "$inst" ] || sleep 120
done

ip=$(q compute instance list-vnics --instance-id "$inst" --query 'data[0]."public-ip"')
until ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 -i "$key" "ubuntu@$ip" true 2>/dev/null; do sleep 5; done
FW_SSH_KEY=$key "$repo/deploy/setup.sh" "ubuntu@$ip"

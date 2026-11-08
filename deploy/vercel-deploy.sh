#!/usr/bin/env bash
# Build the console and the FireNode Explorer here and publish them to Vercel's production address.
# Building locally means only the built files are uploaded, not the repo. The first run links frontend/ to a
# Vercel project named firewatch (FW_VERCEL_PROJECT to pick another name).
set -euo pipefail
cd "$(dirname "$0")/../frontend"
[ -f .vercel/project.json ] || vercel link --yes --project "${FW_VERCEL_PROJECT:-firewatch}"
vercel pull --yes --environment=production
vercel build --prod
vercel deploy --prebuilt --prod

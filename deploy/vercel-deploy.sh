#!/usr/bin/env bash
# Build the console and the FireNode Explorer here and publish them to Vercel's production address. Pushes to main
# deploy on their own once the project is connected to GitHub; this is for deploying without a push.
# The first run links the repo to a Vercel project named firewatch (FW_VERCEL_PROJECT to pick another name). Run from
# the repo root: the project's root directory is frontend/, and the build copies in ../sensors/viewer.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .vercel/project.json ] || vercel link --yes --project "${FW_VERCEL_PROJECT:-firewatch}"
vercel pull --yes --environment=production
vercel build --prod
vercel deploy --prebuilt --prod

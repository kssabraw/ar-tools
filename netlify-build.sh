#!/usr/bin/env bash
# Combined Netlify build for the AR Tools suite: builds the main suite frontend
# AND the vendored Topic Fanout app, assembling the latter into dist/fanout so
# the whole suite ships as one Netlify site (one domain, one login).
#
# Publish dir: frontend/dist
set -euo pipefail

echo "── Building AR Tools suite frontend (frontend/) ──"
( cd frontend && npm ci && npm run build )

echo "── Building Topic Fanout frontend (fanout-frontend/, base=/fanout/) ──"
( cd fanout-frontend && npm ci && npm run build )

echo "── Assembling Fanout build into frontend/dist/fanout ──"
rm -rf frontend/dist/fanout
cp -r fanout-frontend/dist frontend/dist/fanout

echo "── Combined build complete ──"

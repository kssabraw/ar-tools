#!/usr/bin/env bash
# Netlify build for the AR Tools suite. The Topic Fan-out app has been merged
# into the suite frontend (Option C) as a native route subtree under /fanout, so
# there is now a single SPA to build — no separate fanout-frontend build/assemble
# step. (fanout-frontend/ is retained temporarily as a rollback reference until
# the merge is verified, but it is no longer built or served.)
#
# Publish dir: frontend/dist
set -euo pipefail

echo "── Building AR Tools suite frontend (frontend/) ──"
( cd frontend && npm ci && npm run build )

echo "── Build complete ──"

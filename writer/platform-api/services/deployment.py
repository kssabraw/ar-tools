"""Deployment identity for the /health endpoint.

Railway injects the deployed commit into the container environment
(``RAILWAY_GIT_COMMIT_SHA``), so a public read of it lets anyone confirm which
commit a service is actually running — the thing you otherwise have to open the
Railway dashboard to see. Pure (env-only), so it degrades to ``None`` locally
and in any environment that doesn't set the var. No secrets: a commit SHA is an
opaque hash, not source.
"""

from __future__ import annotations

import os
from typing import Optional

# In priority order. RAILWAY_GIT_COMMIT_SHA is what Railway sets; the others are
# generic fallbacks for other hosts / local overrides.
_COMMIT_ENV_VARS = ("RAILWAY_GIT_COMMIT_SHA", "SOURCE_COMMIT", "GIT_COMMIT_SHA")


def commit_sha() -> Optional[str]:
    """The deployed commit's full SHA, or None when unset. Pure."""
    for var in _COMMIT_ENV_VARS:
        value = (os.getenv(var) or "").strip()
        if value:
            return value
    return None


def deployment_info() -> dict:
    """``{"commit", "commit_short"}`` for the /health payload. Pure."""
    sha = commit_sha()
    return {"commit": sha, "commit_short": sha[:7] if sha else None}

import os

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    """Liveness probe. Used by Railway's healthcheck (PRD §15.1).

    Reports the deployed git commit (Railway injects RAILWAY_GIT_COMMIT_SHA) so
    the running build can be verified against the repo.
    """
    return {
        "status": "ok",
        "service": "info-site-kw-research-cluster",
        "commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "unknown"),
    }

"""Activity indicator — the current user's in-flight content generation.

Powers a global "N pages still generating" badge + panel that follows the user
across clients and pages, so a long batch they navigated away from is still
visible. Read-only; jobs run server-side regardless of this endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from middleware.auth import require_auth
from services import activity

router = APIRouter(tags=["activity"])


@router.get("/activity")
async def get_activity(auth: dict = Depends(require_auth)) -> dict:
    """Every in-flight content job the current user started (ecommerce / Local
    SEO pages + blog runs), across all clients."""
    return activity.list_user_activity(auth["user_id"])

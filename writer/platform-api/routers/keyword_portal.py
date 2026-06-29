"""Unified Keyword Portal — API route.

One entry point (`POST /clients/{id}/keyword-portal/add`) that fans a keyword
list out to the organic rank tracker, the Maps geo-grid, and the AI-Visibility
(brand) tracker, deduping per tracker, and (optionally) kicking off the first
scans. Internal tool — `require_auth` only. Phase 1 / PR1.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import require_auth
from models.keyword_portal import KeywordPortalRequest, KeywordPortalResponse
from services import keyword_portal

router = APIRouter(tags=["keyword_portal"])


@router.post("/clients/{client_id}/keyword-portal/add", response_model=KeywordPortalResponse)
async def add_keywords_portal(
    client_id: UUID,
    body: KeywordPortalRequest,
    auth: dict = Depends(require_auth),  # adding keywords is open to any team member
) -> KeywordPortalResponse:
    keywords = keyword_portal.split_keywords(body.keywords)
    if not keywords:
        raise HTTPException(status_code=422, detail="validation_error: no keywords provided")
    targets = [t for t in body.targets if t in keyword_portal.VALID_TARGETS]
    if not targets:
        raise HTTPException(status_code=422, detail="validation_error: no valid targets")

    result = keyword_portal.run_portal(
        str(client_id), keywords, targets, body.run_scans, auth.get("user_id")
    )
    return KeywordPortalResponse(**result)

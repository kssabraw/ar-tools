"""Managed engagement spine — API routes.

Create / read / advance a client's managed engagement through its lifecycle.
Internal tool — `require_auth` only. Phase 2 / PR-A.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends

from middleware.auth import require_auth
from models.engagement import EngagementCreateRequest, EngagementResponse, TransitionRequest
from services import engagement_service

router = APIRouter(tags=["engagements"])


@router.post("/clients/{client_id}/engagements", response_model=EngagementResponse)
async def create_engagement(
    client_id: UUID,
    body: EngagementCreateRequest,
    auth: dict = Depends(require_auth),
):
    return engagement_service.create_engagement(
        str(client_id), body.autonomy_level, auth.get("user_id")
    )


@router.get("/clients/{client_id}/engagement", response_model=Optional[EngagementResponse])
async def get_active_engagement(client_id: UUID, auth: dict = Depends(require_auth)):
    return engagement_service.get_active_for_client(str(client_id))


@router.get("/engagements/{engagement_id}", response_model=EngagementResponse)
async def get_engagement(engagement_id: UUID, auth: dict = Depends(require_auth)):
    return engagement_service.get_engagement(str(engagement_id))


@router.post("/engagements/{engagement_id}/transition", response_model=EngagementResponse)
async def transition_engagement(
    engagement_id: UUID,
    body: TransitionRequest,
    auth: dict = Depends(require_auth),
):
    return engagement_service.transition(str(engagement_id), body.to_status)

"""Strategy Engine — API routes.

Build (recommend-only) and read the unified cross-module strategy plan for an
engagement. Internal tool — `require_auth` only. Phase 2 / PR-B.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from middleware.auth import require_auth
from models.engagement import StrategyPlanResponse
from services import engagement_executor, strategy_engine

router = APIRouter(tags=["strategy"])


class ActionStatusRequest(BaseModel):
    status: str


@router.post("/engagements/{engagement_id}/plan/refresh", response_model=StrategyPlanResponse)
async def refresh_plan(engagement_id: UUID, auth: dict = Depends(require_auth)):
    strategy_engine.build_plan(str(engagement_id))
    return strategy_engine.get_latest_plan(str(engagement_id))


@router.get("/engagements/{engagement_id}/plan", response_model=Optional[StrategyPlanResponse])
async def get_plan(engagement_id: UUID, auth: dict = Depends(require_auth)):
    return strategy_engine.get_latest_plan(str(engagement_id))


@router.post("/engagements/{engagement_id}/plan/approve")
async def approve_plan(engagement_id: UUID, auth: dict = Depends(require_auth)):
    return engagement_executor.approve_plan(str(engagement_id), auth.get("user_id"))


@router.post("/strategy-actions/{action_id}/status")
async def set_action_status(
    action_id: UUID, body: ActionStatusRequest, auth: dict = Depends(require_auth)
):
    return engagement_executor.update_action_status(str(action_id), body.status)


@router.get("/engagements/{engagement_id}/events")
async def list_events(engagement_id: UUID, auth: dict = Depends(require_auth)):
    return engagement_executor.list_events(str(engagement_id))

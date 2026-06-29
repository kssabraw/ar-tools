"""Strategy Engine — API routes.

Build (recommend-only) and read the unified cross-module strategy plan for an
engagement. Internal tool — `require_auth` only. Phase 2 / PR-B.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends

from middleware.auth import require_auth
from models.engagement import StrategyPlanResponse
from services import strategy_engine

router = APIRouter(tags=["strategy"])


@router.post("/engagements/{engagement_id}/plan/refresh", response_model=StrategyPlanResponse)
async def refresh_plan(engagement_id: UUID, auth: dict = Depends(require_auth)):
    strategy_engine.build_plan(str(engagement_id))
    return strategy_engine.get_latest_plan(str(engagement_id))


@router.get("/engagements/{engagement_id}/plan", response_model=Optional[StrategyPlanResponse])
async def get_plan(engagement_id: UUID, auth: dict = Depends(require_auth)):
    return strategy_engine.get_latest_plan(str(engagement_id))

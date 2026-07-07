"""Campaign goals API — per-client success targets + assessed progress.

The GET returns goals WITH freshly computed current_value/status/progress
(services/campaign_goals.assess_goals) — status is never stored, so every
read is honest. Create captures the metric's current value as the baseline.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.goals import (
    CampaignGoalCreateRequest,
    CampaignGoalResponse,
    CampaignGoalUpdateRequest,
)
from services import campaign_goals

router = APIRouter(tags=["goals"])
logger = logging.getLogger(__name__)


@router.get("/clients/{client_id}/goals", response_model=list[CampaignGoalResponse])
async def list_goals(
    client_id: UUID,
    include_inactive: bool = False,
    auth: dict = Depends(require_auth),
) -> list[CampaignGoalResponse]:
    try:
        assessed = campaign_goals.assess_goals(str(client_id), include_inactive=include_inactive)
    except Exception as exc:
        logger.error("goals_list_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return [CampaignGoalResponse(**g) for g in assessed]


@router.post("/clients/{client_id}/goals", response_model=CampaignGoalResponse)
async def create_goal(
    client_id: UUID,
    body: CampaignGoalCreateRequest,
    auth: dict = Depends(require_auth),
) -> CampaignGoalResponse:
    if body.goal_type != "custom" and body.target_value is None:
        raise HTTPException(status_code=422, detail="target_value_required")
    if body.goal_type == "keyword_position" and not (body.keyword or "").strip():
        raise HTTPException(status_code=422, detail="keyword_required")
    if body.goal_type == "keywords_in_top" and not body.target_position:
        raise HTTPException(status_code=422, detail="target_position_required")
    try:
        fields = body.model_dump()
        if fields.get("due_date"):
            fields["due_date"] = fields["due_date"].isoformat()
        row = campaign_goals.create_goal(str(client_id), fields, created_by=auth["user_id"])
    except Exception as exc:
        logger.error("goals_create_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    # Return it assessed so the UI shows status immediately.
    assessed = campaign_goals.assess_goals(str(client_id), include_inactive=True)
    match = next((g for g in assessed if g["id"] == row["id"]), row)
    return CampaignGoalResponse(**match)


@router.put("/clients/{client_id}/goals/{goal_id}", response_model=CampaignGoalResponse)
async def update_goal(
    client_id: UUID,
    goal_id: UUID,
    body: CampaignGoalUpdateRequest,
    auth: dict = Depends(require_auth),
) -> CampaignGoalResponse:
    # exclude_unset (not is-not-None) so an explicit null CLEARS a field —
    # inline editing needs "remove the due date" to be expressible.
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="nothing_to_update")
    if changes.get("label") is not None and not str(changes["label"]).strip():
        raise HTTPException(status_code=422, detail="label_required")
    if changes.get("due_date") is not None:
        changes["due_date"] = changes["due_date"].isoformat()
    changes["updated_at"] = "now()"
    try:
        rows = (
            get_supabase().table("campaign_goals").update(changes)
            .eq("id", str(goal_id)).eq("client_id", str(client_id)).execute()
        ).data
    except Exception as exc:
        logger.error("goals_update_failed", extra={"goal_id": str(goal_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not rows:
        raise HTTPException(status_code=404, detail="goal_not_found")
    assessed = campaign_goals.assess_goals(str(client_id), include_inactive=True)
    match = next((g for g in assessed if g["id"] == str(goal_id)), rows[0])
    return CampaignGoalResponse(**match)


@router.delete("/clients/{client_id}/goals/{goal_id}")
async def delete_goal(
    client_id: UUID,
    goal_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict:
    try:
        rows = (
            get_supabase().table("campaign_goals").delete()
            .eq("id", str(goal_id)).eq("client_id", str(client_id)).execute()
        ).data
    except Exception as exc:
        logger.error("goals_delete_failed", extra={"goal_id": str(goal_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not rows:
        raise HTTPException(status_code=404, detail="goal_not_found")
    return {"status": "deleted"}

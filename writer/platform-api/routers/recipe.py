"""Recipe Engine endpoints — generate and read a client's monthly task plan.

Generation is synchronous (pure allocation math over already-stored suite
data). Any signed-in user can generate/read; the retainer/margin inputs are
edited on the client record (admin-gated there).
"""

from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from services import recipe_engine

router = APIRouter(tags=["recipe"])


class TaskPlanRequest(BaseModel):
    month: Optional[date] = None
    # 0.34 = 66% margin target (default); 0.50 allowed for stagnating/drop
    # months; anything past 0.50 is rejected by the engine (escalate flag).
    margin: Optional[float] = Field(None, gt=0, le=0.6)
    special_projects_cost: float = Field(0.0, ge=0)


@router.post("/clients/{client_id}/task-plan", status_code=201)
async def create_task_plan(
    client_id: UUID,
    body: TaskPlanRequest,
    auth: dict = Depends(require_auth),
) -> dict:
    try:
        row = recipe_engine.build_plan(
            str(client_id),
            month=body.month,
            margin=body.margin,
            special_projects_cost=body.special_projects_cost,
            created_by=auth["user_id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return row


@router.get("/clients/{client_id}/task-plan")
async def get_task_plans(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    rows = (
        get_supabase()
        .table("monthly_task_plans")
        .select("*")
        .eq("client_id", str(client_id))
        .order("created_at", desc=True)
        .limit(12)
        .execute()
    ).data or []
    return {"latest": rows[0] if rows else None, "history": rows}


@router.post("/clients/{client_id}/task-plan/{plan_row_id}/push")
async def push_task_plan(
    client_id: UUID, plan_row_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """Push a stored plan's task lines into the client's Asana project as an
    async job (idempotent per line — a re-push creates only missing tasks).
    409 when Asana isn't configured or the client has no project mapping."""
    from services import asana_push, asana_service
    from services.asana_monthly import get_project_gid

    if not asana_service.is_configured():
        raise HTTPException(status_code=409, detail="asana_not_configured")
    if not get_project_gid(str(client_id)):
        raise HTTPException(status_code=409, detail="no_project_mapping")
    exists = (
        get_supabase().table("monthly_task_plans").select("id")
        .eq("id", str(plan_row_id)).eq("client_id", str(client_id)).limit(1).execute()
    ).data
    if not exists:
        raise HTTPException(status_code=404, detail="plan_not_found")
    job_id = asana_push.enqueue_asana_push(str(client_id), str(plan_row_id))
    return {"job_id": job_id}


@router.get("/clients/{client_id}/task-plan/push/{job_id}")
async def get_push_status(
    client_id: UUID, job_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    rows = (
        get_supabase().table("async_jobs")
        .select("status, result, error, entity_id, job_type")
        .eq("id", str(job_id)).limit(1).execute()
    ).data
    if not rows or rows[0].get("entity_id") != str(client_id) or rows[0].get("job_type") != "asana_push":
        raise HTTPException(status_code=404, detail="push_not_found")
    row = rows[0]
    return {"status": row["status"], "result": row.get("result"), "error": row.get("error")}

"""Reoptimization planner router — the Action Plan surface.

Reads the latest stored plan and rebuilds it on demand. The plan is built from
signals the rank tracker already produces (open drops, rankability Quick wins,
GSC-Research opportunities), so a manual rebuild is a set of cheap DB reads — run
synchronously here rather than as a background job. The weekly digest + on-drop
refresh are enqueued by the scheduler / rank materializer instead.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.reopt import ReoptPlan
from services import reopt_planner

router = APIRouter(tags=["reopt"])
logger = logging.getLogger(__name__)


def _latest_plan(client_id: str) -> dict | None:
    supabase = get_supabase()
    rows = (
        supabase.table("reopt_plans")
        .select("*")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    return rows[0] if rows else None


@router.get("/clients/{client_id}/action-plan", response_model=ReoptPlan | None)
async def get_action_plan(client_id: UUID, auth: dict = Depends(require_auth)) -> ReoptPlan | None:
    """The client's latest action plan (null if none built yet)."""
    row = _latest_plan(str(client_id))
    return ReoptPlan(**row) if row else None


@router.get("/clients/{client_id}/response-episodes")
async def get_response_episodes(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """The client's response episodes (the SOPs' verify loop): open + escalated
    first, then recent history. Read-only — episodes are opened/checked by the
    daily sync, recovered by the trackers, escalated by the 6-week rule."""
    rows = (
        get_supabase()
        .table("response_episodes")
        .select("*")
        .eq("client_id", str(client_id))
        .order("opened_at", desc=True)
        .limit(50)
        .execute()
    ).data or []
    return {
        "active": [r for r in rows if r["status"] in ("open", "escalated")],
        "history": rows,
    }


@router.post("/clients/{client_id}/action-plan/refresh", response_model=ReoptPlan)
async def refresh_action_plan(client_id: UUID, auth: dict = Depends(require_auth)) -> ReoptPlan:
    """Rebuild the plan now (manual trigger — no notification) and return it."""
    try:
        result = reopt_planner.build_plan(str(client_id), trigger="manual")
    except Exception as exc:
        logger.error("action_plan_refresh_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    # SOP-grounded enrichment (best-effort; no-op when no SOPs exist).
    try:
        await reopt_planner.enrich_plan(str(client_id), plan_id=result.get("plan_id"))
    except Exception as exc:  # enrichment must never fail the refresh
        logger.warning("action_plan_enrich_failed", extra={"client_id": str(client_id), "error": str(exc)})
    row = _latest_plan(str(client_id))
    if not row:
        raise HTTPException(status_code=500, detail="internal_error")
    return ReoptPlan(**row)

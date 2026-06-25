"""GSC Research module router.

On-demand opportunity analysis off the client's ingested GSC query×page data:
keyword cannibalization, quick wins, and hidden wins. Runs are computed by an
async job (DataForSEO enrichment runs out of band); the UI polls run detail
while a run is pending/running. All DB access uses the service-role client; any
authenticated user can operate it.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.gsc_research import (
    GscResearchRunDetail,
    GscResearchRunResponse,
    GscResearchRunSummary,
)
from services import gsc_research

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gsc-research"])

_SUMMARY_FIELDS = (
    "id, status, trigger, gsc_connected, cannibalization_count, quick_wins_count, "
    "hidden_wins_count, error, requested_at, completed_at"
)


@router.post("/clients/{client_id}/gsc-research/run", response_model=GscResearchRunResponse)
async def run_research(client_id: UUID, auth: dict = Depends(require_auth)) -> GscResearchRunResponse:
    """Enqueue an on-demand research run. Dedupes against an in-flight run."""
    supabase = get_supabase()
    client = supabase.table("clients").select("id").eq("id", str(client_id)).limit(1).execute().data
    if not client:
        raise HTTPException(status_code=404, detail="client_not_found")
    run_id = gsc_research.enqueue_gsc_research(str(client_id))
    return GscResearchRunResponse(run_id=run_id, status="enqueued")


@router.get("/clients/{client_id}/gsc-research/runs", response_model=list[GscResearchRunSummary])
async def list_runs(client_id: UUID, auth: dict = Depends(require_auth)) -> list[GscResearchRunSummary]:
    rows = (
        get_supabase().table("gsc_research_runs")
        .select(_SUMMARY_FIELDS)
        .eq("client_id", str(client_id))
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    ).data or []
    return [GscResearchRunSummary(**r) for r in rows]


@router.get("/clients/{client_id}/gsc-research/latest", response_model=GscResearchRunDetail)
async def latest_run(client_id: UUID, auth: dict = Depends(require_auth)) -> GscResearchRunDetail:
    """The most recent run (any status) — the module's landing view."""
    rows = (
        get_supabase().table("gsc_research_runs")
        .select("*")
        .eq("client_id", str(client_id))
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="no_runs")
    return GscResearchRunDetail(**rows[0])


@router.get("/gsc-research-runs/{run_id}", response_model=GscResearchRunDetail)
async def get_run(run_id: UUID, auth: dict = Depends(require_auth)) -> GscResearchRunDetail:
    rows = (
        get_supabase().table("gsc_research_runs").select("*").eq("id", str(run_id)).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="not_found")
    return GscResearchRunDetail(**rows[0])


@router.delete("/gsc-research-runs/{run_id}", status_code=204, response_class=Response)
async def delete_run(run_id: UUID, auth: dict = Depends(require_auth)) -> Response:
    get_supabase().table("gsc_research_runs").delete().eq("id", str(run_id)).execute()
    return Response(status_code=204)


@router.delete("/clients/{client_id}/gsc-research/runs")
async def clear_runs(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Clear the client's research history. Leaves in-flight runs untouched."""
    res = (
        get_supabase().table("gsc_research_runs").delete()
        .eq("client_id", str(client_id))
        .in_("status", ["complete", "failed"])
        .execute()
    )
    return {"deleted": len(res.data or [])}

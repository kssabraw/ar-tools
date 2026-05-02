"""Runs router — create, list, detail, poll, cancel, rerun."""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.runs import (
    ClientContextSnapshot,
    ModuleOutputSummary,
    RunCreateRequest,
    RunCreateResponse,
    RunDetail,
    RunListItem,
    RunListResponse,
    RunPollResponse,
)
from services.orchestrator import NON_TERMINAL_STATUSES, orchestrate_run
from services.file_parser import detect_format

logger = logging.getLogger(__name__)

router = APIRouter(tags=["runs"])

_TERMINAL_STATUSES = {"complete", "failed", "cancelled"}
_COMPLETED_STAGE_MAP = {
    "brief_running": [],
    "sie_running": [],
    "research_running": ["brief", "sie"],
    "writer_running": ["brief", "sie", "research"],
    "sources_cited_running": ["brief", "sie", "research", "writer"],
    "complete": ["brief", "sie", "research", "writer", "sources_cited"],
    "failed": [],
    "cancelled": [],
    "queued": [],
}


def _completed_stages_for_status(status: str, module_outputs: list[dict]) -> list[str]:
    """Derive completed stages from module_outputs records."""
    return [
        m["module"]
        for m in module_outputs
        if m.get("status") == "complete"
    ]


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    client_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    auth: dict = Depends(require_auth),
) -> RunListResponse:
    supabase = get_supabase()
    query = supabase.table("runs").select(
        "id, keyword, client_id, status, sie_cache_hit, total_cost_usd, "
        "created_at, started_at, completed_at, clients(name)",
        count="exact",
    )

    if client_id:
        query = query.eq("client_id", str(client_id))
    if status:
        query = query.eq("status", status)
    if search:
        query = query.ilike("keyword", f"%{search}%")

    offset = (page - 1) * page_size
    result = query.order("created_at", desc=True).range(offset, offset + page_size - 1).execute()

    run_rows = result.data or []

    # Bulk-fetch the brief module_output's title for every run on this page
    # so the list view can show the actual generated article title alongside
    # the user-typed keyword. Single round-trip, scoped to the current page.
    titles_by_run_id: dict[str, Optional[str]] = {}
    if run_rows:
        run_ids = [r["id"] for r in run_rows]
        brief_rows = (
            supabase.table("module_outputs")
            .select("run_id, output_payload")
            .in_("run_id", run_ids)
            .eq("module", "brief")
            .eq("status", "complete")
            .execute()
        )
        for br in brief_rows.data or []:
            payload = br.get("output_payload") or {}
            title = payload.get("title")
            if isinstance(title, str) and title.strip():
                titles_by_run_id[br["run_id"]] = title.strip()

    rows = []
    for r in run_rows:
        client_name = (r.get("clients") or {}).get("name", "")
        rows.append(
            RunListItem(
                id=r["id"],
                keyword=r["keyword"],
                title=titles_by_run_id.get(r["id"]),
                client_id=r["client_id"],
                client_name=client_name,
                status=r["status"],
                sie_cache_hit=r.get("sie_cache_hit"),
                total_cost_usd=r.get("total_cost_usd"),
                created_at=r["created_at"],
                started_at=r.get("started_at"),
                completed_at=r.get("completed_at"),
            )
        )

    return RunListResponse(data=rows, total=result.count or 0, page=page)


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: UUID,
    auth: dict = Depends(require_auth),
) -> RunDetail:
    supabase = get_supabase()
    run_result = (
        supabase.table("runs").select("*").eq("id", str(run_id)).single().execute()
    )
    if not run_result.data:
        raise HTTPException(status_code=404, detail="run_not_found")
    run = run_result.data

    # Load snapshot
    snap_result = (
        supabase.table("client_context_snapshots")
        .select("*")
        .eq("run_id", str(run_id))
        .execute()
    )
    snap = (snap_result.data or [None])[0]
    snapshot = None
    if snap:
        snapshot = ClientContextSnapshot(
            brand_guide_text=snap.get("brand_guide_text"),
            brand_guide_format=snap.get("brand_guide_format"),
            icp_text=snap.get("icp_text"),
            icp_format=snap.get("icp_format"),
            website_analysis=snap.get("website_analysis"),
            website_analysis_unavailable=snap.get("website_analysis_unavailable", False),
        )

    # Load module outputs
    mo_result = (
        supabase.table("module_outputs")
        .select("module, status, output_payload, cost_usd, duration_ms, module_version")
        .eq("run_id", str(run_id))
        .execute()
    )
    module_outputs: dict[str, Optional[ModuleOutputSummary]] = {
        "brief": None,
        "sie": None,
        "research": None,
        "writer": None,
        "sources_cited": None,
    }
    for mo in mo_result.data or []:
        module_outputs[mo["module"]] = ModuleOutputSummary(
            status=mo["status"],
            output_payload=mo.get("output_payload"),
            cost_usd=mo.get("cost_usd"),
            duration_ms=mo.get("duration_ms"),
            module_version=mo.get("module_version"),
        )

    # Surface the article's generated title from the brief module_output
    # (populated by Brief Generator v2.0 Step 3.5). Falls back to None when
    # the brief hasn't completed yet — the keyword is shown in that case.
    article_title: Optional[str] = None
    brief_mo = module_outputs.get("brief")
    if brief_mo and brief_mo.output_payload:
        candidate = brief_mo.output_payload.get("title")
        if isinstance(candidate, str) and candidate.strip():
            article_title = candidate.strip()

    return RunDetail(
        id=run["id"],
        keyword=run["keyword"],
        title=article_title,
        client_id=run["client_id"],
        status=run["status"],
        sie_cache_hit=run.get("sie_cache_hit"),
        error_stage=run.get("error_stage"),
        error_message=run.get("error_message"),
        total_cost_usd=run.get("total_cost_usd"),
        created_at=run["created_at"],
        started_at=run.get("started_at"),
        completed_at=run.get("completed_at"),
        client_context_snapshot=snapshot,
        module_outputs=module_outputs,
    )


@router.post("/runs", response_model=RunCreateResponse, status_code=202)
async def create_run(
    body: RunCreateRequest,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_auth),
) -> RunCreateResponse:
    supabase = get_supabase()

    # Concurrency check
    in_flight = (
        supabase.table("runs")
        .select("id", count="exact")
        .in_("status", list(NON_TERMINAL_STATUSES))
        .execute()
    )
    if (in_flight.count or 0) >= 5:
        logger.warning("concurrency_limit_hit", extra={"user_id": auth["user_id"]})
        raise HTTPException(status_code=429, detail="concurrency_limit")

    # Verify client exists
    client_result = (
        supabase.table("clients").select("*").eq("id", str(body.client_id)).single().execute()
    )
    if not client_result.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    client = client_result.data

    # Create run row
    run_result = supabase.table("runs").insert(
        {
            "client_id": str(body.client_id),
            "keyword": body.keyword,
            "intent_override": body.intent_override,
            "sie_outlier_mode": body.sie_outlier_mode,
            "sie_force_refresh": body.sie_force_refresh,
            "status": "queued",
            "created_by": auth["user_id"],
        }
    ).execute()
    run = run_result.data[0]
    run_id = run["id"]

    # Determine brand_guide format and icp_format from text content + source type
    brand_text = client.get("brand_guide_text") or ""
    icp_text = client.get("icp_text") or ""
    website_analysis = client.get("website_analysis")
    website_unavailable = website_analysis is None or client.get("website_analysis_status") != "complete"

    supabase.table("client_context_snapshots").insert(
        {
            "run_id": run_id,
            "client_id": str(body.client_id),
            "brand_guide_text": brand_text,
            "brand_guide_format": detect_format(brand_text, "text/plain"),
            "icp_text": icp_text,
            "icp_format": detect_format(icp_text, "text/plain"),
            "website_analysis": website_analysis,
            "website_analysis_unavailable": website_unavailable,
        }
    ).execute()

    logger.info(
        "run_dispatched",
        extra={"run_id": run_id, "keyword": body.keyword, "user_id": auth["user_id"]},
    )
    background_tasks.add_task(orchestrate_run, run_id)

    return RunCreateResponse(run_id=run_id, status="queued")


@router.post("/runs/{run_id}/cancel", response_model=dict)
async def cancel_run(
    run_id: UUID,
    auth: dict = Depends(require_auth),
) -> dict:
    supabase = get_supabase()
    run_result = (
        supabase.table("runs").select("status, created_by").eq("id", str(run_id)).single().execute()
    )
    if not run_result.data:
        raise HTTPException(status_code=404, detail="run_not_found")
    run = run_result.data

    if run["status"] in _TERMINAL_STATUSES:
        return {"id": str(run_id), "status": run["status"]}

    # Only creator or admin may cancel
    if auth["role"] != "admin" and str(run.get("created_by")) != auth["user_id"]:
        raise HTTPException(status_code=403, detail="forbidden")

    supabase.table("runs").update(
        {"status": "cancelled", "completed_at": "now()", "updated_at": "now()"}
    ).eq("id", str(run_id)).execute()

    logger.info("run_cancelled", extra={"run_id": str(run_id), "user_id": auth["user_id"]})
    return {"id": str(run_id), "status": "cancelled"}


@router.post("/runs/{run_id}/resume", response_model=RunCreateResponse, status_code=202)
async def resume_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_auth),
) -> RunCreateResponse:
    """Resume a failed/cancelled run from the last completed stage.

    Reuses any module_outputs already in 'complete' status — the orchestrator
    skips those stages and picks up at the first incomplete one.
    """
    supabase = get_supabase()
    run_result = (
        supabase.table("runs").select("*").eq("id", str(run_id)).single().execute()
    )
    if not run_result.data:
        raise HTTPException(status_code=404, detail="run_not_found")
    run = run_result.data

    if run["status"] not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="run_not_resumable")

    if auth["role"] != "admin" and str(run.get("created_by")) != auth["user_id"]:
        raise HTTPException(status_code=403, detail="forbidden")

    in_flight = (
        supabase.table("runs")
        .select("id", count="exact")
        .in_("status", list(NON_TERMINAL_STATUSES))
        .execute()
    )
    if (in_flight.count or 0) >= 5:
        raise HTTPException(status_code=429, detail="concurrency_limit")

    # Determine completed stages so we can pick the right re-entry status
    mo_result = (
        supabase.table("module_outputs")
        .select("module, status")
        .eq("run_id", str(run_id))
        .execute()
    )
    completed = {m["module"] for m in (mo_result.data or []) if m.get("status") == "complete"}

    if "writer" in completed:
        next_status = "sources_cited_running"
    elif "research" in completed:
        next_status = "writer_running"
    elif {"brief", "sie"}.issubset(completed):
        next_status = "research_running"
    else:
        next_status = "brief_running"

    supabase.table("runs").update(
        {
            "status": next_status,
            "error_stage": None,
            "error_message": None,
            "completed_at": None,
            "updated_at": "now()",
        }
    ).eq("id", str(run_id)).execute()

    logger.info(
        "run_resumed",
        extra={
            "run_id": str(run_id),
            "next_status": next_status,
            "resumed_completed_stages": list(completed),
            "user_id": auth["user_id"],
        },
    )
    background_tasks.add_task(orchestrate_run, str(run_id))
    return RunCreateResponse(run_id=run_id, status=next_status)


@router.post("/runs/{run_id}/rerun", response_model=RunCreateResponse, status_code=202)
async def rerun(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_auth),
) -> RunCreateResponse:
    supabase = get_supabase()
    original_result = (
        supabase.table("runs").select("*").eq("id", str(run_id)).single().execute()
    )
    if not original_result.data:
        raise HTTPException(status_code=404, detail="run_not_found")
    original = original_result.data

    # Concurrency check
    in_flight = (
        supabase.table("runs")
        .select("id", count="exact")
        .in_("status", list(NON_TERMINAL_STATUSES))
        .execute()
    )
    if (in_flight.count or 0) >= 5:
        raise HTTPException(status_code=429, detail="concurrency_limit")

    new_run_result = supabase.table("runs").insert(
        {
            "client_id": original["client_id"],
            "keyword": original["keyword"],
            "intent_override": original.get("intent_override"),
            "sie_outlier_mode": original.get("sie_outlier_mode", "safe"),
            "sie_force_refresh": original.get("sie_force_refresh", False),
            "status": "queued",
            "created_by": auth["user_id"],
        }
    ).execute()
    new_run = new_run_result.data[0]
    new_run_id = new_run["id"]

    # Fresh snapshot from current client context
    client_result = (
        supabase.table("clients").select("*").eq("id", original["client_id"]).single().execute()
    )
    client = client_result.data or {}
    brand_text = client.get("brand_guide_text") or ""
    icp_text = client.get("icp_text") or ""
    website_analysis = client.get("website_analysis")
    website_unavailable = website_analysis is None or client.get("website_analysis_status") != "complete"

    supabase.table("client_context_snapshots").insert(
        {
            "run_id": new_run_id,
            "client_id": original["client_id"],
            "brand_guide_text": brand_text,
            "brand_guide_format": detect_format(brand_text, "text/plain"),
            "icp_text": icp_text,
            "icp_format": detect_format(icp_text, "text/plain"),
            "website_analysis": website_analysis,
            "website_analysis_unavailable": website_unavailable,
        }
    ).execute()

    background_tasks.add_task(orchestrate_run, new_run_id)
    return RunCreateResponse(run_id=new_run_id, status="queued")


@router.get("/runs/{run_id}/poll", response_model=RunPollResponse)
async def poll_run(
    run_id: UUID,
    auth: dict = Depends(require_auth),
) -> RunPollResponse:
    supabase = get_supabase()
    run_result = (
        supabase.table("runs")
        .select("id, status, error_stage, updated_at")
        .eq("id", str(run_id))
        .single()
        .execute()
    )
    if not run_result.data:
        raise HTTPException(status_code=404, detail="run_not_found")
    run = run_result.data

    mo_result = (
        supabase.table("module_outputs")
        .select("module, status")
        .eq("run_id", str(run_id))
        .execute()
    )
    completed = _completed_stages_for_status(run["status"], mo_result.data or [])

    return RunPollResponse(
        run_id=run_id,
        status=run["status"],
        completed_stages=completed,
        error_stage=run.get("error_stage"),
        updated_at=run.get("updated_at", ""),
    )

"""Runs router — create, list, detail, poll, cancel, rerun."""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from db.supabase_client import get_supabase
from middleware.auth import is_staff_or_above, require_auth
from models.runs import (
    BULK_RUNS_MAX,
    ClientContextSnapshot,
    ModuleOutputSummary,
    RunBulkCreateRequest,
    RunBulkCreateResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunDetail,
    RunListItem,
    RunListResponse,
    RunPollResponse,
    ServicePagePlanJob,
    ServicePagePlanResult,
    ServicePageReoptimizeExistingRequest,
    ServicePageReoptimizeRequest,
    SIETermsByCategory,
    bucket_sie_required_terms,
)
from services.freeze import assert_not_frozen
from services.orchestrator import NON_TERMINAL_STATUSES, orchestrate_run
from services.run_dispatch import create_run_and_snapshot
from services.file_parser import detect_format
from services import (
    brand_voice_service,
    icp_service,
    service_page_plan,
    service_page_score,
)
from sse import sse_response

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
    content_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    auth: dict = Depends(require_auth),
) -> RunListResponse:
    supabase = get_supabase()
    query = supabase.table("runs").select(
        "id, keyword, client_id, content_type, status, sie_cache_hit, total_cost_usd, "
        "created_at, started_at, completed_at, published_doc_url, published_url, clients(name)",
        count="exact",
    )

    if client_id:
        query = query.eq("client_id", str(client_id))
    if status:
        query = query.eq("status", status)
    if content_type:
        query = query.eq("content_type", content_type)
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
                content_type=r.get("content_type") or "blog_post",
                status=r["status"],
                sie_cache_hit=r.get("sie_cache_hit"),
                total_cost_usd=r.get("total_cost_usd"),
                created_at=r["created_at"],
                started_at=r.get("started_at"),
                completed_at=r.get("completed_at"),
                published_doc_url=r.get("published_doc_url"),
                published_url=r.get("published_url"),
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

    # Load module outputs, ordered by attempt so later attempts come last.
    mo_result = (
        supabase.table("module_outputs")
        .select("module, status, output_payload, cost_usd, duration_ms, module_version, attempt_number")
        .eq("run_id", str(run_id))
        .order("attempt_number")
        .execute()
    )
    module_outputs: dict[str, Optional[ModuleOutputSummary]] = {
        "brief": None,
        "sie": None,
        "research": None,
        "writer": None,
        "sources_cited": None,
    }
    # Pick the latest COMPLETE attempt per module (a reoptimized service_writer or
    # a re-score creates a 2nd attempt); fall back to the latest non-complete row
    # so an in-flight/failed stage is still visible. Rows arrive attempt-ascending.
    for mo in mo_result.data or []:
        existing = module_outputs.get(mo["module"])
        if existing is not None and existing.status == "complete" and mo["status"] != "complete":
            continue
        module_outputs[mo["module"]] = ModuleOutputSummary(
            status=mo["status"],
            output_payload=mo.get("output_payload"),
            cost_usd=mo.get("cost_usd"),
            duration_ms=mo.get("duration_ms"),
            module_version=mo.get("module_version"),
        )

    # Surface the article's generated title and H1 from the brief
    # module_output (populated by Brief Generator v2.0 Step 3.5). Title and
    # H1 are SEPARATE concepts: title is SEO/meta (browser tab, SERP),
    # H1 is the on-page main heading (first H1 in article body). Both
    # fall back to None when the brief hasn't completed yet.
    article_title: Optional[str] = None
    article_h1: Optional[str] = None
    brief_mo = module_outputs.get("brief")
    if brief_mo and brief_mo.output_payload:
        title_candidate = brief_mo.output_payload.get("title")
        if isinstance(title_candidate, str) and title_candidate.strip():
            article_title = title_candidate.strip()
        h1_candidate = brief_mo.output_payload.get("h1")
        if isinstance(h1_candidate, str) and h1_candidate.strip():
            article_h1 = h1_candidate.strip()

    # Pre-bucket SIE required terms into entities / related_keywords /
    # keyword_variants for the UI (mirrors writer/sections.py and
    # faqs.py prompt-side bucketing). Frontend can render three
    # categorized lists without re-implementing the classification
    # rule (and without needing to know about is_entity /
    # is_seed_fragment flags).
    sie_terms_by_category: Optional[SIETermsByCategory] = None
    sie_mo = module_outputs.get("sie")
    if sie_mo and sie_mo.output_payload:
        required = (sie_mo.output_payload.get("terms") or {}).get("required") or []
        sie_terms_by_category = bucket_sie_required_terms(required)

    return RunDetail(
        id=run["id"],
        keyword=run["keyword"],
        title=article_title,
        h1=article_h1,
        client_id=run["client_id"],
        content_type=run.get("content_type") or "blog_post",
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
        sie_terms_by_category=sie_terms_by_category,
        services=run.get("services") or [],
        featured_image_url=run.get("featured_image_url"),
        writer_notes=run.get("writer_notes"),
    )


@router.post("/runs", response_model=RunCreateResponse, status_code=202)
async def create_run(
    body: RunCreateRequest,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_auth),
) -> RunCreateResponse:
    supabase = get_supabase()

    # Freeze Protocol: content creation stops under an active freeze.
    assert_not_frozen(str(body.client_id))

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

    # A location page is a multi-service hub for one area — both the target
    # location and at least one service to cover are required.
    services = [s.strip() for s in (body.services or []) if s and s.strip()]
    if body.content_type == "location_page":
        if not (body.location or "").strip():
            raise HTTPException(status_code=400, detail="location_required")
        if not services:
            raise HTTPException(status_code=400, detail="services_required")

    run_id = create_run_and_snapshot(
        client=client,
        keyword=body.keyword,
        content_type=body.content_type,
        service=body.service,
        location=body.location,
        location_code=body.location_code,
        services=services,
        intent_override=body.intent_override,
        sie_outlier_mode=body.sie_outlier_mode,
        sie_force_refresh=body.sie_force_refresh,
        brief_force_refresh=body.brief_force_refresh,
        writer_notes=(body.writer_notes or "").strip() or None,
        created_by=auth["user_id"],
    )

    logger.info(
        "run_dispatched",
        extra={"run_id": run_id, "keyword": body.keyword, "user_id": auth["user_id"]},
    )
    background_tasks.add_task(orchestrate_run, run_id)

    return RunCreateResponse(run_id=run_id, status="queued")


@router.post("/runs/bulk", response_model=RunBulkCreateResponse, status_code=202)
async def create_runs_bulk(
    body: RunBulkCreateRequest,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_auth),
) -> RunBulkCreateResponse:
    """Create several runs at once (e.g. bulk service pages from a pasted list).

    Each keyword becomes its own queued run; the runs are dispatched as
    sequential background tasks (one processes at a time — no concurrency
    burst), so this intentionally skips the single-run in-flight cap. For
    large, paced batches use the Topic Fanout content scheduler instead.
    """
    supabase = get_supabase()

    # Freeze Protocol: content creation stops under an active freeze.
    assert_not_frozen(str(body.client_id))

    client_result = (
        supabase.table("clients").select("*").eq("id", str(body.client_id)).single().execute()
    )
    if not client_result.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    client = client_result.data

    # Normalize: trim, drop blanks + over-length, de-dupe (case-insensitive),
    # preserve order.
    seen: set[str] = set()
    keywords: list[str] = []
    for raw in body.keywords:
        kw = (raw or "").strip()
        key = kw.lower()
        if kw and len(kw) <= 150 and key not in seen:
            seen.add(key)
            keywords.append(kw)
    skipped = len(body.keywords) - len(keywords)
    if not keywords:
        raise HTTPException(status_code=400, detail="no_valid_keywords")
    if len(keywords) > BULK_RUNS_MAX:
        raise HTTPException(status_code=400, detail="bulk_limit_exceeded")

    run_ids: list[str] = []
    for kw in keywords:
        run_id = create_run_and_snapshot(
            client=client,
            keyword=kw,
            content_type=body.content_type,
            created_by=auth["user_id"],
        )
        background_tasks.add_task(orchestrate_run, run_id)
        run_ids.append(run_id)

    logger.info(
        "runs_bulk_dispatched",
        extra={"count": len(run_ids), "content_type": body.content_type, "user_id": auth["user_id"]},
    )
    return RunBulkCreateResponse(run_ids=run_ids, created=len(run_ids), skipped=skipped)


@router.post(
    "/clients/{client_id}/service-page-plan",
    response_model=ServicePagePlanJob,
    status_code=202,
)
async def start_service_page_plan(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> ServicePagePlanJob:
    """Enqueue a Fanout-powered service-page completeness plan (seeded by the
    client's business category; runs minutes, poll for the result)."""
    job_id = await service_page_plan.start_service_plan(
        client_id=str(client_id), user_id=auth["user_id"]
    )
    return ServicePagePlanJob(job_id=job_id, status="pending")


@router.get(
    "/clients/{client_id}/service-page-plan/{job_id}",
    response_model=ServicePagePlanResult,
)
async def get_service_page_plan(
    client_id: UUID,
    job_id: UUID,
    auth: dict = Depends(require_auth),
) -> ServicePagePlanResult:
    """Poll a service-page plan job; returns its status and (when complete) the
    candidate service pages grouped by silo, each marked found/missing."""
    return ServicePagePlanResult(
        **service_page_plan.get_service_plan(str(job_id), str(client_id))
    )


@router.post("/runs/{run_id}/score")
async def score_service_page(
    run_id: UUID,
    auth: dict = Depends(require_auth),
):
    """Score a service_page run's current page (nlp-api national mode). SSE
    heartbeat stream → the ScoreResult (composite + per-engine + deficiencies)."""
    return sse_response(service_page_score.score_run(str(run_id), user_id=auth["user_id"]))


@router.post("/runs/{run_id}/reoptimize")
async def reoptimize_service_page(
    run_id: UUID,
    body: ServicePageReoptimizeRequest,
    auth: dict = Depends(require_auth),
):
    """Reoptimize a service_page run via the Service Page Writer (fed the given
    deficiencies), persist a new attempt, then re-score. SSE → {page, score}."""
    return sse_response(
        service_page_score.reoptimize_run(str(run_id), body.deficiencies, user_id=auth["user_id"])
    )


@router.post(
    "/service-pages/reoptimize-existing",
    response_model=RunCreateResponse,
    status_code=202,
)
async def reoptimize_existing_service_page(
    body: ServicePageReoptimizeExistingRequest,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_auth),
) -> RunCreateResponse:
    """Reoptimize a page already published on the client's live site (the planner
    surfaced it as not ranking top N). Spawns a service_page run tagged with the
    live URL; the orchestrator scrapes + scores that page and feeds its deficiencies
    into the writer's first pass. Poll the returned run like any other."""
    supabase = get_supabase()
    client_result = (
        supabase.table("clients").select("*").eq("id", str(body.client_id)).single().execute()
    )
    if not client_result.data:
        raise HTTPException(status_code=404, detail="client_not_found")

    keyword = (body.keyword or "").strip()
    source_url = (body.source_url or "").strip()
    if not keyword or not source_url:
        raise HTTPException(status_code=400, detail="keyword_and_source_url_required")

    run_id = create_run_and_snapshot(
        client=client_result.data,
        keyword=keyword,
        content_type="service_page",
        location=body.location,
        location_code=body.location_code,
        reoptimize_source_url=source_url,
        created_by=auth["user_id"],
    )
    background_tasks.add_task(orchestrate_run, run_id)
    logger.info(
        "service_page_reoptimize_existing_dispatched",
        extra={"run_id": run_id, "keyword": keyword, "user_id": auth["user_id"]},
    )
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

    # Only the creator or a senior operator (staff/admin) may cancel
    if not is_staff_or_above(auth["role"]) and str(run.get("created_by")) != auth["user_id"]:
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

    if not is_staff_or_above(auth["role"]) and str(run.get("created_by")) != auth["user_id"]:
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
            # Manual resume grants a fresh transient-auto-retry budget — a run
            # that exhausted its retries during an outage shouldn't fail
            # instantly on the next blip after a human explicitly restarts it.
            "retry_count": 0,
            "next_retry_at": None,
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
    brief_force_refresh: bool = Query(
        True,
        description=(
            "When true (default for rerun), the new run regenerates the "
            "brief from scratch instead of reusing the 7-day cache. "
            "Defaults to true because 'rerun' implies the user wants a "
            "different result — reusing the cached brief produces an "
            "identical title/h1/heading_structure and defeats the "
            "purpose. Frontend can pass false explicitly to opt into "
            "cache reuse (cheaper / faster)."
        ),
    ),
    sie_force_refresh: bool = Query(
        True,
        description=(
            "When true (default for rerun), the new run regenerates the "
            "SIE entity set from scratch instead of reusing the 7-day "
            "cache. Defaults to true so that the entities feeding the "
            "brief's title/h1 prompts can shift between reruns — without "
            "this, the same entity list flows into the same prompts and "
            "constrains title diversity. Frontend can pass false to opt "
            "into cache reuse."
        ),
    ),
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
            # Caller's explicit choice on the modal wins. Don't inherit
            # from the original run (which might have force-refreshed
            # for an unrelated reason a week ago).
            "sie_force_refresh": sie_force_refresh,
            "brief_force_refresh": brief_force_refresh,
            # A rerun keeps the original's editorial guidance - the notes
            # describe the article, not the attempt.
            "writer_notes": original.get("writer_notes"),
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
    brand_text = brand_voice_service.resolve_brand_guide_text(client)
    icp_text = icp_service.resolve_icp_text(client)
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

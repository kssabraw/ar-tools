"""Silos router — dashboard list, status updates, promotion, bulk actions
(Platform PRD v1.4 §7.7)."""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.silos import (
    SiloBulkRequest,
    SiloBulkResponse,
    SiloDetail,
    SiloListItem,
    SiloListResponse,
    SiloMetricsResponse,
    SiloPromoteResponse,
    SiloStatusUpdateRequest,
)
from services.orchestrator import orchestrate_run
from services.silo_promotion import (
    PromotionError,
    in_flight_run_count,
    promote_candidate,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["silos"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Default visibility per PRD §7.7.1 — all statuses except 'rejected' shown by default.
_VISIBLE_STATUSES_DEFAULT = (
    "proposed", "approved", "in_progress", "published", "superseded",
)

# Display order across statuses — drives the default sort (PRD §7.7.1).
_STATUS_ORDER = {
    "proposed": 0,
    "approved": 1,
    "in_progress": 2,
    "published": 3,
    "superseded": 4,
    "rejected": 5,
}


def _row_to_list_item(row: dict) -> SiloListItem:
    return SiloListItem(
        id=row["id"],
        client_id=row["client_id"],
        suggested_keyword=row["suggested_keyword"],
        status=row["status"],
        occurrence_count=row.get("occurrence_count", 1),
        cluster_coherence_score=row.get("cluster_coherence_score"),
        search_demand_score=row.get("search_demand_score"),
        viable_as_standalone_article=row.get("viable_as_standalone_article", True),
        estimated_intent=row.get("estimated_intent"),
        routed_from=row.get("routed_from"),
        first_seen_run_id=row["first_seen_run_id"],
        last_seen_run_id=row["last_seen_run_id"],
        promoted_to_run_id=row.get("promoted_to_run_id"),
        last_promotion_failed_at=row.get("last_promotion_failed_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# GET /silos — dashboard list with filter / search / pagination
# ---------------------------------------------------------------------------


@router.get("/silos", response_model=SiloListResponse)
async def list_silos(
    client_id: UUID = Query(..., description="Required: silos are client-scoped"),
    status: Optional[list[str]] = Query(None, description="Multi-select status filter"),
    estimated_intent: Optional[list[str]] = Query(None),
    routed_from: Optional[list[str]] = Query(None),
    viable_as_standalone_article: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, description="Free-text on suggested_keyword"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    auth: dict = Depends(require_auth),
) -> SiloListResponse:
    supabase = get_supabase()
    query = (
        supabase.table("silo_candidates")
        .select("*", count="exact")
        .eq("client_id", str(client_id))
    )

    if status:
        query = query.in_("status", status)
    else:
        # Default visibility: hide 'rejected'
        query = query.in_("status", list(_VISIBLE_STATUSES_DEFAULT))

    if estimated_intent:
        query = query.in_("estimated_intent", estimated_intent)
    if routed_from:
        query = query.in_("routed_from", routed_from)
    if viable_as_standalone_article is not None:
        query = query.eq("viable_as_standalone_article", viable_as_standalone_article)
    if search:
        query = query.ilike("suggested_keyword", f"%{search}%")

    # Pull all rows in the page-window, then sort in Python by the
    # status order defined in PRD §7.7.1. (Postgres CASE-based sorting
    # via supabase-py is awkward; sorting in app code is fine at <10k
    # candidates per client.)
    offset = (page - 1) * page_size
    result = (
        query.order("occurrence_count", desc=True)
        .order("search_demand_score", desc=True)
        .range(offset, offset + page_size - 1)
        .execute()
    )

    rows = result.data or []
    rows.sort(
        key=lambda r: (
            _STATUS_ORDER.get(r.get("status", ""), 99),
            -1 * (r.get("occurrence_count") or 0),
            -1 * (r.get("search_demand_score") or 0.0),
        )
    )

    return SiloListResponse(
        items=[_row_to_list_item(r) for r in rows],
        total=result.count or len(rows),
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /silos/{id} — drawer detail
# ---------------------------------------------------------------------------


@router.get("/silos/{silo_id}", response_model=SiloDetail)
async def get_silo(
    silo_id: UUID,
    auth: dict = Depends(require_auth),
) -> SiloDetail:
    supabase = get_supabase()
    result = (
        supabase.table("silo_candidates")
        .select("*")
        .eq("id", str(silo_id))
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="silo_not_found")
    row = result.data
    return SiloDetail(
        **_row_to_list_item(row).model_dump(),
        source_run_ids=row.get("source_run_ids") or [],
        viability_reasoning=row.get("viability_reasoning"),
        discard_reason_breakdown=row.get("discard_reason_breakdown") or {},
        source_headings=row.get("source_headings") or [],
    )


# ---------------------------------------------------------------------------
# PATCH /silos/{id} — approve / reject status update
# ---------------------------------------------------------------------------


@router.patch("/silos/{silo_id}", response_model=SiloListItem)
async def update_silo_status(
    silo_id: UUID,
    body: SiloStatusUpdateRequest,
    auth: dict = Depends(require_auth),
) -> SiloListItem:
    supabase = get_supabase()
    cand = (
        supabase.table("silo_candidates")
        .select("*")
        .eq("id", str(silo_id))
        .single()
        .execute()
    )
    if not cand.data:
        raise HTTPException(status_code=404, detail="silo_not_found")
    current = cand.data["status"]

    # Allowed transitions for manual status change (PRD §7.7.2):
    #   proposed → approved | rejected
    #   approved → rejected
    #   published → approved (re-trigger workflow); rejected
    #   in_progress / superseded → cannot manually change
    if body.status == "approved":
        if current not in {"proposed", "published"}:
            raise HTTPException(
                status_code=409,
                detail=f"invalid_transition: {current!r} → approved",
            )
    elif body.status == "rejected":
        if current in {"in_progress"}:
            raise HTTPException(
                status_code=409,
                detail=f"invalid_transition: {current!r} → rejected",
            )

    updated = (
        supabase.table("silo_candidates")
        .update({"status": body.status})
        .eq("id", str(silo_id))
        .execute()
    )
    logger.info(
        "silo_status_changed",
        extra={
            "silo_id": str(silo_id),
            "from": current,
            "to": body.status,
            "user_id": auth["user_id"],
        },
    )
    return _row_to_list_item((updated.data or [cand.data])[0])


# ---------------------------------------------------------------------------
# POST /silos/{id}/promote — single-candidate promotion (creates a run)
# ---------------------------------------------------------------------------


@router.post(
    "/silos/{silo_id}/promote",
    response_model=SiloPromoteResponse,
    status_code=202,
)
async def promote_silo(
    silo_id: UUID,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_auth),
) -> SiloPromoteResponse:
    try:
        result = promote_candidate(
            candidate_id=str(silo_id),
            user_id=auth["user_id"],
            max_concurrent=settings.max_concurrent_runs,
        )
    except PromotionError as exc:
        if exc.code == "candidate_not_found":
            raise HTTPException(status_code=404, detail=exc.code)
        if exc.code == "concurrency_limit":
            raise HTTPException(status_code=429, detail=exc.code)
        raise HTTPException(status_code=409, detail=f"{exc.code}: {exc.message}")

    background_tasks.add_task(orchestrate_run, result["run_id"])
    return SiloPromoteResponse(
        silo_id=UUID(result["candidate_id"]),
        run_id=UUID(result["run_id"]),
        status=result["status"],
    )


# ---------------------------------------------------------------------------
# Bulk actions (PRD §7.7.4)
# ---------------------------------------------------------------------------


@router.post(
    "/silos/bulk-approve-and-generate",
    response_model=SiloBulkResponse,
    status_code=202,
)
async def bulk_approve_and_generate(
    body: SiloBulkRequest,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(require_auth),
) -> SiloBulkResponse:
    """Approve N candidates and create a run for each. The orchestrator's
    existing 5-run concurrency cap means at most 5 will be running at any
    time; the rest sit in `runs.state='queued'` until slots open."""
    response = SiloBulkResponse()
    for candidate_id in body.ids:
        try:
            # We deliberately disable the per-call concurrency check —
            # multiple runs CAN be queued at once; the cap only stops
            # them from EXECUTING in parallel. Queued runs sit waiting.
            result = promote_candidate(
                candidate_id=str(candidate_id),
                user_id=auth["user_id"],
                enforce_concurrency_cap=False,
            )
            response.succeeded.append(candidate_id)
            response.runs_dispatched.append(UUID(result["run_id"]))
            background_tasks.add_task(orchestrate_run, result["run_id"])
        except PromotionError as exc:
            response.failed.append({"id": str(candidate_id), "reason": exc.code})
        except Exception as exc:
            logger.error(
                "bulk_promote_unexpected",
                extra={"candidate_id": str(candidate_id), "error": str(exc)},
            )
            response.failed.append({"id": str(candidate_id), "reason": "internal_error"})

    return response


@router.post("/silos/bulk-approve", response_model=SiloBulkResponse)
async def bulk_approve(
    body: SiloBulkRequest,
    auth: dict = Depends(require_auth),
) -> SiloBulkResponse:
    """Mark all selected as `approved` without dispatching runs (two-pass
    triage workflow)."""
    supabase = get_supabase()
    response = SiloBulkResponse()
    for candidate_id in body.ids:
        try:
            cand = (
                supabase.table("silo_candidates")
                .select("status")
                .eq("id", str(candidate_id))
                .single()
                .execute()
            )
            if not cand.data:
                response.failed.append(
                    {"id": str(candidate_id), "reason": "candidate_not_found"}
                )
                continue
            if cand.data["status"] not in {"proposed", "published"}:
                response.failed.append(
                    {
                        "id": str(candidate_id),
                        "reason": f"invalid_status:{cand.data['status']}",
                    }
                )
                continue
            supabase.table("silo_candidates").update(
                {"status": "approved"}
            ).eq("id", str(candidate_id)).execute()
            response.succeeded.append(candidate_id)
        except Exception as exc:
            logger.error(
                "bulk_approve_unexpected",
                extra={"candidate_id": str(candidate_id), "error": str(exc)},
            )
            response.failed.append({"id": str(candidate_id), "reason": "internal_error"})
    return response


@router.post("/silos/bulk-reject", response_model=SiloBulkResponse)
async def bulk_reject(
    body: SiloBulkRequest,
    auth: dict = Depends(require_auth),
) -> SiloBulkResponse:
    supabase = get_supabase()
    response = SiloBulkResponse()
    for candidate_id in body.ids:
        try:
            cand = (
                supabase.table("silo_candidates")
                .select("status")
                .eq("id", str(candidate_id))
                .single()
                .execute()
            )
            if not cand.data:
                response.failed.append(
                    {"id": str(candidate_id), "reason": "candidate_not_found"}
                )
                continue
            if cand.data["status"] == "in_progress":
                response.failed.append(
                    {"id": str(candidate_id), "reason": "in_progress_cannot_reject"}
                )
                continue
            supabase.table("silo_candidates").update(
                {"status": "rejected"}
            ).eq("id", str(candidate_id)).execute()
            response.succeeded.append(candidate_id)
        except Exception as exc:
            logger.error(
                "bulk_reject_unexpected",
                extra={"candidate_id": str(candidate_id), "error": str(exc)},
            )
            response.failed.append({"id": str(candidate_id), "reason": "internal_error"})
    return response


# ---------------------------------------------------------------------------
# GET /silos/metrics — dashboard header counts
# ---------------------------------------------------------------------------


@router.get("/silos/metrics", response_model=SiloMetricsResponse)
async def silo_metrics(
    client_id: UUID = Query(...),
    auth: dict = Depends(require_auth),
) -> SiloMetricsResponse:
    supabase = get_supabase()
    rows = (
        supabase.table("silo_candidates")
        .select("status, occurrence_count")
        .eq("client_id", str(client_id))
        .execute()
    ).data or []

    counts: dict[str, int] = {}
    occurrences: list[int] = []
    for r in rows:
        counts[r.get("status", "unknown")] = counts.get(r.get("status", "unknown"), 0) + 1
        occurrences.append(r.get("occurrence_count") or 1)

    threshold = settings.silo_frequent_threshold
    high_freq_count = sum(1 for n in occurrences if n >= threshold)
    avg_occurrence = round(sum(occurrences) / len(occurrences), 4) if occurrences else 0.0

    return SiloMetricsResponse(
        client_id=client_id,
        counts_by_status=counts,
        average_occurrence_count=avg_occurrence,
        high_frequency_threshold=threshold,
        high_frequency_count=high_freq_count,
    )

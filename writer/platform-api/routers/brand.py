"""AI Visibility (Brand Strength) — API routes.

Keyword/competitor CRUD, scan dispatch + status polling, mention history, and
trend rollups for each client's workspace. The scan runs as an async_jobs
'brand_scan' job (see services/brand_scan.py); these routes enqueue it and read
its results. Internal tool — `require_auth` only (no per-user client scoping).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from middleware.auth import require_auth
from models.brand import (
    BrandCompetitorCreateRequest,
    BrandCompetitorResponse,
    BrandKeywordCreateRequest,
    BrandKeywordResponse,
    BrandKeywordUpdateRequest,
    BrandScanRequest,
    BrandScanStartResponse,
    BrandScanStatusResponse,
    BrandScheduleResponse,
    BrandScheduleUpdateRequest,
)
from services import brand_schedule, brand_service

router = APIRouter(tags=["brand"])


# ── keywords ─────────────────────────────────────────────────────────────────
@router.get("/clients/{client_id}/brand/keywords", response_model=list[BrandKeywordResponse])
async def list_brand_keywords(
    client_id: UUID,
    include_inactive: bool = Query(True),
    auth: dict = Depends(require_auth),
):
    return brand_service.list_keywords(str(client_id), include_inactive=include_inactive)


@router.post("/clients/{client_id}/brand/keywords", response_model=BrandKeywordResponse)
async def add_brand_keyword(
    client_id: UUID,
    body: BrandKeywordCreateRequest,
    auth: dict = Depends(require_auth),
):
    return brand_service.add_keyword(str(client_id), body.keyword, body.category)


@router.patch("/clients/{client_id}/brand/keywords/{keyword_id}", response_model=BrandKeywordResponse)
async def update_brand_keyword(
    client_id: UUID,
    keyword_id: UUID,
    body: BrandKeywordUpdateRequest,
    auth: dict = Depends(require_auth),
):
    return brand_service.update_keyword(str(client_id), str(keyword_id), body.is_active, body.category)


@router.delete("/clients/{client_id}/brand/keywords/{keyword_id}")
async def delete_brand_keyword(
    client_id: UUID,
    keyword_id: UUID,
    auth: dict = Depends(require_auth),
):
    brand_service.delete_keyword(str(client_id), str(keyword_id))
    return {"ok": True}


# ── competitors ──────────────────────────────────────────────────────────────
@router.get("/clients/{client_id}/brand/competitors", response_model=list[BrandCompetitorResponse])
async def list_brand_competitors(client_id: UUID, auth: dict = Depends(require_auth)):
    return brand_service.list_competitors(str(client_id))


@router.post("/clients/{client_id}/brand/competitors", response_model=BrandCompetitorResponse)
async def add_brand_competitor(
    client_id: UUID,
    body: BrandCompetitorCreateRequest,
    auth: dict = Depends(require_auth),
):
    return brand_service.add_competitor(
        str(client_id), body.competitor_name, body.competitor_website, body.google_place_id
    )


@router.delete("/clients/{client_id}/brand/competitors/{competitor_id}")
async def delete_brand_competitor(
    client_id: UUID,
    competitor_id: UUID,
    auth: dict = Depends(require_auth),
):
    brand_service.delete_competitor(str(client_id), str(competitor_id))
    return {"ok": True}


# ── scans ────────────────────────────────────────────────────────────────────
@router.post("/clients/{client_id}/brand/scan", response_model=BrandScanStartResponse)
async def start_brand_scan(
    client_id: UUID,
    body: BrandScanRequest,
    auth: dict = Depends(require_auth),
):
    result = brand_service.start_scan(
        str(client_id),
        body.keyword_ids,
        body.engines,
        body.include_competitors,
        auth.get("user_id"),
    )
    return BrandScanStartResponse(job_id=result["job_id"], scan_batch_id=result["scan_batch_id"])


@router.get("/clients/{client_id}/brand/scan/{job_id}", response_model=BrandScanStatusResponse)
async def get_brand_scan_status(
    client_id: UUID,
    job_id: UUID,
    auth: dict = Depends(require_auth),
):
    return brand_service.get_scan_status(str(client_id), str(job_id))


# ── history / trends ─────────────────────────────────────────────────────────
@router.get("/clients/{client_id}/brand/history")
async def get_brand_history(
    client_id: UUID,
    limit: int = Query(200, ge=1, le=1000),
    engine: str | None = Query(None),
    keyword_id: UUID | None = Query(None),
    scan_batch_id: UUID | None = Query(None),
    auth: dict = Depends(require_auth),
):
    return brand_service.list_history(
        str(client_id),
        limit=limit,
        engine=engine,
        keyword_id=str(keyword_id) if keyword_id else None,
        scan_batch_id=str(scan_batch_id) if scan_batch_id else None,
    )


@router.get("/clients/{client_id}/brand/scans/{scan_batch_id}")
async def get_brand_scan_results(
    client_id: UUID,
    scan_batch_id: UUID,
    auth: dict = Depends(require_auth),
):
    return brand_service.list_history(str(client_id), limit=1000, scan_batch_id=str(scan_batch_id))


@router.get("/clients/{client_id}/brand/keyword-market")
async def get_brand_keyword_market(client_id: UUID, auth: dict = Depends(require_auth)):
    """CPC/volume/competition for active brand keywords (Lead Valuation card).
    Cache-first via the shared keyword_market table; best-effort live fill."""
    return await brand_service.get_keyword_market(str(client_id))


@router.get("/clients/{client_id}/brand/mentions/{mention_id}")
async def get_brand_mention(
    client_id: UUID,
    mention_id: UUID,
    auth: dict = Depends(require_auth),
):
    """Single mention incl. raw_response/retry_count (omitted from the history
    list for payload size) — fetched lazily by the frontend detail sheet."""
    return brand_service.get_mention(str(client_id), str(mention_id))


@router.get("/clients/{client_id}/brand/trends")
async def get_brand_trends(client_id: UUID, auth: dict = Depends(require_auth)):
    return brand_service.get_trends(str(client_id))


@router.get("/clients/{client_id}/brand/scans/{scan_batch_id}/insights")
async def get_brand_scan_insights(
    client_id: UUID,
    scan_batch_id: UUID,
    auth: dict = Depends(require_auth),
):
    """Batch-wide response-analysis insights: cross-engine consensus, discovered
    (untracked) competitors, and AIO mention-kind / source-type tallies."""
    return brand_service.get_scan_insights(str(client_id), str(scan_batch_id))


# ── insights ─────────────────────────────────────────────────────────────────
@router.post("/clients/{client_id}/brand/mentions/{mention_id}/diagnose")
async def diagnose_brand_mention(
    client_id: UUID,
    mention_id: UUID,
    auth: dict = Depends(require_auth),
):
    return await brand_service.diagnose_mention(str(client_id), str(mention_id))


@router.post("/clients/{client_id}/brand/suggest-keywords")
async def suggest_brand_keywords(client_id: UUID, auth: dict = Depends(require_auth)):
    return await brand_service.suggest_keywords_for_client(str(client_id))


@router.post("/clients/{client_id}/brand/report")
async def start_brand_report(client_id: UUID, auth: dict = Depends(require_auth)):
    from services.brand_report import enqueue_brand_report
    return {"job_id": enqueue_brand_report(str(client_id))}


@router.get("/clients/{client_id}/brand/report/{job_id}")
async def get_brand_report_status(client_id: UUID, job_id: UUID, auth: dict = Depends(require_auth)):
    return brand_service.get_report_status(str(client_id), str(job_id))


# ── schedule ─────────────────────────────────────────────────────────────────
@router.get("/clients/{client_id}/brand/schedule", response_model=BrandScheduleResponse)
async def get_brand_schedule(client_id: UUID, auth: dict = Depends(require_auth)):
    return brand_schedule.get_schedule(str(client_id))


@router.put("/clients/{client_id}/brand/schedule", response_model=BrandScheduleResponse)
async def set_brand_schedule(
    client_id: UUID,
    body: BrandScheduleUpdateRequest,
    auth: dict = Depends(require_auth),
):
    return brand_schedule.upsert_schedule(
        str(client_id), body.cadence, body.day_of_week, body.day_of_month,
        body.hour_utc, body.selected_engines, body.include_competitors, body.is_active,
    )

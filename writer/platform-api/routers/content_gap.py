"""Content Gap Analyzer API — the per-client "are we winning the SERP, and if
not what do the competitors above us have" workspace.

Phase 2 surface: the free `estimate` preflight, the ad-hoc `scan` trigger
(staff-gated, 503 while dark), the run list + detail reads, and a CSV export.
The heavy analysis is the async `content_gap_scan` job (services/content_gap.py);
these routes never spend directly — a scan enqueues a job that reserves its own
budget fail-closed. See docs/modules/content-gap-analyzer-prd-v1_0.md §8–§9.
"""

from __future__ import annotations

import csv
import io
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth, require_staff
from models.content_gap import (
    ContentGapScanRequest,
    ContentGapStatus,
    EstimateResponse,
    ScanResponse,
)
from services import content_gap

router = APIRouter(tags=["content-gap"])
logger = logging.getLogger(__name__)


@router.get("/clients/{client_id}/content-gap", response_model=ContentGapStatus)
async def content_gap_status(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Page bootstrap: enabled/auto flags, remaining budget, and the run history.

    Renders nothing (the dark-state gate) until `content_gap_enabled`, so a
    disabled module returns an empty run list rather than 403 — the workspace
    card hides itself on `enabled=false`."""
    try:
        runs = content_gap.list_runs(str(client_id)) if settings.content_gap_enabled else []
    except Exception as exc:  # noqa: BLE001
        logger.error("content_gap_status_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {
        "enabled": settings.content_gap_enabled,
        "auto_enabled": settings.content_gap_auto_enabled,
        "budget_remaining": content_gap.budget_remaining(),
        "runs": runs,
    }


@router.get("/clients/{client_id}/content-gap/estimate", response_model=EstimateResponse)
async def content_gap_estimate(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Free preflight (§8): the keyword × money-page scope + the worst-case paid
    call ceiling + today's remaining budget. No spend, no enqueue."""
    try:
        est = content_gap.estimate_scan(get_supabase(), str(client_id))
    except Exception as exc:  # noqa: BLE001
        logger.error("content_gap_estimate_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"enabled": settings.content_gap_enabled, **est}


@router.get("/clients/{client_id}/content-gap/runs")
async def content_gap_runs(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """The client's content-gap runs, newest first (summary rows)."""
    try:
        return {"runs": content_gap.list_runs(str(client_id))}
    except Exception as exc:  # noqa: BLE001
        logger.error("content_gap_runs_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/clients/{client_id}/content-gap/runs/{run_id}")
async def content_gap_run_detail(
    client_id: UUID, run_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """One run + its per-keyword rows (verdict + competitor set + per-dimension
    gap + on-page diff). Plain dict — the nested jsonb is returned verbatim so
    no dimension field is stripped. Poll `run.status` here for completion."""
    try:
        detail = content_gap.get_run_detail(str(client_id), str(run_id))
    except Exception as exc:  # noqa: BLE001
        logger.error("content_gap_run_detail_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return detail


@router.post("/clients/{client_id}/content-gap/scan", response_model=ScanResponse)
async def content_gap_scan(
    client_id: UUID,
    body: ContentGapScanRequest | None = None,
    auth: dict = Depends(require_staff),
) -> dict:
    """Enqueue an ad-hoc scan (staff-gated). 503 while the module is dark; 429
    when today's budget is exhausted. Returns the run id — poll
    `GET …/content-gap/runs/{run_id}` for status. Deduped against an in-flight
    run (returns the existing run id)."""
    if not settings.content_gap_enabled:
        raise HTTPException(status_code=503, detail="content_gap_disabled")
    if content_gap.budget_remaining() <= 0:
        raise HTTPException(status_code=429, detail="budget_exceeded")
    try:
        run_id = content_gap.enqueue_content_gap_scan(str(client_id), trigger="manual")
    except Exception as exc:  # noqa: BLE001
        logger.error("content_gap_scan_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not run_id:
        # enqueue returns None only when the module is disabled — guarded above,
        # so this is a defensive belt-and-suspenders.
        raise HTTPException(status_code=503, detail="content_gap_disabled")
    return {"run_id": run_id, "status": "pending"}


@router.get("/clients/{client_id}/content-gap/runs/{run_id}/export")
async def content_gap_export(
    client_id: UUID, run_id: UUID, auth: dict = Depends(require_auth)
) -> Response:
    """CSV export of a run's verdict table + headline authority/on-page deltas."""
    try:
        detail = content_gap.get_run_detail(str(client_id), str(run_id))
    except Exception as exc:  # noqa: BLE001
        logger.error("content_gap_export_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(content_gap.CSV_HEADERS)
    for row in content_gap.build_run_csv_rows(detail["keywords"]):
        w.writerow(["" if v is None else v for v in row])
    filename = f"content-gap-{run_id}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

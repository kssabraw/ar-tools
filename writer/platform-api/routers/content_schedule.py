"""Content Scheduler router — suite bulk page creation + scheduling.

Per-client, content-type-scoped batches: paste/upload a keyword list, choose a
page type, then create every page now or drip/weekly/monthly-schedule them.
Backed by services/content_schedule_store.py (persistence + planning) and
services/content_batch.py (generation job + release). "Create now" enqueues the
`content_batch_item` jobs immediately; scheduled batches are released by the
shared scheduler when each item comes due.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import ROLE_RANK, require_auth, role_rank
from models.content_batch import (
    ContentBatchCreateRequest,
    ContentBatchCreateResponse,
    ContentBatchEstimateRequest,
    ContentBatchEstimateResponse,
)
from services import content_batch, content_schedule_feed, content_schedule_store as store
from services.freeze import assert_not_frozen

router = APIRouter(tags=["content-scheduler"])
logger = logging.getLogger(__name__)


def _cost_per_type() -> dict[str, float]:
    return {
        "blog_post": settings.content_batch_cost_blog_usd,
        "service_page": settings.content_batch_cost_service_usd,
        "location_page": settings.content_batch_cost_location_usd,
        "local_seo_page": settings.content_batch_cost_local_seo_usd,
        "ecommerce": settings.content_batch_cost_ecommerce_usd,
    }


def _require_client(client_id: str) -> dict:
    row = (get_supabase().table("clients").select("*")
           .eq("id", client_id).single().execute()).data
    if not row:
        raise HTTPException(status_code=404, detail="client_not_found")
    return row


def _explicit_finish(items) -> Optional[date]:
    """The latest per-row publish Date across the batch (for the estimate's finish
    date), or None when no row is dated."""
    dates = [it.scheduled_date for it in items if getattr(it, "scheduled_date", None)]
    return max(dates) if dates else None


def _validate_items(content_type: str, items) -> None:
    """Per-content-type input requirements. Local SEO pages target a place, so each
    item needs a location (per-row). Its `keyword` carries the CSV "Service" column
    (a local SEO page is "<service> in <location>"), so a location-only row is
    dropped as blank upstream. Blog/service/ecommerce are keyword-only; location
    pages take a location as their head term but no per-row services."""
    if content_type == "local_seo_page":
        missing = [it.keyword for it in items if not (it.location or "").strip()]
        if missing:
            raise HTTPException(
                status_code=400,
                detail="local_seo_page items each need a location (e.g. a suburb/city).",
            )


@router.post(
    "/clients/{client_id}/content-batches/estimate",
    response_model=ContentBatchEstimateResponse,
)
async def estimate_batch(
    client_id: UUID, body: ContentBatchEstimateRequest, auth: dict = Depends(require_auth)
) -> ContentBatchEstimateResponse:
    """Preview a batch without creating it: count (after normalize/dedupe), the
    per-content-type cost, drip/weekly finish date, and whether a VA (team_member)
    would need senior approval."""
    _require_client(str(client_id))
    items, skipped = store.normalize_items(
        [i.model_dump() for i in body.items], max_items=settings.content_batch_max_items
    )
    est = store.estimate_batch(
        len(items), body.content_type, body.mode, cost_per_type=_cost_per_type(),
        per_day=body.per_day, start_date=body.start_date, time_of_day=body.time_of_day,
        tz_name=body.timezone, weekday=body.weekday, weekdays=body.weekdays,
        day_of_month=body.day_of_month, week_of_month=body.week_of_month,
        explicit_finish=_explicit_finish(items),
    )
    threshold = settings.content_batch_approval_threshold_usd
    requires_approval = (
        role_rank(auth["role"]) < ROLE_RANK["staff"] and est["cost_estimate_usd"] > threshold
    )
    return ContentBatchEstimateResponse(
        **est, skipped=skipped, requires_approval=requires_approval,
        approval_threshold_usd=threshold,
    )


@router.post(
    "/clients/{client_id}/content-batches",
    response_model=ContentBatchCreateResponse,
    status_code=202,
)
async def create_batch(
    client_id: UUID, body: ContentBatchCreateRequest, auth: dict = Depends(require_auth)
) -> ContentBatchCreateResponse:
    """Create a batch. `mode='now'` enqueues every page immediately; scheduled
    modes materialize items the shared scheduler releases when due. A VA over the
    approval threshold is refused with `requires_approval` (staff/admin never
    gated). Content creation is blocked under an active freeze."""
    cid = str(client_id)
    _require_client(cid)
    assert_not_frozen(cid)

    items, skipped = store.normalize_items(
        [i.model_dump() for i in body.items], max_items=settings.content_batch_max_items
    )
    if not items:
        raise HTTPException(status_code=400, detail="no_valid_keywords")
    _validate_items(body.content_type, items)

    est = store.estimate_batch(
        len(items), body.content_type, body.mode, cost_per_type=_cost_per_type(),
        per_day=body.per_day, start_date=body.start_date, time_of_day=body.time_of_day,
        tz_name=body.timezone, weekday=body.weekday, weekdays=body.weekdays,
        day_of_month=body.day_of_month, week_of_month=body.week_of_month,
        explicit_finish=_explicit_finish(items),
    )
    threshold = settings.content_batch_approval_threshold_usd
    est_resp = ContentBatchEstimateResponse(
        **est, skipped=skipped,
        requires_approval=(role_rank(auth["role"]) < ROLE_RANK["staff"]
                           and est["cost_estimate_usd"] > threshold),
        approval_threshold_usd=threshold,
    )
    if est_resp.requires_approval:
        return ContentBatchCreateResponse(
            status="requires_approval", created=False, count=len(items),
            skipped=skipped, estimate=est_resp,
        )

    try:
        batch = store.create_batch(
            client_id=cid, created_by=auth["user_id"], content_type=body.content_type,
            mode=body.mode, items=items, per_day=body.per_day, start_date=body.start_date,
            time_of_day=body.time_of_day, tz_name=body.timezone, weekday=body.weekday,
            weekdays=body.weekdays, day_of_month=body.day_of_month,
            week_of_month=body.week_of_month, auto_publish=body.auto_publish,
            wp_publish=body.wp_publish, wp_status=body.wp_status,
        )
    except ValueError as exc:                       # bad cadence params from the planner
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    enqueued = 0
    if body.mode == "now":
        enqueued = content_batch.enqueue_items(batch, batch.get("items") or [])

    logger.info("content_batch.created",
                extra={"batch_id": batch["id"], "content_type": body.content_type,
                       "mode": body.mode, "count": len(items), "enqueued": enqueued})
    return ContentBatchCreateResponse(
        status="created", created=True, batch_id=batch["id"], count=len(items),
        skipped=skipped, enqueued=enqueued, estimate=est_resp,
    )


@router.get("/clients/{client_id}/scheduled-content")
async def scheduled_content(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """The unified per-client feed for the workspace 'Scheduled Content' card:
    suite Content Scheduler batches + client-linked Fanout schedules, normalized
    and newest-first. Read-only; the Fanout half degrades to empty on any error."""
    return {"items": content_schedule_feed.unified_feed(str(client_id))}


@router.get("/clients/{client_id}/content-batches")
async def list_batches(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """The client's batches with live per-batch status counts."""
    cid = str(client_id)
    batches = store.list_batches(cid)
    progress = store.progress_by_batch(cid)
    empty = {s: 0 for s in ("scheduled", "queued", "running", "complete",
                            "failed", "cancelled")} | {"total": 0}
    for b in batches:
        b["progress"] = progress.get(b["id"], dict(empty))
    return {"batches": batches}


@router.get("/clients/{client_id}/content-batches/{batch_id}")
async def get_batch(
    client_id: UUID, batch_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """A single batch + its items."""
    batch = store.get_batch(str(batch_id))
    if not batch or batch["client_id"] != str(client_id):
        raise HTTPException(status_code=404, detail="batch_not_found")
    batch["items"] = store.list_items(str(batch_id))
    return batch


def _owned_batch(client_id: UUID, batch_id: UUID) -> dict:
    batch = store.get_batch(str(batch_id))
    if not batch or batch["client_id"] != str(client_id):
        raise HTTPException(status_code=404, detail="batch_not_found")
    return batch


@router.post("/clients/{client_id}/content-batches/{batch_id}/pause")
async def pause_batch(
    client_id: UUID, batch_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """Pause releases: the scheduler stops enqueuing this batch's scheduled items
    (already-running items finish). Only an active batch can be paused."""
    batch = _owned_batch(client_id, batch_id)
    if batch["status"] != "active":
        raise HTTPException(status_code=409, detail=f"batch_{batch['status']}")
    store.set_batch_status(str(batch_id), "paused")
    return {"status": "paused"}


@router.post("/clients/{client_id}/content-batches/{batch_id}/resume")
async def resume_batch(
    client_id: UUID, batch_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    batch = _owned_batch(client_id, batch_id)
    if batch["status"] != "paused":
        raise HTTPException(status_code=409, detail=f"batch_{batch['status']}")
    store.set_batch_status(str(batch_id), "active")
    return {"status": "active"}


@router.post("/clients/{client_id}/content-batches/{batch_id}/cancel")
async def cancel_batch(
    client_id: UUID, batch_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """Cancel the batch + all still-pending (scheduled/queued) items. Running/
    finished items are left as historical record."""
    _owned_batch(client_id, batch_id)
    cancelled = store.cancel_batch(str(batch_id))
    return {"status": "cancelled", "cancelled_items": cancelled}


@router.post("/clients/{client_id}/content-batches/{batch_id}/items/{item_id}/cancel")
async def cancel_item(
    client_id: UUID, batch_id: UUID, item_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """Cancel a single still-scheduled item (a released/running one can't be
    stopped)."""
    _owned_batch(client_id, batch_id)
    if not store.cancel_item(str(item_id)):
        raise HTTPException(status_code=409, detail="item_not_cancellable")
    store.complete_if_drained(str(batch_id))
    return {"status": "cancelled"}


@router.post("/clients/{client_id}/content-batches/{batch_id}/items/{item_id}/reinstate")
async def reinstate_item(
    client_id: UUID, batch_id: UUID, item_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """Un-cancel a scheduled item (reactivating the batch if it had settled)."""
    batch = _owned_batch(client_id, batch_id)
    if not store.reinstate_item(str(item_id)):
        raise HTTPException(status_code=409, detail="item_not_reinstatable")
    if batch["status"] in ("complete", "cancelled"):
        store.set_batch_status(str(batch_id), "active")
    return {"status": "scheduled"}

"""Content Syndication module router.

Per-client config (enable + cadence + content-type toggles + sharing mode), an
items list, an on-demand "Scan now", and a per-item retry. Discovery + rewrite +
publish run out of band in async jobs; the UI polls the items list while work is
in flight. All DB access uses the service-role client; any authenticated user may
operate it.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.syndication import (
    PublishRequest,
    PublishResponse,
    ScanResponse,
    SyndicationConfigResponse,
    SyndicationConfigUpdate,
    SyndicationCounts,
    SyndicationItem,
    SyndicationItemsResponse,
)
from services import syndication_service
from services.freeze import assert_not_frozen

logger = logging.getLogger(__name__)

router = APIRouter(tags=["syndication"])

_ITEM_FIELDS = (
    "id, source_url, content_type, title, status, rewritten_title, doc_url, "
    "sheet_url, error, first_seen_at, published_at"
)


def _require_client(client_id: str) -> None:
    rows = get_supabase().table("clients").select("id").eq("id", client_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="client_not_found")


@router.get("/clients/{client_id}/syndication/config", response_model=SyndicationConfigResponse)
async def get_config(client_id: UUID, auth: dict = Depends(require_auth)) -> SyndicationConfigResponse:
    _require_client(str(client_id))
    cfg = syndication_service.get_or_create_config(str(client_id))
    return SyndicationConfigResponse(**_config_view(cfg))


@router.put("/clients/{client_id}/syndication/config", response_model=SyndicationConfigResponse)
async def update_config(
    client_id: UUID, body: SyndicationConfigUpdate, auth: dict = Depends(require_auth)
) -> SyndicationConfigResponse:
    _require_client(str(client_id))
    syndication_service.get_or_create_config(str(client_id))  # ensure a row exists
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "interval_days" in updates:
        updates["interval_days"] = max(1, int(updates["interval_days"]))
    if updates:
        updates["updated_at"] = "now()"
        get_supabase().table("syndication_config").update(updates).eq(
            "client_id", str(client_id)
        ).execute()
    cfg = syndication_service.get_or_create_config(str(client_id))
    return SyndicationConfigResponse(**_config_view(cfg))


# Filter tab → the item statuses it covers. None = all.
_FILTER_STATUSES: dict[str, Optional[list[str]]] = {
    "all": None,
    "published": ["published"],
    "failed": ["failed"],
    "not_published": ["discovered", "rewriting", "skipped"],
}


def _count(supabase, client_id: str, statuses: Optional[list[str]]) -> int:
    q = (
        supabase.table("syndication_items")
        .select("id", count="exact")
        .eq("client_id", client_id)
    )
    if statuses is not None:
        q = q.in_("status", statuses)
    res = q.limit(1).execute()
    return res.count or 0


@router.get("/clients/{client_id}/syndication/items", response_model=SyndicationItemsResponse)
async def list_items(
    client_id: UUID,
    filter: str = Query(default="all"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    auth: dict = Depends(require_auth),
) -> SyndicationItemsResponse:
    """Paginated items for one tab, plus per-tab counts for the filter bar."""
    supabase = get_supabase()
    cid = str(client_id)

    total = _count(supabase, cid, None)
    published = _count(supabase, cid, ["published"])
    failed = _count(supabase, cid, ["failed"])
    counts = SyndicationCounts(
        all=total,
        published=published,
        failed=failed,
        not_published=max(0, total - published - failed),
    )

    statuses = _FILTER_STATUSES.get(filter, None)
    query = (
        supabase.table("syndication_items")
        .select(_ITEM_FIELDS)
        .eq("client_id", cid)
    )
    if statuses is not None:
        query = query.in_("status", statuses)
    rows = (
        query.order("first_seen_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
        .data
        or []
    )
    return SyndicationItemsResponse(
        items=[SyndicationItem(**r) for r in rows], counts=counts
    )


@router.post("/clients/{client_id}/syndication/scan", response_model=ScanResponse)
async def scan_now(client_id: UUID, auth: dict = Depends(require_auth)) -> ScanResponse:
    """Enqueue an on-demand scan (deduped against an in-flight scan)."""
    _require_client(str(client_id))
    job_id = syndication_service.enqueue_scan(str(client_id))
    return ScanResponse(job_id=job_id, status="enqueued" if job_id else "already_running")


@router.post("/clients/{client_id}/syndication/publish", response_model=PublishResponse)
async def publish_selected(
    client_id: UUID, body: PublishRequest, auth: dict = Depends(require_auth)
) -> PublishResponse:
    """Rewrite + publish the selected discovered items (to Doc / Sheet / Both per
    the client's publish_target setting), public per share_mode."""
    _require_client(str(client_id))
    assert_not_frozen(str(client_id))  # Freeze Protocol: publishing paused
    ids = [str(i) for i in body.item_ids]
    queued = syndication_service.publish_items(str(client_id), ids)
    return PublishResponse(queued=queued)


@router.post("/clients/{client_id}/syndication/items/{item_id}/retry", response_model=ScanResponse)
async def retry_item(
    client_id: UUID, item_id: UUID, auth: dict = Depends(require_auth)
) -> ScanResponse:
    rows = (
        get_supabase().table("syndication_items")
        .select("id")
        .eq("id", str(item_id))
        .eq("client_id", str(client_id))
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="item_not_found")
    job_id = syndication_service.retry_item(str(item_id))
    return ScanResponse(job_id=job_id, status="enqueued" if job_id else "already_running")


def _config_view(cfg: dict) -> dict:
    """Normalize a config row (or in-memory default) into the response shape."""
    last = cfg.get("last_scan_date")
    return {
        "client_id": str(cfg.get("client_id")),
        "enabled": bool(cfg.get("enabled", False)),
        "interval_days": int(cfg.get("interval_days") or 1),
        "include_blog": bool(cfg.get("include_blog", True)),
        "include_pages": bool(cfg.get("include_pages", True)),
        "include_products": bool(cfg.get("include_products", True)),
        "share_mode": cfg.get("share_mode") or "public",
        "publish_target": cfg.get("publish_target") or "both",
        "last_scan_date": str(last) if last else None,
    }

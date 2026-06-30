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
    ScanResponse,
    SyndicationConfigResponse,
    SyndicationConfigUpdate,
    SyndicationItem,
)
from services import syndication_service

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


@router.get("/clients/{client_id}/syndication/items", response_model=list[SyndicationItem])
async def list_items(
    client_id: UUID,
    status: Optional[str] = Query(default=None),
    content_type: Optional[str] = Query(default=None),
    auth: dict = Depends(require_auth),
) -> list[SyndicationItem]:
    query = (
        get_supabase().table("syndication_items")
        .select(_ITEM_FIELDS)
        .eq("client_id", str(client_id))
    )
    if status:
        query = query.eq("status", status)
    if content_type:
        query = query.eq("content_type", content_type)
    rows = query.order("first_seen_at", desc=True).limit(500).execute().data or []
    return [SyndicationItem(**r) for r in rows]


@router.post("/clients/{client_id}/syndication/scan", response_model=ScanResponse)
async def scan_now(client_id: UUID, auth: dict = Depends(require_auth)) -> ScanResponse:
    """Enqueue an on-demand scan (deduped against an in-flight scan)."""
    _require_client(str(client_id))
    job_id = syndication_service.enqueue_scan(str(client_id))
    return ScanResponse(job_id=job_id, status="enqueued" if job_id else "already_running")


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
        "last_scan_date": str(last) if last else None,
    }

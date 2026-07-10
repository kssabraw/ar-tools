"""Backlink explorer API — an any-domain Site Explorer over the DataForSEO
Backlinks API family (services/backlink_explorer.py).

Overview / referring domains / anchors / history are cached per target (24h
TTL); the individual-link list is fetched on demand with a one-per-domain
default to bound cost.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import settings
from middleware.auth import require_auth
from services import backlink_explorer

router = APIRouter(tags=["backlinks"])
logger = logging.getLogger(__name__)


class BacklinkLookupRequest(BaseModel):
    target: str
    client_id: Optional[UUID] = None
    force: bool = False


@router.post("/backlinks/lookup")
async def backlink_lookup(body: BacklinkLookupRequest, auth: dict = Depends(require_auth)) -> dict:
    """Overview + referring domains + anchors + history for any domain/url.
    Served from cache when a snapshot is within the TTL (unless `force`)."""
    if not (settings.dataforseo_login and settings.dataforseo_password):
        raise HTTPException(status_code=503, detail="dataforseo_not_configured")
    try:
        return await backlink_explorer.lookup(
            body.target,
            client_id=str(body.client_id) if body.client_id else None,
            created_by=auth.get("sub"),
            force=body.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("backlink_lookup_failed", extra={"target": body.target, "error": str(exc)})
        raise HTTPException(status_code=502, detail="backlink_provider_error") from exc


@router.get("/backlinks/links")
async def backlink_links(
    target: str = Query(...),
    filter: str = Query("all", pattern="^(all|dofollow|nofollow|new|lost|broken)$"),
    mode: str = Query("one_per_domain"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    auth: dict = Depends(require_auth),
) -> dict:
    """The individual-link list (paginated, filterable). Defaults to
    one-per-domain to bound the billed rows."""
    if not (settings.dataforseo_login and settings.dataforseo_password):
        raise HTTPException(status_code=503, detail="dataforseo_not_configured")
    try:
        return await backlink_explorer.list_links(
            target, filter_key=filter, mode=mode, limit=limit, offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("backlink_links_failed", extra={"target": target, "error": str(exc)})
        raise HTTPException(status_code=502, detail="backlink_provider_error") from exc

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
    except backlink_explorer.BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail="backlink_budget_exceeded") from exc
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
    except backlink_explorer.BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail="backlink_budget_exceeded") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("backlink_links_failed", extra={"target": target, "error": str(exc)})
        raise HTTPException(status_code=502, detail="backlink_provider_error") from exc


# ----------------------------------------------------------------------------
# Tracked targets (client-scoped) — scheduled re-snapshots + new/lost alerts
# ----------------------------------------------------------------------------
class TrackRequest(BaseModel):
    target: str
    label: Optional[str] = None


@router.get("/clients/{client_id}/backlinks/tracked")
async def list_tracked(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Tracked targets for a client + each one's latest snapshot summary."""
    try:
        return {"tracked": backlink_explorer.list_tracked(str(client_id))}
    except Exception as exc:
        logger.error("backlink_tracked_list_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/clients/{client_id}/backlinks/tracked")
async def track(client_id: UUID, body: TrackRequest, auth: dict = Depends(require_auth)) -> dict:
    """Track a domain for this client (its own or a competitor's) + kick a first capture."""
    try:
        return backlink_explorer.track_target(
            str(client_id), body.target, label=body.label, created_by=auth.get("sub"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("backlink_track_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.delete("/clients/{client_id}/backlinks/tracked/{target_id}")
async def untrack(client_id: UUID, target_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Stop tracking a target (its snapshots are kept)."""
    try:
        backlink_explorer.untrack_target(str(client_id), str(target_id))
        return {"ok": True}
    except Exception as exc:
        logger.error("backlink_untrack_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc

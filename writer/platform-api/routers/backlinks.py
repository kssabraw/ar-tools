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
from services import authority_report, backlink_explorer

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
# Lazy tab loads — referring-domains list + anchors are NOT part of the default
# lookup; each is one explicit paid call, cached onto the latest snapshot.
# ----------------------------------------------------------------------------
async def _lazy_route(loader, target: str, client_id: Optional[UUID], force: bool) -> dict:
    if not (settings.dataforseo_login and settings.dataforseo_password):
        raise HTTPException(status_code=503, detail="dataforseo_not_configured")
    try:
        return await loader(target, client_id=str(client_id) if client_id else None, force=force)
    except backlink_explorer.BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail="backlink_budget_exceeded") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("backlink_lazy_load_failed", extra={"target": target, "error": str(exc)})
        raise HTTPException(status_code=502, detail="backlink_provider_error") from exc


@router.get("/backlinks/referring-domains")
async def backlink_referring_domains(
    target: str = Query(...),
    client_id: Optional[UUID] = Query(None),
    force: bool = Query(False),
    auth: dict = Depends(require_auth),
) -> dict:
    """The referring-domains list for a looked-up target (lazy tab load)."""
    return await _lazy_route(backlink_explorer.load_referring_domains, target, client_id, force)


@router.get("/backlinks/anchors")
async def backlink_anchors(
    target: str = Query(...),
    client_id: Optional[UUID] = Query(None),
    force: bool = Query(False),
    auth: dict = Depends(require_auth),
) -> dict:
    """The anchor-text distribution for a looked-up target (lazy tab load)."""
    return await _lazy_route(backlink_explorer.load_anchors, target, client_id, force)


# ----------------------------------------------------------------------------
# Authority reports (RD / DR / UR) — the rank trackers' on-demand comparison of
# link authority vs the competitors each tracker already knows about.
# ----------------------------------------------------------------------------
class OrganicAuthorityRequest(BaseModel):
    keyword_id: UUID


@router.post("/clients/{client_id}/authority/organic")
async def organic_authority(
    client_id: UUID, body: OrganicAuthorityRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Fresh RD/DR/UR for everyone in a tracked keyword's latest SERP snapshot
    (2 paid bulk calls). Returns needs_snapshot when no snapshot exists yet."""
    if not (settings.dataforseo_login and settings.dataforseo_password):
        raise HTTPException(status_code=503, detail="dataforseo_not_configured")
    try:
        return await authority_report.build_organic_authority(str(client_id), str(body.keyword_id))
    except backlink_explorer.BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail="backlink_budget_exceeded") from exc
    except Exception as exc:
        logger.error("authority_organic_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=502, detail="backlink_provider_error") from exc


@router.post("/clients/{client_id}/authority/maps")
async def maps_authority(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Fresh RD/DR/homepage-UR for the latest geo-grid scan's local-pack
    leaderboard vs the client (2 paid bulk calls). needs_scan when no scan."""
    if not (settings.dataforseo_login and settings.dataforseo_password):
        raise HTTPException(status_code=503, detail="dataforseo_not_configured")
    try:
        return await authority_report.build_maps_authority(str(client_id))
    except backlink_explorer.BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail="backlink_budget_exceeded") from exc
    except Exception as exc:
        logger.error("authority_maps_failed", extra={"client_id": str(client_id), "error": str(exc)})
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

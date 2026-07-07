"""Competitive intelligence API — the per-client competitor registry +
assembled cross-module profiles (services/competitor_intel.py)."""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from services import competitor_intel

router = APIRouter(tags=["competitors"])
logger = logging.getLogger(__name__)


class CompetitorAddRequest(BaseModel):
    name: str
    domain: Optional[str] = None
    place_id: Optional[str] = None
    notes: Optional[str] = None


@router.get("/clients/{client_id}/competitors")
async def list_competitors(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """The assembled profiles (registry × every module) + client comparison."""
    try:
        return competitor_intel.build_profiles(str(client_id))
    except Exception as exc:
        logger.error("competitors_list_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/clients/{client_id}/competitors")
async def add_competitor(
    client_id: UUID, body: CompetitorAddRequest, auth: dict = Depends(require_auth)
) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name_required")
    domain = competitor_intel.normalize_domain(body.domain)
    try:
        row = (
            get_supabase().table("client_competitors").insert({
                "client_id": str(client_id),
                "name": name,
                "domain": domain,
                "place_id": (body.place_id or "").strip() or None,
                "sources": ["manual"],
                "notes": body.notes,
            }).execute()
        ).data[0]
    except Exception as exc:
        if "uq_client_competitors" in str(exc) or "duplicate" in str(exc).lower():
            raise HTTPException(status_code=409, detail="competitor_exists") from exc
        logger.error("competitors_add_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return row


@router.delete("/clients/{client_id}/competitors/{competitor_id}")
async def remove_competitor(
    client_id: UUID, competitor_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """Deactivate (auto-discovery will not resurrect a deactivated row —
    matches by identity and only updates, never re-activates)."""
    try:
        rows = (
            get_supabase().table("client_competitors")
            .update({"active": False})
            .eq("id", str(competitor_id)).eq("client_id", str(client_id)).execute()
        ).data
    except Exception as exc:
        logger.error("competitors_remove_failed", extra={"competitor_id": str(competitor_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not rows:
        raise HTTPException(status_code=404, detail="competitor_not_found")
    return {"status": "deactivated"}


@router.post("/clients/{client_id}/competitors/sync")
async def sync_now(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Run discovery + content watch now (async job; poll the list)."""
    try:
        job_id = competitor_intel.enqueue_competitor_intel(str(client_id))
    except Exception as exc:
        logger.error("competitors_sync_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"job_id": job_id}


@router.get("/clients/{client_id}/competitors/sync/{job_id}")
async def sync_status(client_id: UUID, job_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    rows = (
        get_supabase().table("async_jobs").select("id, status, result, error")
        .eq("id", str(job_id)).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="job_not_found")
    return rows[0]

"""Domain Intelligence API — the per-client competitive-intelligence workspace
(the "SEMrush clone"). Phase 1: Domain Overview + Ranked Keywords.

Enter any domain (a competitor, a prospect, the client's own site) → an async
Domain Overview snapshot (traffic/keyword-count/authority estimate + every
keyword it ranks for). See docs/modules/domain-intelligence-module-prd-v1_0.md.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth
from services import domain_intel

router = APIRouter(tags=["domain-intel"])
logger = logging.getLogger(__name__)


class OverviewRequest(BaseModel):
    target_domain: str
    role: str = "competitor"
    location_code: Optional[int] = None
    language_code: Optional[str] = None
    force: bool = False


class KeywordGapRequest(BaseModel):
    # Optional explicit competitor domains; when omitted the client's registered
    # competitors are used.
    competitor_domains: Optional[list[str]] = None
    location_code: Optional[int] = None
    language_code: Optional[str] = None


class LinkGapRequest(BaseModel):
    competitor_domains: Optional[list[str]] = None


@router.get("/clients/{client_id}/domain-intel")
async def list_domain_snapshots(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """History of analyzed domains for the client (summary rows, newest first)."""
    try:
        return {
            "enabled": settings.domain_intel_enabled,
            "budget_remaining": domain_intel.budget_remaining(),
            "snapshots": domain_intel.list_snapshots(str(client_id)),
        }
    except Exception as exc:
        logger.error("domain_intel_list_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/clients/{client_id}/domain-intel/overview/{target_domain}")
async def get_overview(
    client_id: UUID, target_domain: str, auth: dict = Depends(require_auth)
) -> dict:
    """Latest snapshot + ranked keywords for a domain (null when never analyzed)."""
    try:
        result = domain_intel.get_latest_overview(str(client_id), target_domain)
    except Exception as exc:
        logger.error("domain_intel_get_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return result or {"snapshot": None, "ranked_keywords": []}


@router.post("/clients/{client_id}/domain-intel/overview")
async def start_overview(
    client_id: UUID, body: OverviewRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Enqueue a Domain Overview analysis (poll the job, then GET the overview)."""
    if not settings.domain_intel_enabled:
        raise HTTPException(status_code=403, detail="domain_intel_disabled")
    domain = domain_intel.normalize_domain(body.target_domain)
    if not domain:
        raise HTTPException(status_code=422, detail="invalid_domain")
    if body.role not in ("competitor", "client", "prospect"):
        raise HTTPException(status_code=422, detail="invalid_role")
    if domain_intel.budget_remaining() <= 0:
        raise HTTPException(status_code=429, detail="budget_exceeded")
    try:
        job_id = domain_intel.enqueue_domain_overview(
            str(client_id), domain, role=body.role,
            location_code=body.location_code, language_code=body.language_code,
            force=body.force,
        )
    except Exception as exc:
        logger.error("domain_intel_start_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"job_id": job_id, "target_domain": domain}


@router.get("/clients/{client_id}/domain-intel/keyword-gap")
async def get_keyword_gap(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """The client's current keyword-gap set (latest run), ordered by opportunity."""
    try:
        return domain_intel.get_keyword_gaps(str(client_id))
    except Exception as exc:
        logger.error("keyword_gap_get_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/clients/{client_id}/domain-intel/keyword-gap")
async def start_keyword_gap(
    client_id: UUID, body: KeywordGapRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Enqueue a Keyword Gap analysis (client vs competitors). Poll the job."""
    if not settings.domain_intel_enabled:
        raise HTTPException(status_code=403, detail="domain_intel_disabled")
    if domain_intel.budget_remaining() <= 0:
        raise HTTPException(status_code=429, detail="budget_exceeded")
    try:
        job_id = domain_intel.enqueue_keyword_gap(
            str(client_id), competitor_domains=body.competitor_domains,
            location_code=body.location_code, language_code=body.language_code,
        )
    except Exception as exc:
        logger.error("keyword_gap_start_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"job_id": job_id}


@router.get("/clients/{client_id}/domain-intel/link-gap")
async def get_link_gap(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """The client's current backlink-gap set (referring domains it lacks)."""
    try:
        return domain_intel.get_link_gaps(str(client_id))
    except Exception as exc:
        logger.error("link_gap_get_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/clients/{client_id}/domain-intel/link-gap")
async def start_link_gap(
    client_id: UUID, body: LinkGapRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Enqueue a Backlink Gap analysis (referring domains competitors have, client lacks)."""
    if not settings.domain_intel_enabled:
        raise HTTPException(status_code=403, detail="domain_intel_disabled")
    if domain_intel.budget_remaining() <= 0:
        raise HTTPException(status_code=429, detail="budget_exceeded")
    try:
        job_id = domain_intel.enqueue_link_gap(str(client_id), competitor_domains=body.competitor_domains)
    except Exception as exc:
        logger.error("link_gap_start_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"job_id": job_id}


@router.get("/clients/{client_id}/domain-intel/discover")
async def discover(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """SERP-overlap competitor suggestions for the client's own domain (1 paid call)."""
    if not settings.domain_intel_enabled:
        raise HTTPException(status_code=403, detail="domain_intel_disabled")
    if domain_intel.budget_remaining() <= 0:
        raise HTTPException(status_code=429, detail="budget_exceeded")
    try:
        return await domain_intel.discover_competitors(str(client_id))
    except domain_intel.BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail="budget_exceeded") from exc
    except Exception as exc:
        logger.error("domain_intel_discover_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/clients/{client_id}/domain-intel/jobs/{job_id}")
async def overview_status(
    client_id: UUID, job_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    rows = (
        get_supabase().table("async_jobs").select("id, status, result, error")
        .eq("id", str(job_id)).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="job_not_found")
    return rows[0]

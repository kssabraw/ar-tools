"""Audit modules — trigger + read engagement audits (Phase 3).

Starts with the site/technical audit (§6.2); backlink-gap and local-citation
land next. Internal tool — `require_auth` only.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from services import backlink_gap, citation_audit, site_audit

router = APIRouter(tags=["audits"])


@router.post("/engagements/{engagement_id}/audits/site")
async def trigger_site_audit(engagement_id: UUID, auth: dict = Depends(require_auth)):
    site_audit.enqueue_site_audit(str(engagement_id))
    return {"status": "enqueued"}


@router.post("/engagements/{engagement_id}/audits/backlinks")
async def trigger_backlink_audit(engagement_id: UUID, auth: dict = Depends(require_auth)):
    backlink_gap.enqueue_backlink_audit(str(engagement_id))
    return {"status": "enqueued"}


@router.post("/engagements/{engagement_id}/audits/citations")
async def trigger_citation_audit(engagement_id: UUID, auth: dict = Depends(require_auth)):
    citation_audit.enqueue_citation_audit(str(engagement_id))
    return {"status": "enqueued"}


@router.get("/engagements/{engagement_id}/audits")
async def list_audits(engagement_id: UUID, auth: dict = Depends(require_auth)):
    return (
        get_supabase().table("audit_runs").select("*")
        .eq("engagement_id", str(engagement_id))
        .order("created_at", desc=True).limit(20).execute()
    ).data or []

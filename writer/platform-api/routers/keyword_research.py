"""Keyword Research API — the per-client seed-keyword explorer.

Enter seed keyword(s) → an async run that expands them (DataForSEO Labs keyword
ideas), enriches each with volume / CPC / competition / KD / intent, and
auto-clusters them into topic groups. Save & CSV export; no content generation.
This module backs the "Keyword Research" workspace card (the Topic Fanout, which
it replaced there, remains behind "Create Mass Posts").
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
from services import keyword_research, keyword_research_report

router = APIRouter(tags=["keyword-research"])
logger = logging.getLogger(__name__)


class ResearchRequest(BaseModel):
    # Seed keyword(s): a string (comma/newline-separated) or an explicit list.
    seeds: object
    location_code: Optional[int] = None
    language_code: Optional[str] = None


@router.get("/clients/{client_id}/keyword-research")
async def list_research(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Research-run history for the client (summary rows, newest first)."""
    try:
        return {
            "enabled": settings.keyword_research_enabled,
            "budget_remaining": keyword_research.budget_remaining(),
            "runs": keyword_research.list_runs(str(client_id)),
        }
    except Exception as exc:
        logger.error("keyword_research_list_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/clients/{client_id}/keyword-research/runs/{run_id}")
async def get_research_run(
    client_id: UUID, run_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """A run's keywords + clusters (null when the run doesn't exist for this client)."""
    try:
        result = keyword_research.get_run(str(client_id), str(run_id))
    except Exception as exc:
        logger.error("keyword_research_get_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return result or {"run": None, "keywords": [], "clusters": []}


@router.post("/clients/{client_id}/keyword-research")
async def start_research(
    client_id: UUID, body: ResearchRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Enqueue a keyword research run (poll the job, then GET the run)."""
    if not settings.keyword_research_enabled:
        raise HTTPException(status_code=403, detail="keyword_research_disabled")
    seeds = keyword_research.parse_seeds(body.seeds)
    if not seeds:
        raise HTTPException(status_code=422, detail="no_seeds")
    if keyword_research.budget_remaining() <= 0:
        raise HTTPException(status_code=429, detail="budget_exceeded")
    try:
        job_id = keyword_research.enqueue_keyword_research(
            str(client_id), seeds,
            location_code=body.location_code, language_code=body.language_code,
        )
    except Exception as exc:
        logger.error("keyword_research_start_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"job_id": job_id, "seeds": seeds}


@router.post("/clients/{client_id}/keyword-research/runs/{run_id}/report")
async def create_report(
    client_id: UUID, run_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """Generate a client-facing PDF report for a run (synchronous: build →
    exec-summary → PDF → store → Drive copy). Returns the report + download link."""
    try:
        return keyword_research_report.generate_report(
            str(client_id), str(run_id), user_id=auth.get("sub") or auth.get("user_id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("keyword_research_report_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/clients/{client_id}/keyword-research/reports")
async def list_reports(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Report history for the client (newest first)."""
    try:
        return {"reports": keyword_research_report.list_reports(str(client_id))}
    except Exception as exc:
        logger.error("keyword_research_reports_list_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/clients/{client_id}/keyword-research/reports/{report_id}/download")
async def download_report(
    client_id: UUID, report_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """A fresh signed download URL for a stored report PDF."""
    url = keyword_research_report.report_download_url(str(client_id), str(report_id))
    if not url:
        raise HTTPException(status_code=404, detail="report_not_found")
    return {"download_url": url}


@router.get("/clients/{client_id}/keyword-research/jobs/{job_id}")
async def research_status(
    client_id: UUID, job_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    rows = (
        get_supabase().table("async_jobs").select("id, status, result, error")
        .eq("id", str(job_id)).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="job_not_found")
    return rows[0]

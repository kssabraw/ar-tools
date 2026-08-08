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
from services import (
    keyword_research,
    keyword_research_content,
    keyword_research_handoff,
    keyword_research_report,
    keyword_research_seeds,
    keyword_topic_research,
)

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


@router.delete("/clients/{client_id}/keyword-research")
async def clear_research(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Clear ALL keyword research runs for the client (start over). Child keyword
    and report rows cascade-delete. Returns the number of runs removed."""
    try:
        deleted = keyword_research.clear_runs(str(client_id))
    except Exception as exc:
        logger.error("keyword_research_clear_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"deleted": deleted}


@router.get("/clients/{client_id}/keyword-research/seed-suggestions")
async def seed_suggestions(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Suggest seed keywords/topics to start research from, grounded in the
    client's business context (GBP category, location, ICP, website). Best-effort:
    falls back to a deterministic GBP-derived set when no LLM key is configured.
    Returns {seeds, grounded, source}."""
    try:
        return keyword_research_seeds.suggest_seeds(str(client_id))
    except Exception as exc:
        logger.error("keyword_research_seed_suggestions_failed",
                     extra={"client_id": str(client_id), "error": str(exc)})
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


class RemoveSeedRequest(BaseModel):
    seed: str


@router.post("/clients/{client_id}/keyword-research/runs/{run_id}/remove-seed")
async def remove_seed(
    client_id: UUID, run_id: UUID, body: RemoveSeedRequest,
    auth: dict = Depends(require_auth),
) -> dict:
    """Remove one seed from a multi-seed run and delete the keywords it solely
    produced (keywords also from another seed are kept). The run must keep at
    least two seeds. Returns the updated {seeds, removed_keywords, keyword_count,
    cluster_count}."""
    try:
        return keyword_research.remove_seed(str(client_id), str(run_id), body.seed)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("keyword_research_remove_seed_failed",
                     extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


class ToSchedulerRequest(BaseModel):
    keywords: list[str]


@router.post("/clients/{client_id}/keyword-research/runs/{run_id}/to-scheduler")
async def to_scheduler(
    client_id: UUID, run_id: UUID, body: ToSchedulerRequest,
    auth: dict = Depends(require_auth),
) -> dict:
    """Turn selected research keywords into a ready-to-schedule Content Scheduler
    (Fanout) session — one article per keyword. Returns {session_id,
    cluster_count, schedule_url} for the frontend to navigate to."""
    if not body.keywords:
        raise HTTPException(status_code=422, detail="no_keywords")
    try:
        return keyword_research_handoff.send_keywords_to_scheduler(
            str(client_id), str(run_id), body.keywords, auth["user_id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("keyword_research_to_scheduler_failed",
                     extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


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


@router.post("/clients/{client_id}/topic-research")
async def start_topic_research(
    client_id: UUID, body: ResearchRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Start a problem-first Topic Research run (async): buyer problem-themes →
    real demand (PAA + suggestions) → competitor mining → ranked topic cards.
    Seeds are optional context (the engine works from the ICP + site themes)."""
    try:
        seeds = keyword_research.parse_seeds(body.seeds)
        job_id = keyword_topic_research.enqueue_topic_research(
            str(client_id), seeds, location_code=body.location_code,
            language_code=body.language_code)
        return {"job_id": job_id, "seeds": seeds}
    except Exception as exc:
        logger.error("topic_research_start_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/clients/{client_id}/topic-research")
async def topic_research_history(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Topic-research run history + the latest run's topic cards."""
    try:
        return {
            "runs": keyword_topic_research.list_runs(str(client_id)),
            "latest": keyword_topic_research.latest_run(str(client_id)),
            "budget_remaining": keyword_research.budget_remaining(),
        }
    except Exception as exc:
        logger.error("topic_research_history_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/clients/{client_id}/topic-research/runs/{run_id}")
async def topic_research_run(client_id: UUID, run_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """One topic-research run (its topic cards + competitors)."""
    run = keyword_topic_research.get_run(str(client_id), str(run_id))
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    return {"run": run}


@router.get("/clients/{client_id}/topic-research/jobs/{job_id}")
async def topic_research_job(client_id: UUID, job_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Poll a topic-research async job."""
    rows = (get_supabase().table("async_jobs").select("id, status, error, result")
            .eq("id", str(job_id)).limit(1).execute()).data
    if not rows:
        raise HTTPException(status_code=404, detail="job_not_found")
    return rows[0]


@router.post("/clients/{client_id}/keyword-research/runs/{run_id}/blog-topics")
async def blog_topics(
    client_id: UUID, run_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """Generate blog post ideas from a run's BUYER-FIT keywords + the client's ICP
    (one LLM call, cached on the run). Returns {topics, generated}."""
    try:
        return keyword_research_content.generate_blog_topics(str(client_id), str(run_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("keyword_research_blog_topics_failed",
                     extra={"client_id": str(client_id), "error": str(exc)})
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

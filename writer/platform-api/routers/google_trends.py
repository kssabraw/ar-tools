"""Google Trends Discovery API — the per-client rising-query scanner.

Enter seed keyword(s) (optionally filtered to a Google Trends category) → an async
scan that pulls RISING related queries from Google Trends (via DataForSEO), qualifies
each with volume/CPC, scores by velocity × the existing opportunity model, and
persists a run. Phase 1 (ecommerce, keyword-anchored). Downstream (cluster / draft /
"Write this post") reuses existing modules. Ships dark behind google_trends_enabled.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_admin, require_auth
from services import google_trends

router = APIRouter(tags=["google-trends"])
logger = logging.getLogger(__name__)


class TrendsScanRequest(BaseModel):
    # Seed keyword(s): a string (comma/newline-separated) or an explicit list.
    seeds: object
    category_code: Optional[int] = None
    category_name: Optional[str] = None
    location_code: Optional[int] = None
    language_code: Optional[str] = None
    trends_type: Optional[str] = None


class TrendsCategoryScanRequest(BaseModel):
    # Phase 2: a SEEDLESS category scan — seeds are derived from the client's own
    # site topics/ICP, so only the category (+ optional geo/type) is supplied.
    category_code: Optional[int] = None
    category_name: Optional[str] = None
    location_code: Optional[int] = None
    language_code: Optional[str] = None
    trends_type: Optional[str] = None


class TrendsSeasonalRequest(BaseModel):
    # Phase 4: local seasonal — keyword(s) + a metro location.
    keywords: object
    location_code: Optional[int] = None
    language_code: Optional[str] = None


def _require_enabled() -> None:
    if not settings.google_trends_enabled:
        raise HTTPException(status_code=503, detail="google_trends_not_enabled")


@router.get("/clients/{client_id}/google-trends")
async def list_scans(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Scan-run history for the client (summary rows, newest first)."""
    try:
        return {
            "enabled": settings.google_trends_enabled,
            "budget_remaining": google_trends.budget_remaining(),
            "runs": google_trends.list_runs(str(client_id)),
        }
    except Exception as exc:
        logger.error("google_trends_list_failed",
                     extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.delete("/clients/{client_id}/google-trends")
async def clear_scans(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Clear ALL Google Trends scans for the client. Child rows cascade."""
    try:
        removed = google_trends.clear_runs(str(client_id))
        return {"removed": removed}
    except Exception as exc:
        logger.error("google_trends_clear_failed",
                     extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/google-trends/categories")
async def categories(auth: dict = Depends(require_auth)) -> dict:
    """The Google Trends category tree for the scan-form dropdown (free endpoint,
    cached). Degrades to an empty list when unreachable — the form falls back to a
    free-text category code."""
    try:
        return {"categories": await google_trends.fetch_categories()}
    except Exception as exc:
        logger.warning("google_trends_categories_failed", extra={"error": str(exc)})
        return {"categories": []}


@router.get("/clients/{client_id}/google-trends/runs/{run_id}")
async def get_scan(
    client_id: UUID, run_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """A single scan + its rising-query rows."""
    try:
        run = google_trends.get_run(str(client_id), str(run_id))
        if run is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        return run
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("google_trends_run_failed",
                     extra={"run_id": str(run_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/clients/{client_id}/google-trends/scan")
async def start_scan(
    client_id: UUID, body: TrendsScanRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Enqueue a Google Trends scan (keyword-anchored). Returns the job id."""
    _require_enabled()
    seeds = google_trends.keyword_research.parse_seeds(body.seeds)
    if not seeds:
        raise HTTPException(status_code=400, detail="no_seeds")
    try:
        job_id = google_trends.enqueue_google_trends_scan(
            str(client_id), seeds,
            category_code=body.category_code, category_name=body.category_name,
            location_code=body.location_code, language_code=body.language_code,
            trends_type=body.trends_type or settings.google_trends_default_type,
            user_id=auth["user_id"],
        )
        return {"job_id": job_id, "seeds": seeds}
    except Exception as exc:
        logger.error("google_trends_scan_failed",
                     extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/clients/{client_id}/google-trends/jobs/{job_id}")
async def scan_status(
    client_id: UUID, job_id: UUID, auth: dict = Depends(require_auth)
) -> dict:
    """Poll a scan job's status (for the resumable in-flight UI)."""
    rows = (
        get_supabase().table("async_jobs").select("id, status, result, error")
        .eq("id", str(job_id)).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="job_not_found")
    return rows[0]


@router.get("/clients/{client_id}/google-trends/estimate")
async def estimate(
    client_id: UUID, seeds: str = "", auth: dict = Depends(require_auth)
) -> dict:
    """Free preflight: how many paid calls a scan of these seeds would spend, and
    the budget left. One explore call per ≤5 seeds + one overview batch."""
    parsed = google_trends.keyword_research.parse_seeds(seeds)
    chunks = max(1, (len(parsed) + settings.google_trends_max_seeds - 1) // settings.google_trends_max_seeds)
    return {
        "seeds": parsed,
        "estimated_calls": chunks + (1 if parsed else 0),
        "budget_remaining": google_trends.budget_remaining(),
    }


# ---------------------------------------------------------------------------
# Phase 2 — informational: a SEEDLESS category scan anchored on the client's own
# site topics/ICP + the relevance/audience gates. Survivors route to Topic
# Research via the EXISTING POST /clients/{id}/topic-research (a frontend step).
# ---------------------------------------------------------------------------
@router.post("/clients/{client_id}/google-trends/category-scan")
async def start_category_scan(
    client_id: UUID, body: TrendsCategoryScanRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Enqueue a Phase 2 category scan (seeds derived from the client's site
    topics/ICP). Returns the job id."""
    _require_enabled()
    try:
        job_id = google_trends.enqueue_google_trends_scan(
            str(client_id), [], mode="category",
            category_code=body.category_code, category_name=body.category_name,
            location_code=body.location_code, language_code=body.language_code,
            trends_type=body.trends_type or settings.google_trends_default_type,
            user_id=auth["user_id"],
        )
        return {"job_id": job_id}
    except Exception as exc:
        logger.error("google_trends_category_scan_failed",
                     extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


# ---------------------------------------------------------------------------
# Phase 4 — local seasonal (metro-geo only): interest_over_time → seasonality
# profile → trend_watch.demand_outlook. Result rides the job row.
# ---------------------------------------------------------------------------
@router.post("/clients/{client_id}/google-trends/seasonal")
async def start_seasonal_scan(
    client_id: UUID, body: TrendsSeasonalRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Enqueue a Phase 4 local-seasonal scan. Returns the job id."""
    _require_enabled()
    keywords = google_trends.keyword_research.parse_seeds(body.keywords)
    if not keywords:
        raise HTTPException(status_code=400, detail="no_keywords")
    try:
        job_id = google_trends.enqueue_local_seasonal_scan(
            str(client_id), keywords,
            location_code=body.location_code, language_code=body.language_code,
            user_id=auth["user_id"],
        )
        return {"job_id": job_id, "keywords": keywords}
    except Exception as exc:
        logger.error("google_trends_seasonal_scan_failed",
                     extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


# ---------------------------------------------------------------------------
# Phase 3 — portfolio-wide "what's rising this week" (agency, no client scope).
# Also runs weekly on the shared scheduler; these endpoints are the on-demand
# trigger + the read surface. The digest goes to the SerMaStr strategy channel.
# ---------------------------------------------------------------------------
@router.post("/google-trends/portfolio-sweep")
async def start_portfolio_sweep(auth: dict = Depends(require_admin)) -> dict:
    """Enqueue an on-demand portfolio sweep (admin). Returns the job id."""
    _require_enabled()
    try:
        job_id = google_trends.enqueue_portfolio_sweep(user_id=auth["user_id"])
        return {"job_id": job_id}
    except Exception as exc:
        logger.error("google_trends_portfolio_sweep_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/google-trends/portfolio")
async def list_portfolio(auth: dict = Depends(require_auth)) -> dict:
    """Portfolio sweep history (agency-wide runs, newest first)."""
    try:
        return {
            "enabled": settings.google_trends_enabled,
            "runs": google_trends.list_portfolio_runs(),
        }
    except Exception as exc:
        logger.error("google_trends_portfolio_list_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/google-trends/portfolio/runs/{run_id}")
async def get_portfolio_run(run_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """A single portfolio run + its aggregated rising-query rows."""
    run = google_trends.get_run(None, str(run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return run


@router.get("/google-trends/jobs/{job_id}")
async def portfolio_job_status(job_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Poll a client-less job (portfolio sweep) — same shape as the per-client poll."""
    rows = (
        get_supabase().table("async_jobs").select("id, status, result, error")
        .eq("id", str(job_id)).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="job_not_found")
    return rows[0]

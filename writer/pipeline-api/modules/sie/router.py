"""POST /sie — SERP Intelligence Engine endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models.sie import SIERequest, SIEResponse

from .pipeline import SIEError, run_sie

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sie"])


@router.post("/sie", response_model=SIEResponse)
async def generate_sie(request: SIERequest) -> SIEResponse:
    logger.info(
        "sie.start",
        extra={
            "run_id": request.run_id,
            "keyword": request.keyword,
            "outlier_mode": request.outlier_mode,
            "force_refresh": request.force_refresh,
        },
    )
    try:
        result = await run_sie(request)
    except SIEError as exc:
        logger.warning("sie.failed: %s — %s", exc.code, exc.message)
        raise HTTPException(status_code=422, detail=exc.message)
    except Exception as exc:
        logger.exception("sie.unexpected: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")

    logger.info(
        "sie.complete",
        extra={
            "run_id": request.run_id,
            "cache_hit": result.sie_cache_hit,
            "required_terms": len(result.terms.required),
            "avoid_terms": len(result.terms.avoid),
            "low_coverage_terms": len(result.terms.low_coverage_candidates),
        },
    )
    return result

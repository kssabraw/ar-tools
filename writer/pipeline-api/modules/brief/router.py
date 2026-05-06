"""POST /brief - Brief Generator endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models.brief import BriefRequest, BriefResponse

from .pipeline import BriefError, run_brief

logger = logging.getLogger(__name__)

router = APIRouter(tags=["brief"])


@router.post("/brief", response_model=BriefResponse)
async def generate_brief(request: BriefRequest) -> BriefResponse:
    logger.info(
        "brief.start",
        extra={"run_id": request.run_id, "keyword": request.keyword, "attempt": request.attempt},
    )
    try:
        result = await run_brief(request)
    except BriefError as exc:
        logger.warning("brief.failed: %s - %s", exc.code, exc.message)
        raise HTTPException(status_code=422, detail=exc.message)
    except Exception as exc:
        logger.exception("brief.unexpected: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")
    logger.info(
        "brief.complete",
        extra={
            "run_id": request.run_id,
            "h2_count": result.metadata.h2_count,
            "h3_count": result.metadata.h3_count,
            "faq_count": result.metadata.faq_count,
            "silos": result.metadata.silo_candidates_count,
        },
    )
    return result

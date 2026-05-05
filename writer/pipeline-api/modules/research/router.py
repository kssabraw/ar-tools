"""POST /research — Research & Citations endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models.research import ResearchRequest, ResearchResponse

from .pipeline import ResearchError, run_research

logger = logging.getLogger(__name__)

router = APIRouter(tags=["research"])


@router.post("/research", response_model=ResearchResponse)
async def generate_research(request: ResearchRequest) -> ResearchResponse:
    logger.info(
        "research.start",
        extra={"run_id": request.run_id, "keyword": request.keyword},
    )
    try:
        result = await run_research(request)
    except ResearchError as exc:
        logger.warning("research.failed: %s — %s", exc.code, exc.message)
        raise HTTPException(status_code=422, detail=exc.message)
    except Exception as exc:
        logger.exception("research.unexpected: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")

    logger.info(
        "research.complete",
        extra={
            "run_id": request.run_id,
            "total_citations": result.citations_metadata.total_citations,
            "h2s_with_citations": result.citations_metadata.h2s_with_citations,
            "tier_1": result.citations_metadata.citations_by_tier.tier_1,
            "tier_2": result.citations_metadata.citations_by_tier.tier_2,
        },
    )
    return result

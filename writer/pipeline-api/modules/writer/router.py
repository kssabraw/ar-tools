"""POST /write — Content Writer endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models.writer import WriterRequest, WriterResponse

from .banned_terms import BannedTermLeakage
from .pipeline import WriterError, run_writer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["writer"])


@router.post("/write", response_model=WriterResponse)
async def generate_article(request: WriterRequest) -> WriterResponse:
    logger.info(
        "writer.start",
        extra={
            "run_id": request.run_id,
            "has_client_context": request.client_context is not None,
            "has_research": request.research_output is not None,
        },
    )
    try:
        result = await run_writer(request)
    except BannedTermLeakage as exc:
        logger.warning("writer.banned_term_leakage: %s in %s", exc.term, exc.location)
        raise HTTPException(
            status_code=422,
            detail={
                "code": "banned_term_leakage",
                "term": exc.term,
                "location": exc.location,
                "snippet": exc.snippet,
            },
        )
    except WriterError as exc:
        logger.warning("writer.failed: %s — %s", exc.code, exc.message)
        raise HTTPException(status_code=422, detail=exc.message)
    except Exception as exc:
        logger.exception("writer.unexpected: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")

    logger.info(
        "writer.complete",
        extra={
            "run_id": request.run_id,
            "title": result.title,
            "section_count": result.metadata.section_count,
            "total_words": result.metadata.total_word_count,
            "schema_version": result.metadata.schema_version,
            "brand_conflicts": len(result.brand_conflict_log),
        },
    )
    return result

"""POST /sources-cited — Sources Cited endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models.sources_cited import SourcesCitedRequest, SourcesCitedResponse

from .pipeline import SourcesCitedError, run_sources_cited

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sources_cited"])


@router.post("/sources-cited", response_model=SourcesCitedResponse)
async def generate_sources_cited(request: SourcesCitedRequest) -> SourcesCitedResponse:
    logger.info("sources_cited.start", extra={"run_id": request.run_id})
    try:
        result = run_sources_cited(request)
    except SourcesCitedError as exc:
        logger.warning("sources_cited.failed: %s — %s", exc.code, exc.message)
        raise HTTPException(status_code=422, detail=exc.message)
    except Exception as exc:
        logger.exception("sources_cited.unexpected: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")

    logger.info(
        "sources_cited.complete",
        extra={
            "run_id": request.run_id,
            "total_citations": result.sources_cited_metadata.total_citations_in_sources_cited,
            "orphans": len(result.sources_cited_metadata.orphaned_usage_records),
            "placeholders": len(result.sources_cited_metadata.entries_with_placeholder),
        },
    )
    return result

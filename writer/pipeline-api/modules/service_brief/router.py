"""POST /service-brief - Service Page Brief Generator endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models.service_brief import ServiceBriefRequest, ServiceBriefResponse

from .errors import ServiceBriefError
from .pipeline import run_service_brief

logger = logging.getLogger(__name__)

router = APIRouter(tags=["service_brief"])


@router.post("/service-brief", response_model=ServiceBriefResponse)
async def generate_service_brief(request: ServiceBriefRequest) -> ServiceBriefResponse:
    logger.info(
        "service_brief.start",
        extra={
            "run_id": request.run_id,
            "service": request.service,
            "primary_query": request.primary_query,
            "attempt": request.attempt,
        },
    )
    try:
        result = await run_service_brief(request)
    except ServiceBriefError as exc:
        logger.warning("service_brief.failed: %s - %s", exc.code, exc.message)
        # Stage-1 (SERP) failures are unprocessable input; surface as 422.
        raise HTTPException(status_code=422, detail=exc.message)
    except Exception as exc:
        logger.exception("service_brief.unexpected: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")
    return result

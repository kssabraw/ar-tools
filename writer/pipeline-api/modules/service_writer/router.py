"""POST /service-write - Service Page Writer endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from models.service_writer import ServiceWriterRequest, ServiceWriterResponse

from .errors import ServiceWriterError
from .pipeline import run_service_writer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["service_writer"])


@router.post("/service-write", response_model=ServiceWriterResponse)
async def generate_service_page(request: ServiceWriterRequest) -> ServiceWriterResponse:
    logger.info(
        "service_writer.start",
        extra={"run_id": request.run_id, "attempt": request.attempt},
    )
    try:
        result = await run_service_writer(request)
    except ServiceWriterError as exc:
        logger.warning("service_writer.failed: %s - %s", exc.code, exc.message)
        raise HTTPException(status_code=422, detail=exc.message)
    except Exception as exc:
        logger.exception("service_writer.unexpected: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")
    return result

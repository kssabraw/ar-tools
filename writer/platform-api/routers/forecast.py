"""Forecasting API — deterministic rank/traffic/value projections computed
on read (services/forecasting.py). Nothing stored, no paid calls."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import require_auth
from services import forecasting

router = APIRouter(tags=["forecast"])
logger = logging.getLogger(__name__)


@router.get("/clients/{client_id}/forecast")
async def get_forecast(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    try:
        return forecasting.build_forecast(str(client_id))
    except Exception as exc:
        logger.error("forecast_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc

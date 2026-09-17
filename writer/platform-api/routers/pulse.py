"""Weekly Pulse — the copyable client update block on the workspace.

GET returns the latest stored pulse (building this week's on the fly when none
exists yet, so the card always has content); POST regenerates from live data;
PUT saves a staff edit to the current-week pulse (Email/List view preserved).
Staff-facing reads — the pulse is never auto-sent anywhere.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from middleware.auth import require_auth
from services import client_pulse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pulse"])


class PulseSaveRequest(BaseModel):
    # A staff edit to the pulse. Send whichever view was edited (Email → body,
    # List → body_list); the other view is preserved. At least one is required.
    body: str | None = None
    body_list: str | None = None


@router.get("/clients/{client_id}/pulse")
async def get_pulse(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    try:
        row = await run_in_threadpool(client_pulse.latest_pulse, str(client_id))
        if not row:
            body = await run_in_threadpool(client_pulse.build_pulse, str(client_id))
            if body is None:
                raise HTTPException(status_code=404, detail="client_not_found")
            row = await run_in_threadpool(client_pulse.latest_pulse, str(client_id)) or {"body": body}
        return row
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("pulse_get_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/clients/{client_id}/pulse/regenerate")
async def regenerate_pulse(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    try:
        body = await run_in_threadpool(client_pulse.build_pulse, str(client_id))
    except Exception as exc:
        logger.error("pulse_regen_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if body is None:
        raise HTTPException(status_code=404, detail="client_not_found")
    return await run_in_threadpool(client_pulse.latest_pulse, str(client_id)) or {"body": body}


@router.put("/clients/{client_id}/pulse")
async def update_pulse(client_id: UUID, req: PulseSaveRequest,
                       auth: dict = Depends(require_auth)) -> dict:
    if req.body is None and req.body_list is None:
        raise HTTPException(status_code=400, detail="nothing_to_save")
    try:
        row = await run_in_threadpool(
            client_pulse.save_pulse, str(client_id),
            body=req.body, body_list=req.body_list,
        )
    except Exception as exc:
        logger.error("pulse_save_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if row is None:
        raise HTTPException(status_code=404, detail="client_not_found")
    return row

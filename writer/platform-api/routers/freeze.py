"""Freeze Protocol endpoints — view, open, and lift a client freeze.

Opening/lifting is admin-gated (the SOP's escalation owners are the Admins);
viewing is any signed-in user (the freeze banner on the client workspace).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.supabase_client import get_supabase
from middleware.auth import require_admin, require_auth
from services import freeze as freeze_service

router = APIRouter(tags=["freeze"])

_VALID_REASONS = {"manual_action", "deindexing", "manual"}


class FreezeCreateRequest(BaseModel):
    reason: str = "manual"
    note: Optional[str] = None


@router.get("/clients/{client_id}/freeze")
async def get_freeze(client_id: str, auth: dict = Depends(require_auth)) -> dict:
    active = freeze_service.active_freeze(client_id)
    history = (
        get_supabase()
        .table("client_freezes")
        .select("*")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    ).data or []
    return {"active": active, "history": history}


@router.post("/clients/{client_id}/freeze", status_code=201)
async def create_freeze(
    client_id: str,
    body: FreezeCreateRequest,
    auth: dict = Depends(require_admin),
) -> dict:
    if body.reason not in _VALID_REASONS:
        raise HTTPException(status_code=422, detail="invalid_reason")
    row = freeze_service.freeze_client(
        client_id, body.reason, source="manual", note=body.note
    )
    return {"active": row}


@router.post("/clients/{client_id}/freeze/lift")
async def lift_freeze(client_id: str, auth: dict = Depends(require_admin)) -> dict:
    lifted = freeze_service.lift_freeze(client_id, lifted_by=auth.get("user_id"))
    return {"lifted": lifted}

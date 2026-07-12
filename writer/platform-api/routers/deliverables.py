"""Deliverables Sheet Sync admin endpoints (docs/modules/deliverables-sheet-sync-prd-v1_0.md §10).

Small management surface — the module itself runs headless (task-Complete hook
+ scheduler poller):

* GET  /clients/{id}/deliverables-sheet          — status: sheet id, recent sync log
* PUT  /clients/{id}/deliverables-sheet          — attach an EXISTING sheet by id
                                                   (validated: the service account
                                                   must be able to open it; reports
                                                   the tabs/dropdowns found)
* POST /clients/{id}/deliverables-sheet/provision — enqueue auto-creation from the
                                                   master template (admin; idempotent)
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.supabase_client import get_supabase
from middleware.auth import require_admin, require_auth
from services import deliverables_sheet

logger = logging.getLogger(__name__)

router = APIRouter(tags=["deliverables"])


class DeliverablesSheetSetRequest(BaseModel):
    sheet_id: str


def _client_or_404(client_id: UUID) -> dict:
    rows = (
        get_supabase().table("clients")
        .select("id, name, deliverables_sheet_id")
        .eq("id", str(client_id)).limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="client_not_found")
    return rows[0]


@router.get("/clients/{client_id}/deliverables-sheet")
async def get_deliverables_sheet(client_id: UUID, auth: dict = Depends(require_auth)):
    client = _client_or_404(client_id)
    log = (
        get_supabase().table("deliverables_sync_log")
        .select("task_id, tab, status, link_url, error, created_at, written_at")
        .eq("client_id", str(client_id))
        .order("created_at", desc=True).limit(20).execute().data
    ) or []
    sheet_id = client.get("deliverables_sheet_id")
    return {
        "sheet_id": sheet_id,
        "sheet_url": f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id else None,
        "provision_configured": deliverables_sheet.provision_configured(),
        "recent": log,
    }


@router.put("/clients/{client_id}/deliverables-sheet")
async def set_deliverables_sheet(
    client_id: UUID, body: DeliverablesSheetSetRequest, auth: dict = Depends(require_admin)
):
    """Attach an existing native Google Sheet as this client's deliverables
    sheet. Validates reachability + structure before storing (a bad id or an
    unshared/.xlsx file fails here, not silently at the first sync)."""
    _client_or_404(client_id)
    sheet_id = body.sheet_id.strip()
    if not sheet_id:
        raise HTTPException(status_code=400, detail="sheet_id_required")
    try:
        found = await asyncio.to_thread(deliverables_sheet.validate_sheet, sheet_id)
    except Exception as exc:
        logger.warning("deliverables_sheet_validate_failed",
                       extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=422, detail="sheet_unreachable") from exc
    if not found.get("content_tab") and not found.get("links_tab"):
        raise HTTPException(status_code=422, detail="sheet_tabs_not_recognized")
    get_supabase().table("clients").update(
        {"deliverables_sheet_id": sheet_id}
    ).eq("id", str(client_id)).execute()
    return {"sheet_id": sheet_id, **found}


@router.post("/clients/{client_id}/deliverables-sheet/provision")
async def provision_deliverables_sheet(client_id: UUID, auth: dict = Depends(require_admin)):
    """Enqueue auto-creation from the master template (backfill for existing
    clients / PACE-triggered). Idempotent — the job no-ops when the client
    already has a sheet."""
    client = _client_or_404(client_id)
    if client.get("deliverables_sheet_id"):
        return {"enqueued": False, "reason": "already_provisioned",
                "sheet_id": client["deliverables_sheet_id"]}
    if not deliverables_sheet.provision_configured():
        raise HTTPException(status_code=409, detail="provisioning_not_configured")
    ok = deliverables_sheet.enqueue_provision(str(client_id))
    if not ok:
        raise HTTPException(status_code=500, detail="enqueue_failed")
    return {"enqueued": True}

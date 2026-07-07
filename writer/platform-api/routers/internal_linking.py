"""Internal-linking analyzer + injector — trigger, review, approve/deny, apply.

The analyzer fans out link suggestions; each is reviewed + approved by a human
before the WordPress injector writes it (the gated live-site mutation, design
§6.5). Internal tool — `require_auth` only.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from services import internal_linking

router = APIRouter(tags=["internal-linking"])


class ApplyRequest(BaseModel):
    batch_id: Optional[str] = None


@router.post("/clients/{client_id}/internal-links/analyze")
async def analyze(client_id: UUID, auth: dict = Depends(require_auth)):
    internal_linking.enqueue_analyze(str(client_id))
    return {"status": "enqueued"}


@router.get("/clients/{client_id}/internal-links")
async def list_edits(
    client_id: UUID, status: Optional[str] = None, batch_id: Optional[str] = None,
    auth: dict = Depends(require_auth),
):
    """Edits for the client (default: the latest batch), newest first, + the
    in-flight job status so the UI can poll while an analysis/apply runs."""
    supabase = get_supabase()
    q = supabase.table("internal_link_edits").select("*").eq("client_id", str(client_id))
    if status:
        q = q.eq("status", status)
    if batch_id:
        q = q.eq("batch_id", batch_id)
    else:
        latest = (
            supabase.table("internal_link_edits").select("batch_id, created_at")
            .eq("client_id", str(client_id)).order("created_at", desc=True).limit(1).execute()
        ).data
        if latest:
            q = q.eq("batch_id", latest[0]["batch_id"])
    edits = q.order("match_score", desc=True).execute().data or []

    jobs = (
        supabase.table("async_jobs").select("job_type, status")
        .in_("job_type", ["internal_link_analyze", "internal_link_apply"])
        .eq("entity_id", str(client_id)).in_("status", ["pending", "running"]).execute()
    ).data or []
    return {"edits": edits, "running": [j["job_type"] for j in jobs]}


def _set_status(edit_id: str, status: str) -> dict:
    rows = (
        get_supabase().table("internal_link_edits")
        .update({"status": status, "updated_at": "now()"})
        .eq("id", edit_id).eq("status", "proposed").execute()
    ).data
    if not rows:
        raise HTTPException(status_code=409, detail="edit_not_pending")
    return rows[0]


@router.post("/internal-link-edits/{edit_id}/approve")
async def approve_edit(edit_id: UUID, auth: dict = Depends(require_auth)):
    return _set_status(str(edit_id), "approved")


@router.post("/internal-link-edits/{edit_id}/deny")
async def deny_edit(edit_id: UUID, auth: dict = Depends(require_auth)):
    return _set_status(str(edit_id), "denied")


@router.post("/clients/{client_id}/internal-links/apply")
async def apply_approved(client_id: UUID, body: ApplyRequest | None = None, auth: dict = Depends(require_auth)):
    """Enqueue injection of the client's APPROVED edits (WordPress only)."""
    internal_linking.enqueue_apply(str(client_id), body.batch_id if body else None)
    return {"status": "enqueued"}

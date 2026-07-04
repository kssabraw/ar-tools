"""SerMaStr router — the strategist's API surface (spec §5).

POST /clients/{id}/strategy-review        enqueue an on-demand run (flag-gated)
GET  /clients/{id}/strategy-reviews       recent reviews, newest first
POST /strategy-proposals/{review_id}/{idx}  approve / dismiss one proposal

Approving a proposal (v1) marks it approved in place; the Action Plan page pins
approved proposals above the deterministic plan (source="strategist"). Nothing
is executed — pushing approved proposals into Asana rides the separate
Asana-push build (Phase 5).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth
from services import strategist, strategy_report
from services.google_docs import GoogleDocError

router = APIRouter(tags=["strategist"])
logger = logging.getLogger(__name__)


class ProposalStatusRequest(BaseModel):
    status: str  # approved | dismissed


@router.post("/clients/{client_id}/strategy-review")
async def start_strategy_review(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Enqueue an on-demand strategist run. 409 when the feature flag is off or
    a run is already in flight for this client."""
    if not settings.strategist_enabled:
        raise HTTPException(status_code=409, detail="strategist_disabled")
    try:
        review_id = strategist.enqueue_strategy_review(str(client_id), trigger="on_demand")
    except Exception as exc:
        logger.error("strategy_review_enqueue_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=502, detail="strategy_review_enqueue_failed") from exc
    if review_id is None:
        raise HTTPException(status_code=409, detail="strategy_review_in_progress")
    return {"review_id": review_id, "status": "queued"}


@router.get("/clients/{client_id}/strategy-reviews")
async def list_strategy_reviews(
    client_id: UUID, limit: int = 10, auth: dict = Depends(require_auth)
) -> dict:
    """The client's recent strategy reviews, newest first. `input_digest` is
    omitted from the list payload (it's large); everything the card renders is
    included."""
    rows = (
        get_supabase()
        .table("strategy_reviews")
        .select("id, client_id, trigger, status, model, assessment, findings, "
                "proposals, questions, token_usage, error, created_at, completed_at, "
                "published_doc_id, published_doc_url, published_at")
        .eq("client_id", str(client_id))
        .order("created_at", desc=True)
        .limit(max(1, min(limit, 50)))
        .execute()
    ).data or []
    return {"reviews": rows, "enabled": settings.strategist_enabled}


@router.post("/strategy-reviews/{review_id}/publish")
async def publish_strategy_review(review_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Publish a completed strategy review as an INTERNAL Google Doc in the
    client's Drive folder. Idempotent-ish: re-publishing makes a fresh Doc and
    repoints the stored link (Docs can't be updated in place via the webhook)."""
    try:
        return await strategy_report.publish_review(str(review_id))
    except GoogleDocError as exc:
        # Map the known prerequisite failures to a clear 4xx; the rest are 502.
        code = str(exc).split(":", 1)[0]
        if code in ("review_not_found", "client_not_found"):
            raise HTTPException(status_code=404, detail=code) from exc
        if code in ("review_not_complete", "missing_google_drive_folder_id", "publish_not_configured"):
            raise HTTPException(status_code=409, detail=code) from exc
        logger.error("strategy_review_publish_failed", extra={"review_id": str(review_id), "error": str(exc)})
        raise HTTPException(status_code=502, detail="strategy_review_publish_failed") from exc


@router.post("/strategy-proposals/{review_id}/{idx}")
async def set_proposal_status(
    review_id: UUID, idx: int, body: ProposalStatusRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Approve or dismiss one proposal (patched in place in the JSONB list)."""
    if body.status not in ("approved", "dismissed"):
        raise HTTPException(status_code=422, detail="invalid_status")
    supabase = get_supabase()
    rows = (
        supabase.table("strategy_reviews")
        .select("id, proposals")
        .eq("id", str(review_id)).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="review_not_found")
    proposals = rows[0].get("proposals") or []
    if not (0 <= idx < len(proposals)):
        raise HTTPException(status_code=404, detail="proposal_not_found")
    # §3 passthroughs: a requires='senior' proposal is Kyle/Ryan territory —
    # enforce at the state-change chokepoint, not just the emit-time label.
    # (Admins are the senior owners in this suite's role model.)
    if proposals[idx].get("requires") == "senior" and auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="senior_approval_required")
    proposals[idx]["status"] = body.status
    proposals[idx]["decided_by"] = auth.get("user_id")
    try:
        supabase.table("strategy_reviews").update({"proposals": proposals}).eq(
            "id", str(review_id)
        ).execute()
    except Exception as exc:
        logger.error("proposal_status_failed", extra={"review_id": str(review_id), "error": str(exc)})
        raise HTTPException(status_code=502, detail="proposal_status_failed") from exc
    return {"review_id": str(review_id), "idx": idx, "status": body.status}

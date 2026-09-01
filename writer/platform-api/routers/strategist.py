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
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
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


@router.get("/strategist/status")
async def strategist_status(auth: dict = Depends(require_auth)) -> dict:
    """Whether the strategist feature is on — drives the SerMaStr Log nav entry.
    (The action log itself defaults on, but there are no proposals to log until
    the strategist runs, so the log surface follows strategist_enabled.)"""
    return {"enabled": settings.strategist_enabled}


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


_PROPOSAL_ERROR_STATUS = {
    "invalid_status": 422,
    "review_not_found": 404,
    "proposal_not_found": 404,
    "senior_approval_required": 403,
}


@router.post("/strategy-proposals/{review_id}/{idx}")
async def set_proposal_status(
    review_id: UUID, idx: int, body: ProposalStatusRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Approve or dismiss one proposal (patched in place in the JSONB list).

    Delegates to ``strategist_proposals.apply_decision`` — the same core the bulk
    plan→PACE handoff uses — so "approve a proposal" (push + place the board task,
    register the intervention, record the decision, post the SerMaStr→PACE handoff)
    is defined once.
    """
    from services import strategist_proposals

    try:
        return await strategist_proposals.apply_decision(
            str(review_id), idx, body.status,
            actor_id=auth.get("user_id"), actor_role=auth.get("role"), actor_source="web",
        )
    except strategist_proposals.ProposalError as exc:
        raise HTTPException(
            status_code=_PROPOSAL_ERROR_STATUS.get(exc.code, 400), detail=exc.code
        ) from exc
    except Exception as exc:
        logger.error("proposal_status_failed", extra={"review_id": str(review_id), "error": str(exc)})
        raise HTTPException(status_code=502, detail="proposal_status_failed") from exc


# ---------------------------------------------------------------------------
# Action Log — the audit + learning ledger read API (admin-gated).
# ---------------------------------------------------------------------------
@router.get("/strategist/action-log")
async def get_strategist_action_log(
    client_id: Optional[str] = None,
    proposal_kind: Optional[str] = None,
    decision: Optional[str] = None,
    trigger: Optional[str] = None,
    outcome_verdict: Optional[str] = None,
    decided: Optional[bool] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    auth: dict = Depends(require_auth),
) -> dict:
    """A filtered page of SerMaStr's action log — what it proposed, how a human
    dispositioned each proposal, and whether the approved tactic worked. Admin-gated
    (the log is sensitive: it names actors, clients, and proposal content)."""
    if auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin_only")
    from services import sermastr_audit

    return await run_in_threadpool(
        sermastr_audit.list_log, client_id=client_id, proposal_kind=proposal_kind,
        decision=decision, trigger=trigger, outcome_verdict=outcome_verdict,
        decided=decided, since=since, until=until, limit=limit, offset=offset,
    )


@router.get("/strategist/action-log/stats")
async def get_strategist_action_log_stats(
    client_id: Optional[str] = None,
    proposal_kind: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    auth: dict = Depends(require_auth),
) -> dict:
    """Approve/dismiss + worked/no_effect rollup over a filtered window — the log
    view's summary strip + the learning read. Admin-gated."""
    if auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin_only")
    from services import sermastr_audit

    return await run_in_threadpool(
        sermastr_audit.stats_window, client_id=client_id, proposal_kind=proposal_kind,
        since=since, until=until,
    )

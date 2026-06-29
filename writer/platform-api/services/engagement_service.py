"""Managed engagement spine — the lifecycle state machine.

One active engagement per client, moving through:
  onboarding → intake → auditing → strategizing → plan_review → provisioning
  → executing → steady_state   (plus paused / closed)

The pure transition logic (`VALID_TRANSITIONS` + `can_transition`) is unit-tested;
the DB ops are thin wrappers over supabase. Phase 2 / PR-A of the managed-
engagement build (docs/managed-engagement-and-strategy-engine-design-v1_0.md §3).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from db.supabase_client import get_supabase

logger = logging.getLogger("engagement_service")

LIFECYCLE = (
    "onboarding", "intake", "auditing", "strategizing",
    "plan_review", "provisioning", "executing", "steady_state",
)
ALL_STATUSES = (*LIFECYCLE, "paused", "closed")
AUTONOMY_LEVELS = ("recommend", "assisted", "autonomous")

# Forward lifecycle edges only — the universal paused/closed edges are handled
# in can_transition() so they don't have to be repeated on every state.
VALID_TRANSITIONS: dict[str, set[str]] = {
    "onboarding": {"intake"},
    "intake": {"auditing"},
    "auditing": {"strategizing"},
    "strategizing": {"plan_review"},
    "plan_review": {"provisioning", "strategizing"},  # approve | send back to re-plan
    "provisioning": {"executing"},
    "executing": {"steady_state"},
    "steady_state": {"plan_review", "executing"},     # amend plan | run more work
    "paused": {"executing", "steady_state"},          # resume points
    "closed": set(),                                  # terminal
}


def can_transition(frm: str, to: str) -> bool:
    """Pure: is moving an engagement from `frm` to `to` allowed?"""
    if frm not in ALL_STATUSES or to not in ALL_STATUSES:
        return False
    if frm == to or frm == "closed":
        return False
    if to == "closed":           # any live engagement may be closed
        return True
    if to == "paused":           # any live, non-paused engagement may be paused
        return frm != "paused"
    return to in VALID_TRANSITIONS.get(frm, set())


# ── DB ops ────────────────────────────────────────────────────────────────────
def _safe(fn, *, code: str = "internal_error"):
    try:
        return fn()
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - thin DB-error wrapper
        logger.warning("engagement_service.db_error", extra={"error": str(exc), "code": code})
        raise HTTPException(status_code=500, detail=code)


def get_active_for_client(client_id: str) -> Optional[dict]:
    def _q():
        rows = (
            get_supabase().table("engagements").select("*")
            .eq("client_id", client_id).neq("status", "closed")
            .limit(1).execute().data or []
        )
        return rows[0] if rows else None
    return _safe(_q)


def get_engagement(engagement_id: str) -> dict:
    def _q():
        rows = (
            get_supabase().table("engagements").select("*")
            .eq("id", engagement_id).limit(1).execute().data or []
        )
        if not rows:
            raise HTTPException(status_code=404, detail="engagement_not_found")
        return rows[0]
    return _safe(_q)


def create_engagement(client_id: str, autonomy_level: str, user_id: Optional[str]) -> dict:
    if autonomy_level not in AUTONOMY_LEVELS:
        raise HTTPException(status_code=422, detail="invalid_autonomy_level")
    if get_active_for_client(client_id):
        raise HTTPException(status_code=409, detail="active_engagement_exists")

    def _q():
        return (
            get_supabase().table("engagements")
            .insert({
                "client_id": client_id,
                "status": "onboarding",
                "autonomy_level": autonomy_level,
                "created_by": user_id,
            })
            .execute().data[0]
        )
    return _safe(_q)


def _is_voice_approved(brand_voice: Optional[dict]) -> bool:
    """Pure: has the client's brand voice been explicitly set/accepted?"""
    bv = brand_voice or {}
    has_content = bool(bv.get("raw_text") or bv.get("current_voice") or bv.get("recommended_voice"))
    accepted = bool(bv.get("recommended_accepted") or bv.get("source") == "user" or bv.get("raw_text"))
    return has_content and accepted


def _is_icp_ready(detected_icp: Optional[dict], differentiators: Optional[list]) -> bool:
    """Pure: does the client have an ICP (or differentiators) on file?"""
    icp = detected_icp or {}
    return bool(icp.get("raw_text") or icp.get("segments") or differentiators)


def onboarding_readiness(client_id: str) -> dict:
    """Whether brand voice + ICP are approved — the gate to leave `onboarding`."""
    def _q():
        rows = (
            get_supabase().table("clients")
            .select("brand_voice, detected_icp, differentiators")
            .eq("id", client_id).limit(1).execute().data or []
        )
        return rows[0] if rows else {}
    c = _safe(_q)
    voice = _is_voice_approved(c.get("brand_voice"))
    icp = _is_icp_ready(c.get("detected_icp"), c.get("differentiators"))
    return {"voice_approved": voice, "icp_ready": icp, "ready": voice and icp}


def transition(engagement_id: str, to_status: str) -> dict:
    current = get_engagement(engagement_id)
    if not can_transition(current["status"], to_status):
        raise HTTPException(
            status_code=409,
            detail=f"invalid_transition: {current['status']} -> {to_status}",
        )

    # Approval gate: leaving onboarding requires brand voice + ICP approved.
    if current["status"] == "onboarding" and to_status == "intake":
        if not onboarding_readiness(current["client_id"])["ready"]:
            raise HTTPException(status_code=409, detail="onboarding_incomplete")

    def _q():
        return (
            get_supabase().table("engagements")
            .update({"status": to_status, "updated_at": "now()"})
            .eq("id", engagement_id)
            .execute().data[0]
        )
    return _safe(_q)

"""Engagement executor — approval (the consent boundary), the action lifecycle,
and the `execution_events` audit trail.

Phase 4 · PR-A. Approving a plan is the consent boundary for any execution
(design §8): it marks the plan approved, sets each action's working status
(`auto` → `queued` for the executor; `assigned` → `assigned` for a human / Asana),
and advances the engagement `plan_review → provisioning`. Humans can then drive
actions to `done`/`skipped`. The **autonomous** execution of `auto` actions +
WordPress internal-linking come in the next increment; this lays the spine.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from db.supabase_client import get_supabase
from services import engagement_service

logger = logging.getLogger("engagement_executor")

# Statuses a human (or the API) may set on an action.
ACTION_STATUSES = {
    "proposed", "approved", "queued", "in_progress",
    "assigned", "done", "blocked", "skipped",
}


# ── pure helper (unit-tested) ────────────────────────────────────────────────
def on_approve_status(execution_mode: str) -> str:
    """A proposed action's status once the plan is approved.

    `auto` → `queued` (the executor will run it); `assigned` → `assigned`
    (handed to a human / Asana). Pure.
    """
    return "queued" if execution_mode == "auto" else "assigned"


# ── DB ops ────────────────────────────────────────────────────────────────────
def record_event(
    engagement_id: str, event_type: str, action_id: Optional[str] = None, detail: Optional[dict] = None
) -> None:
    """Append an execution_events row (best-effort — never raises into the caller)."""
    try:
        get_supabase().table("execution_events").insert(
            {"engagement_id": engagement_id, "action_id": action_id,
             "type": event_type, "detail": detail or {}}
        ).execute()
    except Exception as exc:  # pragma: no cover - audit trail must not break the action
        logger.warning("execution_event_failed", extra={"type": event_type, "error": str(exc)})


def approve_plan(engagement_id: str, user_id: Optional[str]) -> dict:
    """Consent boundary: approve the latest pending plan + set its actions' working status."""
    supabase = get_supabase()
    plans = (
        supabase.table("strategy_plans").select("id, status")
        .eq("engagement_id", engagement_id).order("created_at", desc=True).limit(1).execute()
    ).data
    if not plans:
        raise HTTPException(status_code=404, detail="no_plan")
    plan = plans[0]
    if plan["status"] not in ("proposed", "draft"):
        raise HTTPException(status_code=409, detail="plan_not_pending")

    supabase.table("strategy_plans").update(
        {"status": "approved", "approved_by": user_id, "approved_at": "now()"}
    ).eq("id", plan["id"]).execute()

    actions = (
        supabase.table("strategy_actions").select("id, execution_mode")
        .eq("plan_id", plan["id"]).eq("status", "proposed").execute()
    ).data or []
    for a in actions:
        supabase.table("strategy_actions").update(
            {"status": on_approve_status(a["execution_mode"])}
        ).eq("id", a["id"]).execute()

    record_event(engagement_id, "approved", detail={"plan_id": plan["id"], "actions": len(actions)})

    # Hand the `assigned` actions to Asana off the request path (best-effort —
    # rides main's Asana integration; skips cleanly when Asana isn't configured).
    if any(a["execution_mode"] != "auto" for a in actions):
        try:
            from services import engagement_asana  # lazy: avoids an import cycle

            engagement_asana.enqueue_asana_push(engagement_id)
        except Exception as exc:  # noqa: BLE001 — approval succeeds even if the push can't enqueue
            logger.warning("approve_plan.asana_enqueue_skipped", extra={"error": str(exc)})

    # Advance the engagement out of plan_review (best-effort; only if it's there).
    try:
        eng = engagement_service.get_engagement(engagement_id)
        if eng["status"] == "plan_review":
            engagement_service.transition(engagement_id, "provisioning")
    except Exception as exc:  # noqa: BLE001 — approval succeeds even if the stage can't advance
        logger.warning("approve_plan.transition_skipped", extra={"error": str(exc)})

    return {"plan_id": plan["id"], "approved_actions": len(actions)}


def update_action_status(action_id: str, status: str) -> dict:
    """Set a single action's status + record the change."""
    if status not in ACTION_STATUSES:
        raise HTTPException(status_code=422, detail="invalid_status")
    supabase = get_supabase()
    rows = (
        supabase.table("strategy_actions").update({"status": status}).eq("id", action_id).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="action_not_found")
    action = rows[0]
    plan = (
        supabase.table("strategy_plans").select("engagement_id")
        .eq("id", action["plan_id"]).limit(1).execute()
    ).data
    if plan:
        record_event(
            plan[0]["engagement_id"],
            "skipped" if status == "skipped" else "status_change",
            action_id=action_id, detail={"status": status},
        )
    return action


def list_events(engagement_id: str, limit: int = 50) -> list[dict]:
    return (
        get_supabase().table("execution_events").select("*")
        .eq("engagement_id", engagement_id).order("created_at", desc=True).limit(limit).execute()
    ).data or []

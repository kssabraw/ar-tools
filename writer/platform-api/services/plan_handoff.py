"""Plan → PACE handoff — the on-demand bridge from a SerMaStr-authored plan to
the native task board, with PACE's placement engine assigning each task out.

The gap this fills: the Action Plan (``reopt_plans``) is recommend-only, and
strategist proposals need per-item approval — there was no on-demand "send the
plan to the board and assign it out". Both agents expose this via one shared
engine:

* **Action Plan items** → a native task per action (reusing the auto-producer's
  ``source='action_plan'`` + ``action_source_ref`` idempotency, so this composes
  with ``task_producers.sync_action_plan_tasks`` — no duplicate tasks), then
  ``pm_assign.place_task`` on each (skilled + eligible + least-loaded, or held at
  capacity).
* **Open strategist proposals** → approved through ``strategist_proposals`` (which
  pushes + auto-places each), exactly as the per-proposal Approve button does.

Native-board only — placement is native-board (``pm_assign``). The whole handoff
gates on ``native_tasks_enabled``; pre-cutover it returns a clear "not enabled"
result rather than writing to Asana (where there is no placement engine).

Heavy/batch work runs as a ``plan_handoff`` async job (mirrors ``asana_push`` —
the existing "push a plan to the board" precedent), so a chat confirm returns
immediately and the tasks land shortly. Best-effort per item — one failure never
aborts the batch.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

VALID_SCOPES = ("action_plan", "proposals", "both")


def native_enabled() -> bool:
    return bool(settings.native_tasks_enabled)


# ---------------------------------------------------------------------------
# Reads (preview counts for the confirm line)
# ---------------------------------------------------------------------------
def _latest_plan_items(client_id: str) -> list[dict]:
    rows = (
        get_supabase().table("reopt_plans")
        .select("items")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    return (rows[0].get("items") if rows else None) or []


def _eligible_actions(items: list[dict]) -> list[dict]:
    """The Action Plan items a handoff would push: not drop-driven (those are the
    alert producers' job), capped at ``plan_handoff_max_actions``. Pure-ish."""
    from services.task_producers import ACTION_PLAN_SKIP_KINDS

    eligible = [a for a in items if a.get("kind") not in ACTION_PLAN_SKIP_KINDS]
    return eligible[: settings.plan_handoff_max_actions]


def preview_counts(client_id: str, scope: str) -> dict:
    """How many items each half of a handoff would act on, for the confirm line.
    Cheap reads; best-effort (a failing read reports 0 for that half)."""
    counts = {"action_plan": 0, "proposals": 0}
    if scope in ("action_plan", "both"):
        try:
            counts["action_plan"] = len(_eligible_actions(_latest_plan_items(client_id)))
        except Exception as exc:
            logger.warning("plan_handoff.preview_action_plan_failed",
                           extra={"client_id": client_id, "error": str(exc)})
    if scope in ("proposals", "both"):
        try:
            from services import strategist_proposals

            review = strategist_proposals._latest_review_with_proposals(client_id)
            if review:
                counts["proposals"] = len(
                    strategist_proposals.open_proposal_indices(review.get("proposals") or [])
                )
        except Exception as exc:
            logger.warning("plan_handoff.preview_proposals_failed",
                           extra={"client_id": client_id, "error": str(exc)})
    return counts


def confirm_phrase(client_id: str, scope: str) -> str:
    """Human confirm text naming the exact work — '… push N Action Plan items +
    M open proposals to the board and hand each to PACE to assign'."""
    c = preview_counts(client_id, scope)
    parts = []
    if scope in ("action_plan", "both"):
        parts.append(f"{c['action_plan']} Action Plan item" + ("" if c["action_plan"] == 1 else "s"))
    if scope in ("proposals", "both"):
        parts.append(f"{c['proposals']} open proposal" + ("" if c["proposals"] == 1 else "s"))
    what = " + ".join(parts) if parts else "the plan"
    return f"push {what} to the task board and hand each task to PACE to assign to the best-fit member"


# ---------------------------------------------------------------------------
# Action Plan half
# ---------------------------------------------------------------------------
def handoff_action_plan(client_id: str, *, actor_id: Optional[str] = None) -> dict:
    """Materialize the latest Action Plan's items as native tasks and place each
    via PACE's engine. Idempotent (reuses the producer's (source, source_ref)) —
    an item already on the board as a producer task is reused and simply placed if
    still unassigned. Best-effort per item. Native-board only."""
    from services import pm_assign, task_service
    from services.task_monthly import ensure_month_section
    from services.task_producers import (action_source_ref, action_task_description,
                                          action_task_name)

    items = _eligible_actions(_latest_plan_items(client_id))
    if not items:
        return {"status": "empty", "created": 0, "existing": 0, "placed": 0, "held": 0, "total": 0}

    try:
        section_id = ensure_month_section(client_id, date.today())["id"]
    except Exception as exc:
        logger.warning("plan_handoff.section_failed", extra={"client_id": client_id, "error": str(exc)})
        section_id = None

    created = existing = placed = held = 0
    rows: list[dict] = []
    for idx, a in enumerate(items):
        ref = action_source_ref(client_id, a)
        try:
            task = task_service.create_task(
                action_task_name(a),
                client_id=client_id,
                section_id=section_id,
                description=action_task_description(client_id, a),
                sort_order=idx,
                source="action_plan",
                source_ref=ref,
                created_by=actor_id,
            )
            if task.get("_existing"):
                existing += 1
            else:
                created += 1
            # Hand it to PACE — skilled/eligible/least-loaded, or held at capacity.
            # place_task no-ops when already assigned (a human's pick / prior place).
            res = pm_assign.place_task(task["id"], actor_id=actor_id)
            outcome = pm_assign.classify_placement(res)
            if outcome == "placed":
                placed += 1
            elif outcome == "held":
                held += 1
            rows.append({"task_id": task["id"], "name": action_task_name(a),
                         "outcome": outcome, "assignee_name": res.get("name")})
        except Exception as exc:  # one item never aborts the batch
            logger.warning("plan_handoff.action_item_failed",
                           extra={"client_id": client_id, "source_ref": ref, "error": str(exc)})
    return {"status": "ok", "created": created, "existing": existing,
            "placed": placed, "held": held, "total": len(items), "results": rows}


# ---------------------------------------------------------------------------
# Combined engine
# ---------------------------------------------------------------------------
async def run_handoff(
    client_id: str,
    *,
    scope: str = "both",
    actor_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    actor_source: str = "system",
) -> dict:
    """Run the requested handoff half/halves. Returns a per-half summary."""
    if scope not in VALID_SCOPES:
        scope = "both"
    if not native_enabled():
        return {"status": "native_disabled"}

    result: dict = {"status": "ok", "scope": scope}
    if scope in ("action_plan", "both"):
        # The Action Plan half is sync + DB-heavy — run it off the event loop so a
        # big plan doesn't stall the worker/request loop.
        result["action_plan"] = await asyncio.to_thread(
            handoff_action_plan, client_id, actor_id=actor_id
        )
    if scope in ("proposals", "both"):
        from services import strategist_proposals

        result["proposals"] = await strategist_proposals.handoff_open_proposals(
            client_id, actor_id=actor_id, actor_role=actor_role, actor_source=actor_source,
        )
    return result


def summarize(result: dict) -> str:
    """A one-line human summary of a run_handoff result (for a chat/notification)."""
    if result.get("status") == "native_disabled":
        return "The native task board isn't enabled yet — assignment runs on it."
    parts = []
    ap = result.get("action_plan")
    if ap and ap.get("status") == "ok":
        placed, held = ap.get("placed", 0), ap.get("held", 0)
        seg = f"{ap.get('created', 0) + ap.get('existing', 0)} Action Plan task(s) on the board"
        seg += f" — {placed} assigned"
        if held:
            seg += f", {held} held (team at capacity)"
        parts.append(seg)
    elif ap and ap.get("status") == "empty":
        parts.append("no Action Plan items to push")
    pr = result.get("proposals")
    if pr and pr.get("status") == "ok":
        # "approved + task created" is always true; placement (assign vs hold at
        # capacity) isn't tracked back through the approve path, so don't claim
        # "assigned" — PACE places each the same as an Action Plan task.
        seg = f"{pr.get('approved', 0)} proposal(s) approved + task created"
        if pr.get("skipped_senior"):
            seg += f", {pr['skipped_senior']} left for admin sign-off (senior)"
        parts.append(seg)
    elif pr and pr.get("status") == "no_review":
        parts.append("no strategist proposals to hand over")
    return "; ".join(parts) if parts else "nothing to hand over."


# ---------------------------------------------------------------------------
# Async job (mirrors asana_push — "push a plan to the board")
# ---------------------------------------------------------------------------
def enqueue_plan_handoff(
    client_id: str,
    *,
    scope: str = "both",
    actor_id: Optional[str] = None,
    actor_role: Optional[str] = None,
) -> Optional[str]:
    """Enqueue the handoff job (deduped against an in-flight handoff for this
    client). Returns the job id, or None when deduped."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "plan_handoff")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1).execute()
    ).data
    if existing:
        return existing[0]["id"]
    row = (
        supabase.table("async_jobs").insert({
            "job_type": "plan_handoff",
            "entity_id": client_id,
            "payload": {"client_id": client_id, "scope": scope,
                        "actor_id": actor_id, "actor_role": actor_role},
        }).execute()
    ).data[0]
    return row["id"]


async def run_plan_handoff_job(job: dict) -> None:
    """async_jobs handler for job_type='plan_handoff'."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        result = await run_handoff(
            client_id,
            scope=payload.get("scope") or "both",
            actor_id=payload.get("actor_id"),
            actor_role=payload.get("actor_role"),
            actor_source="system",
        )
    except Exception as exc:
        logger.warning("plan_handoff.job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update({
        "status": "complete",
        "result": {**result, "summary": summarize(result)},
        "completed_at": "now()",
    }).eq("id", job_id).execute()

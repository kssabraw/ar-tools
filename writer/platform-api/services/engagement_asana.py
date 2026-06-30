"""Engagement → Asana push.

The executor's `assigned` actions are the *craft* work SerMaStr hands to a
human ("auto the automatable, assign the craft" — design §7). This module turns
each approved `assigned` strategy action into a real Asana task in the client's
mapped project, routed to the team member whose `role` matches the action's
`assignee_role`.

It rides **main's** Asana integration (services/asana_service.py + the
`asana_client_projects` mapping + the `asana_team_members` roster) rather than a
parallel client — the merge reconciliation. Best-effort throughout: absent the
Asana token / a project mapping the actions simply stay `assigned` with no task
id (a human still sees them in the Strategy UI), and one task failing never
aborts the rest. Runs off the request path as an ``engagement_asana_push``
async job so Asana latency doesn't block plan approval.

Two-way status sync (Asana task done → action done) is a deliberate follow-up;
this is the outbound leg only.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from db.supabase_client import get_supabase
from services import asana_service, engagement_executor, engagement_service
from services.asana_monthly import get_project_gid

logger = logging.getLogger("engagement_asana")


# ── pure helpers (unit-tested) ────────────────────────────────────────────────
def compose_notes(action: dict) -> str:
    """Human-readable task notes for an Asana task built from a strategy action.

    Carries the rationale + provenance + a deep link back into the suite tool
    that does the work, so the assignee has full context. Pure.
    """
    lines: list[str] = []
    if action.get("rationale"):
        lines.append(action["rationale"])
    meta = " · ".join(
        str(v) for v in (action.get("module"), action.get("category"), action.get("kind")) if v
    )
    if meta:
        lines.append("")
        lines.append(meta)
    if action.get("deep_link"):
        lines.append(action["deep_link"])
    lines.append("")
    lines.append("Created by SerMaStr (managed engagement).")
    return "\n".join(lines)


def build_action_task_payload(
    action: dict,
    project_gid: str,
    *,
    section_gid: Optional[str] = None,
    assignee_gid: Optional[str] = None,
    fields: Optional[dict] = None,
) -> dict:
    """Build the ``POST /tasks`` body for one `assigned` strategy action.

    Places it in ``project_gid`` (in ``section_gid`` when given), assigns it when
    a role match was found, sets Status = Not Started when those field GIDs
    resolved, and writes the rationale/links into the notes. Pure — unit-tested.
    """
    data: dict[str, Any] = {
        "name": (action.get("title") or "SerMaStr action").strip(),
        "projects": [project_gid],
    }
    if section_gid:
        data["memberships"] = [{"project": project_gid, "section": section_gid}]
    if assignee_gid:
        data["assignee"] = assignee_gid
    notes = compose_notes(action)
    if notes:
        data["notes"] = notes

    f = fields or {}
    custom_fields: dict[str, Any] = {}
    if f.get("status_field_gid") and f.get("not_started_option_gid"):
        custom_fields[f["status_field_gid"]] = f["not_started_option_gid"]
    if custom_fields:
        data["custom_fields"] = custom_fields
    return data


def current_month_section_gid(sections: list[dict], month_label: str) -> Optional[str]:
    """The GID of the existing section named ``month_label`` (None if absent).

    SerMaStr drops its tasks into the team's current-month section **when it
    already exists** (so the work shows up in the monthly flow); it does NOT
    create the section itself — that's the monthly-automation job's role, and
    creating it here would race that idempotent job. Pure.
    """
    target = (month_label or "").strip().casefold()
    for s in sections:
        if (s.get("name") or "").strip().casefold() == target:
            return s.get("gid")
    return None


# ── DB ops ────────────────────────────────────────────────────────────────────
def resolve_role_assignee(role: Optional[str]) -> Optional[str]:
    """The Asana user gid for an `assignee_role` (first active member with that
    role), or None when the role is unset / unmapped. An unmapped role yields an
    unassigned task a human picks up."""
    if not role:
        return None
    rows = (
        get_supabase().table("asana_team_members").select("gid")
        .eq("role", role).eq("active", True).limit(1).execute()
    ).data or []
    return rows[0]["gid"] if rows else None


def _assigned_actions_for_engagement(engagement_id: str) -> list[dict]:
    """The latest approved plan's `assigned` actions still missing an Asana task."""
    supabase = get_supabase()
    plans = (
        supabase.table("strategy_plans").select("id")
        .eq("engagement_id", engagement_id).eq("status", "approved")
        .order("created_at", desc=True).limit(1).execute()
    ).data
    if not plans:
        return []
    return (
        supabase.table("strategy_actions").select("*")
        .eq("plan_id", plans[0]["id"]).eq("status", "assigned")
        .is_("asana_task_id", "null").execute()
    ).data or []


async def push_assigned_actions(engagement_id: str) -> dict:
    """Create an Asana task for each approved `assigned` action without one.

    Returns a summary ``{status, created, skipped, errors}``. Never raises for a
    "nothing to do" condition — those return a status the caller can surface.
    """
    if not asana_service.is_configured():
        engagement_executor.record_event(engagement_id, "asana_skipped",
                                          detail={"reason": "asana_not_configured"})
        return {"status": "skipped", "reason": "asana_not_configured", "created": 0}

    eng = engagement_service.get_engagement(engagement_id)
    client_id = eng["client_id"]
    project_gid = get_project_gid(client_id)
    if not project_gid:
        engagement_executor.record_event(engagement_id, "asana_skipped",
                                          detail={"reason": "no_project_mapping"})
        return {"status": "skipped", "reason": "no_project_mapping", "created": 0}

    actions = _assigned_actions_for_engagement(engagement_id)
    if not actions:
        return {"status": "noop", "created": 0}

    # Resolve the project's Status field GIDs once; find the current-month section.
    fields = await asana_service.resolve_project_fields(project_gid)
    section_gid: Optional[str] = None
    try:
        from datetime import datetime, timezone

        sections = await asana_service.list_sections(project_gid)
        label = asana_service.month_label(datetime.now(timezone.utc).date())
        section_gid = current_month_section_gid(sections, label)
    except Exception as exc:  # noqa: BLE001 — section placement is best-effort
        logger.warning("engagement_asana.sections_failed",
                       extra={"engagement_id": engagement_id, "error": str(exc)})

    supabase = get_supabase()
    created = 0
    errors: list[str] = []
    for action in actions:
        try:
            assignee_gid = resolve_role_assignee(action.get("assignee_role"))
            payload = build_action_task_payload(
                action, project_gid,
                section_gid=section_gid, assignee_gid=assignee_gid, fields=fields,
            )
            task = await asana_service.create_task(payload)
            task_gid = (task or {}).get("gid")
            if task_gid:
                supabase.table("strategy_actions").update(
                    {"asana_task_id": task_gid}
                ).eq("id", action["id"]).execute()
            engagement_executor.record_event(
                engagement_id, "asana_task_created", action_id=action["id"],
                detail={"task_gid": task_gid, "assignee_gid": assignee_gid,
                        "role": action.get("assignee_role")},
            )
            created += 1
        except Exception as exc:  # one bad task shouldn't abort the rest
            errors.append(f"{action.get('title')}: {str(exc)[:120]}")
            logger.warning("engagement_asana.task_failed",
                           extra={"engagement_id": engagement_id,
                                  "action": action.get("title"), "error": str(exc)})

    logger.info("engagement_asana.pushed",
                extra={"engagement_id": engagement_id, "created": created, "errors": len(errors)})
    return {"status": "created", "created": created, "errors": errors}


# ── job enqueue + handler ─────────────────────────────────────────────────────
def enqueue_asana_push(engagement_id: str) -> None:
    """Enqueue an engagement_asana_push job (deduped against any in-flight one)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "engagement_asana_push").eq("entity_id", engagement_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "engagement_asana_push", "entity_id": engagement_id,
         "payload": {"engagement_id": engagement_id}}
    ).execute()


async def run_engagement_asana_job(job: dict) -> None:
    """async_jobs handler for job_type='engagement_asana_push'."""
    payload = job.get("payload") or {}
    engagement_id = payload.get("engagement_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not engagement_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing engagement_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        result = await push_assigned_actions(engagement_id)
    except Exception as exc:
        logger.warning("engagement_asana_job_failed",
                       extra={"engagement_id": engagement_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()

"""Asana task push — Recipe Engine plans + approved strategist proposals → tasks.

The Recipe Engine's monthly task plan (`monthly_task_plans`) and the
strategist's approved proposals (`strategy_reviews.proposals[]`) were
recommend-only; this module turns them into real Asana tasks in the client's
mapped project (`asana_client_projects`, same mapping the monthly automation
uses), under the current month's section.

Recipe push (`push_task_plan`, async_jobs `asana_push`):
  * one task per assigned plan line — name = the SOP label, notes carry the
    qty × unit cost, rationale, and a deep link back to the Task Plan page
  * assignee resolved by first-name match against `asana_team_members`
    ("Minda → Ivy" assigns Minda — the handoff chain goes in the notes;
    an unstaffed line pushes UNASSIGNED so it's visible in Asana, not lost)
  * **idempotent**: created task gids persist on `monthly_task_plans.asana_push`
    keyed by line — a re-push after a partial failure creates only the missing
    tasks, never duplicates
  * the month section is ensured (created if absent) — unlike the monthly
    template automation, which deliberately refuses to touch an existing month

Strategist push (`push_proposal`): called from the proposal-approve endpoint,
best-effort — one task per approved proposal, gid/url stored inside the
proposal JSONB so the review card can link to it.

Degradation mirrors asana_monthly: unconfigured token / unmapped project →
a clear skip status, never an exception into the caller.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import asana_service
from services.asana_monthly import get_project_gid

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ---------------------------------------------------------------------------
def task_key(task: dict, idx: int) -> str:
    """Stable identity for one plan line across re-pushes of the same plan."""
    return f"{idx}:{task.get('task_type') or 'task'}"


def primary_assignee_name(assignee: Optional[str]) -> Optional[str]:
    """First person in an assignee chain ("Minda → Ivy" → "Minda"). None when
    the line is unstaffed. Pure."""
    if not assignee:
        return None
    for sep in ("→", "/", ","):
        if sep in assignee:
            assignee = assignee.split(sep, 1)[0]
    name = assignee.strip()
    return name or None


def match_member_gid(name: Optional[str], members: list[dict]) -> Optional[str]:
    """Asana user gid whose name matches (first-name, case-insensitive). Pure.

    Matches on the member's first name or full name so 'Ivy' finds
    'Ivy Santos'. Ambiguous / unknown names return None (task goes unassigned
    rather than to the wrong person)."""
    if not name:
        return None
    target = name.strip().casefold()
    hits = [
        m["gid"] for m in members
        if m.get("gid") and (
            (m.get("name") or "").strip().casefold() == target
            or (m.get("name") or "").strip().casefold().split(" ")[0] == target
        )
    ]
    return hits[0] if len(hits) == 1 else None


def task_notes(task: dict, month_label: str, plan_link: Optional[str]) -> str:
    """Plain-text task description for one plan line. Pure."""
    qty = task.get("quantity") or 1
    unit = task.get("unit_cost")
    line = task.get("line_cost")
    parts = [f"AR Tools · Monthly Task Plan · {month_label}"]
    cost_bits = []
    if unit is not None:
        cost_bits.append(f"{qty} × ${unit:g}")
    if line is not None:
        cost_bits.append(f"= ${line:g}")
    if cost_bits:
        parts.append("Budget: " + " ".join(cost_bits))
    if task.get("assignee"):
        parts.append(f"Assignment chain: {task['assignee']}")
    else:
        parts.append("UNSTAFFED — needs an owner")
    if task.get("rationale"):
        parts.append(f"Why: {task['rationale']}")
    if plan_link:
        parts.append(f"Plan: {plan_link}")
    return "\n".join(parts)


def proposal_task_name(proposal: dict) -> str:
    """Task name for an approved strategist proposal. Pure."""
    title = (proposal.get("title") or proposal.get("action") or "Strategist proposal").strip()
    return f"[Strategist] {title}"[:250]


def proposal_task_notes(proposal: dict, review_link: Optional[str]) -> str:
    """Plain-text description for a strategist-proposal task. Pure."""
    parts = ["AR Tools · Approved strategist proposal"]
    if proposal.get("action"):
        parts.append(f"Do: {proposal['action']}")
    if proposal.get("rationale"):
        parts.append(f"Why: {proposal['rationale']}")
    if proposal.get("sop_citation"):
        parts.append(f"SOP: {proposal['sop_citation']}")
    if review_link:
        parts.append(f"Review: {review_link}")
    return "\n".join(parts)


def _deep_link(path: str) -> Optional[str]:
    base = (settings.app_base_url or "").rstrip("/")
    return f"{base}/{path.lstrip('/')}" if base else None


def task_url(task_gid: str) -> str:
    return f"https://app.asana.com/0/0/{task_gid}/f"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def _team_members(supabase) -> list[dict]:
    return (
        supabase.table("asana_team_members")
        .select("gid, name")
        .eq("active", True)
        .execute()
    ).data or []


async def _ensure_month_section(project_gid: str, target: date) -> Optional[str]:
    """The month section's gid, creating the section if it doesn't exist yet."""
    label = asana_service.month_label(target)
    sections = await asana_service.list_sections(project_gid)
    for s in sections:
        if (s.get("name") or "").strip().casefold() == label.casefold():
            return s.get("gid")
    anchor = asana_service.month_insert_anchor_gid(sections)
    created = await asana_service.create_section(project_gid, label, insert_before=anchor)
    return created.get("gid")


# ---------------------------------------------------------------------------
# Recipe Engine plan push
# ---------------------------------------------------------------------------
async def push_task_plan(client_id: str, plan_row_id: str) -> dict:
    """Push one stored plan's task lines into the client's Asana project.

    Idempotent per line via the plan row's `asana_push` map. Returns
    {status, created, skipped, errors, section} — status 'skipped' with a
    reason when Asana/the mapping/the plan is absent.

    Cutover (native task manager Phase 5): once ``native_tasks_enabled`` is on,
    the push targets the NATIVE task board instead of Asana — same per-line
    idempotency ledger (`monthly_task_plans.asana_push`, gid = the native task
    id, url = a board deep link), so the Task Plan UI keeps working unchanged."""
    if settings.native_tasks_enabled:
        return _push_task_plan_native(client_id, plan_row_id)
    if not asana_service.is_configured():
        return {"status": "skipped", "reason": "asana_not_configured"}

    supabase = get_supabase()
    rows = (
        supabase.table("monthly_task_plans").select("*")
        .eq("id", plan_row_id).eq("client_id", client_id).limit(1).execute()
    ).data
    if not rows:
        return {"status": "failed", "reason": "plan_not_found"}
    plan_row = rows[0]
    tasks = ((plan_row.get("plan") or {}).get("tasks")) or []
    if not tasks:
        return {"status": "skipped", "reason": "plan_has_no_tasks"}

    project_gid = get_project_gid(client_id)
    if not project_gid:
        return {"status": "skipped", "reason": "no_project_mapping"}

    today = date.today()
    label = asana_service.month_label(today)
    section_gid = await _ensure_month_section(project_gid, today)
    if not section_gid:
        return {"status": "failed", "reason": "section_create_failed"}

    fields = await asana_service.resolve_project_fields(project_gid)
    members = _team_members(supabase)
    plan_link = _deep_link(f"clients/{client_id}/task-plan")

    pushed: dict = dict(plan_row.get("asana_push") or {})
    created = 0
    skipped = 0
    errors: list[str] = []
    for idx, task in enumerate(tasks):
        key = task_key(task, idx)
        if pushed.get(key, {}).get("gid"):
            skipped += 1
            continue
        try:
            payload = asana_service.build_task_payload(
                task.get("label") or task.get("task_type") or "Task",
                project_gid,
                section_gid,
                assignee_gid=match_member_gid(primary_assignee_name(task.get("assignee")), members),
                status_field_gid=fields.get("status_field_gid") or "",
                not_started_option_gid=fields.get("not_started_option_gid") or "",
            )
            payload["notes"] = task_notes(task, label, plan_link)
            result = await asana_service.create_task(payload)
            gid = (result or {}).get("gid")
            if not gid:
                raise RuntimeError("no_gid_returned")
            pushed[key] = {"gid": gid, "url": task_url(gid), "name": payload["name"]}
            created += 1
            # Persist after each create so a mid-run crash never re-creates
            # the lines that already landed.
            supabase.table("monthly_task_plans").update({"asana_push": pushed}).eq(
                "id", plan_row_id
            ).execute()
        except Exception as exc:  # one bad line must not abort the rest
            errors.append(f"{task.get('label')}: {str(exc)[:120]}")
            logger.warning(
                "asana_push.task_failed",
                extra={"client_id": client_id, "task": task.get("label"), "error": str(exc)},
            )

    return {
        "status": "ok" if not errors else "partial",
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "section": label,
        "project_gid": project_gid,
    }


def enqueue_asana_push(client_id: str, plan_row_id: str) -> Optional[str]:
    """Enqueue the push job (deduped against an in-flight push for the plan).
    Returns the job id, or None when deduped."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "asana_push")
        .eq("entity_id", client_id)
        .eq("payload->>plan_row_id", plan_row_id)
        .in_("status", ["pending", "running"])
        .limit(1).execute()
    ).data
    if existing:
        return existing[0]["id"]
    row = (
        supabase.table("async_jobs").insert({
            "job_type": "asana_push",
            "entity_id": client_id,
            "payload": {"client_id": client_id, "plan_row_id": plan_row_id},
        }).execute()
    ).data[0]
    return row["id"]


async def run_asana_push_job(job: dict) -> None:
    """async_jobs handler for job_type='asana_push'."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    plan_row_id = payload.get("plan_row_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not (client_id and plan_row_id):
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id/plan_row_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        result = await push_task_plan(client_id, plan_row_id)
    except Exception as exc:
        logger.warning("asana_push.job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update({
        "status": "complete" if result.get("status") in ("ok", "partial", "skipped") else "failed",
        "result": result,
        "error": result.get("reason") if result.get("status") == "failed" else None,
        "completed_at": "now()",
    }).eq("id", job_id).execute()


# ---------------------------------------------------------------------------
# Strategist proposal push (Strategist Phase 5)
# ---------------------------------------------------------------------------
def _push_task_plan_native(client_id: str, plan_row_id: str) -> dict:
    """The native-board sibling of push_task_plan (post-cutover write target)."""
    from services import task_monthly, task_service

    supabase = get_supabase()
    rows = (
        supabase.table("monthly_task_plans").select("*")
        .eq("id", plan_row_id).eq("client_id", client_id).limit(1).execute()
    ).data
    if not rows:
        return {"status": "failed", "reason": "plan_not_found"}
    plan_row = rows[0]
    tasks = ((plan_row.get("plan") or {}).get("tasks")) or []
    if not tasks:
        return {"status": "skipped", "reason": "plan_has_no_tasks"}

    today = date.today()
    label = asana_service.month_label(today)
    section = task_monthly.ensure_month_section(client_id, today)
    members = _team_members(supabase)
    names = {m.get("gid"): m.get("name") for m in members}
    plan_link = _deep_link(f"clients/{client_id}/task-plan")

    pushed: dict = dict(plan_row.get("asana_push") or {})
    created = 0
    skipped = 0
    errors: list[str] = []
    for idx, task in enumerate(tasks):
        key = task_key(task, idx)
        if pushed.get(key, {}).get("gid"):
            skipped += 1
            continue
        try:
            name = task.get("label") or task.get("task_type") or "Task"
            gid = match_member_gid(primary_assignee_name(task.get("assignee")), members)
            row = task_service.create_task(
                name,
                client_id=client_id,
                section_id=section["id"],
                assignee_gid=gid,
                assignee_name=names.get(gid),
                description=task_notes(task, label, plan_link),
                sort_order=idx,
                source="task_plan",
                source_ref=f"{plan_row_id}:{key}",
            )
            pushed[key] = {
                "gid": row["id"],
                "url": f"/clients/{client_id}/tasks?task={row['id']}",
                "name": name,
            }
            created += 1
            supabase.table("monthly_task_plans").update({"asana_push": pushed}).eq(
                "id", plan_row_id
            ).execute()
        except Exception as exc:  # one bad line must not abort the rest
            errors.append(f"{task.get('label')}: {str(exc)[:120]}")
            logger.warning(
                "task_plan_push_native_failed",
                extra={"client_id": client_id, "task": task.get("label"), "error": str(exc)},
            )
    return {
        "status": "ok" if not errors else "partial",
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "section": label,
        "target": "native",
    }


async def push_proposal(client_id: str, review_id: str, proposal: dict) -> Optional[dict]:
    """Create one task for an approved strategist proposal — native board once
    ``native_tasks_enabled`` is on, the client's Asana project until then.

    Best-effort: returns {gid, url} or None (unconfigured / unmapped / API
    error) — approval itself must never fail over the task write."""
    try:
        if settings.native_tasks_enabled:
            from services import task_monthly, task_service

            section = task_monthly.ensure_month_section(client_id, date.today())
            row = task_service.create_task(
                proposal_task_name(proposal),
                client_id=client_id,
                section_id=section["id"],
                description=proposal_task_notes(
                    proposal, _deep_link(f"clients/{client_id}/action-plan")
                ),
                source="strategy_proposal",
                source_ref=f"{review_id}:{proposal_task_name(proposal)[:100].casefold()}",
            )
            return {"gid": row["id"], "url": f"/clients/{client_id}/tasks?task={row['id']}"}
        if not asana_service.is_configured():
            return None
        project_gid = get_project_gid(client_id)
        if not project_gid:
            return None
        today = date.today()
        section_gid = await _ensure_month_section(project_gid, today)
        if not section_gid:
            return None
        fields = await asana_service.resolve_project_fields(project_gid)
        payload = asana_service.build_task_payload(
            proposal_task_name(proposal),
            project_gid,
            section_gid,
            status_field_gid=fields.get("status_field_gid") or "",
            not_started_option_gid=fields.get("not_started_option_gid") or "",
        )
        payload["notes"] = proposal_task_notes(
            proposal, _deep_link(f"clients/{client_id}/action-plan")
        )
        result = await asana_service.create_task(payload)
        gid = (result or {}).get("gid")
        if not gid:
            return None
        return {"gid": gid, "url": task_url(gid)}
    except Exception as exc:
        logger.warning(
            "asana_push.proposal_failed",
            extra={"client_id": client_id, "review_id": review_id, "error": str(exc)},
        )
        return None

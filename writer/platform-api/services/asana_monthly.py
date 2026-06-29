"""Asana monthly section automation (Feature A).

For each client, create a new ``<Month YYYY>`` section in its mapped Asana
project and populate it from the client's app-defined task template
(``asana_client_task_templates``). Idempotent: if the month's section already
exists the run is a no-op, so the auto (scheduled) and manual triggers can't
double up.

See docs/modules/asana-task-integration-plan-v1_0.md §3.
"""

from __future__ import annotations

import logging
from datetime import date

from config import settings
from db.supabase_client import get_supabase
from services import asana_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def get_project_gid(client_id: str) -> str | None:
    """The Asana project GID mapped to a client (None when unmapped)."""
    rows = (
        get_supabase()
        .table("asana_client_projects")
        .select("project_gid")
        .eq("client_id", client_id)
        .limit(1)
        .execute()
    ).data
    return rows[0]["project_gid"] if rows else None


def get_active_templates(client_id: str) -> list[dict]:
    """The client's active task-template rows, in display order."""
    return (
        get_supabase()
        .table("asana_client_task_templates")
        .select("*")
        .eq("client_id", client_id)
        .eq("active", True)
        .order("sort_order")
        .execute()
    ).data or []


def get_task_library() -> dict:
    """The active Task Library keyed by lowercased name → row (default hours +
    category). The single source of truth for standard task durations."""
    rows = (
        get_supabase()
        .table("asana_task_library")
        .select("name, default_hours, default_category_name")
        .eq("active", True)
        .execute()
    ).data or []
    return {(r.get("name") or "").strip().casefold(): r for r in rows}


def apply_library_defaults(templates: list[dict], library: dict, category_options: dict) -> int:
    """Fill each template row's blank est_hours / category from the Task Library
    (matched by task name), mutating rows in place. A row's own value always
    wins (per-client override). Returns how many rows inherited something. Pure
    — unit-tested."""
    applied = 0
    for row in templates:
        lib = library.get((row.get("name") or "").strip().casefold())
        if not lib:
            continue
        touched = False
        if row.get("est_hours") is None and lib.get("default_hours") is not None:
            row["est_hours"] = lib["default_hours"]
            touched = True
        if not row.get("category_option_gid") and lib.get("default_category_name"):
            opt = (category_options or {}).get(lib["default_category_name"].strip().casefold())
            if opt:
                row["category_option_gid"] = opt
                touched = True
        if touched:
            applied += 1
    return applied


def get_eligible_assignees(client_id: str) -> list[str]:
    """The per-client auto-distribution eligibility list (Asana user GIDs)."""
    rows = (
        get_supabase()
        .table("asana_client_projects")
        .select("auto_assignee_gids")
        .eq("client_id", client_id)
        .limit(1)
        .execute()
    ).data
    return list(rows[0].get("auto_assignee_gids") or []) if rows else []


def get_member_capacity(gids: list[str]) -> dict[str, float]:
    """Weekly capacity per gid (from asana_team_members; default for the rest)."""
    if not gids:
        return {}
    rows = (
        get_supabase()
        .table("asana_team_members")
        .select("gid, weekly_hours")
        .in_("gid", gids)
        .execute()
    ).data or []
    by_gid = {r["gid"]: r.get("weekly_hours") for r in rows}
    return {g: float(by_gid.get(g) or settings.asana_default_weekly_hours) for g in gids}


async def assign_auto_tasks(client_id: str, templates: list[dict]) -> int:
    """Distribute auto-assign template rows across the client's eligible members
    by remaining capacity, mutating each chosen row's ``assignee_gid`` in place.
    Returns how many rows got an auto assignment. Best-effort: no eligible members
    (or feature off) leaves auto rows unassigned."""
    from services import asana_workload

    if not settings.asana_auto_distribute_enabled:
        return 0
    auto_rows = [r for r in templates if r.get("auto_assign") and not r.get("assignee_gid")]
    if not auto_rows:
        return 0
    eligible = get_eligible_assignees(client_id)
    if not eligible:
        logger.info("asana_monthly.auto_distribute_no_eligible", extra={"client_id": client_id})
        return 0

    capacity = get_member_capacity(eligible)
    open_hours = await asana_workload.open_hours_for_members(eligible)
    members = [
        {"gid": g, "remaining": capacity.get(g, settings.asana_default_weekly_hours) - open_hours.get(g, 0.0)}
        for g in eligible
    ]
    task_hours = [float(r.get("est_hours") or settings.asana_default_task_hours) for r in auto_rows]
    assigned = asana_service.distribute_tasks(task_hours, members)
    n = 0
    for row, gid in zip(auto_rows, assigned):
        if gid:
            row["assignee_gid"] = gid
            n += 1
    return n


async def _create_task_for_row(
    row: dict, project_gid: str, section_gid: str, fields: dict, template_by_name: dict
) -> None:
    """Create one task: instantiate the matching Asana task template (preserving
    its subtasks) then set assignee/fields + move into the section; otherwise
    create a plain task."""
    name = (row.get("name") or "").strip()
    template_gid = template_by_name.get(name.casefold())
    if template_gid:
        new_task_gid = await asana_service.instantiate_task_template(template_gid, name)
        if new_task_gid:
            update = asana_service.build_task_update(row, fields)
            if update:
                await asana_service.update_task(new_task_gid, update)
            await asana_service.add_task_to_section(section_gid, new_task_gid)
            return
        # Instantiation returned no task → fall back to a plain task below.
    payload = asana_service.payload_from_template_row(row, project_gid, section_gid, fields=fields)
    await asana_service.create_task(payload)


# ---------------------------------------------------------------------------
# Core: generate one month for one client
# ---------------------------------------------------------------------------
async def generate_month_for_client(client_id: str, target: date) -> dict:
    """Create ``<Month YYYY>`` for ``target`` and populate it from the template.

    Returns a summary dict: ``{status, section, created, ...}``. Never raises for
    a "nothing to do" condition (unconfigured / unmapped / no template / already
    exists) — those return a status the caller can surface.
    """
    label = asana_service.month_label(target)

    if not asana_service.is_configured():
        return {"status": "skipped", "reason": "asana_not_configured", "section": label}

    project_gid = get_project_gid(client_id)
    if not project_gid:
        return {"status": "skipped", "reason": "no_project_mapping", "section": label}

    templates = get_active_templates(client_id)
    if not templates:
        return {"status": "skipped", "reason": "no_template", "section": label}

    sections = await asana_service.list_sections(project_gid)
    if asana_service.section_name_exists(sections, label):
        return {"status": "exists", "reason": "section_already_exists", "section": label, "created": 0}

    # Resolve this project's Status / category / effort field GIDs by name
    # (project-local fields differ per project), once for the whole batch.
    fields = await asana_service.resolve_project_fields(project_gid)

    # Inherit standard durations / category from the Task Library (by task name)
    # for any row that didn't set its own — the single source of truth.
    apply_library_defaults(templates, get_task_library(), fields.get("category_options") or {})

    # Capacity-aware auto-distribution: fill in assignees for auto-assign rows
    # (mutates those rows' assignee_gid in place before payloads are built).
    await assign_auto_tasks(client_id, templates)

    # A row whose name matches an Asana task template is INSTANTIATED (so its
    # subtasks come along); others are created as plain tasks. Best-effort: if
    # the template list can't be fetched, everything falls back to plain tasks.
    template_by_name: dict[str, str] = {}
    try:
        for t in await asana_service.list_project_task_templates(project_gid):
            if t.get("gid") and t.get("name"):
                template_by_name[t["name"].strip().casefold()] = t["gid"]
    except Exception as exc:
        logger.warning("asana_monthly.task_templates_failed", extra={"client_id": client_id, "error": str(exc)})

    anchor = asana_service.month_insert_anchor_gid(sections)
    new_section = await asana_service.create_section(project_gid, label, insert_before=anchor)
    section_gid = new_section.get("gid")

    created = 0
    errors: list[str] = []
    for row in templates:
        try:
            await _create_task_for_row(row, project_gid, section_gid, fields, template_by_name)
            created += 1
        except Exception as exc:  # one bad task shouldn't abort the rest
            errors.append(f"{row.get('name')}: {str(exc)[:120]}")
            logger.warning(
                "asana_monthly.task_create_failed",
                extra={"client_id": client_id, "task": row.get("name"), "error": str(exc)},
            )

    logger.info(
        "asana_monthly.generated",
        extra={"client_id": client_id, "section": label, "created": created, "errors": len(errors)},
    )
    return {
        "status": "created",
        "section": label,
        "section_gid": section_gid,
        "created": created,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Job enqueue + handler
# ---------------------------------------------------------------------------
def enqueue_asana_monthly(client_id: str, target: date, trigger: str = "scheduled") -> None:
    """Enqueue an asana_monthly job (deduped against any in-flight one)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "asana_monthly")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {
            "job_type": "asana_monthly",
            "entity_id": client_id,
            "payload": {"client_id": client_id, "month": target.isoformat(), "trigger": trigger},
        }
    ).execute()


async def run_asana_monthly_job(job: dict) -> None:
    """async_jobs handler for job_type='asana_monthly'."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    month = payload.get("month")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id or not month:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id/month", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        result = await generate_month_for_client(client_id, date.fromisoformat(month))
    except Exception as exc:
        logger.warning("asana_monthly_job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()


# ---------------------------------------------------------------------------
# Scheduler due-check (monthly)
# ---------------------------------------------------------------------------
def enqueue_due_asana_monthly(target: date) -> int:
    """Enqueue an asana_monthly job for every mapped client, for ``target``'s
    month. Called once per month by the scheduler on ``asana_month_generate_day``.
    Idempotent at execution (the job no-ops if the section exists)."""
    if not settings.asana_monthly_enabled or not asana_service.is_configured():
        return 0
    rows = (
        get_supabase()
        .table("asana_client_projects")
        .select("client_id")
        .execute()
    ).data or []
    month_start = target.replace(day=1)
    for r in rows:
        enqueue_asana_monthly(r["client_id"], month_start, trigger="scheduled")
    if rows:
        logger.info("gsc_scheduler.asana_monthly_enqueued", extra={"clients": len(rows)})
    return len(rows)

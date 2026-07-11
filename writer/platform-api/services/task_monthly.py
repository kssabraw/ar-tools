"""Native task manager — recurring monthly generation (PRD §6.8/§10).

The native replacement for ``asana_monthly``: once per month (or on demand),
create a client's "<Month YYYY>" section in ``task_sections`` and populate it
from the client's recurring template (``asana_client_task_templates``, reused
as-is), inheriting blank hours/category from the Task Library and copying each
library task's **default subtask checklist** (``task_library_subtasks`` — the
native replacement for instantiating Asana task templates).

Reuses the Asana module's brains verbatim where they're I/O-free or
target-agnostic: ``asana_service.month_label``/``shift_months``/
``distribute_tasks`` and ``asana_monthly``'s template/library/eligibility DB
readers. Only the write target changes (``tasks`` inserts instead of Asana
POSTs).

Idempotency is **per task**, not per section: every generated task carries
``source='monthly'`` + a stable ``source_ref`` (client + month + template row),
so a re-run after a partial failure fills only the gaps — strictly better than
the Asana version's section-exists no-op.

Dormant until ``settings.native_tasks_enabled`` — the scheduler hook and job
are gated so nothing runs while the team still executes in Asana.
"""

from __future__ import annotations

import logging
from datetime import date

from config import settings
from db.supabase_client import get_supabase
from services import task_service, task_workload
from services.asana_monthly import (
    get_active_templates,
    get_eligible_assignees,
    get_member_capacity,
    get_task_library,
)
from services.asana_service import distribute_tasks, month_label

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def apply_native_defaults(templates: list[dict], library: dict) -> int:
    """Fill each template row's blank ``est_hours`` / ``category_name`` from the
    Task Library (matched by task name), mutating rows in place. A row's own
    value always wins (per-client override). The native sibling of
    ``asana_monthly.apply_library_defaults`` — categories are names here, not
    Asana option GIDs. Returns how many rows inherited something."""
    applied = 0
    for row in templates:
        lib = library.get((row.get("name") or "").strip().casefold())
        if not lib:
            continue
        touched = False
        if row.get("est_hours") is None and lib.get("default_hours") is not None:
            row["est_hours"] = lib["default_hours"]
            touched = True
        if not row.get("category_name") and lib.get("default_category_name"):
            row["category_name"] = lib["default_category_name"]
            touched = True
        if touched:
            applied += 1
    return applied


def month_source_ref(client_id: str, target: date, template_row_id: str) -> str:
    """The stable per-task idempotency key for one template row in one month."""
    return f"monthly:{client_id}:{target.strftime('%Y-%m')}:{template_row_id}"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def get_library_checklists() -> dict[str, list[str]]:
    """Every library task's default subtask checklist, keyed by casefolded
    library name → ordered subtask names."""
    rows = (
        get_supabase()
        .table("task_library_subtasks")
        .select("library_name, name, sort_order")
        .order("sort_order")
        .execute()
    ).data or []
    checklists: dict[str, list[str]] = {}
    for r in rows:
        key = (r.get("library_name") or "").strip().casefold()
        if key and (r.get("name") or "").strip():
            checklists.setdefault(key, []).append(r["name"].strip())
    return checklists


def ensure_month_section(client_id: str, target: date) -> dict:
    """Get-or-create the client's month section (idempotent, case-insensitive;
    the unique index backstops a create race)."""
    supabase = get_supabase()
    label = month_label(target)
    existing = (
        supabase.table("task_sections")
        .select("*")
        .eq("client_id", client_id)
        .ilike("name", label)
        .limit(1)
        .execute()
    ).data
    if existing:
        return existing[0]
    try:
        return (
            supabase.table("task_sections")
            .insert(
                {
                    "client_id": client_id,
                    "name": label,
                    "kind": "month",
                    "period_month": target.replace(day=1).isoformat(),
                }
            )
            .execute()
        ).data[0]
    except Exception:
        # Lost a create race to the unique index — re-read the winner.
        rows = (
            supabase.table("task_sections")
            .select("*")
            .eq("client_id", client_id)
            .ilike("name", label)
            .limit(1)
            .execute()
        ).data
        if rows:
            return rows[0]
        raise


def get_member_names(gids: list[str]) -> dict[str, str]:
    """Display names for team-member gids (for the cached assignee_name)."""
    if not gids:
        return {}
    rows = (
        get_supabase()
        .table("asana_team_members")
        .select("gid, name")
        .in_("gid", gids)
        .execute()
    ).data or []
    return {r["gid"]: r.get("name") for r in rows if r.get("gid")}


def assign_auto_tasks(client_id: str, templates: list[dict]) -> int:
    """Distribute auto-assign template rows across the client's eligible members
    by remaining capacity (native open hours — a DB sum, not an Asana fetch),
    mutating each chosen row's ``assignee_gid`` in place. Best-effort: no
    eligible members (or feature off) leaves auto rows unassigned."""
    if not settings.asana_auto_distribute_enabled:
        return 0
    auto_rows = [r for r in templates if r.get("auto_assign") and not r.get("assignee_gid")]
    if not auto_rows:
        return 0
    eligible = get_eligible_assignees(client_id)
    if not eligible:
        logger.info("task_monthly.auto_distribute_no_eligible", extra={"client_id": client_id})
        return 0

    capacity = get_member_capacity(eligible)
    open_hours = task_workload.open_hours_for_members(eligible)
    members = [
        {"gid": g, "remaining": capacity.get(g, settings.asana_default_weekly_hours) - open_hours.get(g, 0.0)}
        for g in eligible
    ]
    hours = [float(r.get("est_hours") or settings.asana_default_task_hours) for r in auto_rows]
    assigned = distribute_tasks(hours, members)
    names = get_member_names([g for g in assigned if g])
    n = 0
    for row, gid in zip(auto_rows, assigned):
        if gid:
            row["assignee_gid"] = gid
            row["assignee_name"] = names.get(gid) or row.get("assignee_name")
            n += 1
    return n


# ---------------------------------------------------------------------------
# Core: generate one month for one client
# ---------------------------------------------------------------------------
def generate_month_for_client(client_id: str, target: date) -> dict:
    """Create/populate the "<Month YYYY>" section for ``target`` from the
    client's template. Idempotent per task (source_ref); re-runs fill gaps.

    Returns ``{status, section, created, existing, errors}``. Never raises for
    a "nothing to do" condition — those return a status the caller surfaces.
    """
    label = month_label(target)

    templates = get_active_templates(client_id)
    if not templates:
        return {"status": "skipped", "reason": "no_template", "section": label}

    section = ensure_month_section(client_id, target)

    # Inherit standard durations / category from the Task Library (by name),
    # then fill auto-assign rows by remaining capacity.
    apply_native_defaults(templates, get_task_library())
    assign_auto_tasks(client_id, templates)

    categories = task_service.get_categories()
    initial = task_service.initial_status_key(task_service.get_statuses())
    checklists = get_library_checklists()

    created = 0
    existing = 0
    errors: list[str] = []
    assigned_counts: dict[str, int] = {}
    for idx, row in enumerate(templates):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        try:
            task = task_service.create_task(
                name,
                client_id=client_id,
                section_id=section["id"],
                assignee_gid=row.get("assignee_gid"),
                assignee_name=row.get("assignee_name"),
                status_key=initial,
                category=task_service.resolve_category_key(row.get("category_name"), categories),
                est_hours=row.get("est_hours"),
                sort_order=idx,
                source="monthly",
                source_ref=month_source_ref(client_id, target, str(row.get("id"))),
                library_task_name=name,
            )
            if task.get("_existing"):
                existing += 1
                continue
            subtasks = checklists.get(name.casefold()) or []
            if subtasks:
                task_service.create_subtasks(task, subtasks)
            created += 1
            who = row.get("assignee_name") or row.get("assignee_gid") or "Unassigned"
            assigned_counts[who] = assigned_counts.get(who, 0) + 1
        except Exception as exc:  # one bad task shouldn't abort the rest
            errors.append(f"{name}: {str(exc)[:120]}")
            logger.warning(
                "task_monthly.task_create_failed",
                extra={"client_id": client_id, "task": name, "error": str(exc)},
            )

    status = "created" if created else ("exists" if existing else "skipped")
    if created:
        # One digest per generation run (not one ping per task) — covers the
        # PRD's "assigned to you incl. auto-distribution results" without
        # flooding the channel on the 1st of the month. Best-effort.
        try:
            from services import notifications

            breakdown = ", ".join(f"{who} {n}" for who, n in sorted(assigned_counts.items(), key=lambda kv: -kv[1]))
            notifications.emit(
                client_id=client_id,
                kind="task_month_generated",
                title=f"{label}: {created} task{'s' if created != 1 else ''} generated",
                summary=breakdown,
                severity="info",
                payload={"link": f"/clients/{client_id}/tasks", "section_id": section["id"]},
            )
        except Exception as exc:
            logger.warning("task_month_notify_failed", extra={"client_id": client_id, "error": str(exc)})
    logger.info(
        "task_monthly.generated",
        extra={"client_id": client_id, "section": label, "created_count": created, "existing": existing, "errors": len(errors)},
    )
    return {
        "status": status,
        "section": label,
        "section_id": section["id"],
        "created": created,
        "existing": existing,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Job enqueue + handler (async_jobs type 'task_month_generate')
# ---------------------------------------------------------------------------
def enqueue_task_month(client_id: str, target: date, trigger: str = "scheduled") -> None:
    """Enqueue a task_month_generate job (deduped against any in-flight one)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "task_month_generate")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {
            "job_type": "task_month_generate",
            "entity_id": client_id,
            "payload": {"client_id": client_id, "month": target.isoformat(), "trigger": trigger},
        }
    ).execute()


async def run_task_month_job(job: dict) -> None:
    """async_jobs handler for job_type='task_month_generate'."""
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
        result = generate_month_for_client(client_id, date.fromisoformat(month))
    except Exception as exc:
        logger.warning("task_month_job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()


# ---------------------------------------------------------------------------
# Scheduler due-check (monthly; rides the Asana cadence settings)
# ---------------------------------------------------------------------------
def enqueue_due_task_months(target: date) -> int:
    """Enqueue a task_month_generate job for every client with an active
    template, for ``target``'s month. Called once per month by the scheduler on
    ``asana_month_generate_day`` (the shared cadence), gated on
    ``native_tasks_enabled``. Idempotent at execution (per-task source_ref)."""
    if not settings.native_tasks_enabled:
        return 0
    rows = (
        get_supabase()
        .table("asana_client_task_templates")
        .select("client_id")
        .eq("active", True)
        .execute()
    ).data or []
    client_ids = sorted({r["client_id"] for r in rows if r.get("client_id")})
    month_start = target.replace(day=1)
    for cid in client_ids:
        enqueue_task_month(cid, month_start, trigger="scheduled")
    if client_ids:
        logger.info("gsc_scheduler.task_monthly_enqueued", extra={"clients": len(client_ids)})
    return len(client_ids)

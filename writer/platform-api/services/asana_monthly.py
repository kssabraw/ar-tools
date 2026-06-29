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

    anchor = asana_service.month_insert_anchor_gid(sections)
    new_section = await asana_service.create_section(project_gid, label, insert_before=anchor)
    section_gid = new_section.get("gid")

    created = 0
    errors: list[str] = []
    for row in templates:
        payload = asana_service.payload_from_template_row(row, project_gid, section_gid)
        try:
            await asana_service.create_task(payload)
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

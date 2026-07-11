"""Native task manager — Team Workload + daily due sweep (PRD §6.12/§6.11).

The native replacement for ``asana_workload``'s data source: per-person open
**estimated hours** vs weekly capacity, computed from the ``tasks`` table (a DB
sum) instead of Asana fetches. The workload *math* is reused verbatim
(``asana_service.build_workload_report`` — tested, effort-weighted, same
thresholds); native task rows are adapted into the shape it already consumes.

Team list + capacity stay in ``asana_team_members`` for v1 (the planning
decision: assignees are member gids until the profiles unification).

Subtasks are EXCLUDED from workload: the parent task's estimate covers its
whole checklist, so counting children would double-book people.

Also home to the **daily due sweep** (async_jobs type ``task_due_sweep``): one
suite-level digest of due-today/overdue open tasks per assignee, via the shared
notifications service. Dormant until ``settings.native_tasks_enabled``.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import notifications
from services.asana_service import build_workload_report
from services.asana_workload import get_team_members

logger = logging.getLogger(__name__)

# The synthetic effort-field name the adapter emits so the reused Asana
# workload math reads native est_hours through its custom-field path.
_EFFORT_FIELD = "est_hours"


# ---------------------------------------------------------------------------
# Native reads
# ---------------------------------------------------------------------------
def _open_task_rows(gids: Optional[list[str]] = None) -> list[dict]:
    """Open, non-trashed, top-level task rows (optionally for specific
    assignees): the workload unit set."""
    q = (
        get_supabase()
        .table("tasks")
        .select("assignee_gid, est_hours, due_date, name, client_id")
        .eq("completed", False)
        .is_("deleted_at", "null")
        .is_("parent_task_id", "null")
    )
    if gids is not None:
        if not gids:
            return []
        q = q.in_("assignee_gid", gids)
    return q.execute().data or []


def open_hours_for_members(gids: list[str]) -> dict[str, float]:
    """Current open-task hours per member (native DB sum; unestimated tasks
    count as the default). Reused by monthly auto-distribution to seed load."""
    totals = {g: 0.0 for g in gids}
    for row in _open_task_rows(gids):
        gid = row.get("assignee_gid")
        if gid in totals:
            hrs = row.get("est_hours")
            totals[gid] += float(hrs) if hrs is not None else float(settings.asana_default_task_hours)
    return totals


def adapt_task_row(row: dict) -> dict:
    """Adapt a native tasks row into the dict shape the reused Asana workload
    math consumes (``due_on`` + an effort custom field). Pure — unit-tested."""
    est = row.get("est_hours")
    return {
        "due_on": row.get("due_date"),
        "custom_fields": [
            {"name": _EFFORT_FIELD, "number_value": float(est) if est is not None else None}
        ],
    }


def build_team_workload() -> dict:
    """The effort-weighted Team Workload report, from native tasks."""
    members = get_team_members()
    if not members:
        return {
            "configured": True,
            "source": "tasks",
            "members": [],
            "overloaded": [],
            "note": "no_team_list",
        }

    rows = _open_task_rows([m["gid"] for m in members])
    by_gid: dict[str, list[dict]] = {}
    for r in rows:
        gid = r.get("assignee_gid")
        if gid:
            by_gid.setdefault(gid, []).append(adapt_task_row(r))

    report = build_workload_report(
        [
            {
                "gid": m["gid"],
                "name": m.get("name") or m["gid"],
                "weekly_hours": m.get("weekly_hours"),
                "tasks": by_gid.get(m["gid"], []),
            }
            for m in members
        ],
        effort_field_name=_EFFORT_FIELD,
        effort_field_gid="",
        default_task_hours=settings.asana_default_task_hours,
        daily_workdays=settings.asana_workload_daily_workdays,
        backlog_weeks=settings.asana_workload_backlog_weeks,
        default_weekly_hours=settings.asana_default_weekly_hours,
    )
    report["configured"] = True
    report["source"] = "tasks"
    return report


async def run_workload_alert() -> dict:
    """Daily overload alert from native tasks (the scheduler calls this instead
    of the Asana one once native_tasks_enabled). Same digest shape/kind flow as
    asana_workload.run_workload_alert."""
    report = build_team_workload()
    overloaded = report.get("overloaded") or []
    if not overloaded:
        return {"emitted": False, "overloaded": 0}
    names = ", ".join(m["name"] for m in overloaded)
    lines = "; ".join(f"{m['name']}: {'; '.join(m['flags'])}" for m in overloaded)
    notifications.emit(
        client_id=None,  # suite-wide
        kind="task_overload",
        title=f"{len(overloaded)} team member{'s' if len(overloaded) != 1 else ''} overloaded ({names})",
        summary=lines,
        severity="warning",
        payload={"link": "/workload", "overloaded": [m["gid"] for m in overloaded]},
    )
    logger.info("task_workload.alert_emitted", extra={"overloaded": len(overloaded)})
    return {"emitted": True, "overloaded": len(overloaded)}


# ---------------------------------------------------------------------------
# Daily due sweep (async_jobs type 'task_due_sweep')
# ---------------------------------------------------------------------------
def select_due_tasks(rows: list[dict], today: date) -> dict[str, dict]:
    """Group open tasks into due-today / overdue buckets per assignee.
    Undated and unassigned tasks are skipped (nothing to nudge, no one to
    nudge). Pure — unit-tested."""
    buckets: dict[str, dict] = {}
    for r in rows:
        gid = r.get("assignee_gid")
        due_raw = r.get("due_date")
        if not gid or not due_raw:
            continue
        due = date.fromisoformat(due_raw) if isinstance(due_raw, str) else due_raw
        if due > today:
            continue
        entry = buckets.setdefault(gid, {"name": r.get("assignee_name"), "due_today": [], "overdue": []})
        (entry["due_today"] if due == today else entry["overdue"]).append(r.get("name") or "")
    return buckets


def run_due_sweep(today: Optional[date] = None) -> dict:
    """Build the due digest and emit ONE suite-level notification when anything
    is due today or overdue. Returns a summary for the job result."""
    today = today or date.today()
    rows = (
        get_supabase()
        .table("tasks")
        .select("assignee_gid, assignee_name, due_date, name")
        .eq("completed", False)
        .is_("deleted_at", "null")
        .is_("parent_task_id", "null")
        .lte("due_date", today.isoformat())
        .execute()
    ).data or []
    buckets = select_due_tasks(rows, today)
    if not buckets:
        return {"emitted": False, "assignees": 0}

    due_count = sum(len(b["due_today"]) for b in buckets.values())
    overdue_count = sum(len(b["overdue"]) for b in buckets.values())
    lines = "; ".join(
        f"{b.get('name') or gid}: {len(b['due_today'])} due today, {len(b['overdue'])} overdue"
        for gid, b in sorted(buckets.items(), key=lambda kv: -(len(kv[1]["overdue"]) + len(kv[1]["due_today"])))
    )
    notifications.emit(
        client_id=None,  # suite-wide digest
        kind="task_due",
        title=f"Tasks: {due_count} due today, {overdue_count} overdue",
        summary=lines,
        severity="warning" if overdue_count else "info",
        payload={"link": "/tasks", "assignees": list(buckets.keys())},
    )
    return {"emitted": True, "assignees": len(buckets), "due_today": due_count, "overdue": overdue_count}


def enqueue_due_sweep() -> None:
    """Enqueue the daily task_due_sweep job (deduped against in-flight).
    No-ops while the native task manager is dormant."""
    if not settings.native_tasks_enabled:
        return
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "task_due_sweep")
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "task_due_sweep", "payload": {}}
    ).execute()


async def run_due_sweep_job(job: dict) -> None:
    """async_jobs handler for job_type='task_due_sweep'."""
    supabase = get_supabase()
    try:
        result = run_due_sweep()
    except Exception as exc:
        logger.warning("task_due_sweep_failed", extra={"error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job["id"]).execute()

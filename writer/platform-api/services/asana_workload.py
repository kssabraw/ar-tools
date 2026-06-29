"""Asana Team Workload (Feature B) — effort-weighted read + daily alert.

Pulls the tracked team list's open tasks across all client projects and
aggregates per-person **estimated hours** vs each person's weekly capacity,
flagging overloads (a single day's due hours over daily capacity, or an open
backlog over N weeks of capacity). Suite-level, read-only for the view; the
daily alert (Phase 3) pings Slack/in-app via the notifications service.

Team list + capacity live in ``asana_team_members`` (editable in the Workload
page); the env ``asana_team_member_gids`` is a fallback seed only.

See docs/modules/asana-task-integration-plan-v1_0.md §4.
"""

from __future__ import annotations

import asyncio
import logging

from config import settings
from db.supabase_client import get_supabase
from services import asana_service, notifications

logger = logging.getLogger(__name__)


def _thresholds() -> dict:
    return {
        "default_weekly_hours": settings.asana_default_weekly_hours,
        "daily_workdays": settings.asana_workload_daily_workdays,
        "backlog_weeks": settings.asana_workload_backlog_weeks,
        "default_task_hours": settings.asana_default_task_hours,
    }


def _empty(configured: bool, note: str | None = None) -> dict:
    report = {"configured": configured, "members": [], "overloaded": [], "thresholds": _thresholds()}
    if note:
        report["note"] = note
    return report


def get_team_members() -> list[dict]:
    """The tracked team (gid, name, weekly_hours) from the DB table, falling
    back to the env gid list (default capacity) when the table is empty."""
    rows = (
        get_supabase()
        .table("asana_team_members")
        .select("gid, name, weekly_hours")
        .eq("active", True)
        .execute()
    ).data or []
    if rows:
        return rows
    return [{"gid": g, "name": None, "weekly_hours": None} for g in asana_service.parse_gids(settings.asana_team_member_gids)]


async def _member_entry(member: dict, name_by: dict) -> dict:
    """Fetch one member's open tasks (best-effort — a failure yields no tasks)."""
    gid = member["gid"]
    try:
        tasks = await asana_service.list_member_open_tasks(gid)
    except Exception as exc:
        logger.warning("asana_workload.member_fetch_failed", extra={"gid": gid, "error": str(exc)})
        tasks = []
    return {
        "gid": gid,
        "name": member.get("name") or name_by.get(gid) or gid,
        "weekly_hours": member.get("weekly_hours"),
        "tasks": tasks,
    }


async def open_hours_for_members(gids: list[str]) -> dict[str, float]:
    """Current open-task hours per member (best-effort; a failed fetch → 0).

    Reused by the monthly job's auto-distribution to seed each member's load.
    """
    async def _hours(gid: str) -> tuple[str, float]:
        try:
            tasks = await asana_service.list_member_open_tasks(gid)
        except Exception as exc:
            logger.warning("asana_workload.open_hours_failed", extra={"gid": gid, "error": str(exc)})
            return gid, 0.0
        total = sum(
            asana_service.task_hours(t, settings.asana_effort_field_gid, settings.asana_default_task_hours)
            for t in tasks
        )
        return gid, total

    results = await asyncio.gather(*[_hours(g) for g in gids])
    return dict(results)


async def build_team_workload() -> dict:
    """Build the effort-weighted Team Workload report for the tracked team."""
    if not asana_service.is_configured() or not settings.asana_workload_enabled:
        return _empty(asana_service.is_configured(), note="not_configured")

    members = get_team_members()
    if not members:
        return _empty(True, note="no_team_list")

    try:
        users = await asana_service.list_workspace_users()
    except Exception as exc:
        logger.warning("asana_workload.users_failed", extra={"error": str(exc)})
        users = []
    name_by = {u["gid"]: u.get("name") for u in users}

    entries = await asyncio.gather(*[_member_entry(m, name_by) for m in members])

    report = asana_service.build_workload_report(
        list(entries),
        effort_field_gid=settings.asana_effort_field_gid,
        default_task_hours=settings.asana_default_task_hours,
        daily_workdays=settings.asana_workload_daily_workdays,
        backlog_weeks=settings.asana_workload_backlog_weeks,
        default_weekly_hours=settings.asana_default_weekly_hours,
    )
    report["configured"] = True
    return report


# ---------------------------------------------------------------------------
# Daily alert (Phase 3) — notifications producer
# ---------------------------------------------------------------------------
async def run_workload_alert() -> dict:
    """Build the report and, if anyone is overloaded, emit one suite-level
    notification (in-app + Slack via the notifications dispatch). Called once
    per day by the scheduler. Returns a small summary for logging."""
    if not asana_service.is_configured() or not settings.asana_workload_enabled:
        return {"emitted": False, "reason": "not_configured"}
    report = await build_team_workload()
    overloaded = report.get("overloaded") or []
    if not overloaded:
        return {"emitted": False, "overloaded": 0}

    names = ", ".join(m["name"] for m in overloaded)
    lines = "; ".join(f"{m['name']}: {'; '.join(m['flags'])}" for m in overloaded)
    notifications.emit(
        client_id=None,  # suite-wide
        kind="asana_workload",
        title=f"{len(overloaded)} team member{'s' if len(overloaded) != 1 else ''} overloaded ({names})",
        summary=lines,
        severity="warning",
        payload={"link": "/workload", "overloaded": [m["gid"] for m in overloaded]},
    )
    logger.info("asana_workload.alert_emitted", extra={"overloaded": len(overloaded)})
    return {"emitted": True, "overloaded": len(overloaded)}

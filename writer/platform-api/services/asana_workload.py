"""Asana Team Workload (Feature B, read half).

Pulls a defined team list's open tasks across all client projects and aggregates
per-person load + same-day due-date clustering, flagging overloads. Suite-level
(spans people and clients), read-only. The daily proactive-alert producer is
Phase 3; this module is the on-demand read.

See docs/modules/asana-task-integration-plan-v1_0.md §4.
"""

from __future__ import annotations

import asyncio
import logging

from config import settings
from services import asana_service

logger = logging.getLogger(__name__)


def _empty(configured: bool, note: str | None = None) -> dict:
    report = {
        "configured": configured,
        "members": [],
        "overloaded": [],
        "thresholds": {
            "max_open": settings.asana_workload_max_open,
            "max_due_same_day": settings.asana_workload_max_due_same_day,
        },
    }
    if note:
        report["note"] = note
    return report


async def _member_entry(gid: str, name: str) -> dict:
    """Fetch one member's open tasks (best-effort — a failure yields no tasks)."""
    try:
        tasks = await asana_service.list_member_open_tasks(gid)
    except Exception as exc:
        logger.warning("asana_workload.member_fetch_failed", extra={"gid": gid, "error": str(exc)})
        tasks = []
    return {"gid": gid, "name": name, "tasks": tasks}


async def build_team_workload() -> dict:
    """Build the Team Workload report for the configured team list.

    Returns the ``build_workload_report`` shape plus a ``configured`` flag (and a
    ``note`` when there's nothing to show), so the UI can render a clear empty
    state rather than erroring.
    """
    if not asana_service.is_configured() or not settings.asana_workload_enabled:
        return _empty(asana_service.is_configured(), note="not_configured")

    gids = asana_service.parse_gids(settings.asana_team_member_gids)
    if not gids:
        return _empty(True, note="no_team_list")

    # Resolve display names once (best-effort), then fetch each member's tasks
    # concurrently.
    try:
        users = await asana_service.list_workspace_users()
    except Exception as exc:
        logger.warning("asana_workload.users_failed", extra={"error": str(exc)})
        users = []
    name_by = {u["gid"]: u.get("name") for u in users}

    members = await asyncio.gather(
        *[_member_entry(gid, name_by.get(gid) or gid) for gid in gids]
    )

    report = asana_service.build_workload_report(
        list(members),
        max_open=settings.asana_workload_max_open,
        max_due_same_day=settings.asana_workload_max_due_same_day,
    )
    report["configured"] = True
    return report

"""Asana task integration — REST client + pure helpers.

Phase 0 scaffolding for docs/modules/asana-task-integration-plan-v1_0.md.

Two features ride this module on one Asana token:

  A. Monthly section automation (write) — clone a hand-maintained ``Template``
     section forward into a new ``<Month YYYY>`` section per client project:
     task name + assignee + category custom field carried over, Status reset to
     "Not Started", no due dates, idempotent.

  B. Team Workload (read + alerts) — pull a defined team list's open tasks
     across all client projects, aggregate per-person load + same-day due-date
     clustering, and flag overloads (the daily alert producer comes in Phase 3).

This file holds the async Asana REST client (thin httpx wrapper, no business
logic) and the **pure helpers** (no I/O) that the jobs/routers in later phases
compose. The pure helpers are independently unit-tested; the I/O methods are
mocked in tests, never hit live.

Graceful degradation: ``is_configured()`` gates every entry point. Absent the
token / workspace the features are skipped with a note, never an error — the
same provisioning pattern as GSC / Slack.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://app.asana.com/api/1.0"
_TIMEOUT = 30.0

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# ---------------------------------------------------------------------------
# Configuration gating
# ---------------------------------------------------------------------------
def is_configured() -> bool:
    """True when the Asana token + workspace are provisioned."""
    return bool(settings.asana_token and settings.asana_workspace_gid)


def parse_gids(raw: Optional[str]) -> list[str]:
    """Parse a comma-separated GID list (e.g. asana_team_member_gids).

    Trims whitespace and drops empties — mirrors notifications.email_recipients.
    """
    if not raw:
        return []
    return [g.strip() for g in raw.split(",") if g.strip()]


# ---------------------------------------------------------------------------
# Month-label helpers (Feature A)
# ---------------------------------------------------------------------------
def month_label(d: date) -> str:
    """The Asana section name for a month, e.g. date(2026, 7, 3) -> 'July 2026'."""
    return f"{_MONTHS[d.month - 1]} {d.year}"


def shift_months(d: date, months: int) -> date:
    """First day of the month ``months`` away from ``d`` (months may be negative).

    Used to compute the target month for the section to create:
    ``shift_months(today, 0)`` = the current month, ``+1`` = next month.
    """
    index = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def section_name_exists(sections: list[dict], name: str) -> bool:
    """True if a section with this exact name (case-insensitive) already exists.

    Drives idempotency: the monthly job no-ops when the target month's section
    is already present, so auto + manual triggers can't double up.
    """
    target = name.strip().casefold()
    return any((s.get("name") or "").strip().casefold() == target for s in sections)


# ---------------------------------------------------------------------------
# Custom-field extraction (Feature A)
# ---------------------------------------------------------------------------
def extract_assignee_gid(task: dict) -> Optional[str]:
    """The assignee GID from a task (None when unassigned)."""
    assignee = task.get("assignee")
    if isinstance(assignee, dict):
        return assignee.get("gid")
    return None


def extract_enum_option_gid(task: dict, field_gid: str) -> Optional[str]:
    """The selected enum-option GID for ``field_gid`` on a task (None if unset).

    Asana returns each custom field on a task as ``{gid, name, type,
    enum_value: {gid, name}}`` (enum_value is null when nothing is selected).
    """
    if not field_gid:
        return None
    for cf in task.get("custom_fields") or []:
        if cf.get("gid") == field_gid:
            enum_value = cf.get("enum_value")
            if isinstance(enum_value, dict):
                return enum_value.get("gid")
            return None
    return None


def build_task_payload(
    template_task: dict,
    project_gid: str,
    section_gid: str,
    *,
    status_field_gid: str = "",
    not_started_option_gid: str = "",
    category_field_gid: str = "",
) -> dict:
    """Build the ``POST /tasks`` ``data`` body that clones a template task forward.

    Carries name + assignee + category enum value; sets Status = Not Started;
    sets **no** due date (the team fills dates in). Places the new task directly
    in ``section_gid`` via a project membership.
    """
    data: dict[str, Any] = {
        "name": template_task.get("name") or "",
        "projects": [project_gid],
        "memberships": [{"project": project_gid, "section": section_gid}],
    }

    assignee = extract_assignee_gid(template_task)
    if assignee:
        data["assignee"] = assignee

    custom_fields: dict[str, str] = {}
    if status_field_gid and not_started_option_gid:
        custom_fields[status_field_gid] = not_started_option_gid
    if category_field_gid:
        category_option = extract_enum_option_gid(template_task, category_field_gid)
        if category_option:
            custom_fields[category_field_gid] = category_option
    if custom_fields:
        data["custom_fields"] = custom_fields

    return data


# ---------------------------------------------------------------------------
# Workload aggregation (Feature B)
# ---------------------------------------------------------------------------
def aggregate_member_workload(
    gid: str,
    name: str,
    tasks: list[dict],
    *,
    max_open: int,
    max_due_same_day: int,
) -> dict:
    """Summarise one member's open tasks: count, per-day due distribution, flags.

    ``tasks`` are the member's incomplete tasks (each may carry ``due_on`` as a
    'YYYY-MM-DD' string or null). Returns a dict with ``open_count``,
    ``due_by_day`` (sorted), the worst same-day stack, and any overload flags.
    """
    due_by_day: dict[str, int] = {}
    for t in tasks:
        due = t.get("due_on")
        if due:
            due_by_day[due] = due_by_day.get(due, 0) + 1

    worst_day: Optional[str] = None
    worst_count = 0
    for day, count in due_by_day.items():
        if count > worst_count or (count == worst_count and (worst_day is None or day < worst_day)):
            worst_day, worst_count = day, count

    open_count = len(tasks)
    flags: list[str] = []
    if open_count > max_open:
        flags.append(f"{open_count} open tasks (over {max_open})")
    if worst_day and worst_count > max_due_same_day:
        flags.append(f"{worst_count} tasks due {worst_day} (over {max_due_same_day})")

    return {
        "gid": gid,
        "name": name,
        "open_count": open_count,
        "due_by_day": dict(sorted(due_by_day.items())),
        "worst_same_day": ({"date": worst_day, "count": worst_count} if worst_day else None),
        "overloaded": bool(flags),
        "flags": flags,
    }


def build_workload_report(
    members: list[dict],
    *,
    max_open: int,
    max_due_same_day: int,
) -> dict:
    """Aggregate a defined team list into a workload report.

    ``members`` is a list of ``{"gid", "name", "tasks": [...]}``. Returns
    per-member summaries (most loaded first) + the subset that is overloaded.
    """
    summaries = [
        aggregate_member_workload(
            m["gid"], m.get("name") or m["gid"], m.get("tasks") or [],
            max_open=max_open, max_due_same_day=max_due_same_day,
        )
        for m in members
    ]
    summaries.sort(key=lambda s: s["open_count"], reverse=True)
    overloaded = [s for s in summaries if s["overloaded"]]
    return {
        "members": summaries,
        "overloaded": overloaded,
        "thresholds": {"max_open": max_open, "max_due_same_day": max_due_same_day},
    }


# ---------------------------------------------------------------------------
# Async REST client (thin httpx wrapper — mocked in tests, never hit live)
# ---------------------------------------------------------------------------
def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.asana_token}",
        "Accept": "application/json",
    }


async def _get(path: str, params: Optional[dict] = None) -> Any:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{_BASE_URL}{path}", headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json().get("data")


async def _post(path: str, data: dict) -> Any:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{_BASE_URL}{path}", headers=_headers(), json={"data": data})
        resp.raise_for_status()
        return resp.json().get("data")


async def list_sections(project_gid: str) -> list[dict]:
    """All sections in a project (used to find Template + the insert anchor)."""
    return await _get(f"/projects/{project_gid}/sections", {"opt_fields": "name"}) or []


async def list_section_tasks(section_gid: str) -> list[dict]:
    """Tasks in a section, with the fields the monthly clone needs."""
    return await _get(
        f"/sections/{section_gid}/tasks",
        {"opt_fields": "name,assignee.gid,custom_fields"},
    ) or []


async def create_section(
    project_gid: str, name: str, *, insert_before: Optional[str] = None
) -> dict:
    """Create a section in a project (optionally inserted before another)."""
    data: dict[str, Any] = {"name": name}
    if insert_before:
        data["insert_before"] = insert_before
    return await _post(f"/projects/{project_gid}/sections", data)


async def create_task(payload: dict) -> dict:
    """Create a task from a ``build_task_payload`` body."""
    return await _post("/tasks", payload)


async def list_member_open_tasks(user_gid: str) -> list[dict]:
    """A member's incomplete tasks across the workspace (with due dates).

    ``completed_since=now`` returns only tasks not yet complete — the standard
    Asana idiom for "open tasks".
    """
    return await _get(
        "/tasks",
        {
            "assignee": user_gid,
            "workspace": settings.asana_workspace_gid,
            "completed_since": "now",
            "opt_fields": "name,due_on,completed",
        },
    ) or []

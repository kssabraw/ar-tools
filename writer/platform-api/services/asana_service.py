"""Asana task integration — REST client + pure helpers.

Backs docs/modules/asana-task-integration-plan-v1_0.md.

Two features ride this module on one Asana token:

  A. Monthly section automation (write) — for each client, create a new
     ``<Month YYYY>`` section in its Asana project and populate it from the
     client's **app-defined task template** (per-client task list, each row a
     name + optional assignee + optional category). Status is set to
     "Not Started", no due dates (the team fills dates in), idempotent.

  B. Team Workload (read + alerts) — pull a defined team list's open tasks
     across all client projects, aggregate per-person load + same-day due-date
     clustering, and flag overloads (the daily alert producer is Phase 3).

This file holds the async Asana REST client (thin httpx wrapper, no business
logic) and the **pure helpers** (no I/O) that the monthly job / workload view
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
_MONTH_INDEX = {name.casefold(): i + 1 for i, name in enumerate(_MONTHS)}


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


def is_month_label(name: Optional[str]) -> bool:
    """True if ``name`` looks like a '<Month> <Year>' section label."""
    if not name:
        return False
    parts = name.strip().split()
    if len(parts) != 2:
        return False
    month, year = parts
    return month.casefold() in _MONTH_INDEX and year.isdigit() and len(year) == 4


def section_name_exists(sections: list[dict], name: str) -> bool:
    """True if a section with this exact name (case-insensitive) already exists.

    Drives idempotency: the monthly job no-ops when the target month's section
    is already present, so auto + manual triggers can't double up.
    """
    target = name.strip().casefold()
    return any((s.get("name") or "").strip().casefold() == target for s in sections)


def month_insert_anchor_gid(sections: list[dict]) -> Optional[str]:
    """The section GID to insert a new month *before* (None → append at end).

    Months are added newest-last each cycle, so the new month belongs right
    after the existing month group and before any non-month section (e.g. an
    "Untitled section" backlog). We return the first non-month section's GID;
    if every section is a month label, append at the end (None).
    """
    for s in sections:
        if not is_month_label(s.get("name")):
            return s.get("gid")
    return None


# ---------------------------------------------------------------------------
# Task payload (Feature A) — built from an app-defined template row
# ---------------------------------------------------------------------------
def build_task_payload(
    name: str,
    project_gid: str,
    section_gid: str,
    *,
    assignee_gid: Optional[str] = None,
    category_field_gid: str = "",
    category_option_gid: Optional[str] = None,
    status_field_gid: str = "",
    not_started_option_gid: str = "",
    effort_field_gid: str = "",
    est_hours: Optional[float] = None,
    due_on: Optional[str] = None,
) -> dict:
    """Build the ``POST /tasks`` ``data`` body for one template row.

    Sets name + (optional) assignee + (optional) category; Status = Not Started
    when both the field and option GIDs are configured; stamps the estimated
    hours into the effort number field when configured. A ``due_on`` date
    (``YYYY-MM-DD``) is set only when explicitly provided — the bulk monthly
    push leaves it unset so the team fills dates in, but an on-demand task
    (e.g. via SerMastr) may carry one. Places the task directly in
    ``section_gid``.
    """
    data: dict[str, Any] = {
        "name": name or "",
        "projects": [project_gid],
        "memberships": [{"project": project_gid, "section": section_gid}],
    }
    if assignee_gid:
        data["assignee"] = assignee_gid
    if due_on:
        data["due_on"] = due_on

    custom_fields: dict[str, Any] = {}
    if status_field_gid and not_started_option_gid:
        custom_fields[status_field_gid] = not_started_option_gid
    if category_field_gid and category_option_gid:
        custom_fields[category_field_gid] = category_option_gid
    if effort_field_gid and est_hours is not None:
        custom_fields[effort_field_gid] = est_hours
    if custom_fields:
        data["custom_fields"] = custom_fields

    return data


def _config_fields() -> dict:
    """The configured GID fallbacks (used when by-name resolution is off/misses)."""
    return {
        "status_field_gid": settings.asana_status_field_gid,
        "not_started_option_gid": settings.asana_status_not_started_option_gid,
        "category_field_gid": settings.asana_category_field_gid,
        "effort_field_gid": settings.asana_effort_field_gid,
    }


def payload_from_template_row(
    row: dict, project_gid: str, section_gid: str, fields: Optional[dict] = None
) -> dict:
    """Adapt a DB ``asana_client_task_templates`` row into a create-task payload.

    ``fields`` is the resolved-per-project field GID map (from
    ``resolve_project_fields``); when omitted, the configured GIDs are used.
    """
    f = fields if fields is not None else _config_fields()
    return build_task_payload(
        row.get("name") or "",
        project_gid,
        section_gid,
        assignee_gid=row.get("assignee_gid"),
        category_field_gid=f.get("category_field_gid") or "",
        category_option_gid=row.get("category_option_gid"),
        status_field_gid=f.get("status_field_gid") or "",
        not_started_option_gid=f.get("not_started_option_gid") or "",
        effort_field_gid=f.get("effort_field_gid") or "",
        est_hours=row.get("est_hours"),
    )


# ---------------------------------------------------------------------------
# Resolve a project's custom fields BY NAME (project-local fields differ per
# project, so a single global GID won't match every client's project).
# ---------------------------------------------------------------------------
def _match_field(settings_rows: list[dict], name: str, subtype: Optional[str] = None) -> Optional[dict]:
    """Find a project's custom field by (case-insensitive) name, optional subtype."""
    target = (name or "").strip().casefold()
    if not target:
        return None
    for r in settings_rows:
        cf = r.get("custom_field") or {}
        if (cf.get("name") or "").strip().casefold() == target:
            if subtype and cf.get("resource_subtype") != subtype:
                continue
            return cf
    return None


def _match_option(custom_field: Optional[dict], name: str) -> Optional[str]:
    """Find an enum option GID on a custom field by name."""
    if not custom_field:
        return None
    target = (name or "").strip().casefold()
    for o in custom_field.get("enum_options") or []:
        if (o.get("name") or "").strip().casefold() == target:
            return o.get("gid")
    return None


def match_project_fields(
    settings_rows: list[dict],
    *,
    status_field_name: str,
    not_started_option_name: str,
    category_field_name: str,
    effort_field_name: str,
) -> dict:
    """Resolve the Status / category / effort field GIDs from a project's
    ``custom_field_settings`` by field name. Pure (no I/O) — unit-tested.
    Each value is None when the named field/option isn't on the project."""
    status_cf = _match_field(settings_rows, status_field_name)
    category_cf = _match_field(settings_rows, category_field_name)
    effort_cf = _match_field(settings_rows, effort_field_name, subtype="number")
    category_options = {
        (o.get("name") or "").strip().casefold(): o.get("gid")
        for o in ((category_cf or {}).get("enum_options") or [])
        if o.get("gid")
    }
    return {
        "status_field_gid": status_cf.get("gid") if status_cf else None,
        "not_started_option_gid": _match_option(status_cf, not_started_option_name),
        "category_field_gid": category_cf.get("gid") if category_cf else None,
        "category_options": category_options,
        "effort_field_gid": effort_cf.get("gid") if effort_cf else None,
    }


def extract_number_field(task: dict, field_gid: str) -> Optional[float]:
    """The numeric value of a task's number custom field by GID (None when unset)."""
    if not field_gid:
        return None
    for cf in task.get("custom_fields") or []:
        if cf.get("gid") == field_gid:
            val = cf.get("number_value")
            return float(val) if val is not None else None
    return None


def extract_number_field_by_name(task: dict, field_name: str) -> Optional[float]:
    """The numeric value of a task's number custom field by (case-insensitive)
    name (None when unset). Project-local effort fields differ by GID per
    project, so matching by name reads them uniformly across all projects."""
    target = (field_name or "").strip().casefold()
    if not target:
        return None
    for cf in task.get("custom_fields") or []:
        if (cf.get("name") or "").strip().casefold() == target:
            val = cf.get("number_value")
            return float(val) if val is not None else None
    return None


# ---------------------------------------------------------------------------
# Workload aggregation (Feature B)
# ---------------------------------------------------------------------------
def task_effort(task: dict, effort_field_name: str, effort_field_gid: str) -> Optional[float]:
    """A task's estimated hours — by effort-field name first (project-agnostic),
    then by GID — or None when neither is set/found."""
    if effort_field_name:
        val = extract_number_field_by_name(task, effort_field_name)
        if val is not None:
            return val
    return extract_number_field(task, effort_field_gid)


def task_hours(
    task: dict, effort_field_name: str, effort_field_gid: str, default_task_hours: float
) -> float:
    """Estimated hours for one task — its effort number field (by name, then
    GID), else the default."""
    val = task_effort(task, effort_field_name, effort_field_gid)
    return float(val) if val is not None else float(default_task_hours)


def distribute_tasks(task_hours_list: list[float], members: list[dict]) -> list[Optional[str]]:
    """Capacity-aware greedy distribution of tasks across eligible members.

    ``members`` is ``[{"gid", "remaining"}]`` where ``remaining`` is each member's
    free capacity (weekly_hours − current open hours; may be negative). Tasks are
    assigned heaviest-first to whoever currently has the most remaining capacity,
    decrementing as we go — so load evens out and the person with the most room
    gets the most work. Returns the assigned gid per task in **original order**
    (all None when there are no eligible members). Pure; unit-tested.
    """
    n = len(task_hours_list)
    if not members:
        return [None] * n
    remaining = {m["gid"]: float(m.get("remaining") or 0.0) for m in members}
    result: list[Optional[str]] = [None] * n
    # Heaviest tasks first; stable on original index for ties.
    order = sorted(range(n), key=lambda i: (-task_hours_list[i], i))
    for i in order:
        # Most remaining capacity; first member in list order wins ties.
        best_gid = members[0]["gid"]
        best_rem = remaining[best_gid]
        for m in members[1:]:
            r = remaining[m["gid"]]
            if r > best_rem:
                best_gid, best_rem = m["gid"], r
        result[i] = best_gid
        remaining[best_gid] -= float(task_hours_list[i])
    return result


def build_task_update(row: dict, fields: dict) -> dict:
    """Build a ``PUT /tasks`` body (assignee + custom fields) for a task that was
    created by **instantiating an Asana task template** (which already set its
    name + subtasks). Mirrors build_task_payload's field logic, minus
    name/project/section."""
    data: dict[str, Any] = {}
    if row.get("assignee_gid"):
        data["assignee"] = row["assignee_gid"]
    custom_fields: dict[str, Any] = {}
    if fields.get("status_field_gid") and fields.get("not_started_option_gid"):
        custom_fields[fields["status_field_gid"]] = fields["not_started_option_gid"]
    if fields.get("category_field_gid") and row.get("category_option_gid"):
        custom_fields[fields["category_field_gid"]] = row["category_option_gid"]
    if fields.get("effort_field_gid") and row.get("est_hours") is not None:
        custom_fields[fields["effort_field_gid"]] = row["est_hours"]
    if custom_fields:
        data["custom_fields"] = custom_fields
    return data


def aggregate_member_workload(
    gid: str,
    name: str,
    tasks: list[dict],
    *,
    weekly_hours: float,
    effort_field_name: str,
    effort_field_gid: str,
    default_task_hours: float,
    daily_workdays: int,
    backlog_weeks: float,
) -> dict:
    """Summarise one member's open tasks by estimated **hours** vs their capacity.

    ``tasks`` are the member's incomplete tasks (``due_on`` 'YYYY-MM-DD' or null;
    effort read from the number field by name first, then GID, else
    ``default_task_hours``). Flags fire when a single day's due hours exceed daily
    capacity (weekly/workdays), or the open backlog exceeds ``backlog_weeks`` of
    capacity.
    """
    due_hours_by_day: dict[str, float] = {}
    open_hours = 0.0
    unestimated = 0
    for t in tasks:
        if task_effort(t, effort_field_name, effort_field_gid) is None:
            unestimated += 1
        hrs = task_hours(t, effort_field_name, effort_field_gid, default_task_hours)
        open_hours += hrs
        due = t.get("due_on")
        if due:
            due_hours_by_day[due] = due_hours_by_day.get(due, 0.0) + hrs

    worst_day: Optional[str] = None
    worst_hours = 0.0
    for day, hrs in due_hours_by_day.items():
        if hrs > worst_hours or (hrs == worst_hours and (worst_day is None or day < worst_day)):
            worst_day, worst_hours = day, hrs

    daily_capacity = (weekly_hours / daily_workdays) if (weekly_hours and daily_workdays) else 0.0
    backlog_capacity = (weekly_hours * backlog_weeks) if weekly_hours else 0.0

    flags: list[str] = []
    if daily_capacity and worst_day and worst_hours > daily_capacity:
        flags.append(
            f"{round(worst_hours, 1)}h due {worst_day} (over {round(daily_capacity, 1)}h/day)"
        )
    if backlog_capacity and open_hours > backlog_capacity:
        flags.append(
            f"{round(open_hours, 1)}h open (over {round(backlog_weeks, 1)} weeks at {round(weekly_hours, 1)}h/wk)"
        )

    return {
        "gid": gid,
        "name": name,
        "open_count": len(tasks),
        "open_hours": round(open_hours, 1),
        "unestimated": unestimated,
        "weekly_hours": round(float(weekly_hours), 1) if weekly_hours else None,
        "daily_capacity": round(daily_capacity, 1) if daily_capacity else None,
        "due_hours_by_day": {k: round(v, 1) for k, v in sorted(due_hours_by_day.items())},
        "worst_same_day": ({"date": worst_day, "hours": round(worst_hours, 1)} if worst_day else None),
        "overloaded": bool(flags),
        "flags": flags,
    }


def build_workload_report(
    members: list[dict],
    *,
    effort_field_name: str,
    effort_field_gid: str,
    default_task_hours: float,
    daily_workdays: int,
    backlog_weeks: float,
    default_weekly_hours: float,
) -> dict:
    """Aggregate a defined team list into an effort-weighted workload report.

    ``members`` is a list of ``{"gid", "name", "tasks": [...], "weekly_hours"?}``
    (a member with no ``weekly_hours`` uses ``default_weekly_hours``). Returns
    per-member summaries (most loaded first by hours) + the overloaded subset.
    """
    summaries = [
        aggregate_member_workload(
            m["gid"], m.get("name") or m["gid"], m.get("tasks") or [],
            weekly_hours=(m.get("weekly_hours") or default_weekly_hours),
            effort_field_name=effort_field_name,
            effort_field_gid=effort_field_gid,
            default_task_hours=default_task_hours,
            daily_workdays=daily_workdays,
            backlog_weeks=backlog_weeks,
        )
        for m in members
    ]
    summaries.sort(key=lambda s: s["open_hours"], reverse=True)
    overloaded = [s for s in summaries if s["overloaded"]]
    return {
        "members": summaries,
        "overloaded": overloaded,
        "thresholds": {
            "default_weekly_hours": default_weekly_hours,
            "daily_workdays": daily_workdays,
            "backlog_weeks": backlog_weeks,
            "default_task_hours": default_task_hours,
        },
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


async def _put(path: str, data: dict) -> Any:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.put(f"{_BASE_URL}{path}", headers=_headers(), json={"data": data})
        resp.raise_for_status()
        return resp.json().get("data")


# ---------------------------------------------------------------------------
# Task templates (Asana's native templates — instantiate to preserve subtasks)
# ---------------------------------------------------------------------------
async def list_project_task_templates(project_gid: str) -> list[dict]:
    """The Asana task templates defined on a project [{gid, name}]."""
    return await _get("/task_templates", {"project": project_gid, "opt_fields": "name"}) or []


async def instantiate_task_template(template_gid: str, name: str) -> Optional[str]:
    """Instantiate an Asana task template (creates the task + its subtasks) and
    return the new task's GID. Asana returns a Job whose ``new_task`` references
    the created task."""
    job = await _post(f"/task_templates/{template_gid}/instantiateTask", {"name": name})
    new_task = (job or {}).get("new_task") or {}
    return new_task.get("gid")


async def update_task(task_gid: str, data: dict) -> dict:
    """Update a task (assignee / custom fields)."""
    return await _put(f"/tasks/{task_gid}", data)


async def add_task_to_section(section_gid: str, task_gid: str) -> Any:
    """Move a task into a section (within its project)."""
    return await _post(f"/sections/{section_gid}/addTask", {"task": task_gid})


async def _delete(path: str) -> None:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.delete(f"{_BASE_URL}{path}", headers=_headers())
        resp.raise_for_status()


async def list_project_tasks(project_gid: str) -> list[dict]:
    """Tasks in a project [{gid, name, completed, assignee, permalink_url}].

    One page of 100 — enough for the conversational lookup this powers (a
    month's board section is a handful of tasks; we don't paginate)."""
    return await _get(
        f"/projects/{project_gid}/tasks",
        {"opt_fields": "name,completed,assignee.name,permalink_url", "limit": 100},
    ) or []


async def delete_task(task_gid: str) -> None:
    """Permanently delete a task."""
    await _delete(f"/tasks/{task_gid}")


async def complete_task(task_gid: str) -> dict:
    """Mark a task complete."""
    return await _put(f"/tasks/{task_gid}", {"completed": True})


async def get_project(project_gid: str) -> dict:
    """One project's basics — used to validate a pasted project GID at save
    time (a wrong number, e.g. a workspace id from the new Asana URL format,
    404s here instead of failing later inside a push/monthly run)."""
    return await _get(f"/projects/{project_gid}", {"opt_fields": "name"}) or {}


async def list_sections(project_gid: str) -> list[dict]:
    """All sections in a project (used to find the insert anchor + idempotency)."""
    return await _get(f"/projects/{project_gid}/sections", {"opt_fields": "name"}) or []


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


async def list_workspace_users() -> list[dict]:
    """Workspace members [{gid, name, email}] — populates the assignee picker."""
    users = await _get(
        f"/workspaces/{settings.asana_workspace_gid}/users",
        {"opt_fields": "name,email"},
    ) or []
    return [{"gid": u.get("gid"), "name": u.get("name"), "email": u.get("email")} for u in users]


async def _project_field_settings(project_gid: str) -> list[dict]:
    """A project's custom_field_settings (with names + enum options)."""
    return await _get(
        f"/projects/{project_gid}/custom_field_settings",
        {"opt_fields": "custom_field.gid,custom_field.name,custom_field.resource_subtype,custom_field.enum_options.name"},
    ) or []


async def resolve_project_fields(project_gid: str) -> dict:
    """Resolve a project's Status / category / effort field GIDs **by name**,
    falling back to the configured GIDs when a name is unset or not found.

    Returns ``{status_field_gid, not_started_option_gid, category_field_gid,
    effort_field_gid}``. Best-effort: an API failure falls back to config GIDs,
    so the monthly job degrades rather than aborting."""
    resolved = _config_fields()
    # Skip the API call entirely if no names are configured to resolve by.
    if not (settings.asana_status_field_name or settings.asana_category_field_name or settings.asana_effort_field_name):
        return resolved
    try:
        rows = await _project_field_settings(project_gid)
    except Exception as exc:
        logger.warning("asana.resolve_fields_failed", extra={"project_gid": project_gid, "error": str(exc)})
        return resolved
    matched = match_project_fields(
        rows,
        status_field_name=settings.asana_status_field_name,
        not_started_option_name=settings.asana_status_not_started_option_name,
        category_field_name=settings.asana_category_field_name,
        effort_field_name=settings.asana_effort_field_name,
    )
    # Prefer a by-name match; keep the config fallback when a name didn't resolve.
    for key, val in matched.items():
        if val:
            resolved[key] = val
    return resolved


async def list_project_category_options(project_gid: str) -> list[dict]:
    """The category custom field's enum options [{gid, name}] for a project —
    populates the category picker. Matches the field BY NAME
    (`asana_category_field_name`), falling back to the configured GID."""
    name = settings.asana_category_field_name
    gid = settings.asana_category_field_gid
    if not name and not gid:
        return []
    settings_rows = await _project_field_settings(project_gid)
    target = (name or "").strip().casefold()
    for s in settings_rows:
        cf = s.get("custom_field") or {}
        if (target and (cf.get("name") or "").strip().casefold() == target) or (gid and cf.get("gid") == gid):
            return [
                {"gid": o.get("gid"), "name": o.get("name")}
                for o in (cf.get("enum_options") or [])
                if o.get("gid")
            ]
    return []


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
            "opt_fields": "name,due_on,completed,custom_fields.gid,custom_fields.name,custom_fields.number_value",
        },
    ) or []

"""PACE v1.4 Phase 12 — slip forecasting (§4.12).

A PM prevents misses; v1.3 PACE reported them afterward. Deterministic
look-ahead over the next `pace_slip_horizon_days`: a task **will slip** when
it's due inside the horizon and EITHER nobody owns it, OR it hasn't been
started and its assignee can't fit it before the due date under the
daily-capacity model (weekly hours / workdays, minus their other unfinished
work due by then). Started tasks are presumed on track — this is a
not-yet-started early-warning, not a progress tracker.

Each slip gets a fix proposal, cheaper first: **reassign** to a teammate with
room (the §4.6 pool, capacity-held), else a **due-date move** to the earliest
day the current assignee can actually make, else a warning-only flag line.
Pure model (`forecast_slips`, `next_feasible_due`) unit-tested; the generator
gathers batched reads and emits Chase-Plan proposals.
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import pm_assign, task_service, task_workload
from services.pace_episodes import business_days_between
from services.pace_proposals import register_generator

logger = logging.getLogger(__name__)

_SLIP_PRIORITY = 75  # preventing a miss outranks routine chasing (50–70)


# ---------------------------------------------------------------------------
# Pure model (unit-tested)
# ---------------------------------------------------------------------------
def _to_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _est(task: dict, default_hours: float) -> float:
    raw = task.get("est_hours")
    return float(raw) if raw is not None else float(default_hours)


def available_hours(member: dict, today: date, due: date, queue: list[dict], task_id,
                    *, default_hours: float, default_weekly_hours: float,
                    daily_workdays: float) -> float:
    """Hours the member realistically has for THIS task before ``due``: daily
    capacity × business days remaining, minus their other unfinished work due
    by then. Pure."""
    weekly = member.get("weekly_hours")
    weekly = float(weekly) if weekly is not None else float(default_weekly_hours)
    daily = weekly / max(1.0, float(daily_workdays))
    days = business_days_between(today, due)
    committed = sum(
        _est(t, default_hours) for t in queue
        if t.get("id") != task_id
        and (d := _to_date(t.get("due_date"))) is not None and d <= due
    )
    return daily * days - committed


def forecast_slips(tasks: list[dict], members_by_gid: dict, initial_keys: set,
                   today: date, horizon_days: int, *, default_hours: float,
                   default_weekly_hours: float, daily_workdays: float) -> list[dict]:
    """The tasks that will miss their due date. Pure.
    Returns [{task, due, reason: unassigned|no_capacity, available, needed}]."""
    horizon_end = today + timedelta(days=horizon_days)
    queues: dict[str, list[dict]] = {}
    for t in tasks:
        gid = t.get("assignee_gid")
        if gid:
            queues.setdefault(gid, []).append(t)

    slips: list[dict] = []
    for t in tasks:
        due = _to_date(t.get("due_date"))
        if not due or not (today < due <= horizon_end):
            continue
        if t.get("status_key") not in initial_keys:
            continue  # started ⇒ presumed on track
        needed = _est(t, default_hours)
        gid = t.get("assignee_gid")
        if not gid:
            slips.append({"task": t, "due": due, "reason": "unassigned",
                          "available": 0.0, "needed": needed})
            continue
        member = members_by_gid.get(gid)
        if not member:
            continue  # untracked assignee — no capacity model, stay silent
        avail = available_hours(member, today, due, queues.get(gid, []), t.get("id"),
                                default_hours=default_hours,
                                default_weekly_hours=default_weekly_hours,
                                daily_workdays=daily_workdays)
        if avail < needed:
            slips.append({"task": t, "due": due, "reason": "no_capacity",
                          "available": max(0.0, avail), "needed": needed})
    return slips


def next_feasible_due(slip: dict, member: dict, today: date, *, default_weekly_hours: float,
                      daily_workdays: float, max_extra_business_days: int = 10) -> Optional[date]:
    """The earliest due date the current assignee can actually make: push the
    deficit's worth of business days past the original due. None when even
    +max extra days wouldn't cover it. Pure (approximation: commitments due
    after the original date aren't re-counted — deterministic and cheap)."""
    weekly = member.get("weekly_hours")
    weekly = float(weekly) if weekly is not None else float(default_weekly_hours)
    daily = weekly / max(1.0, float(daily_workdays))
    if daily <= 0:
        return None
    deficit = slip["needed"] - slip["available"]
    extra = math.ceil(deficit / daily)
    if extra > max_extra_business_days:
        return None
    new_due = slip["due"]
    added = 0
    while added < extra:
        new_due += timedelta(days=1)
        if new_due.weekday() < 5:
            added += 1
    return new_due


# ---------------------------------------------------------------------------
# The registered generator
# ---------------------------------------------------------------------------
@register_generator
def slip_proposals(today: date) -> list[dict]:
    if not (settings.pace_enabled and settings.pace_initiative_enabled):
        return []
    sb = get_supabase()
    tasks = (
        sb.table("tasks")
        .select("id, client_id, name, category, est_hours, status_key, assignee_gid, assignee_name, due_date")
        .eq("completed", False).is_("deleted_at", "null").is_("parent_task_id", "null")
        .not_.is_("due_date", "null").not_.is_("client_id", "null")
        .execute()
    ).data or []
    if not tasks:
        return []
    members = pm_assign._active_members()
    members_by_gid = {m["gid"]: m for m in members}
    initial_keys = {
        s["key"] for s in task_service.get_statuses(active_only=False)
        if s.get("is_initial") or s.get("category") == "not_started"
    }
    slips = forecast_slips(
        tasks, members_by_gid, initial_keys, today, settings.pace_slip_horizon_days,
        default_hours=settings.asana_default_task_hours,
        default_weekly_hours=settings.asana_default_weekly_hours,
        daily_workdays=settings.asana_workload_daily_workdays,
    )
    if not slips:
        return []

    gids = list(members_by_gid)
    skills = pm_assign._skills_by_gid(gids)
    load = task_workload.open_hours_for_members(gids)
    eligible_cache: dict = {}
    client_names: dict = {}
    for c in (sb.table("clients").select("id, name")
              .in_("id", sorted({s["task"]["client_id"] for s in slips})).execute()).data or []:
        client_names[c["id"]] = c.get("name")

    proposals: list[dict] = []
    for s in slips:
        t = s["task"]
        cid = t["client_id"]
        cname = client_names.get(cid, "client")
        warn = (f"Will slip: “{t.get('name')}” due {s['due'].isoformat()} "
                f"({s['reason'].replace('_', ' ')}: has {s['available']:g}h for a {s['needed']:g}h task)")
        if s["reason"] == "unassigned":
            proposals.append({
                "action": "assign_task", "client_id": cid, "client_name": cname,
                "args": {"task_name": t.get("name") or ""},
                "reason": f"{warn} — place it now", "priority": _SLIP_PRIORITY,
                "kind": "slip_fix", "perm": "assign_task",
            })
            continue
        # Fix 1 (cheaper): a teammate with room takes it.
        if cid not in eligible_cache:
            eligible_cache[cid] = pm_assign._eligible_gids(cid)
        pool = [m for m in members if m["gid"] != t.get("assignee_gid")]
        pick = pm_assign.pick_assignee(
            t, pool, skills, eligible_cache[cid], load,
            default_hours=settings.asana_default_task_hours,
            default_weekly_hours=settings.asana_default_weekly_hours, overload="hold",
        )
        if pick.get("gid"):
            proposals.append({
                "action": "reassign_task", "client_id": cid, "client_name": cname,
                "args": {"task_name": t.get("name") or "", "assignee": pick.get("name")},
                "reason": f"{warn} — move it to {pick.get('name')}",
                "priority": _SLIP_PRIORITY, "kind": "slip_fix", "perm": "reassign_task",
            })
            continue
        # Fix 2: the earliest date the current assignee can actually make.
        member = members_by_gid.get(t.get("assignee_gid")) or {}
        new_due = next_feasible_due(
            s, member, today,
            default_weekly_hours=settings.asana_default_weekly_hours,
            daily_workdays=settings.asana_workload_daily_workdays,
        )
        if new_due:
            proposals.append({
                "action": "set_task_due", "client_id": cid, "client_name": cname,
                "args": {"task_name": t.get("name") or "", "due_date": new_due.isoformat()},
                "reason": f"{warn} — nobody can absorb it; move the due date to {new_due.isoformat()}",
                "priority": _SLIP_PRIORITY, "kind": "slip_fix", "perm": "set_task_due_other",
            })
        else:
            proposals.append({  # warning-only flag line (action-less)
                "action": None, "client_id": cid, "client_name": cname, "args": {},
                "reason": f"{warn} — no feasible fix found (needs a human call)",
                "priority": _SLIP_PRIORITY, "kind": "slip_warn", "perm": "read_board",
            })
    return proposals

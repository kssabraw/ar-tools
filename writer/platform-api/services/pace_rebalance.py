"""PACE v1.4 Phase 11 — the rebalancing generator (§4.11).

When the workload engine flags someone overloaded, PACE proposes the FIX, not
just the fact: `pm_assign.build_rebalance` plans which of their **not-yet-
started** tasks (in-flight work is never yanked) move to which skilled,
eligible, under-loaded teammates, and this generator turns the plan into
`reassign_task` Chase-Plan proposals. Partial relief is stated honestly.
"""

from __future__ import annotations

import logging
from datetime import date

from config import settings
from db.supabase_client import get_supabase
from services import pm_assign, task_service, task_workload
from services.pace_proposals import register_generator

logger = logging.getLogger(__name__)

_REBALANCE_PRIORITY = 45  # between triage (40) and the chase loop (50–80)


def _initial_status_keys() -> set[str]:
    return {
        s["key"] for s in task_service.get_statuses(active_only=False)
        if s.get("is_initial") or s.get("category") == "not_started"
    }


def _movable_tasks(gid: str, initial_keys: set[str]) -> list[dict]:
    rows = (
        get_supabase().table("tasks")
        .select("id, client_id, name, category, est_hours, status_key")
        .eq("assignee_gid", gid).eq("completed", False)
        .is_("deleted_at", "null").is_("parent_task_id", "null")
        .execute()
    ).data or []
    return [t for t in rows if t.get("status_key") in initial_keys and t.get("client_id")]


@register_generator
def rebalance_proposals(today: date) -> list[dict]:
    if not (settings.pace_enabled and settings.pace_initiative_enabled):
        return []
    report = task_workload.build_team_workload()
    overloaded = report.get("overloaded") or []
    if not overloaded:
        return []

    members = pm_assign._active_members()
    gids = [m["gid"] for m in members]
    skills = pm_assign._skills_by_gid(gids)
    load = task_workload.open_hours_for_members(gids)
    initial_keys = _initial_status_keys()
    default_weekly = settings.asana_default_weekly_hours
    by_gid = {m.get("gid"): m for m in report.get("members") or []}

    client_names: dict = {}
    proposals: list[dict] = []
    for om in overloaded:
        gid = om.get("gid")
        rm = by_gid.get(gid) or om
        cap = rm.get("weekly_hours") if rm.get("weekly_hours") is not None else default_weekly
        over_hours = max(0.0, float(rm.get("open_hours") or 0) - float(cap))
        if over_hours <= 0:
            continue
        movable = _movable_tasks(gid, initial_keys)
        if not movable:
            continue
        eligible_by_client = {
            cid: pm_assign._eligible_gids(cid)
            for cid in sorted({t["client_id"] for t in movable})
        }
        plan = pm_assign.build_rebalance(
            gid, over_hours, movable, members, skills, eligible_by_client, load,
            default_hours=settings.asana_default_task_hours,
            default_weekly_hours=default_weekly,
        )
        if not plan["moves"]:
            continue
        missing = sorted({m["client_id"] for m in plan["moves"]} - set(client_names))
        if missing:
            for c in (get_supabase().table("clients").select("id, name").in_("id", missing).execute()).data or []:
                client_names[c["id"]] = c.get("name")
        pct = f" ({round(100 * float(rm.get('open_hours') or 0) / float(cap))}%)" if cap else ""
        relief = (f" — frees {plan['freed']:g}h of {over_hours:g}h over"
                  if plan["remaining_over"] > 0 else "")
        for mv in plan["moves"]:
            proposals.append({
                "action": "reassign_task", "client_id": mv["client_id"],
                "client_name": client_names.get(mv["client_id"], "client"),
                "args": {"task_name": mv["task_name"], "assignee": mv["to_name"]},
                "reason": (f"Rebalance: move “{mv['task_name']}” ({mv['est']:g}h) from "
                           f"{om.get('name') or gid}{pct} → {mv['to_name']}{relief}"),
                "priority": _REBALANCE_PRIORITY, "kind": "rebalance", "perm": "reassign_task",
            })
    return proposals

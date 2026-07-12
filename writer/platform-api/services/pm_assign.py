"""PACE v1.3 Phase 5 — workload-aware assignment with role/skill matching.

docs/modules/project-manager-agent-plan-v1_0.md §4.6. The "correct party" engine:
given an unassigned task, pick the member who is **skilled** in its category,
**eligible** for its client, and **least-loaded** — or **hold** it (leave
unassigned + flag) when that pool is at capacity.

This is *deterministic distribution* — the same class as the monthly
`distribute_tasks`, NOT an LLM decision (§9 guardrail). The pure `pick_assignee`
is unit-tested; the impure wrappers gather DB state and write the assignment (or
a `placement_deferred` activity row when held). Native-board only.

Callers:
- the approval hook (`asana_push.push_proposal` → `place_task`),
- optional producer auto-placement (`task_producers`, flag-gated),
- the conversational `assign_task` PACE action (`preview_placement` at stage).
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import task_service, task_workload

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure core (unit-tested)
# ---------------------------------------------------------------------------
def _skilled(member_gid: str, category: Optional[str], skills_by_gid: dict) -> bool:
    """True when the member can do this category. A member with NO skill rows is
    a **generalist** (eligible for any category) — the safe day-one default."""
    rows = skills_by_gid.get(member_gid) or []
    if not rows or not category:
        return True
    return any(s.get("category_key") == category for s in rows)


def _is_primary(member_gid: str, category: Optional[str], skills_by_gid: dict) -> bool:
    return any(
        s.get("category_key") == category and s.get("is_primary")
        for s in (skills_by_gid.get(member_gid) or [])
    )


def pick_assignee(
    task: dict,
    members: list[dict],
    skills_by_gid: dict,
    eligible_gids: Optional[list[str]],
    load_by_gid: dict,
    *,
    default_hours: float,
    default_weekly_hours: float,
    overload: str = "hold",
) -> dict:
    """Pure. Choose the correct party for ``task``, or hold it.

    Returns one of:
      {"gid","name","reason","remaining"}   — placed (reason: placed | placed_widened)
      {"gid": None, "held": True, "reason", "category", "candidates"}  — held
        (reason: team_at_capacity | no_eligible_member)

    Candidate pool = active ∩ client-eligible ∩ skilled (or generalist). With no
    skilled candidate the pool widens to eligible-ignoring-skill (flagged). Ranked
    by remaining weekly capacity, then is_primary for the category, then gid.
    """
    category = (task.get("category") or "").strip() or None
    raw = task.get("est_hours")
    est = float(raw) if raw is not None else float(default_hours)

    pool = [m for m in members if m.get("active", True)]
    if eligible_gids:
        elig = set(eligible_gids)
        pool = [m for m in pool if m.get("gid") in elig]

    skilled = [m for m in pool if _skilled(m.get("gid"), category, skills_by_gid)]
    if skilled:
        candidates, widened = skilled, False
    elif pool:
        candidates, widened = pool, True  # no skilled match → widen to eligible
    else:
        return {"gid": None, "held": True, "reason": "no_eligible_member",
                "category": category, "candidates": []}

    def remaining(m: dict) -> float:
        cap = m.get("weekly_hours")
        cap = float(cap) if cap is not None else float(default_weekly_hours)
        return cap - float(load_by_gid.get(m.get("gid"), 0.0))

    ranked = sorted(
        candidates,
        key=lambda m: (
            -remaining(m),
            not _is_primary(m.get("gid"), category, skills_by_gid),
            m.get("gid") or "",
        ),
    )
    top = ranked[0]
    if remaining(top) < est and overload == "hold":
        return {"gid": None, "held": True, "reason": "team_at_capacity",
                "category": category, "candidates": [m.get("gid") for m in ranked]}
    return {"gid": top.get("gid"), "name": top.get("name"),
            "reason": "placed_widened" if widened else "placed",
            "remaining": remaining(top)}


# ---------------------------------------------------------------------------
# Impure state-gather + write
# ---------------------------------------------------------------------------
def _get_task(task_id: str) -> Optional[dict]:
    rows = (
        get_supabase().table("tasks")
        .select("id, client_id, name, category, est_hours, assignee_gid")
        .eq("id", task_id).is_("deleted_at", "null").limit(1).execute()
    ).data
    return rows[0] if rows else None


def _active_members() -> list[dict]:
    return (
        get_supabase().table("asana_team_members")
        .select("gid, name, weekly_hours, active").eq("active", True).execute()
    ).data or []


def _skills_by_gid(gids: list[str]) -> dict:
    if not gids:
        return {}
    rows = (
        get_supabase().table("task_member_skills")
        .select("member_gid, category_key, is_primary, weight")
        .in_("member_gid", gids).execute()
    ).data or []
    out: dict = {}
    for r in rows:
        out.setdefault(r["member_gid"], []).append(r)
    return out


def _eligible_gids(client_id: str) -> Optional[list[str]]:
    """The client's auto-assignee eligibility list (empty/absent ⇒ all members)."""
    rows = (
        get_supabase().table("asana_client_projects")
        .select("auto_assignee_gids").eq("client_id", client_id).limit(1).execute()
    ).data
    if rows and rows[0].get("auto_assignee_gids"):
        return rows[0]["auto_assignee_gids"]
    return None


# ---------------------------------------------------------------------------
# Competency CRUD (the Workload-page editor)
# ---------------------------------------------------------------------------
def list_all_skills() -> dict:
    """All members' competencies grouped by member_gid → [{category_key, is_primary}]."""
    rows = (
        get_supabase().table("task_member_skills")
        .select("member_gid, category_key, is_primary").execute()
    ).data or []
    out: dict = {}
    for r in rows:
        out.setdefault(r["member_gid"], []).append(
            {"category_key": r["category_key"], "is_primary": bool(r.get("is_primary"))}
        )
    return out


def replace_member_skills(member_gid: str, items: list[dict]) -> list[dict]:
    """Whole-set replace of one member's competencies (deduped by category)."""
    sb = get_supabase()
    sb.table("task_member_skills").delete().eq("member_gid", member_gid).execute()
    rows, seen = [], set()
    for it in items:
        key = (it.get("category_key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append({"member_gid": member_gid, "category_key": key,
                     "is_primary": bool(it.get("is_primary"))})
    if rows:
        sb.table("task_member_skills").insert(rows).execute()
    return [{"category_key": r["category_key"], "is_primary": r["is_primary"]} for r in rows]


def _compute(task: dict) -> dict:
    """Gather live state for the task's client and run `pick_assignee`."""
    members = _active_members()
    gids = [m["gid"] for m in members]
    return pick_assignee(
        task, members, _skills_by_gid(gids), _eligible_gids(task.get("client_id")),
        task_workload.open_hours_for_members(gids),
        default_hours=settings.asana_default_task_hours,
        default_weekly_hours=settings.asana_default_weekly_hours,
        overload=settings.pace_placement_overload,
    )


def preview_placement(task_id: str) -> Optional[dict]:
    """The placement `pick_assignee` would choose, without writing (the confirm
    preview for the `assign_task` action). None when the task is gone."""
    task = _get_task(task_id)
    return _compute(task) if task else None


def place_task(task_id: str, *, actor_id: Optional[str] = None) -> dict:
    """Assign ``task_id`` to the computed correct party, or record a held flag
    when the eligible pool is at capacity. Best-effort — never raises into the
    caller (approval/producer hooks). Native-board only."""
    try:
        task = _get_task(task_id)
        if not task:
            return {"gid": None, "held": True, "reason": "task_not_found"}
        # Never overwrite an existing assignment — a producer gap-fill re-run or a
        # human's manual pick must stand. (The explicit `assign_task` action goes
        # through update_task directly, so it's unaffected by this guard.)
        if task.get("assignee_gid"):
            return {"gid": task["assignee_gid"], "reason": "already_assigned"}
        result = _compute(task)
        if result.get("gid"):
            task_service.update_task(
                task_id,
                {"assignee_gid": result["gid"], "assignee_name": result.get("name")},
                actor_id=actor_id,
            )
        else:
            # Held: leave unassigned (pm_signals already surfaces unassigned work)
            # and record WHY, so the digest/board can explain the gap.
            task_service.record_activity(
                task_id, "placement_deferred", actor_id=actor_id,
                detail={"reason": result.get("reason"), "category": result.get("category")},
            )
        return result
    except Exception as exc:
        logger.warning("pm_assign.place_failed", extra={"task_id": task_id, "error": str(exc)})
        return {"gid": None, "held": True, "reason": "error"}

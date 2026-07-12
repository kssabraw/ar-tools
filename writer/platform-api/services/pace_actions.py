"""PACE — the action layer (Phase 2).

docs/modules/project-manager-agent-plan-v1_0.md §4.2. The write actions PACE can
take: reassign, set/bump due date, unblock, generate the month, nudge. Each is
**permission-checked at stage** (`pace_auth.require`), **target-resolved before
the confirm**, and carries the **requester** so the confirmation is actor-bound
(§3.3). Actor-authorized + reply-*yes* gated — a human always approves.

This module is self-contained and does **not** wire into the live SerMaStr
`interpret()`/`_pending` flow — that (the persona + router that *exposes* these
actions with two-way tool isolation) is Phase 3, where the live assistant is
touched carefully. Here the actions exist as tested `stage`/`run` functions +
the persona-scoped `PACE_ACTIONS` registry Phase 3 will mount.

`stage(context, client_id, args)` returns:
  ("reply", str)      — a clarification/refusal to send back verbatim, OR
  ("confirm", dict)   — the resolved, staged action: carries the executable args,
                        a "_confirm" one-liner naming the exact change, and
                        "_requester" (the stager's profile_id) for §3.3.
`run(context, client_id, args)` executes and returns a result string.

Pure helpers (previous-status extraction, mention building) are unit-tested.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from db.supabase_client import get_supabase
from services import pace_auth, task_service
from services.pace_auth import ActionContext
from services.slack_assistant.actions import match_named, match_open_tasks

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def previous_status_from_activity(activities: list[dict], blocked_status_key: str) -> Optional[str]:
    """The status a task held *before* it entered ``blocked_status_key`` — the
    ``detail.from`` of the most recent ``status_changed`` activity whose
    ``detail.to`` is the blocked status. None when there's no such record (→ the
    caller asks which status to restore). Pure — the corrected §4.2 source (not
    "the most recent status_changed", which is the current status)."""
    best_from = None
    best_at = None
    for a in activities:
        if a.get("kind") != "status_changed":
            continue
        detail = a.get("detail") or {}
        if detail.get("to") != blocked_status_key or not detail.get("from"):
            continue
        at = a.get("created_at") or ""
        if best_at is None or at >= best_at:
            best_at, best_from = at, detail["from"]
    return best_from


def build_nudge_mention(slack_user_id: Optional[str]) -> Optional[str]:
    """A real Slack mention token for an assignee, or None when they have no
    Slack link (→ in-app-only delivery, never a dead plain-text name). Pure."""
    return f"<@{slack_user_id}>" if slack_user_id else None


# ---------------------------------------------------------------------------
# Small DB reads
# ---------------------------------------------------------------------------
def _open_tasks(client_id: str) -> list[dict]:
    return (
        get_supabase().table("tasks")
        .select("id, name, status_key, assignee_gid, assignee_name, due_date, category, est_hours, completed")
        .eq("client_id", client_id).eq("completed", False)
        .is_("deleted_at", "null").is_("parent_task_id", "null")
        .execute()
    ).data or []


def _team_members() -> list[dict]:
    return (
        get_supabase().table("asana_team_members")
        .select("gid, name, profile_id").eq("active", True).execute()
    ).data or []


def _task_activity(task_id: str) -> list[dict]:
    return (
        get_supabase().table("task_activity").select("kind, detail, created_at")
        .eq("task_id", task_id).execute()
    ).data or []


def _actor_member_gid(context: ActionContext) -> Optional[str]:
    """The actor's own roster-member gid via the identity bridge, if linked."""
    if not context.profile_id:
        return None
    rows = (
        get_supabase().table("asana_team_members")
        .select("gid").eq("profile_id", context.profile_id).limit(1).execute()
    ).data
    return rows[0]["gid"] if rows else None


def _resolve_one_task(client_id: str, query: str, verb: str):
    """(task, None) on a unique match; (None, reply) to send back otherwise."""
    if not (query or "").strip():
        return None, f"Which task should I {verb}? Give me (part of) its name."
    tasks = _open_tasks(client_id)
    matches = match_open_tasks(tasks, query)
    if not matches:
        names = "; ".join(t.get("name") for t in tasks[:8]) or "none"
        return None, f"No open task matches “{query}”. Open: {names}."
    if len(matches) > 1:
        listing = "\n".join(f"• {t.get('name')}" for t in matches[:8])
        return None, f"“{query}” matches {len(matches)} tasks — which one?\n{listing}"
    return matches[0], None


def _staged(args: dict, context: ActionContext, confirm: str) -> tuple[str, dict]:
    return "confirm", {**args, "_confirm": confirm, "_requester": context.profile_id}


# ---------------------------------------------------------------------------
# reassign_task
# ---------------------------------------------------------------------------
def stage_reassign(context: ActionContext, client_id: str, args: dict) -> tuple[str, dict | str]:
    ok, reason = pace_auth.require(context, "reassign_task")
    if not ok:
        return "reply", reason
    task, reply = _resolve_one_task(client_id, args.get("task_name", ""), "reassign")
    if reply:
        return "reply", reply
    members = _team_members()
    who = (args.get("assignee") or "").strip()
    m = match_named(members, who)
    if not who or not m:
        names = ", ".join(x.get("name") for x in members) or "none"
        return "reply", f"Who should “{task['name']}” go to? Tracked members: {names}."
    if len(m) > 1:
        return "reply", f"“{who}” matches {len(m)} members — be more specific."
    member = m[0]
    frm = task.get("assignee_name") or "unassigned"
    return _staged(
        {"task_id": task["id"], "task_name": task["name"],
         "assignee_gid": member["gid"], "assignee_name": member.get("name")},
        context, f"reassign *“{task['name']}”* from {frm} to *{member.get('name')}*",
    )


def run_reassign(context: ActionContext, client_id: str, args: dict) -> str:
    task_service.update_task(
        args["task_id"],
        {"assignee_gid": args["assignee_gid"], "assignee_name": args.get("assignee_name")},
        actor_id=context.profile_id,
    )
    return f"✅ Reassigned *“{args['task_name']}”* to {args.get('assignee_name')}."


# ---------------------------------------------------------------------------
# assign_task (v1.3) — workload-aware auto-placement (§4.6)
# ---------------------------------------------------------------------------
def stage_assign(context: ActionContext, client_id: str, args: dict) -> tuple[str, dict | str]:
    ok, reason = pace_auth.require(context, "assign_task")
    if not ok:
        return "reply", reason
    task, reply = _resolve_one_task(client_id, args.get("task_name", ""), "assign")
    if reply:
        return "reply", reply
    from services import pm_assign

    result = pm_assign.preview_placement(task["id"]) or {}
    if not result.get("gid"):
        if result.get("reason") == "team_at_capacity":
            return "reply", (
                f"“{task['name']}” can't be placed right now — everyone eligible for its work "
                f"is over capacity this week. I've left it unassigned; reassign manually or free "
                f"up someone's load."
            )
        return "reply", f"I couldn't find an eligible member to take “{task['name']}”."
    note = " — no exact skill match, widened to the eligible team" if result.get("reason") == "placed_widened" else ""
    return _staged(
        {"task_id": task["id"], "task_name": task["name"],
         "assignee_gid": result["gid"], "assignee_name": result.get("name")},
        context,
        f"assign *“{task['name']}”* to *{result.get('name')}* (least-loaded eligible member{note})",
    )


def run_assign(context: ActionContext, client_id: str, args: dict) -> str:
    task_service.update_task(
        args["task_id"],
        {"assignee_gid": args["assignee_gid"], "assignee_name": args.get("assignee_name")},
        actor_id=context.profile_id,
    )
    return f"✅ Assigned *“{args['task_name']}”* to {args.get('assignee_name')}."


# ---------------------------------------------------------------------------
# set_task_due
# ---------------------------------------------------------------------------
def stage_set_due(context: ActionContext, client_id: str, args: dict) -> tuple[str, dict | str]:
    due = (args.get("due_date") or "").strip()
    try:
        date.fromisoformat(due)
    except ValueError:
        return "reply", "The due date must be YYYY-MM-DD (e.g. 2026-12-31)."
    # Peek the task to decide own-vs-other permission before the full resolve.
    task, reply = _resolve_one_task(client_id, args.get("task_name", ""), "set a due date on")
    if reply:
        return "reply", reply
    own = task.get("assignee_gid") and task.get("assignee_gid") == _actor_member_gid(context)
    ok, reason = pace_auth.require(context, "set_task_due_own" if own else "set_task_due_other")
    if not ok:
        return "reply", reason
    return _staged(
        {"task_id": task["id"], "task_name": task["name"], "due_date": due},
        context, f"set *“{task['name']}”* due {due}",
    )


def run_set_due(context: ActionContext, client_id: str, args: dict) -> str:
    task_service.update_task(args["task_id"], {"due_date": args["due_date"]}, actor_id=context.profile_id)
    return f"✅ *“{args['task_name']}”* due {args['due_date']}."


# ---------------------------------------------------------------------------
# unblock_task
# ---------------------------------------------------------------------------
def stage_unblock(context: ActionContext, client_id: str, args: dict) -> tuple[str, dict | str]:
    ok, reason = pace_auth.require(context, "unblock_task")
    if not ok:
        return "reply", reason
    task, reply = _resolve_one_task(client_id, args.get("task_name", ""), "unblock")
    if reply:
        return "reply", reply
    statuses = task_service.get_statuses()
    cat = {s["key"]: s.get("category") for s in statuses}
    if cat.get(task.get("status_key")) != "blocked":
        return "reply", f"“{task['name']}” isn't blocked (it's {task.get('status_key')})."
    prev = previous_status_from_activity(_task_activity(task["id"]), task["status_key"])
    if not prev or prev not in cat:
        # Ask which status to restore rather than hardcoding in_progress.
        opts = ", ".join(s["key"] for s in statuses if s.get("category") != "done" and s.get("active", True))
        return "reply", (
            f"I can't tell what “{task['name']}” was before it was blocked. "
            f"Which status should it go to? ({opts})"
        )
    return _staged(
        {"task_id": task["id"], "task_name": task["name"], "status_key": prev},
        context, f"unblock *“{task['name']}”* → *{prev}* (its status before it was blocked)",
    )


def run_unblock(context: ActionContext, client_id: str, args: dict) -> str:
    task_service.update_task(args["task_id"], {"status_key": args["status_key"]}, actor_id=context.profile_id)
    return f"✅ Unblocked *“{args['task_name']}”* → {args['status_key']}."


# ---------------------------------------------------------------------------
# generate_client_month
# ---------------------------------------------------------------------------
def stage_generate_month(context: ActionContext, client_id: str, args: dict) -> tuple[str, dict | str]:
    ok, reason = pace_auth.require(context, "generate_client_month")
    if not ok:
        return "reply", reason
    from services.asana_service import month_label
    target = date.today().replace(day=1)
    return _staged(
        {"month": target.isoformat()}, context,
        f"generate the *{month_label(target)}* tasks for this client from its template",
    )


def run_generate_month(context: ActionContext, client_id: str, args: dict) -> str:
    from services.task_monthly import enqueue_task_month
    from services.asana_service import month_label
    target = date.fromisoformat(args["month"])
    enqueue_task_month(client_id, target, trigger="pace", actor_id=context.profile_id)
    return f"✅ Queued {month_label(target)} generation (you'll see the tasks land shortly)."


# ---------------------------------------------------------------------------
# nudge_assignee
# ---------------------------------------------------------------------------
def stage_nudge(context: ActionContext, client_id: str, args: dict) -> tuple[str, dict | str]:
    task, reply = _resolve_one_task(client_id, args.get("task_name", ""), "nudge about")
    if reply:
        return "reply", reply
    if not task.get("assignee_gid"):
        return "reply", f"“{task['name']}” is unassigned — nobody to nudge (assign it first)."
    own = task.get("assignee_gid") == _actor_member_gid(context)
    ok, reason = pace_auth.require(context, "nudge_self" if own else "nudge_other")
    if not ok:
        return "reply", reason
    return _staged(
        {"task_id": task["id"], "task_name": task["name"],
         "assignee_gid": task["assignee_gid"], "assignee_name": task.get("assignee_name")},
        context, f"nudge {task.get('assignee_name') or 'the assignee'} about *“{task['name']}”*",
    )


def run_nudge(context: ActionContext, client_id: str, args: dict) -> str:
    from services import notifications
    # Resolve the assignee's Slack id via member → profile → slack_user_id.
    slack_id = None
    member = (
        get_supabase().table("asana_team_members")
        .select("profile_id").eq("gid", args["assignee_gid"]).limit(1).execute()
    ).data
    if member and member[0].get("profile_id"):
        prof = (
            get_supabase().table("profiles").select("slack_user_id")
            .eq("id", member[0]["profile_id"]).limit(1).execute()
        ).data
        if prof:
            slack_id = prof[0].get("slack_user_id")
    mention = build_nudge_mention(slack_id)
    who = args.get("assignee_name") or "the assignee"
    lead = f"{mention} " if mention else ""
    notifications.emit(
        client_id=client_id, kind="task_nudge",
        title=f"Nudge: “{args['task_name']}”",
        summary=f"{lead}a reminder to move *“{args['task_name']}”* along.",
        severity="info",
        payload={"link": f"/clients/{client_id}/tasks?task={args['task_id']}", "assignee_gid": args["assignee_gid"]},
    )
    delivery = f"pinged {who}" if mention else f"posted an in-app nudge ({who} has no Slack link)"
    return f"✅ Nudge sent — {delivery}."


# ---------------------------------------------------------------------------
# triage_task (v1.4) — set missing due date / category / estimate in one write
# ---------------------------------------------------------------------------
_TRIAGE_FIELDS = ("due_date", "category", "est_hours")


def stage_triage(context: ActionContext, client_id: str, args: dict) -> tuple[str, dict | str]:
    ok, reason = pace_auth.require(context, "triage_task")
    if not ok:
        return "reply", reason
    task, reply = _resolve_one_task(client_id, args.get("task_name", ""), "triage")
    if reply:
        return "reply", reply
    updates = {k: args[k] for k in _TRIAGE_FIELDS if args.get(k) not in (None, "")}
    if "due_date" in updates:
        try:
            date.fromisoformat(str(updates["due_date"]))
        except ValueError:
            return "reply", "The due date must be YYYY-MM-DD."
    # Triage fills GAPS only — never overwrite a value a human already set.
    updates = {k: v for k, v in updates.items() if not task.get(k)}
    if not updates:
        return "reply", f"“{task['name']}” is already triaged — nothing to set."
    parts = []
    if "due_date" in updates:
        parts.append(f"due {updates['due_date']}")
    if "category" in updates:
        parts.append(f"category *{updates['category']}*")
    if "est_hours" in updates:
        parts.append(f"est {updates['est_hours']}h")
    return _staged(
        {"task_id": task["id"], "task_name": task["name"], "updates": updates},
        context, f"triage *“{task['name']}”* — set {', '.join(parts)}",
    )


def run_triage(context: ActionContext, client_id: str, args: dict) -> str:
    task_service.update_task(args["task_id"], args["updates"], actor_id=context.profile_id)
    fields = ", ".join(args["updates"].keys())
    return f"✅ Triaged *“{args['task_name']}”* ({fields})."


# ---------------------------------------------------------------------------
# generate_pace_report (v1.3) — delivery report (§4.7), read-only (no confirm)
# ---------------------------------------------------------------------------
def stage_generate_report(context: ActionContext, client_id: str, args: dict) -> tuple[str, dict | str]:
    ok, reason = pace_auth.require(context, "generate_pace_report")
    if not ok:
        return "reply", reason
    from services import pace_report

    # A read: build + render immediately and return as the reply (no confirm).
    report = pace_report.build_report(client_id)
    return "reply", pace_report.render_text(report, scope_name="this client")


def run_generate_report(context: ActionContext, client_id: str, args: dict) -> str:
    # Reads resolve at stage (reply); run is never reached but kept for the
    # registry's stage/run contract.
    from services import pace_report

    return pace_report.render_text(pace_report.build_report(client_id), scope_name="this client")


# ---------------------------------------------------------------------------
# Persona-scoped registry (Phase 3 mounts this under persona='pace')
# ---------------------------------------------------------------------------
PACE_ACTIONS: dict[str, dict] = {
    "reassign_task": {"label": "reassign a task", "stage": stage_reassign, "run": run_reassign},
    "assign_task": {"label": "auto-assign a task to the best-fit member", "stage": stage_assign, "run": run_assign},
    "set_task_due": {"label": "set a task's due date", "stage": stage_set_due, "run": run_set_due},
    "unblock_task": {"label": "unblock a task", "stage": stage_unblock, "run": run_unblock},
    "generate_client_month": {"label": "generate this month's tasks", "stage": stage_generate_month, "run": run_generate_month},
    "nudge_assignee": {"label": "nudge an assignee", "stage": stage_nudge, "run": run_nudge},
    "generate_pace_report": {"label": "generate a delivery report", "stage": stage_generate_report, "run": run_generate_report},
    "triage_task": {"label": "triage a task (set missing due date / category / estimate)", "stage": stage_triage, "run": run_triage},
}

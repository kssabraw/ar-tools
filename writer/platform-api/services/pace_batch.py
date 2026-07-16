"""PACE — structural-autonomy helpers (v1.5): drill-down + on-demand batches.

Two conversational-autonomy features on top of the persona:

- **Drill-down** (`drill_task` read tool): PACE can pull a single task's full
  context — subtask rollup, recent activity, comments, days-in-status — so it
  can explain *why* something is stuck instead of just naming it. This module
  owns the tool schema + the pure text formatter; the impure read lives in
  `pace_agent._drill_read`.

- **On-demand batches** (`batch_action` tool): one instruction — "nudge all of
  Ivy's overdue", "bump every overdue task on Acme by a week" — fans out to the
  matching tasks and stages them as ONE confirm, reusing the Chase Plan executor
  (`pace_proposals.execute_plan_selection` / `parse_plan_reply`). This module
  owns the tool schema, the pure selector→targets expansion, and the confirm
  renderer; `pace_agent` stages the items (under the requester) + wires the
  confirm into both surfaces.

Everything here is pure (unit-tested in `tests/test_pace_batch.py`); the impure
staging/reads stay in `pace_agent`.
"""

from __future__ import annotations

from typing import Optional

# The per-task PACE_ACTIONS that make sense to run in bulk (a batch never touches
# whole-client actions like generate_client_month / generate_pace_report).
BATCH_ACTIONS = {"nudge_assignee", "reassign_task", "set_task_due", "unblock_task", "triage_task"}

# selector → the signal-envelope / member-context bucket it reads from. "stuck"
# maps to the stale list (client/portfolio scope only — member context has no
# per-person staleness, so a member-scope "stuck" batch resolves empty).
_SELECTOR_TO_KEY = {
    "overdue": "overdue",
    "stuck": "stale",
    "blocked": "stale",
    "unassigned": "unassigned",
    "no_due_date": "no_due_date",
}
_MEMBER_SELECTOR_TO_KEY = {
    "overdue": "overdue",
    "due_today": "due_today",
    "this_week": "this_week",
    "no_due_date": "no_due_date",
}


# ---------------------------------------------------------------------------
# Tool schemas (mounted onto PACE's tool list alongside PACE_ACTIONS)
# ---------------------------------------------------------------------------
DRILL_TOOL = {
    "name": "drill_task",
    "description": (
        "Pull the full detail of ONE task — its subtasks, recent activity, "
        "comments, and how long it's been stuck — so you can explain why it's "
        "not moving. Use this when asked why a task is stuck/blocked/late, or "
        "proactively when a task looks stuck and the teammate would want the "
        "reason. Read-only; no confirmation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_name": {"type": "string", "description": "The task to inspect (part of its name)."},
        },
        "required": ["task_name"],
    },
}

BATCH_TOOL = {
    "name": "batch_action",
    "description": (
        "Run ONE operational action over a SET of tasks in the current scope in "
        "a single staged confirmation — e.g. nudge every overdue task, reassign "
        "all unassigned tasks to someone, bump every overdue due date. The set "
        "is resolved deterministically from the board data (you don't list the "
        "tasks); the teammate confirms the batch with 'yes' (or 'yes 1,3' to "
        "pick). Use this instead of calling a per-task action many times."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": sorted(BATCH_ACTIONS),
                       "description": "Which per-task action to run across the set."},
            "selector": {"type": "string", "enum": ["overdue", "stuck", "unassigned", "no_due_date", "due_today", "this_week"],
                         "description": "Which tasks in scope to act on."},
            "assignee": {"type": "string", "description": "For reassign_task: the member to reassign the set to."},
            "due_date": {"type": "string", "description": "For set_task_due: the due date (YYYY-MM-DD) to set across the set."},
        },
        "required": ["action", "selector"],
    },
}


# ---------------------------------------------------------------------------
# Pure: selector → concrete targets across the active scope
# ---------------------------------------------------------------------------
def _rows_for_selector(container: dict, selector: str, member: bool) -> list[dict]:
    table = _MEMBER_SELECTOR_TO_KEY if member else _SELECTOR_TO_KEY
    key = table.get(selector)
    return container.get(key) or [] if key else []


def select_targets(scope: str, subject: Optional[dict], ctx: dict, selector: str,
                   cap: int = 15) -> tuple[list[dict], int]:
    """Expand a selector into concrete ``{client_id, client_name, task_name}``
    targets from the scope's already-built board data. No I/O — the tasks are the
    rows the LLM was already shown, so a batch can never target a hallucinated
    task. Returns (targets, overflow) capped at ``cap``; rows without a name or
    client_id (e.g. a truncation marker) are dropped. Pure."""
    raw: list[dict] = []
    if scope == "portfolio":
        for c in ctx.get("clients", []) or []:
            cid, cname = c.get("client_id"), c.get("client_name") or "client"
            for r in _rows_for_selector(c, selector, member=False):
                raw.append({"client_id": cid, "client_name": cname, "task_name": r.get("name")})
    elif scope == "member":
        for r in _rows_for_selector(ctx, selector, member=True):
            raw.append({"client_id": r.get("client_id"), "client_name": r.get("client"),
                        "task_name": r.get("name")})
    else:  # client
        cid = (subject or {}).get("id")
        cname = (subject or {}).get("name") or "client"
        for r in _rows_for_selector(ctx, selector, member=False):
            raw.append({"client_id": cid, "client_name": cname, "task_name": r.get("name")})

    seen, targets = set(), []
    for t in raw:
        if not (t.get("client_id") and t.get("task_name")):
            continue
        dedupe = (t["client_id"], t["task_name"])
        if dedupe in seen:
            continue
        seen.add(dedupe)
        targets.append(t)
    overflow = max(0, len(targets) - cap)
    return targets[:cap], overflow


# ---------------------------------------------------------------------------
# Pure: confirm renderer + drill formatter
# ---------------------------------------------------------------------------
def render_batch(items: list[dict], flags: list[str], overflow: int = 0, bold: str = "*") -> str:
    """The on-demand batch confirm message. ``bold`` is Slack ``*`` or web
    ``**``. Pure — mirrors the Chase Plan format so replies parse identically."""
    n = len(items)
    lines = [f"{bold}PACE — {n} staged action{'s' if n != 1 else ''}{bold} "
             f"(reply {bold}yes{bold} for all, or `yes 1,3` to pick)"]
    for it in items:
        lines.append(f"{it['index']}. {it['reason']} — _{it['client_name']}_")
    for f in flags or []:
        lines.append(f"• ⚠️ {f}")
    if overflow:
        lines.append(f"…and {overflow} more held back — run it again to stage the rest.")
    return "\n".join(lines)


def format_drill(task: dict, comments: list[dict], days_in_status: Optional[int]) -> str:
    """A compact single-task read for the LLM to narrate: identity, subtask
    rollup, open subtasks, recent activity, recent comments. Pure — the caller
    supplies the already-read task (with ``subtasks``/``activity``) + comments."""
    lines = [f"Task: {task.get('name')}"]
    if task.get("assignee_name"):
        lines.append(f"Assignee: {task['assignee_name']}")
    status = task.get("status_key") or "unknown"
    lines.append(f"Status: {status}" + (f" ({days_in_status}d in this status)" if days_in_status is not None else ""))
    if task.get("due_date"):
        lines.append(f"Due: {task['due_date']}")

    subs = task.get("subtasks") or []
    if subs:
        done = sum(1 for s in subs if s.get("completed"))
        lines.append(f"Subtasks: {done}/{len(subs)} done")
        remaining = [s.get("name") for s in subs if not s.get("completed") and s.get("name")][:8]
        if remaining:
            lines.append("Open subtasks: " + "; ".join(remaining))

    acts = (task.get("activity") or [])[:6]
    if acts:
        lines.append("Recent activity:")
        for a in acts:
            when = str(a.get("created_at") or "")[:10]
            detail = a.get("detail")
            lines.append(f"  - {when} {a.get('kind')}" + (f" {detail}" if detail else ""))

    recent = [c for c in (comments or []) if c.get("body")][-3:]
    if recent:
        lines.append("Recent comments:")
        for c in recent:
            body = " ".join((c.get("body") or "").split())[:160]
            lines.append(f"  - {body}")
    return "\n".join(lines)

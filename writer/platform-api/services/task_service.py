"""Native task manager — core task CRUD, activity, and producer hooks.

Backs docs/modules/in-app-task-manager-prd-v1_0.md (§6.1–§6.2, §7, §11).
Phase 0: the service layer the monthly generation / workload / due sweep and
the (Phase 1) REST router compose. Subtasks are tasks with ``parent_task_id``
set — one model, one API.

Producer contract (§11): suite producers call ``create_task(..., source=<kind>,
source_ref=<stable key>)`` — idempotent on ``(source, source_ref)`` via the
partial unique index — and ``close_task_by_source(source, source_ref)`` when
the underlying signal resolves. Completed tasks keep their key (a resolved
signal must never re-create its task); trashed tasks release it.

Pure helpers (no I/O) are unit-tested; DB calls are mocked in tests.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config reads (statuses / categories)
# ---------------------------------------------------------------------------
def get_statuses(active_only: bool = True) -> list[dict]:
    """The configured workflow statuses, in sort order."""
    q = get_supabase().table("task_statuses").select("*").order("sort_order")
    if active_only:
        q = q.eq("active", True)
    return q.execute().data or []


def get_categories(active_only: bool = True) -> list[dict]:
    """The configured Service Type categories, in sort order."""
    q = get_supabase().table("task_categories").select("*").order("sort_order")
    if active_only:
        q = q.eq("active", True)
    return q.execute().data or []


def initial_status_key(statuses: list[dict]) -> Optional[str]:
    """The status new tasks get — the ``is_initial`` row, else the first active
    row (so a misconfigured set still yields something). Pure — unit-tested."""
    for s in statuses:
        if s.get("is_initial") and s.get("active", True):
            return s.get("key")
    for s in statuses:
        if s.get("active", True):
            return s.get("key")
    return None


def done_status_key(statuses: list[dict]) -> Optional[str]:
    """The status a completed task gets — the first active ``is_done`` row.
    Pure — unit-tested."""
    for s in statuses:
        if s.get("is_done") and s.get("active", True):
            return s.get("key")
    return None


def resolve_category_key(name: Optional[str], categories: list[dict]) -> Optional[str]:
    """Map a category label/key (e.g. a template row's cached ``category_name``
    or a library default) onto the ``task_categories`` key, case-insensitively.
    Unmatched names pass through as-is so imported/legacy labels aren't lost.
    Pure — unit-tested."""
    if not name or not name.strip():
        return None
    target = name.strip().casefold()
    for c in categories:
        if (c.get("key") or "").casefold() == target or (c.get("label") or "").strip().casefold() == target:
            return c.get("key")
    return name.strip()


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------
# Fields whose changes are worth an activity row, mapped to the activity kind.
_ACTIVITY_FIELDS = {
    "name": "renamed",
    "description": "edited",
    "client_note": "edited",
    "assignee_gid": "assigned",
    "status_key": "status_changed",
    "category": "category_changed",
    "due_date": "due_changed",
    "start_date": "due_changed",
    "est_hours": "estimate_changed",
    "section_id": "moved",
}


def diff_activity(before: dict, changes: dict) -> list[dict]:
    """The activity entries a patch produces: one ``{kind, detail:{field,from,to}}``
    per meaningful field that actually changed. Pure — unit-tested."""
    entries: list[dict] = []
    for field, kind in _ACTIVITY_FIELDS.items():
        if field not in changes:
            continue
        old, new = before.get(field), changes.get(field)
        if old == new:
            continue
        detail: dict[str, Any] = {"field": field, "from": old, "to": new}
        # Description bodies are long — record that it changed, not the text.
        if field == "description":
            detail = {"field": field}
        entries.append({"kind": kind, "detail": detail})
    return entries


def record_activity(
    task_id: str, kind: str, actor_id: Optional[str] = None, detail: Optional[dict] = None
) -> None:
    """Append one immutable activity row (best-effort — never fails the caller)."""
    try:
        get_supabase().table("task_activity").insert(
            {"task_id": task_id, "actor_id": actor_id, "kind": kind, "detail": detail}
        ).execute()
    except Exception as exc:
        logger.warning("task_activity_write_failed", extra={"task_id": task_id, "error": str(exc)})


# ---------------------------------------------------------------------------
# Create / update / complete
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_by_source(source: str, source_ref: str) -> Optional[dict]:
    """The live (non-trashed) task holding a producer key, if any."""
    rows = (
        get_supabase()
        .table("tasks")
        .select("*")
        .eq("source", source)
        .eq("source_ref", source_ref)
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    ).data
    return rows[0] if rows else None


def create_task(
    name: str,
    *,
    client_id: Optional[str] = None,
    section_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
    description: Optional[str] = None,
    assignee_gid: Optional[str] = None,
    assignee_name: Optional[str] = None,
    status_key: Optional[str] = None,
    category: Optional[str] = None,
    due_date: Optional[str] = None,
    start_date: Optional[str] = None,
    est_hours: Optional[float] = None,
    sort_order: int = 0,
    source: str = "manual",
    source_ref: Optional[str] = None,
    library_task_name: Optional[str] = None,
    created_by: Optional[str] = None,
) -> dict:
    """Create a task (or subtask, when ``parent_task_id`` is set) + its
    'created' activity row.

    Idempotent for producers: when ``source_ref`` is set and a live task already
    holds ``(source, source_ref)``, that task is returned unchanged (flagged
    ``_existing=True``) instead of inserting a duplicate.
    """
    if source_ref:
        existing = find_by_source(source, source_ref)
        if existing:
            existing["_existing"] = True
            return existing

    if status_key is None:
        status_key = initial_status_key(get_statuses())

    row = {
        "name": (name or "").strip(),
        "client_id": client_id,
        "section_id": section_id,
        "parent_task_id": parent_task_id,
        "description": description,
        "assignee_gid": assignee_gid,
        "assignee_name": assignee_name,
        "status_key": status_key,
        "category": category,
        "due_date": due_date,
        "start_date": start_date,
        "est_hours": est_hours,
        "sort_order": sort_order,
        "source": source,
        "source_ref": source_ref,
        "library_task_name": library_task_name,
        "created_by": created_by,
    }
    created = get_supabase().table("tasks").insert(row).execute().data[0]
    record_activity(created["id"], "created", actor_id=created_by, detail={"source": source})
    if assignee_gid:
        record_activity(
            created["id"], "assigned", actor_id=created_by,
            detail={"field": "assignee_gid", "from": None, "to": assignee_gid},
        )
    return created


def create_subtasks(
    parent: dict, names: list[str], *, created_by: Optional[str] = None
) -> int:
    """Insert an ordered subtask checklist under ``parent`` (a tasks row).
    Subtasks inherit the parent's client and carry no hours (the parent's
    estimate covers the whole checklist — workload must not double-count).
    Returns how many were created."""
    rows = [
        {
            "name": (n or "").strip(),
            "client_id": parent.get("client_id"),
            "section_id": parent.get("section_id"),
            "parent_task_id": parent["id"],
            "status_key": parent.get("status_key"),
            "sort_order": i,
            "source": parent.get("source") or "manual",
            "created_by": created_by,
        }
        for i, n in enumerate(names)
        if n and n.strip()
    ]
    if not rows:
        return 0
    get_supabase().table("tasks").insert(rows).execute()
    return len(rows)


def _notify_assignment(task: dict) -> None:
    """Best-effort 'assigned to you' notification (PRD §6.11). Recipients are
    agency-level channels for v1 (in-app + Slack) — per-user routing waits on
    the profiles unification, so `task_notification_prefs` isn't enforced yet."""
    try:
        from services import notifications

        who = task.get("assignee_name") or task.get("assignee_gid")
        link = (
            f"/clients/{task['client_id']}/tasks?task={task['id']}"
            if task.get("client_id")
            else "/my-tasks"
        )
        notifications.emit(
            client_id=task.get("client_id"),
            kind="task_assigned",
            title=f"{who} was assigned '{task.get('name')}'",
            summary=(f"Due {task['due_date']}" if task.get("due_date") else None),
            severity="info",
            payload={"link": link, "task_id": task["id"], "assignee_gid": task.get("assignee_gid")},
        )
    except Exception as exc:
        logger.warning("task_assign_notify_failed", extra={"task_id": task.get("id"), "error": str(exc)})


def update_task(task_id: str, changes: dict, *, actor_id: Optional[str] = None) -> dict:
    """Partial-update a task; every meaningful field change writes an activity
    row; an assignee change notifies. Returns the updated row."""
    supabase = get_supabase()
    before_rows = supabase.table("tasks").select("*").eq("id", task_id).limit(1).execute().data
    if not before_rows:
        raise ValueError("task_not_found")
    before = before_rows[0]

    payload = dict(changes)
    payload["updated_at"] = _now()
    updated = supabase.table("tasks").update(payload).eq("id", task_id).execute().data[0]
    for entry in diff_activity(before, changes):
        record_activity(task_id, entry["kind"], actor_id=actor_id, detail=entry["detail"])
    if (
        "assignee_gid" in changes
        and changes.get("assignee_gid")
        and changes["assignee_gid"] != before.get("assignee_gid")
    ):
        _notify_assignment(updated)
    return updated


def complete_task(task_id: str, *, actor_id: Optional[str] = None) -> dict:
    """Mark a task complete (+ move it to the done status when one is configured)."""
    payload: dict[str, Any] = {"completed": True, "completed_at": _now(), "updated_at": _now()}
    done_key = done_status_key(get_statuses())
    if done_key:
        payload["status_key"] = done_key
    updated = get_supabase().table("tasks").update(payload).eq("id", task_id).execute().data[0]
    record_activity(task_id, "completed", actor_id=actor_id)
    return updated


def reopen_task(task_id: str, *, actor_id: Optional[str] = None) -> dict:
    """Reopen a completed task (back to the initial status)."""
    payload: dict[str, Any] = {"completed": False, "completed_at": None, "updated_at": _now()}
    initial = initial_status_key(get_statuses())
    if initial:
        payload["status_key"] = initial
    updated = get_supabase().table("tasks").update(payload).eq("id", task_id).execute().data[0]
    record_activity(task_id, "reopened", actor_id=actor_id)
    return updated


def soft_delete_task(task_id: str, *, actor_id: Optional[str] = None) -> None:
    """Move a task to the Trash (restorable; releases its source_ref key)."""
    get_supabase().table("tasks").update(
        {"deleted_at": _now(), "updated_at": _now()}
    ).eq("id", task_id).execute()
    record_activity(task_id, "trashed", actor_id=actor_id)


def restore_task(task_id: str, *, actor_id: Optional[str] = None) -> None:
    """Restore a trashed task."""
    get_supabase().table("tasks").update(
        {"deleted_at": None, "updated_at": _now()}
    ).eq("id", task_id).execute()
    record_activity(task_id, "restored", actor_id=actor_id)


# ---------------------------------------------------------------------------
# Reads (board / detail / My Tasks)
# ---------------------------------------------------------------------------
def list_board_tasks(client_id: Optional[str], include_completed: bool = True) -> list[dict]:
    """All live top-level tasks on one board (a client's, or the null-client
    internal board), oldest sort first."""
    q = (
        get_supabase()
        .table("tasks")
        .select("*")
        .is_("deleted_at", "null")
        .is_("parent_task_id", "null")
        .order("sort_order")
        .order("created_at")
    )
    q = q.eq("client_id", client_id) if client_id else q.is_("client_id", "null")
    if not include_completed:
        q = q.eq("completed", False)
    return q.execute().data or []


def subtask_progress(parent_ids: list[str]) -> dict[str, dict]:
    """``{parent_id: {"total": n, "done": n}}`` for the given parents (live
    subtasks only) — the "3/5" card rollup."""
    if not parent_ids:
        return {}
    rows = (
        get_supabase()
        .table("tasks")
        .select("parent_task_id, completed")
        .in_("parent_task_id", parent_ids)
        .is_("deleted_at", "null")
        .execute()
    ).data or []
    progress: dict[str, dict] = {}
    for r in rows:
        pid = r.get("parent_task_id")
        if not pid:
            continue
        entry = progress.setdefault(pid, {"total": 0, "done": 0})
        entry["total"] += 1
        if r.get("completed"):
            entry["done"] += 1
    return progress


def get_task_detail(task_id: str) -> Optional[dict]:
    """One task + its live subtasks (ordered) + its activity feed."""
    supabase = get_supabase()
    rows = supabase.table("tasks").select("*").eq("id", task_id).is_("deleted_at", "null").limit(1).execute().data
    if not rows:
        return None
    task = rows[0]
    task["subtasks"] = (
        supabase.table("tasks")
        .select("*")
        .eq("parent_task_id", task_id)
        .is_("deleted_at", "null")
        .order("sort_order")
        .order("created_at")
        .execute()
    ).data or []
    task["activity"] = (
        supabase.table("task_activity")
        .select("*")
        .eq("task_id", task_id)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    ).data or []
    return task


# Due buckets for My Tasks, in display order.
_BUCKETS = ("overdue", "today", "this_week", "later", "no_date")


def bucket_by_due(rows: list[dict], today) -> dict[str, list[dict]]:
    """Group open tasks into Overdue / Today / This week / Later / No date.
    "This week" = the next 7 days after today. Pure — unit-tested."""
    from datetime import date as _date, timedelta

    buckets: dict[str, list[dict]] = {b: [] for b in _BUCKETS}
    week_end = today + timedelta(days=7)
    for r in rows:
        raw = r.get("due_date")
        if not raw:
            buckets["no_date"].append(r)
            continue
        due = _date.fromisoformat(raw) if isinstance(raw, str) else raw
        if due < today:
            buckets["overdue"].append(r)
        elif due == today:
            buckets["today"].append(r)
        elif due <= week_end:
            buckets["this_week"].append(r)
        else:
            buckets["later"].append(r)
    for b in ("overdue", "today", "this_week", "later"):
        buckets[b].sort(key=lambda r: (r.get("due_date") or "", r.get("name") or ""))
    return buckets


# ---------------------------------------------------------------------------
# Producer auto-close (§11)
# ---------------------------------------------------------------------------
def close_task_by_source(source: str, source_ref: str) -> bool:
    """Auto-complete the live task a producer opened, if it's still open.
    Returns True when a task was closed. Never raises — producers are
    best-effort riders on their signal writes."""
    try:
        task = find_by_source(source, source_ref)
        if not task or task.get("completed"):
            return False
        complete_task(task["id"])
        record_activity(task["id"], "auto_closed", detail={"source": source, "source_ref": source_ref})
        return True
    except Exception as exc:
        logger.warning(
            "task_auto_close_failed",
            extra={"source": source, "source_ref": source_ref, "error": str(exc)},
        )
        return False

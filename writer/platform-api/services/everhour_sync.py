"""Everhour time-tracking integration — sync orchestration.

Backs docs/modules/everhour-time-tracking-integration-plan-v1_0.md.

**Phase 2 (this file, so far): the task mirror (suite → Everhour, write,
metadata-only).** Give every native task a stable Everhour counterpart so time
logged against it in Everhour joins back to the exact ``tasks`` row — WITHOUT
turning Everhour into a second place task state lives (locked decision #6: name +
optional assignee only; never status / due-date / description / section).

Design (plan §3): the mirror runs **async** (a lightweight ``everhour_mirror``
``async_jobs`` job), not inline. The plan leaned inline, but ``create_task`` is a
sync function called from BOTH threadpool request handlers AND directly on the
event loop (``run_task_month_job`` awaits the sync ``generate_month_for_client``),
so an inline ``asyncio.run`` of Everhour's async client would raise inside a
running loop. Enqueuing a job is a plain sync DB insert that works from anywhere,
decouples Everhour's latency from every task-creation call-site, and gets the
worker's retry/settle machinery for free — the short window where a task exists
natively but has no Everhour counterpart yet is explicitly acceptable (time can't
be logged against it in that window anyway).

One funnel covers every §3 hook point at once: ``task_service.create_task`` is
the single choke point manual creation, the monthly generator, and every producer
all pass through, so ``enqueue_mirror`` is hooked there once rather than in three
places. Subtasks (checklist markers) are never mirrored — they aren't separate
billing targets, and they insert via ``create_subtasks`` (bypassing
``create_task``) anyway.

The **time pull (read) + rollups** are Phase 3 — deliberately not in this file
yet (no ``time_entries`` table, no ``actual_hours``).

Everything is gated: ``everhour_enabled`` AND ``everhour_mirror_enabled`` AND a
present API key AND the task's client being Everhour-mapped. Absent any of those
the mirror is a silent no-op — never an error, the GSC/Slack/Asana pattern.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from config import settings
from db.supabase_client import get_supabase
from services import everhour_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — unit-tested
# ---------------------------------------------------------------------------
def should_mirror(task: Optional[dict]) -> bool:
    """Whether a task row is eligible for the metadata-only mirror. Pure.

    Only TOP-LEVEL, client-scoped, not-yet-mirrored, live tasks qualify:
      * a subtask (``parent_task_id`` set) is a checklist marker, not a billing
        target — never mirrored;
      * a clientless (internal-board) task has no Everhour project to map to;
      * an already-mirrored task (``everhour_task_id`` set) is idempotently
        skipped — a task is mirrored exactly once;
      * a trashed task is skipped.
    Note the CLIENT'S project-mapping is checked in the job (a DB read), not
    here — this keeps the create_task hot path free of an extra query."""
    return bool(
        task
        and task.get("id")
        and task.get("client_id")
        and task.get("parent_task_id") is None
        and not task.get("everhour_task_id")
        and not task.get("deleted_at")
    )


def mirror_user_id(everhour_user_id: Optional[Any]) -> Optional[int]:
    """Cast a stored ``everhour_user_id`` (kept as TEXT like every external-id
    column) to the ``int`` Everhour's task-create ``assignees[].userId`` expects
    (plan §12 gotcha #5). Pure. A missing / blank / non-numeric value → None
    (mirror name-only), never a raised error."""
    if everhour_user_id is None:
        return None
    s = str(everhour_user_id).strip()
    if not s:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backfill_scheduled_at(index: int) -> str:
    """Staggered ``scheduled_at`` for the ``index``-th backfilled mirror job, so
    a large cutover backlog's outbound POSTs stay under Everhour's 100-req/10s
    ceiling (plan §11.7). No delay when the queue is otherwise empty."""
    spacing = settings.everhour_backfill_spacing_seconds
    return (datetime.now(timezone.utc) + timedelta(seconds=index * spacing)).isoformat()


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------
def mirror_gate_open() -> bool:
    """The three feature gates the mirror rides on (master flag + write sub-gate
    + a provisioned key). Client project-mapping is checked per task."""
    return bool(
        settings.everhour_enabled
        and settings.everhour_mirror_enabled
        and everhour_service.is_configured()
    )


# ---------------------------------------------------------------------------
# Enqueue (from task_service.create_task) — best-effort, never raises
# ---------------------------------------------------------------------------
def enqueue_mirror(task: Optional[dict]) -> None:
    """Enqueue an ``everhour_mirror`` job for a freshly-created top-level task.

    Called best-effort from ``task_service.create_task``. A no-op unless the
    mirror gate is open and the task is eligible; idempotent (deduped against an
    in-flight mirror job for the same task). Never raises — the mirror must never
    break the board write that hosts it."""
    try:
        if not mirror_gate_open() or not should_mirror(task):
            return
        task_id = task["id"]
        supabase = get_supabase()
        existing = (
            supabase.table("async_jobs")
            .select("id")
            .eq("job_type", "everhour_mirror")
            .eq("entity_id", task_id)
            .in_("status", ["pending", "running"])
            .limit(1)
            .execute()
        ).data
        if existing:
            return
        supabase.table("async_jobs").insert(
            {
                "job_type": "everhour_mirror",
                "entity_id": task_id,
                "payload": {"task_id": task_id, "client_id": task.get("client_id")},
            }
        ).execute()
    except Exception as exc:  # never fail the task creation over the mirror
        logger.warning(
            "everhour_enqueue_mirror_failed",
            extra={"task_id": (task or {}).get("id"), "error": str(exc)},
        )


# ---------------------------------------------------------------------------
# DB reads for the mirror
# ---------------------------------------------------------------------------
def _client_project_id(client_id: str) -> Optional[str]:
    """The client's mapped Everhour project id, or None (not onboarded)."""
    rows = (
        get_supabase()
        .table("clients")
        .select("everhour_project_id")
        .eq("id", client_id)
        .limit(1)
        .execute()
    ).data
    return (rows[0].get("everhour_project_id") or None) if rows else None


def _assignee_everhour_user_id(assignee_id: Optional[str]) -> Optional[str]:
    """The stored Everhour user id for a roster member (the task's assignee), or
    None (unassigned, or the member isn't Everhour-linked)."""
    if not assignee_id:
        return None
    rows = (
        get_supabase()
        .table("asana_team_members")
        .select("everhour_user_id")
        .eq("id", assignee_id)
        .limit(1)
        .execute()
    ).data
    return (rows[0].get("everhour_user_id") or None) if rows else None


# ---------------------------------------------------------------------------
# The mirror itself (async — hits Everhour)
# ---------------------------------------------------------------------------
async def mirror_task(task_id: str) -> dict:
    """Create the Everhour counterpart for one native task and store its id back
    on ``tasks.everhour_task_id`` (+ stamp ``everhour_synced_at``).

    Idempotent + defensive at every step; returns a ``{status, ...}`` dict rather
    than raising for a "nothing to do" condition (an unmapped client, an
    already-mirrored task, a subtask). A genuine Everhour API failure DOES raise,
    so the job row settles ``failed`` and the error is visible."""
    if not mirror_gate_open():
        return {"status": "skipped", "reason": "gate_closed"}

    supabase = get_supabase()
    rows = (
        supabase.table("tasks")
        .select("id, client_id, parent_task_id, name, assignee_id, "
                "everhour_task_id, deleted_at")
        .eq("id", task_id)
        .limit(1)
        .execute()
    ).data
    if not rows:
        return {"status": "skipped", "reason": "task_not_found"}
    task = rows[0]

    if not should_mirror(task):
        # Already mirrored / subtask / clientless / trashed.
        reason = "already_mirrored" if task.get("everhour_task_id") else "ineligible"
        return {"status": "skipped", "reason": reason}

    project_id = _client_project_id(task["client_id"])
    if not project_id:
        return {"status": "skipped", "reason": "no_project"}

    assignee_user_id = mirror_user_id(_assignee_everhour_user_id(task.get("assignee_id")))
    payload = everhour_service.build_task_payload(
        task.get("name") or "", assignee_user_id=assignee_user_id
    )
    created = await everhour_service.create_task(project_id, payload)
    everhour_task_id = (created or {}).get("id")
    if not everhour_task_id:
        # Everhour returned a 2xx without an id — don't stamp a bogus join key.
        logger.warning(
            "everhour_mirror_no_id",
            extra={"task_id": task_id, "project_id": project_id},
        )
        return {"status": "failed", "reason": "no_everhour_task_id"}

    supabase.table("tasks").update(
        {"everhour_task_id": everhour_task_id, "everhour_synced_at": _now()}
    ).eq("id", task_id).execute()
    logger.info(
        "everhour_mirror.mirrored",
        extra={"task_id": task_id, "everhour_task_id": everhour_task_id},
    )
    return {"status": "mirrored", "everhour_task_id": everhour_task_id}


async def run_mirror_job(job: dict) -> None:
    """``async_jobs`` handler for ``job_type='everhour_mirror'``. Settles the row
    with the mirror result; a genuine API error settles it ``failed`` (visible),
    a "nothing to do" outcome settles it ``complete`` with the skip reason."""
    payload = job.get("payload") or {}
    task_id = payload.get("task_id") or job.get("entity_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not task_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing task_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        result = await mirror_task(task_id)
    except Exception as exc:
        logger.warning(
            "everhour_mirror_job_failed", extra={"task_id": task_id, "error": str(exc)}
        )
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()


# ---------------------------------------------------------------------------
# One-time backfill (§3, §8 step 4) — enqueue a mirror per existing open task
# ---------------------------------------------------------------------------
def backfill_mirror(limit: Optional[int] = None) -> dict:
    """Enqueue an ``everhour_mirror`` job for every existing OPEN, top-level,
    not-yet-mirrored task whose client is Everhour-mapped — the cutover sweep so
    staff can start logging against real Everhour tasks. Per-task jobs are
    staggered (``_backfill_scheduled_at``) to respect the API's rate ceiling,
    and deduped against any already-queued mirror. Idempotent: re-running only
    picks up the still-unmirrored tail. Returns ``{status, candidates,
    enqueued}``."""
    if not mirror_gate_open():
        return {"status": "skipped", "reason": "gate_closed", "enqueued": 0}
    supabase = get_supabase()

    mapped = (
        supabase.table("clients")
        .select("id")
        .not_.is_("everhour_project_id", "null")
        .execute()
    ).data or []
    client_ids = [c["id"] for c in mapped if c.get("id")]
    if not client_ids:
        return {"status": "ok", "reason": "no_mapped_clients", "candidates": 0, "enqueued": 0}

    q = (
        supabase.table("tasks")
        .select("id, client_id")
        .in_("client_id", client_ids)
        .is_("parent_task_id", "null")
        .is_("deleted_at", "null")
        .is_("everhour_task_id", "null")
        .eq("completed", False)
        .order("created_at")
    )
    if limit:
        q = q.limit(limit)
    tasks = q.execute().data or []
    if not tasks:
        return {"status": "ok", "candidates": 0, "enqueued": 0}

    # Skip tasks that already have an in-flight mirror job (a fresh create may
    # have enqueued one moments ago).
    in_flight = (
        supabase.table("async_jobs")
        .select("entity_id")
        .eq("job_type", "everhour_mirror")
        .in_("status", ["pending", "running"])
        .execute()
    ).data or []
    queued_ids = {j.get("entity_id") for j in in_flight}

    rows = []
    for t in tasks:
        if t["id"] in queued_ids:
            continue
        rows.append(
            {
                "job_type": "everhour_mirror",
                "entity_id": t["id"],
                "payload": {"task_id": t["id"], "client_id": t.get("client_id")},
                "scheduled_at": _backfill_scheduled_at(len(rows)),
            }
        )
    if rows:
        supabase.table("async_jobs").insert(rows).execute()
    logger.info(
        "everhour_mirror.backfill_enqueued",
        extra={"candidates": len(tasks), "enqueued": len(rows)},
    )
    return {"status": "ok", "candidates": len(tasks), "enqueued": len(rows)}

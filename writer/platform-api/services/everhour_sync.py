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

**Phase 3 (this file, now added): the time pull (read) + rollups.** A daily
whole-team pull of Everhour time records over a rolling re-pull window into the
``time_entries`` ledger (upsert-by-record-id, so an edited entry changes in
place and a delete re-reads as ``time: 0`` — no reconciliation pass), each
record joined to its native ``tasks`` row / client / roster member, then rolled
up into ``tasks.actual_hours`` (a derived column, always recomputed from
``time_entries``). Per-client and per-member rollups are pure helpers consumed
at read time (Phase 4 surfaces) — only ``tasks.actual_hours`` is persisted.

**Gating.** The MIRROR (write) half rides ``everhour_enabled`` AND
``everhour_mirror_enabled`` AND a key AND the task's client being mapped. The
TIME-PULL (read) half rides only ``everhour_enabled`` AND a key —
``everhour_mirror_enabled`` gates outbound writes, not reads, so time can be
pulled even with the mirror turned off during a read-first rollout. Absent any
required gate every path is a silent no-op — never an error, the GSC/Slack/Asana
pattern.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

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


# ===========================================================================
# Phase 3 — time pull (Everhour -> suite, read) + rollups
# ===========================================================================
# Constants -----------------------------------------------------------------
_MAX_SYNC_PAGES = 200        # defensive page ceiling for one team-time pull
_UPSERT_CHUNK = 500          # time_entries rows per upsert batch
_IN_CHUNK = 200              # ids per `.in_()` lookup / recompute read
_READ_PAGE = 1000            # rows per `.range()` page (PostgREST default cap)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — unit-tested
# ---------------------------------------------------------------------------
def _chunks(items: list, size: int) -> Iterable[list]:
    """Yield ``size``-length slices of ``items``. Pure."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _rollup(entries: Iterable[dict], key: str) -> dict[str, int]:
    """Sum ``seconds`` grouped by ``entries[*][key]``, skipping rows whose key
    or seconds is None. Pure — the one groupby the three named rollups share."""
    out: dict[str, int] = {}
    for e in entries or []:
        k = e.get(key)
        secs = e.get("seconds")
        if k is None or secs is None:
            continue
        out[k] = out.get(k, 0) + int(secs)
    return out


def rollup_by_task(entries: Iterable[dict]) -> dict[str, int]:
    """{task_id: total_seconds} — feeds ``tasks.actual_hours``. Ad-hoc time
    (task_id None) is excluded. Pure."""
    return _rollup(entries, "task_id")


def rollup_by_client(entries: Iterable[dict]) -> dict[str, int]:
    """{client_id: total_seconds} — the client "Time" card (read-time, Phase 4).
    Ad-hoc/internal time with no client is excluded. Pure."""
    return _rollup(entries, "client_id")


def rollup_by_member(entries: Iterable[dict]) -> dict[str, int]:
    """{member_id: total_seconds} — the PACE per-member utilization signal
    (read-time, Phase 4). Counts ALL of a member's time, ad-hoc included (a
    person's hours are a person's hours for capacity). Pure."""
    return _rollup(entries, "member_id")


def resolve_time_entries(
    parsed: Iterable[dict],
    *,
    tasks_by_eh: dict[str, dict],
    clients_by_project: dict[str, str],
    members_by_eh: dict[str, str],
    synced_at: str,
) -> list[dict]:
    """Resolve parsed Everhour records (``everhour_service.parse_time_record``
    output) into ``time_entries`` upsert rows. Pure — the join logic, so it's
    exhaustively unit-tested apart from the DB reads that build its maps.

      * ``tasks_by_eh``: {everhour_task_id: {"id": task_id, "client_id": ...}}
        — the authoritative client for a native, mirrored task.
      * ``clients_by_project``: {everhour_project_id: client_id} — the fallback
        client for AD-HOC time whose task isn't a native mirror.
      * ``members_by_eh``: {everhour_user_id: member_id}.

    A record matched to a native task takes that task's client (authoritative,
    even if the task's project mapping differs). An unmatched (ad-hoc) record
    takes the client of its Everhour project, or None (internal/overhead time —
    kept for member utilization, excluded from client rollups). ``member_id``
    is None when the Everhour user isn't roster-linked."""
    rows: list[dict] = []
    for p in parsed:
        eh_task = p.get("everhour_task_id")
        match = tasks_by_eh.get(eh_task) if eh_task else None
        if match:
            task_id = match.get("id")
            client_id = match.get("client_id")
        else:
            task_id = None
            client_id = clients_by_project.get(p.get("everhour_project_id"))
        rows.append(
            {
                "everhour_record_id": p["everhour_record_id"],
                "client_id": client_id,
                "member_id": members_by_eh.get(p.get("everhour_user_id")),
                "task_id": task_id,
                "everhour_task_id": eh_task,
                "entry_date": p["entry_date"],
                "seconds": int(p["seconds"]),
                "billable": p.get("billable"),
                "comment": p.get("comment"),
                "synced_at": synced_at,
            }
        )
    return rows


def sync_window(today: date, repull_days: int) -> tuple[str, str]:
    """The ``[from, to]`` date strings for the rolling re-pull (staff edit past
    entries, so the pull always re-checks a trailing window). Pure."""
    start = today - timedelta(days=max(0, int(repull_days)))
    return start.isoformat(), today.isoformat()


# ---------------------------------------------------------------------------
# Gating (read half — everhour_mirror_enabled does NOT gate reads)
# ---------------------------------------------------------------------------
def sync_gate_open() -> bool:
    """The time-pull's two gates: the master flag + a provisioned key. Unlike
    the mirror, it does NOT require ``everhour_mirror_enabled`` (that sub-gate is
    for outbound writes) — reads run even during a read-first rollout."""
    return bool(settings.everhour_enabled and everhour_service.is_configured())


# ---------------------------------------------------------------------------
# Enqueue (scheduler due-check + manual "Sync now") — one whole-team job
# ---------------------------------------------------------------------------
def enqueue_everhour_sync() -> dict:
    """Enqueue one ``everhour_sync`` job (a whole-team time pull, per decision
    #4/#7 — not per client), deduped against an in-flight sync. Shared by the
    daily scheduler due-check and the manual "Sync now" endpoint. Returns
    ``{status: queued|skipped, ...}``; never raises for a "nothing to do"
    outcome (gate closed / already queued)."""
    if not sync_gate_open():
        return {"status": "skipped", "reason": "gate_closed"}
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "everhour_sync")
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    ).data
    if existing:
        return {"status": "skipped", "reason": "already_queued"}
    row = (
        supabase.table("async_jobs")
        .insert({"job_type": "everhour_sync", "payload": {}})
        .execute()
    ).data
    job_id = row[0].get("id") if row else None
    return {"status": "queued", "job_id": job_id}


def enqueue_due_everhour_sync() -> int:
    """Daily scheduler step: enqueue the whole-team time pull once a day. The
    daily block already fires once per day (its durable marker) and this dedupes
    against an in-flight sync, so no separate date marker is needed. No-op while
    ``everhour_enabled`` is off. Returns 1 if a job was queued, else 0."""
    return 1 if enqueue_everhour_sync().get("status") == "queued" else 0


# ---------------------------------------------------------------------------
# DB reads for the sync
# ---------------------------------------------------------------------------
async def _pull_time_records(date_from: str, date_to: str) -> list[dict]:
    """All team time records over ``[date_from, date_to]``, paged. Bounded by
    ``_MAX_SYNC_PAGES`` so a misbehaving pager can't loop forever."""
    limit = settings.everhour_sync_page_limit
    page = 1
    out: list[dict] = []
    for _ in range(_MAX_SYNC_PAGES):
        batch = await everhour_service.list_team_time(
            date_from, date_to, page=page, limit=limit
        )
        out.extend(batch or [])
        nxt = everhour_service.next_page(page, len(batch or []), limit)
        if nxt is None:
            break
        page = nxt
    return out


def _resolve_maps(parsed: list[dict]) -> tuple[dict, dict, dict]:
    """Build the three join maps ``resolve_time_entries`` needs, from the ids
    actually present in this batch (chunked ``.in_()`` reads)."""
    supabase = get_supabase()
    eh_task_ids = sorted({p["everhour_task_id"] for p in parsed if p.get("everhour_task_id")})
    project_ids = sorted({p["everhour_project_id"] for p in parsed if p.get("everhour_project_id")})
    user_ids = sorted({p["everhour_user_id"] for p in parsed if p.get("everhour_user_id")})

    tasks_by_eh: dict[str, dict] = {}
    for chunk in _chunks(eh_task_ids, _IN_CHUNK):
        rows = (
            supabase.table("tasks")
            .select("id, client_id, everhour_task_id")
            .in_("everhour_task_id", chunk)
            .execute()
        ).data or []
        for r in rows:
            if r.get("everhour_task_id"):
                tasks_by_eh[r["everhour_task_id"]] = {
                    "id": r["id"],
                    "client_id": r.get("client_id"),
                }

    clients_by_project: dict[str, str] = {}
    for chunk in _chunks(project_ids, _IN_CHUNK):
        rows = (
            supabase.table("clients")
            .select("id, everhour_project_id")
            .in_("everhour_project_id", chunk)
            .execute()
        ).data or []
        for r in rows:
            if r.get("everhour_project_id"):
                clients_by_project[r["everhour_project_id"]] = r["id"]

    members_by_eh: dict[str, str] = {}
    for chunk in _chunks(user_ids, _IN_CHUNK):
        rows = (
            supabase.table("asana_team_members")
            .select("id, everhour_user_id")
            .in_("everhour_user_id", chunk)
            .execute()
        ).data or []
        for r in rows:
            if r.get("everhour_user_id"):
                members_by_eh[r["everhour_user_id"]] = r["id"]

    return tasks_by_eh, clients_by_project, members_by_eh


def _upsert_entries(rows: list[dict]) -> None:
    """Upsert time_entries by ``everhour_record_id`` (chunked). An edited entry
    changes in place; a deleted entry (Everhour sends ``time: 0``) zeroes its
    contribution to every rollup."""
    supabase = get_supabase()
    for chunk in _chunks(rows, _UPSERT_CHUNK):
        supabase.table("time_entries").upsert(
            chunk, on_conflict="everhour_record_id"
        ).execute()


def _entries_for_tasks(task_ids: list[str]) -> list[dict]:
    """Read EVERY ``time_entries`` row for the given tasks (across all windows,
    paged) so ``actual_hours`` is the complete sum, not just this window's."""
    supabase = get_supabase()
    out: list[dict] = []
    for chunk in _chunks(task_ids, _IN_CHUNK):
        offset = 0
        while True:
            rows = (
                supabase.table("time_entries")
                .select("task_id, seconds")
                .in_("task_id", chunk)
                # A total order is REQUIRED for stable paging: `.range()` is
                # LIMIT/OFFSET, which has no guaranteed row order without an
                # ORDER BY, so two successive pages could overlap or skip rows
                # (double-counting/dropping seconds) — worse under a concurrent
                # upsert from the sync. `everhour_record_id` is UNIQUE.
                .order("everhour_record_id")
                .range(offset, offset + _READ_PAGE - 1)
                .execute()
            ).data or []
            out.extend(rows)
            if len(rows) < _READ_PAGE:
                break
            offset += _READ_PAGE
    return out


def _recompute_actual_hours(task_ids: set[str]) -> int:
    """Recompute ``tasks.actual_hours`` from ``time_entries`` for the tasks
    touched this sync (idempotent — a full re-sum, never a delta). Returns the
    number of tasks updated. A task whose entries all went to zero is written to
    0.0 (not left stale)."""
    ids = [t for t in task_ids if t]
    if not ids:
        return 0
    sums = rollup_by_task(_entries_for_tasks(ids))
    supabase = get_supabase()
    updated = 0
    for tid in ids:
        hours = everhour_service.seconds_to_hours(sums.get(tid, 0)) or 0.0
        supabase.table("tasks").update({"actual_hours": hours}).eq("id", tid).execute()
        updated += 1
    return updated


# ---------------------------------------------------------------------------
# The sync itself (async — hits Everhour)
# ---------------------------------------------------------------------------
async def run_everhour_sync() -> dict:
    """Pull the team's Everhour time over the rolling window, upsert
    ``time_entries``, and recompute ``tasks.actual_hours`` for every touched
    task. Returns a ``{status, ...}`` summary. Gated on ``everhour_enabled`` +
    a key (NOT the mirror sub-gate). A genuine Everhour/API error propagates so
    the job settles ``failed`` and is visible; a "nothing to pull" outcome is a
    clean ``ok`` with zero counts."""
    if not sync_gate_open():
        return {"status": "skipped", "reason": "gate_closed"}

    date_from, date_to = sync_window(
        datetime.now(timezone.utc).date(), settings.everhour_sync_repull_days
    )
    raw = await _pull_time_records(date_from, date_to)
    parsed = [everhour_service.parse_time_record(r) for r in raw]
    parsed = [p for p in parsed if everhour_service.is_valid_time_record(p)]
    if not parsed:
        return {
            "status": "ok",
            "window": [date_from, date_to],
            "records": 0,
            "upserted": 0,
            "tasks_updated": 0,
        }

    tasks_by_eh, clients_by_project, members_by_eh = _resolve_maps(parsed)
    rows = resolve_time_entries(
        parsed,
        tasks_by_eh=tasks_by_eh,
        clients_by_project=clients_by_project,
        members_by_eh=members_by_eh,
        synced_at=_now(),
    )
    _upsert_entries(rows)
    affected = {r["task_id"] for r in rows if r["task_id"]}
    tasks_updated = _recompute_actual_hours(affected)
    logger.info(
        "everhour_sync.completed",
        extra={
            "window": [date_from, date_to],
            "records": len(parsed),
            "upserted": len(rows),
            "tasks_updated": tasks_updated,
        },
    )
    return {
        "status": "ok",
        "window": [date_from, date_to],
        "records": len(parsed),
        "upserted": len(rows),
        "tasks_updated": tasks_updated,
    }


async def run_everhour_sync_job(job: dict) -> None:
    """``async_jobs`` handler for ``job_type='everhour_sync'``. Settles the row
    with the sync summary; a genuine API error settles it ``failed`` (visible) —
    a 403 (revoked key / permission) surfaces there rather than being retried
    into the same failure."""
    job_id = job["id"]
    supabase = get_supabase()
    try:
        result = await run_everhour_sync()
    except Exception as exc:
        logger.warning("everhour_sync_job_failed", extra={"error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()


# ===========================================================================
# Phase 4 — read surfaces (client "Time" card, PACE per-member utilization)
# ===========================================================================
# These are READ-time rollups over the ``time_entries`` ledger the daily sync
# maintains — nothing is persisted here (only ``tasks.actual_hours`` is stored,
# by the sync). The pure assemblers are unit-tested; the thin windowed reads
# are mocked. Every entry point is a silent no-op when Everhour isn't enabled,
# so the consuming surfaces stay dark during a read-first rollout.


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — unit-tested
# ---------------------------------------------------------------------------
def billable_split(entries: Iterable[dict]) -> dict[str, int]:
    """Sum ``seconds`` into billable / non-billable / unknown buckets by each
    row's ``billable`` (True / False / None — None = the pull didn't carry
    billing data, per plan §11.5). Pure. v1 surfaces the split for legibility;
    nothing yet weights margin on it (owner ruling: capture, don't split)."""
    out = {"billable": 0, "non_billable": 0, "unknown": 0}
    for e in entries or []:
        secs = e.get("seconds")
        if secs is None:
            continue
        b = e.get("billable")
        key = "billable" if b is True else "non_billable" if b is False else "unknown"
        out[key] += int(secs)
    return out


def build_client_time(
    entries: Iterable[dict],
    *,
    member_names: dict[str, str],
    days: int,
) -> dict:
    """Assemble the client "Time" card summary from that client's
    ``time_entries`` rows over the window. Pure — the DB read that produces
    ``entries`` and ``member_names`` is the only impure part.

    Returns total logged hours, the billable/non-billable/unknown split (all in
    hours), and a per-member breakdown (descending, named where the member is
    roster-linked)."""
    entries = list(entries or [])
    total_secs = sum(int(e["seconds"]) for e in entries if e.get("seconds") is not None)
    split = billable_split(entries)
    by_member_secs = rollup_by_member(entries)
    members = sorted(
        (
            {
                "member_id": mid,
                "name": member_names.get(mid),
                "hours": everhour_service.seconds_to_hours(secs) or 0.0,
            }
            for mid, secs in by_member_secs.items()
        ),
        key=lambda m: m["hours"],
        reverse=True,
    )
    return {
        "window_days": days,
        "total_hours": everhour_service.seconds_to_hours(total_secs) or 0.0,
        "billable_hours": everhour_service.seconds_to_hours(split["billable"]) or 0.0,
        "non_billable_hours": everhour_service.seconds_to_hours(split["non_billable"]) or 0.0,
        "unknown_hours": everhour_service.seconds_to_hours(split["unknown"]) or 0.0,
        "members": members,
    }


def utilization_hours(secs_by_member: dict[str, int]) -> dict[str, float]:
    """{member_id: hours} from {member_id: seconds}. Pure — the read-time
    conversion the PACE workload attach + the Team-page column consume."""
    return {
        mid: (everhour_service.seconds_to_hours(secs) or 0.0)
        for mid, secs in (secs_by_member or {}).items()
    }


# ---------------------------------------------------------------------------
# Windowed time_entries reads (impure — paged)
# ---------------------------------------------------------------------------
def _read_entries(
    *,
    date_from: str,
    date_to: str,
    client_id: Optional[str] = None,
    cols: str = "member_id, seconds, billable",
) -> list[dict]:
    """Read ``time_entries`` rows over ``[date_from, date_to]`` (optionally for
    one client), paged. The window keeps these reads bounded even on a busy
    team. Callers pass the narrowest ``cols`` they need (the default is the
    per-member/billable rollup set)."""
    supabase = get_supabase()
    out: list[dict] = []
    offset = 0
    while True:
        q = (
            supabase.table("time_entries")
            .select(cols)
            .gte("entry_date", date_from)
            .lte("entry_date", date_to)
        )
        if client_id is not None:
            q = q.eq("client_id", client_id)
        # Stable paging needs a total order — `.range()` is LIMIT/OFFSET, so
        # without an ORDER BY two pages can overlap/skip rows. `everhour_record_id`
        # is UNIQUE.
        rows = (
            q.order("everhour_record_id")
            .range(offset, offset + _READ_PAGE - 1)
            .execute()
        ).data or []
        out.extend(rows)
        if len(rows) < _READ_PAGE:
            break
        offset += _READ_PAGE
    return out


def _member_names(member_ids: Iterable[str]) -> dict[str, str]:
    """{member_id: name} for the given roster members (chunked)."""
    ids = sorted({m for m in member_ids if m})
    names: dict[str, str] = {}
    supabase = get_supabase()
    for chunk in _chunks(ids, _IN_CHUNK):
        rows = (
            supabase.table("asana_team_members")
            .select("id, name")
            .in_("id", chunk)
            .execute()
        ).data or []
        for r in rows:
            if r.get("id"):
                names[r["id"]] = r.get("name")
    return names


def _window(days: Optional[int], default: int) -> tuple[str, str, int]:
    """Resolve a lookback ``[from, to]`` (both inclusive) + the effective day
    count for a read surface."""
    n = int(days) if days is not None else int(default)
    n = max(0, n)
    today = datetime.now(timezone.utc).date()
    return (today - timedelta(days=n)).isoformat(), today.isoformat(), n


# ---------------------------------------------------------------------------
# Read entry points (impure orchestration)
# ---------------------------------------------------------------------------
def client_time_summary(client_id: str, days: Optional[int] = None) -> dict:
    """The client "Time" card read: logged hours over the window, the
    billable split, and a per-member breakdown. Gated on ``everhour_enabled``
    — returns ``{available: False}`` (never an error) when the integration is
    off, so the card renders a dark/empty state rather than a 500."""
    if not sync_gate_open():
        return {"available": False, "reason": "not_enabled"}
    date_from, date_to, n = _window(days, settings.everhour_client_time_window_days)
    entries = _read_entries(date_from=date_from, date_to=date_to, client_id=client_id)
    names = _member_names(e.get("member_id") for e in entries)
    summary = build_client_time(entries, member_names=names, days=n)
    return {"available": True, **summary}


def member_utilization(days: Optional[int] = None) -> dict[str, float]:
    """{member_id: hours} logged team-wide over the window (ALL of a member's
    time, ad-hoc/internal included — a person's hours are their hours for
    capacity, owner ruling). Empty dict when Everhour is off. Consumed by the
    PACE workload attach + the Team-page utilization column."""
    if not sync_gate_open():
        return {}
    date_from, date_to, _ = _window(days, settings.everhour_utilization_window_days)
    entries = _read_entries(
        date_from=date_from, date_to=date_to, cols="member_id, seconds"
    )
    return utilization_hours(rollup_by_member(entries))


def client_month_actual_hours(client_id: str, month: date) -> float:
    """Total hours logged against a client within ``month``'s calendar month —
    the Recipe Engine's measured-labor input. 0.0 when Everhour is off (so the
    consumer degrades to its estimate-only behaviour). Excludes ad-hoc/internal
    time with no client (those rows carry a null ``client_id`` and are filtered
    by the client-scoped read)."""
    if not sync_gate_open():
        return 0.0
    first = month.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    last = nxt - timedelta(days=1)
    entries = _read_entries(
        date_from=first.isoformat(),
        date_to=last.isoformat(),
        client_id=client_id,
        cols="seconds, client_id",
    )
    total = sum(int(e["seconds"]) for e in entries if e.get("seconds") is not None)
    return everhour_service.seconds_to_hours(total) or 0.0

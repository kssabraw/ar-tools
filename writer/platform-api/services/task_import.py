"""Native task manager — Asana migration importer (PRD §15, Phase 5).

One admin-triggered ``task_import_asana`` job snapshots every mapped client's
Asana project into the native tables: sections (month/custom by name), tasks
(assignee gid + cached name, Status custom field → ``task_statuses`` via the
§19.2 variant map, Service Type → category, effort number field → est_hours,
completed state), and subtasks. Idempotent end-to-end: every imported row
carries ``source='asana_import'`` + ``source_ref=<asana gid>``, so re-runs
skip what's already here (and a task completed since the last run is NOT
re-created — the partial unique index keeps completed keys).

After the tasks land, ``derive_library_checklists`` seeds each Task Library
entry's default subtask checklist from the newest imported task of that name
(only when the library task has no checklist yet) — the practical §15.4:
instantiating Asana task templates just to read their subtasks would create
junk tasks in live Asana, and the imported real tasks carry the same
checklists.

Comments/stories are intentionally skipped (PRD §15.5 marks them optional).
"""

from __future__ import annotations

import logging
from typing import Optional

from db.supabase_client import get_supabase
from services import asana_service, task_service

logger = logging.getLogger(__name__)

# §19.2: the teams' Status variants across projects → the canonical seed keys.
STATUS_VARIANTS: dict[str, str] = {
    "not started": "not_started",
    "in progress": "in_progress",
    "ongoing": "in_progress",
    "blocked": "blocked",
    "on hold": "blocked",
    "in qa": "in_qa",
    "qa": "in_qa",
    "quality assurance": "in_qa",
    "in review": "in_review",
    "sent for approval": "in_review",
    "for revision": "in_review",
    "needs revisions": "in_review",
    "sent to client": "sent_to_client",
    "with client": "sent_to_client",
    "approved to send to client": "sent_to_client",
    "client approved": "client_approved",
    "approved": "client_approved",
    "waiting on url to go live": "client_approved",
    "complete": "complete",
    "completed": "complete",
    "done": "complete",
}


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def map_status(name: Optional[str], initial_key: Optional[str]) -> Optional[str]:
    """An Asana Status enum name → our status key (unknown/blank → initial)."""
    if name and name.strip().casefold() in STATUS_VARIANTS:
        return STATUS_VARIANTS[name.strip().casefold()]
    return initial_key


def extract_enum_field(task: dict, field_name: str) -> Optional[str]:
    """The display value of a task's enum custom field, matched by name."""
    target = field_name.strip().casefold()
    for cf in task.get("custom_fields") or []:
        if (cf.get("name") or "").strip().casefold() == target:
            enum_val = (cf.get("enum_value") or {}).get("name")
            return enum_val or cf.get("display_value") or None
    return None


def section_name_of(task: dict, project_gid: str) -> Optional[str]:
    """The task's section name within the imported project (memberships may
    span projects)."""
    for m in task.get("memberships") or []:
        proj = (m.get("project") or {}).get("gid")
        if proj and proj != project_gid:
            continue
        name = ((m.get("section") or {}).get("name") or "").strip()
        if name:
            return name
    return None


def month_period(section_name: str) -> Optional[str]:
    """'July 2026' → '2026-07-01' (None for non-month sections)."""
    if not asana_service.is_month_label(section_name):
        return None
    month, year = section_name.strip().split()
    idx = asana_service._MONTH_INDEX[month.casefold()]  # noqa: SLF001 — shared module constant
    return f"{int(year):04d}-{idx:02d}-01"


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------
def _ensure_section(client_id: str, name: str) -> str:
    supabase = get_supabase()
    existing = (
        supabase.table("task_sections")
        .select("id")
        .eq("client_id", client_id)
        .ilike("name", name)
        .limit(1)
        .execute()
    ).data
    if existing:
        return existing[0]["id"]
    period = month_period(name)
    row = {
        "client_id": client_id,
        "name": name,
        "kind": "month" if period else "custom",
        "period_month": period,
    }
    try:
        return supabase.table("task_sections").insert(row).execute().data[0]["id"]
    except Exception:
        rows = (
            supabase.table("task_sections")
            .select("id")
            .eq("client_id", client_id)
            .ilike("name", name)
            .limit(1)
            .execute()
        ).data
        if rows:
            return rows[0]["id"]
        raise


async def import_client(client_id: str, project_gid: str, *, statuses: list[dict], categories: list[dict], effort_field_name: str) -> dict:
    """Import one client's project. Returns per-client counts."""
    initial = task_service.initial_status_key(statuses)
    counts = {"sections": 0, "tasks": 0, "subtasks": 0, "existing": 0, "errors": 0}

    sections = await asana_service.list_sections(project_gid)
    section_ids: dict[str, str] = {}
    for s in sections:
        name = (s.get("name") or "").strip()
        if not name or name.casefold() == "untitled section":
            continue
        section_ids[name.casefold()] = _ensure_section(client_id, name)
        counts["sections"] += 1

    tasks = await asana_service.list_project_tasks_full(project_gid)
    supabase = get_supabase()
    for t in tasks:
        try:
            name = (t.get("name") or "").strip()
            if not name:
                continue
            sec_name = section_name_of(t, project_gid)
            created = task_service.create_task(
                name,
                client_id=client_id,
                section_id=section_ids.get((sec_name or "").casefold()),
                assignee_gid=((t.get("assignee") or {}).get("gid")),
                assignee_name=((t.get("assignee") or {}).get("name")),
                status_key=map_status(extract_enum_field(t, "Status"), initial),
                category=task_service.resolve_category_key(
                    extract_enum_field(t, "Service Type"), categories
                ),
                due_date=t.get("due_on"),
                est_hours=(
                    asana_service.extract_number_field_by_name(t, effort_field_name)
                    if effort_field_name
                    else None
                ),
                source="asana_import",
                source_ref=t.get("gid"),
            )
            if created.get("_existing"):
                counts["existing"] += 1
                continue
            counts["tasks"] += 1
            if t.get("completed"):
                task_service.complete_task(created["id"])
            if t.get("num_subtasks"):
                subs = await asana_service.list_task_subtasks(t["gid"])
                rows = [
                    {
                        "name": (s.get("name") or "").strip(),
                        "client_id": client_id,
                        "section_id": created.get("section_id"),
                        "parent_task_id": created["id"],
                        "assignee_gid": ((s.get("assignee") or {}).get("gid")),
                        "assignee_name": ((s.get("assignee") or {}).get("name")),
                        "status_key": initial,
                        "due_date": s.get("due_on"),
                        "completed": bool(s.get("completed")),
                        "sort_order": i,
                        "source": "asana_import",
                        "source_ref": s.get("gid"),
                    }
                    for i, s in enumerate(subs)
                    if (s.get("name") or "").strip()
                ]
                if rows:
                    supabase.table("tasks").insert(rows).execute()
                    counts["subtasks"] += len(rows)
        except Exception as exc:  # one bad task never aborts the client
            counts["errors"] += 1
            logger.warning(
                "task_import_task_failed",
                extra={"client_id": client_id, "task": t.get("gid"), "error": str(exc)},
            )
    return counts


def derive_library_checklists() -> int:
    """Seed each active Task Library entry's default checklist from the newest
    imported task of that name — only when the library entry has none yet
    (a hand-authored checklist is never overwritten). Returns how many library
    tasks gained a checklist."""
    supabase = get_supabase()
    library = (
        supabase.table("asana_task_library").select("name").eq("active", True).execute()
    ).data or []
    existing = (
        supabase.table("task_library_subtasks").select("library_name").execute()
    ).data or []
    have = {(r.get("library_name") or "").strip().casefold() for r in existing}

    seeded = 0
    for lib in library:
        name = (lib.get("name") or "").strip()
        if not name or name.casefold() in have:
            continue
        parents = (
            supabase.table("tasks")
            .select("id")
            .eq("source", "asana_import")
            .ilike("name", name)
            .is_("parent_task_id", "null")
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        ).data or []
        for p in parents:
            subs = (
                supabase.table("tasks")
                .select("name, sort_order")
                .eq("parent_task_id", p["id"])
                .order("sort_order")
                .execute()
            ).data or []
            if not subs:
                continue
            supabase.table("task_library_subtasks").insert(
                [
                    {"library_name": name, "name": s["name"], "sort_order": i}
                    for i, s in enumerate(subs)
                ]
            ).execute()
            seeded += 1
            break
    if seeded:
        logger.info("task_import.checklists_derived", extra={"seeded": seeded})
    return seeded


async def run_import() -> dict:
    """Import every mapped client. Returns the aggregate summary."""
    if not asana_service.is_configured():
        return {"status": "skipped", "reason": "asana_not_configured"}
    from config import settings

    mappings = (
        get_supabase().table("asana_client_projects").select("client_id, project_gid").execute()
    ).data or []
    statuses = task_service.get_statuses()
    categories = task_service.get_categories()

    totals = {"clients": 0, "sections": 0, "tasks": 0, "subtasks": 0, "existing": 0, "errors": 0}
    for m in mappings:
        try:
            counts = await import_client(
                m["client_id"],
                m["project_gid"],
                statuses=statuses,
                categories=categories,
                effort_field_name=settings.asana_effort_field_name,
            )
            totals["clients"] += 1
            for k in ("sections", "tasks", "subtasks", "existing", "errors"):
                totals[k] += counts[k]
        except Exception as exc:  # one bad project never aborts the run
            totals["errors"] += 1
            logger.warning(
                "task_import_client_failed",
                extra={"client_id": m.get("client_id"), "error": str(exc)},
            )
    totals["checklists_seeded"] = derive_library_checklists()
    totals["status"] = "complete"
    return totals


# ---------------------------------------------------------------------------
# Job enqueue + handler (async_jobs type 'task_import_asana')
# ---------------------------------------------------------------------------
def enqueue_import() -> dict:
    """Enqueue the import (deduped against an in-flight one)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "task_import_asana")
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return {"status": "already_running", "job_id": existing.data[0]["id"]}
    job = (
        supabase.table("async_jobs")
        .insert({"job_type": "task_import_asana", "payload": {}})
        .execute()
    ).data[0]
    return {"status": "queued", "job_id": job["id"]}


def latest_import_job() -> Optional[dict]:
    rows = (
        get_supabase()
        .table("async_jobs")
        .select("id, status, result, error, created_at, completed_at")
        .eq("job_type", "task_import_asana")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    return rows[0] if rows else None


async def run_import_job(job: dict) -> None:
    """async_jobs handler for job_type='task_import_asana'."""
    supabase = get_supabase()
    try:
        result = await run_import()
    except Exception as exc:
        logger.warning("task_import_job_failed", extra={"error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job["id"]).execute()

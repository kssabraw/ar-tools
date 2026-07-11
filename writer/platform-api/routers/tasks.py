"""Native task manager — Phase 0 API (docs/modules/in-app-task-manager-prd-v1_0.md §8).

Config (statuses / categories — admin), Task Library subtask checklists,
on-demand monthly generation, and the native workload read. These only touch
the new ``task_*`` tables, so they're safe while the team still executes in
Asana (the ``native_tasks_enabled`` flag gates the *scheduled* paths, not
these). Task CRUD / board endpoints land with the Phase 1 UI.
"""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from db.supabase_client import get_supabase
from middleware.auth import require_admin, require_auth
from models.tasks import (
    LibraryChecklist,
    TaskCategoryItem,
    TaskCategoryReplaceRequest,
    TaskGenerateMonthRequest,
    TaskGenerateMonthResponse,
    TaskStatusItem,
    TaskStatusReplaceRequest,
)
from services import task_monthly, task_service, task_workload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


# ---------------------------------------------------------------------------
# Workflow config: statuses + categories (admin mutations)
# ---------------------------------------------------------------------------
@router.get("/tasks/statuses", response_model=list[TaskStatusItem])
async def list_statuses(auth: dict = Depends(require_auth)) -> list[TaskStatusItem]:
    return [TaskStatusItem(**s) for s in task_service.get_statuses(active_only=False)]


@router.put("/tasks/statuses", response_model=list[TaskStatusItem])
async def replace_statuses(
    body: TaskStatusReplaceRequest,
    auth: dict = Depends(require_admin),
) -> list[TaskStatusItem]:
    """Replace the status set. Upsert-and-deactivate, never delete — tasks FK
    these keys, so a removed status is deactivated instead."""
    rows = []
    seen: set[str] = set()
    for idx, item in enumerate(body.items):
        key = item.key.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "key": key,
                "label": item.label.strip() or key,
                "color": item.color,
                "category": item.category,
                "is_initial": item.is_initial,
                "is_done": item.is_done,
                "sort_order": idx,
                "active": item.active,
            }
        )
    if not rows:
        raise HTTPException(status_code=400, detail="empty_status_set")
    supabase = get_supabase()
    try:
        supabase.table("task_statuses").upsert(rows).execute()
        existing = supabase.table("task_statuses").select("key").execute().data or []
        stale = [r["key"] for r in existing if r["key"] not in seen]
        if stale:
            supabase.table("task_statuses").update({"active": False}).in_("key", stale).execute()
    except Exception as exc:
        logger.error("task_statuses_replace_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return await list_statuses(auth)


@router.get("/tasks/categories", response_model=list[TaskCategoryItem])
async def list_categories(auth: dict = Depends(require_auth)) -> list[TaskCategoryItem]:
    return [TaskCategoryItem(**c) for c in task_service.get_categories(active_only=False)]


@router.put("/tasks/categories", response_model=list[TaskCategoryItem])
async def replace_categories(
    body: TaskCategoryReplaceRequest,
    auth: dict = Depends(require_admin),
) -> list[TaskCategoryItem]:
    """Replace the Service Type set (upsert-and-deactivate, same as statuses)."""
    rows = []
    seen: set[str] = set()
    for idx, item in enumerate(body.items):
        key = item.key.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "key": key,
                "label": item.label.strip() or key,
                "color": item.color,
                "sort_order": idx,
                "active": item.active,
            }
        )
    if not rows:
        raise HTTPException(status_code=400, detail="empty_category_set")
    supabase = get_supabase()
    try:
        supabase.table("task_categories").upsert(rows).execute()
        existing = supabase.table("task_categories").select("key").execute().data or []
        stale = [r["key"] for r in existing if r["key"] not in seen]
        if stale:
            supabase.table("task_categories").update({"active": False}).in_("key", stale).execute()
    except Exception as exc:
        logger.error("task_categories_replace_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return await list_categories(auth)


# ---------------------------------------------------------------------------
# Task Library subtask checklists (PRD §6.9)
# ---------------------------------------------------------------------------
@router.get("/tasks/library-checklists", response_model=list[LibraryChecklist])
async def list_library_checklists(auth: dict = Depends(require_auth)) -> list[LibraryChecklist]:
    rows = (
        get_supabase()
        .table("task_library_subtasks")
        .select("library_name, name, sort_order")
        .order("sort_order")
        .execute()
    ).data or []
    by_name: dict[str, LibraryChecklist] = {}
    for r in rows:
        key = (r.get("library_name") or "").strip().casefold()
        if not key:
            continue
        if key not in by_name:
            by_name[key] = LibraryChecklist(library_name=r["library_name"].strip(), subtasks=[])
        by_name[key].subtasks.append(r["name"])
    return list(by_name.values())


@router.put("/tasks/library-checklists", response_model=LibraryChecklist)
async def replace_library_checklist(
    body: LibraryChecklist,
    auth: dict = Depends(require_auth),
) -> LibraryChecklist:
    """Replace ONE library task's default subtask checklist (matched by name,
    case-insensitive). An empty list clears it."""
    name = body.library_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing_library_name")
    supabase = get_supabase()
    try:
        supabase.table("task_library_subtasks").delete().ilike("library_name", name).execute()
        rows = [
            {"library_name": name, "name": s.strip(), "sort_order": i}
            for i, s in enumerate(body.subtasks)
            if s and s.strip()
        ]
        if rows:
            supabase.table("task_library_subtasks").insert(rows).execute()
    except Exception as exc:
        logger.error("task_checklist_replace_failed", extra={"library": name, "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return LibraryChecklist(library_name=name, subtasks=[r["name"] for r in rows])


# ---------------------------------------------------------------------------
# Monthly generation (on-demand; idempotent per task)
# ---------------------------------------------------------------------------
def _parse_target_month(raw: str | None) -> date:
    if not raw:
        return date.today().replace(day=1)
    if len(raw) == 7:  # "YYYY-MM"
        raw = f"{raw}-01"
    return date.fromisoformat(raw).replace(day=1)


@router.post(
    "/clients/{client_id}/tasks/generate-month",
    response_model=TaskGenerateMonthResponse,
)
async def generate_month(
    client_id: UUID,
    body: TaskGenerateMonthRequest,
    auth: dict = Depends(require_auth),
) -> TaskGenerateMonthResponse:
    """Create the target month's native section + tasks now (idempotent per
    task — a re-run fills gaps only). Synchronous: one client, DB inserts."""
    try:
        target = _parse_target_month(body.month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_month") from exc
    try:
        result = task_monthly.generate_month_for_client(str(client_id), target)
    except Exception as exc:
        logger.error("task_generate_month_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return TaskGenerateMonthResponse(
        status=result.get("status", "skipped"),
        section=result.get("section", ""),
        created=result.get("created", 0),
        existing=result.get("existing", 0),
        reason=result.get("reason"),
        errors=result.get("errors", []),
    )


# ---------------------------------------------------------------------------
# Native workload read (verification surface before the flag flips; the
# Workload page keeps calling /asana/workload, which follows the flag)
# ---------------------------------------------------------------------------
@router.get("/tasks/workload")
async def native_workload(auth: dict = Depends(require_auth)) -> dict:
    try:
        return task_workload.build_team_workload()
    except Exception as exc:
        logger.error("task_workload_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc

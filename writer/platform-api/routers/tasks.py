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

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_admin, require_auth
from models.tasks import (
    LibraryChecklist,
    TaskCategoryItem,
    TaskCategoryReplaceRequest,
    TaskCommentRequest,
    TaskCreateRequest,
    TaskDuplicateRequest,
    TaskGenerateMonthRequest,
    TaskGenerateMonthResponse,
    TaskReorderRequest,
    TaskSectionCreateRequest,
    TaskSectionUpdateRequest,
    TaskStatusItem,
    TaskStatusReplaceRequest,
    TaskUpdateRequest,
    TaskViewRequest,
)
from services import task_collab, task_monthly, task_service, task_workload

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
# Member competencies (role/skill matching for placement — PACE v1.3 §4.6)
# ---------------------------------------------------------------------------
class MemberSkillItem(BaseModel):
    category_key: str
    is_primary: bool = False


class MemberSkillsReplaceRequest(BaseModel):
    skills: list[MemberSkillItem]


@router.get("/tasks/member-skills")
async def list_member_skills(auth: dict = Depends(require_auth)) -> dict:
    """All members' category competencies, grouped by member_gid. A member absent
    from the map is a generalist (eligible for any category)."""
    from services import pm_assign

    return pm_assign.list_all_skills()


@router.put("/tasks/member-skills/{member_gid}")
async def set_member_skills(
    member_gid: str,
    body: MemberSkillsReplaceRequest,
    auth: dict = Depends(require_auth),
) -> dict:
    """Replace one member's competency set (which task categories they can do)."""
    from services import pm_assign

    try:
        saved = pm_assign.replace_member_skills(member_gid, [s.model_dump() for s in body.skills])
    except Exception as exc:
        logger.error("member_skills_replace_failed", extra={"member_gid": member_gid, "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"member_gid": member_gid, "skills": saved}


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


# ---------------------------------------------------------------------------
# Board read (Phase 1): a client's sections + live top-level tasks + subtask
# progress in one call — the per-client Tasks page's single data source.
# ---------------------------------------------------------------------------
def _section_sort_key(s: dict) -> tuple:
    # Month sections newest-first (current month leads the board), then
    # backlog/custom in their manual order.
    if s.get("kind") == "month" and s.get("period_month"):
        return (0, "", s["period_month"])
    return (1, s.get("sort_order") or 0, "")


@router.get("/clients/{client_id}/task-board")
async def task_board(client_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    try:
        sections = (
            get_supabase()
            .table("task_sections")
            .select("*")
            .eq("client_id", str(client_id))
            .execute()
        ).data or []
        months = sorted(
            [s for s in sections if s.get("kind") == "month" and s.get("period_month")],
            key=lambda s: s["period_month"],
            reverse=True,
        )
        rest = sorted(
            [s for s in sections if not (s.get("kind") == "month" and s.get("period_month"))],
            key=lambda s: (s.get("sort_order") or 0, s.get("name") or ""),
        )
        tasks = task_service.list_board_tasks(str(client_id))
        progress = task_service.subtask_progress([t["id"] for t in tasks])
        for t in tasks:
            p = progress.get(t["id"]) or {"total": 0, "done": 0}
            t["subtask_total"] = p["total"]
            t["subtask_done"] = p["done"]
        return {"sections": months + rest, "tasks": tasks}
    except Exception as exc:
        logger.error("task_board_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
@router.post("/clients/{client_id}/task-sections")
async def create_section(
    client_id: UUID, body: TaskSectionCreateRequest, auth: dict = Depends(require_auth)
) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing_name")
    if body.kind not in ("month", "backlog", "custom"):
        raise HTTPException(status_code=400, detail="invalid_kind")
    try:
        return (
            get_supabase()
            .table("task_sections")
            .insert(
                {
                    "client_id": str(client_id),
                    "name": name,
                    "kind": body.kind,
                    "period_month": body.period_month,
                }
            )
            .execute()
        ).data[0]
    except Exception as exc:
        if "uq_task_sections_board_name" in str(exc) or "duplicate" in str(exc).lower():
            raise HTTPException(status_code=409, detail="section_exists") from exc
        logger.error("task_section_create_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.patch("/task-sections/{section_id}")
async def update_section(
    section_id: UUID, body: TaskSectionUpdateRequest, auth: dict = Depends(require_auth)
) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = (changes["name"] or "").strip()
        if not changes["name"]:
            raise HTTPException(status_code=400, detail="missing_name")
    if not changes:
        raise HTTPException(status_code=400, detail="no_changes")
    try:
        rows = (
            get_supabase().table("task_sections").update(changes).eq("id", str(section_id)).execute()
        ).data
    except Exception as exc:
        logger.error("task_section_update_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not rows:
        raise HTTPException(status_code=404, detail="section_not_found")
    return rows[0]


@router.delete("/task-sections/{section_id}")
async def delete_section(section_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Delete a section; its tasks stay (section_id → null via FK) so nothing
    is silently lost. 200 + body — the suite convention (FastAPI asserts on
    204 routes that could carry a body)."""
    try:
        get_supabase().table("task_sections").delete().eq("id", str(section_id)).execute()
        return {"deleted": True}
    except Exception as exc:
        logger.error("task_section_delete_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


# ---------------------------------------------------------------------------
# My Tasks (cross-client). Assignees are Asana member gids in v1; the identity
# bridge (asana_team_members.profile_id) auto-resolves the logged-in user to
# their linked member, so a linked person sees their own tasks by default. An
# explicit ?gid= (the "viewing as" picker) always wins — a lead can view
# anyone. Unlinked users fall back to the first member.
# ---------------------------------------------------------------------------
@router.get("/tasks/mine")
async def my_tasks(gid: str | None = None, auth: dict = Depends(require_auth)) -> dict:
    from services.asana_workload import get_team_members

    try:
        members = [
            {"gid": m["gid"], "name": m.get("name") or m["gid"]} for m in get_team_members()
        ]
        valid = {m["gid"] for m in members}
        # The current user's own linked member (identity bridge), if any.
        my_gid = None
        link = (
            get_supabase()
            .table("asana_team_members")
            .select("gid")
            .eq("profile_id", auth["user_id"])
            .limit(1)
            .execute()
        ).data
        if link and link[0]["gid"] in valid:
            my_gid = link[0]["gid"]
        resolved = (
            gid if gid in valid else (my_gid if my_gid else (members[0]["gid"] if members else None))
        )
        if not resolved:
            return {"members": [], "gid": None, "my_gid": my_gid, "buckets": {}}
        rows = (
            get_supabase()
            .table("tasks")
            .select("id, client_id, section_id, name, status_key, category, due_date, est_hours")
            .eq("assignee_gid", resolved)
            .eq("completed", False)
            .is_("deleted_at", "null")
            .is_("parent_task_id", "null")
            .execute()
        ).data or []
        client_ids = sorted({r["client_id"] for r in rows if r.get("client_id")})
        names: dict[str, str] = {}
        if client_ids:
            crows = (
                get_supabase().table("clients").select("id, name").in_("id", client_ids).execute()
            ).data or []
            names = {c["id"]: c.get("name") for c in crows}
        for r in rows:
            r["client_name"] = names.get(r.get("client_id"))
        buckets = task_service.bucket_by_due(rows, date.today())
        return {"members": members, "gid": resolved, "my_gid": my_gid, "buckets": buckets}
    except Exception as exc:
        logger.error("my_tasks_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


# ---------------------------------------------------------------------------
# Mention candidates (static route — must register before /tasks/{task_id})
# ---------------------------------------------------------------------------
@router.get("/tasks/mention-candidates")
async def mention_candidates(auth: dict = Depends(require_auth)) -> list[dict]:
    try:
        return task_collab.mention_candidates()
    except Exception as exc:
        logger.error("mention_candidates_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


# ---------------------------------------------------------------------------
# Asana migration importer (PRD §15) — admin one-shot, idempotent re-runs
# ---------------------------------------------------------------------------
@router.post("/tasks/import/asana")
async def import_asana(auth: dict = Depends(require_admin)) -> dict:
    from services import task_import

    try:
        return task_import.enqueue_import()
    except Exception as exc:
        logger.error("task_import_enqueue_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/tasks/import/asana/status")
async def import_asana_status(auth: dict = Depends(require_auth)) -> dict:
    from services import task_import

    try:
        return task_import.latest_import_job() or {"status": "never_run"}
    except Exception as exc:
        logger.error("task_import_status_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


# ---------------------------------------------------------------------------
# Saved views (PRD §6.7) — static /tasks/views routes, before /tasks/{task_id}
# ---------------------------------------------------------------------------
@router.get("/tasks/views")
async def list_views(auth: dict = Depends(require_auth)) -> list[dict]:
    """The caller's private views + the shared (owner-less) ones."""
    try:
        rows = (
            get_supabase()
            .table("task_saved_views")
            .select("*")
            .or_(f"owner_id.eq.{auth['user_id']},owner_id.is.null")
            .order("name")
            .execute()
        ).data or []
        for r in rows:
            r["shared"] = r.get("owner_id") is None
        return rows
    except Exception as exc:
        logger.error("task_views_list_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/tasks/views")
async def create_view(body: TaskViewRequest, auth: dict = Depends(require_auth)) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="missing_name")
    try:
        row = (
            get_supabase()
            .table("task_saved_views")
            .insert(
                {
                    "owner_id": None if body.shared else auth["user_id"],
                    "name": name,
                    "config": body.config,
                }
            )
            .execute()
        ).data[0]
        row["shared"] = row.get("owner_id") is None
        return row
    except Exception as exc:
        logger.error("task_view_create_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.delete("/tasks/views/{view_id}")
async def delete_view(view_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Delete a view — your own always; shared views need admin."""
    supabase = get_supabase()
    try:
        rows = supabase.table("task_saved_views").select("owner_id").eq("id", str(view_id)).limit(1).execute().data
        if not rows:
            raise HTTPException(status_code=404, detail="view_not_found")
        owner = rows[0].get("owner_id")
        if owner != auth["user_id"] and not (owner is None and auth.get("role") == "admin"):
            raise HTTPException(status_code=403, detail="forbidden")
        supabase.table("task_saved_views").delete().eq("id", str(view_id)).execute()
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("task_view_delete_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


# ---------------------------------------------------------------------------
# Task CRUD (kept AFTER the static /tasks/* routes so those match first)
# ---------------------------------------------------------------------------
@router.post("/tasks")
async def create_task(body: TaskCreateRequest, auth: dict = Depends(require_auth)) -> dict:
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="missing_name")
    try:
        return task_service.create_task(
            body.name,
            client_id=body.client_id,
            section_id=body.section_id,
            parent_task_id=body.parent_task_id,
            description=body.description,
            assignee_gid=body.assignee_gid,
            assignee_name=body.assignee_name,
            status_key=body.status_key,
            category=body.category,
            due_date=body.due_date,
            start_date=body.start_date,
            est_hours=body.est_hours,
            sort_order=body.sort_order,
            created_by=auth.get("user_id"),
        )
    except Exception as exc:
        logger.error("task_create_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/tasks/reorder")
async def reorder_tasks(body: TaskReorderRequest, auth: dict = Depends(require_auth)) -> dict:
    """Persist a manual ordering: sort_order = index in ordered_ids."""
    supabase = get_supabase()
    try:
        for idx, task_id in enumerate(body.ordered_ids):
            supabase.table("tasks").update({"sort_order": idx}).eq("id", task_id).execute()
    except Exception as exc:
        logger.error("task_reorder_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"updated": len(body.ordered_ids)}


@router.get("/tasks/{task_id}")
async def task_detail(task_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    try:
        task = task_service.get_task_detail(str(task_id))
        if task:
            task["comments"] = task_collab.list_comments(str(task_id))
            task["attachments"] = task_collab.list_attachments(str(task_id))
            task["watchers"] = task_collab.list_watchers(str(task_id))
    except Exception as exc:
        logger.error("task_detail_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not task:
        raise HTTPException(status_code=404, detail="task_not_found")
    return task


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: UUID, body: TaskUpdateRequest, auth: dict = Depends(require_auth)
) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and not (changes["name"] or "").strip():
        raise HTTPException(status_code=400, detail="missing_name")
    if not changes:
        raise HTTPException(status_code=400, detail="no_changes")
    try:
        return task_service.update_task(str(task_id), changes, actor_id=auth.get("user_id"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="task_not_found") from exc
    except Exception as exc:
        logger.error("task_update_failed", extra={"task_id": str(task_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    try:
        return task_service.complete_task(str(task_id), actor_id=auth.get("user_id"))
    except Exception as exc:
        logger.error("task_complete_failed", extra={"task_id": str(task_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/tasks/{task_id}/reopen")
async def reopen_task(task_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    try:
        return task_service.reopen_task(str(task_id), actor_id=auth.get("user_id"))
    except Exception as exc:
        logger.error("task_reopen_failed", extra={"task_id": str(task_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.delete("/tasks/{task_id}")
async def trash_task(task_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    """Soft-delete (Trash). Permanent delete lands with the Phase 2 Trash UI."""
    try:
        task_service.soft_delete_task(str(task_id), actor_id=auth.get("user_id"))
        return {"deleted": True}
    except Exception as exc:
        logger.error("task_trash_failed", extra={"task_id": str(task_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/tasks/{task_id}/restore")
async def restore_task(task_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    try:
        task_service.restore_task(str(task_id), actor_id=auth.get("user_id"))
        return {"restored": True}
    except Exception as exc:
        logger.error("task_restore_failed", extra={"task_id": str(task_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


# ---------------------------------------------------------------------------
# Collaboration (Phase 2): comments, attachments, watchers, duplicate, trash
# ---------------------------------------------------------------------------
def _load_task_or_404(task_id: UUID) -> dict:
    rows = (
        get_supabase()
        .table("tasks")
        .select("id, client_id, section_id, name")
        .eq("id", str(task_id))
        .is_("deleted_at", "null")
        .limit(1)
        .execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="task_not_found")
    return rows[0]


@router.get("/tasks/{task_id}/comments")
async def list_comments(task_id: UUID, auth: dict = Depends(require_auth)) -> list[dict]:
    try:
        return task_collab.list_comments(str(task_id))
    except Exception as exc:
        logger.error("task_comments_failed", extra={"task_id": str(task_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/tasks/{task_id}/comments")
async def create_comment(
    task_id: UUID, body: TaskCommentRequest, auth: dict = Depends(require_auth)
) -> dict:
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty_comment")
    task = _load_task_or_404(task_id)
    try:
        return task_collab.create_comment(task, auth["user_id"], text)
    except Exception as exc:
        logger.error("task_comment_create_failed", extra={"task_id": str(task_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.patch("/tasks/comments/{comment_id}")
async def edit_comment(
    comment_id: UUID, body: TaskCommentRequest, auth: dict = Depends(require_auth)
) -> dict:
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty_comment")
    try:
        updated = task_collab.update_comment(str(comment_id), auth["user_id"], text)
    except Exception as exc:
        logger.error("task_comment_edit_failed", extra={"comment_id": str(comment_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not updated:
        raise HTTPException(status_code=403, detail="not_comment_author")
    return updated


@router.delete("/tasks/comments/{comment_id}")
async def remove_comment(comment_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    try:
        ok = task_collab.delete_comment(
            str(comment_id), auth["user_id"], is_admin=auth.get("role") == "admin"
        )
    except Exception as exc:
        logger.error("task_comment_delete_failed", extra={"comment_id": str(comment_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not ok:
        raise HTTPException(status_code=403, detail="not_comment_author")
    return {"deleted": True}


@router.get("/tasks/{task_id}/attachments")
async def list_attachments(task_id: UUID, auth: dict = Depends(require_auth)) -> list[dict]:
    try:
        return task_collab.list_attachments(str(task_id))
    except Exception as exc:
        logger.error("task_attachments_failed", extra={"task_id": str(task_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.post("/tasks/{task_id}/attachments", status_code=201)
async def upload_attachment(
    task_id: UUID, file: UploadFile = File(...), auth: dict = Depends(require_auth)
) -> dict:
    task = _load_task_or_404(task_id)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty_file")
    if len(data) > settings.task_attachment_max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file_too_large")
    try:
        return task_collab.add_attachment(
            task,
            file_name=file.filename or "upload",
            data=data,
            mime_type=file.content_type,
            uploaded_by=auth["user_id"],
        )
    except Exception as exc:
        logger.error("task_attachment_upload_failed", extra={"task_id": str(task_id), "error": str(exc)})
        raise HTTPException(status_code=502, detail="attachment_upload_failed") from exc


@router.delete("/tasks/attachments/{attachment_id}")
async def remove_attachment(attachment_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    try:
        ok = task_collab.delete_attachment(str(attachment_id))
    except Exception as exc:
        logger.error("task_attachment_delete_failed", extra={"attachment_id": str(attachment_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not ok:
        raise HTTPException(status_code=404, detail="attachment_not_found")
    return {"deleted": True}


@router.post("/tasks/{task_id}/watch")
async def watch_task(task_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    _load_task_or_404(task_id)
    task_collab.add_watchers(str(task_id), [auth["user_id"]])
    return {"watching": True}


@router.delete("/tasks/{task_id}/watch")
async def unwatch_task(task_id: UUID, auth: dict = Depends(require_auth)) -> dict:
    try:
        task_collab.remove_watcher(str(task_id), auth["user_id"])
    except Exception as exc:
        logger.error("task_unwatch_failed", extra={"task_id": str(task_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"watching": False}


@router.post("/tasks/{task_id}/duplicate")
async def duplicate_task(
    task_id: UUID, body: TaskDuplicateRequest, auth: dict = Depends(require_auth)
) -> dict:
    try:
        copy = task_collab.duplicate_task(
            str(task_id), with_subtasks=body.with_subtasks, actor_id=auth.get("user_id")
        )
    except Exception as exc:
        logger.error("task_duplicate_failed", extra={"task_id": str(task_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not copy:
        raise HTTPException(status_code=404, detail="task_not_found")
    return copy


@router.get("/clients/{client_id}/tasks/trash")
async def list_trash(client_id: UUID, auth: dict = Depends(require_auth)) -> list[dict]:
    try:
        return task_collab.list_trash(str(client_id))
    except Exception as exc:
        logger.error("task_trash_list_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.delete("/tasks/{task_id}/permanent")
async def purge_task(task_id: UUID, auth: dict = Depends(require_admin)) -> dict:
    """Permanent delete — admin-only (PRD §14)."""
    try:
        task_collab.purge_task(str(task_id))
        return {"deleted": True}
    except Exception as exc:
        logger.error("task_purge_failed", extra={"task_id": str(task_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc

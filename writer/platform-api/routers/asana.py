"""Asana task integration router.

Exposes: the client -> Asana project mapping, the per-client monthly task
template (CRUD via whole-list replace), the editor pickers (workspace users +
category options, read live from Asana), and the manual "generate this month"
trigger. The scheduled monthly run is driven by gsc_scheduler; this router is
the on-demand surface.

All Asana-touching endpoints degrade gracefully: absent the token/workspace they
return empty pickers / a skipped status rather than erroring.
"""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.asana import (
    AsanaCategoryOption,
    AsanaProjectMapping,
    AsanaProjectMappingRequest,
    AsanaTaskTemplateItem,
    AsanaTaskTemplateReplaceRequest,
    AsanaLibraryReplaceRequest,
    AsanaLibraryTaskItem,
    AsanaTaskTemplateRef,
    AsanaTeamMemberItem,
    AsanaTeamMembersReplaceRequest,
    AsanaUser,
    GenerateMonthRequest,
    GenerateMonthResponse,
)
from services import asana_monthly, asana_service, asana_workload, pace_auth, task_service

router = APIRouter(tags=["asana"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration status
# ---------------------------------------------------------------------------
@router.get("/asana/status")
async def asana_status(auth: dict = Depends(require_auth)) -> dict:
    """Whether the Asana integration is provisioned (drives UI gating)."""
    return {"configured": asana_service.is_configured()}


# ---------------------------------------------------------------------------
# Team Workload (Feature B, read)
# ---------------------------------------------------------------------------
@router.get("/asana/workload")
async def workload(auth: dict = Depends(require_auth)) -> dict:
    """Per-person open-task load + same-day due clustering for the team list.

    Data source follows the parallel-run flag: native ``tasks`` once
    ``native_tasks_enabled`` is flipped, Asana fetches until then — the
    Workload page needs no change at cutover."""
    try:
        if settings.native_tasks_enabled:
            from services import task_workload

            return task_workload.build_team_workload()
        return await asana_workload.build_team_workload()
    except Exception as exc:
        logger.error("asana_workload_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc


@router.get("/asana/team-members", response_model=list[AsanaTeamMemberItem])
async def list_team_members(auth: dict = Depends(require_auth)) -> list[AsanaTeamMemberItem]:
    """The tracked team list + each member's weekly capacity."""
    rows = (
        get_supabase()
        .table("asana_team_members")
        .select("id, gid, name, weekly_hours, active, profile_id, everhour_user_id")
        .order("name")
        .execute()
    ).data or []
    return [AsanaTeamMemberItem(**r) for r in rows]


@router.put("/asana/team-members", response_model=list[AsanaTeamMemberItem])
async def replace_team_members(
    body: AsanaTeamMembersReplaceRequest,
    auth: dict = Depends(require_auth),
) -> list[AsanaTeamMemberItem]:
    """Replace the tracked team list (name + weekly capacity + the optional
    suite-user link; an Asana gid when the member has one).

    Non-destructive on member id: an existing member is updated in place by id
    (Phase 2a) so its roster id is PRESERVED — the id is the assignee FK target
    on tasks, and a delete-then-reinsert would orphan every assigned task
    (assignee_id → SET NULL). A member with a gid but no id upserts by gid; a
    member with neither is a NEW LOGIN-LESS VA (inserted with gid = NULL, which
    requires the Phase 2a migration). A stored member is removed only when
    neither its id nor its gid is in the payload."""
    supabase = get_supabase()
    # A suite user maps to at most one member (matches the partial-unique index);
    # reject a payload that links the same profile twice rather than 500 on it.
    linked = [m.profile_id for m in body.members if m.profile_id]
    if len(linked) != len(set(linked)):
        raise HTTPException(status_code=400, detail="duplicate_profile_link")
    try:
        existing = (
            supabase.table("asana_team_members").select("id, gid").execute()
        ).data or []
        plan = task_service.partition_roster_write(
            existing, [m.model_dump() for m in body.members]
        )
        if plan["drop_ids"]:
            # Explicitly unassign the removed members' tasks before deleting them.
            # The assignee_id FK is ON DELETE RESTRICT (a safety backstop against
            # the old blanket-delete roster editor), so a member with tasks can't
            # be cascade-nulled — we clear their tasks first, then delete.
            supabase.table("tasks").update(
                {"assignee_id": None, "assignee_name": None}
            ).in_("assignee_id", plan["drop_ids"]).execute()
            supabase.table("asana_team_members").delete().in_("id", plan["drop_ids"]).execute()
        for upd in plan["updates"]:
            supabase.table("asana_team_members").update(
                {**upd["fields"], "updated_at": "now()"}
            ).eq("id", upd["id"]).execute()
        if plan["gid_upserts"]:
            supabase.table("asana_team_members").upsert(
                [{**r, "updated_at": "now()"} for r in plan["gid_upserts"]],
                on_conflict="gid",
            ).execute()
        if plan["inserts"]:
            supabase.table("asana_team_members").insert(plan["inserts"]).execute()
    except Exception as exc:
        logger.error("asana_replace_team_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return await list_team_members(auth)


# ---------------------------------------------------------------------------
# Task Library (global standard durations)
# ---------------------------------------------------------------------------
@router.get("/asana/task-library", response_model=list[AsanaLibraryTaskItem])
async def list_task_library(auth: dict = Depends(require_auth)) -> list[AsanaLibraryTaskItem]:
    rows = (
        get_supabase()
        .table("asana_task_library")
        .select("name, default_hours, default_category_name, active, client_blurb")
        .order("sort_order")
        .execute()
    ).data or []
    return [AsanaLibraryTaskItem(**r) for r in rows]


@router.put("/asana/task-library", response_model=list[AsanaLibraryTaskItem])
async def replace_task_library(
    body: AsanaLibraryReplaceRequest,
    auth: dict = Depends(require_auth),
) -> list[AsanaLibraryTaskItem]:
    """Replace the whole Task Library. Deduped by name (last wins)."""
    supabase = get_supabase()
    seen: dict[str, dict] = {}
    for idx, item in enumerate(body.items):
        if not item.name or not item.name.strip():
            continue
        seen[item.name.strip().casefold()] = {
            "name": item.name.strip(),
            "default_hours": item.default_hours,
            "default_category_name": item.default_category_name,
            "active": item.active,
            "client_blurb": (item.client_blurb or "").strip() or None,
            "sort_order": idx,
        }
    try:
        supabase.table("asana_task_library").delete().neq("name", "").execute()
        rows = list(seen.values())
        if rows:
            supabase.table("asana_task_library").insert(rows).execute()
    except Exception as exc:
        logger.error("asana_replace_library_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return await list_task_library(auth)


# ---------------------------------------------------------------------------
# Client -> project mapping
# ---------------------------------------------------------------------------
@router.get("/clients/{client_id}/asana/project", response_model=AsanaProjectMapping | None)
async def get_project_mapping(
    client_id: UUID, auth: dict = Depends(require_auth)
) -> AsanaProjectMapping | None:
    rows = (
        get_supabase()
        .table("asana_client_projects")
        .select("project_gid, auto_assignee_gids, auto_assignee_ids")
        .eq("client_id", str(client_id))
        .limit(1)
        .execute()
    ).data
    if not rows:
        return None
    return AsanaProjectMapping(
        client_id=client_id,
        project_gid=rows[0]["project_gid"],
        auto_assignee_gids=list(rows[0].get("auto_assignee_gids") or []),
        auto_assignee_ids=list(rows[0].get("auto_assignee_ids") or []),
    )


@router.put("/clients/{client_id}/asana/project", response_model=AsanaProjectMapping)
async def set_project_mapping(
    client_id: UUID,
    body: AsanaProjectMappingRequest,
    auth: dict = Depends(require_auth),
) -> AsanaProjectMapping:
    supabase = get_supabase()
    project_gid = body.project_gid.strip()
    gids = [g.strip() for g in body.auto_assignee_gids if g and g.strip()]
    ids = [i.strip() for i in body.auto_assignee_ids if i and i.strip()]
    # Cross-fill so both eligibility columns agree (the auto_assignee_gids column
    # is retained until the legacy AsanaTasks template/eligibility editor is
    # rewired to member ids — a follow-up to Phase 2b).
    roster = (
        supabase.table("asana_team_members").select("id, gid").execute()
    ).data or []
    id_by_gid = {r["gid"]: r["id"] for r in roster if r.get("gid")}
    gid_by_id = {r["id"]: r.get("gid") for r in roster}
    if ids and not gids:
        gids = [gid_by_id[i] for i in ids if gid_by_id.get(i)]
    elif gids and not ids:
        ids = [id_by_gid[g] for g in gids if id_by_gid.get(g)]

    # Validate the GID against Asana before saving — a pasted workspace id
    # (the first number in the new app.asana.com/1/<workspace>/project/<gid>
    # URL format) or a project the token can't see 404s here, not later inside
    # a monthly run / task-plan push.
    project_name: str | None = None
    if project_gid and asana_service.is_configured():
        try:
            project = await asana_service.get_project(project_gid)
            project_name = project.get("name")
        except Exception as exc:
            logger.warning(
                "asana_project_gid_invalid",
                extra={"client_id": str(client_id), "project_gid": project_gid, "error": str(exc)},
            )
            raise HTTPException(
                status_code=422, detail="asana_project_not_found_or_no_access"
            ) from exc

    try:
        supabase.table("asana_client_projects").upsert(
            {
                "client_id": str(client_id),
                "project_gid": project_gid,
                "auto_assignee_gids": gids,
                "auto_assignee_ids": ids,
                "updated_at": "now()",
            }
        ).execute()
    except Exception as exc:
        logger.error("asana_set_mapping_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return AsanaProjectMapping(
        client_id=client_id,
        project_gid=project_gid,
        auto_assignee_gids=gids,
        auto_assignee_ids=ids,
        project_name=project_name,
    )


# ---------------------------------------------------------------------------
# Per-client task template (whole-list replace)
# ---------------------------------------------------------------------------
@router.get(
    "/clients/{client_id}/asana/task-templates",
    response_model=list[AsanaTaskTemplateItem],
)
async def list_task_templates(
    client_id: UUID, auth: dict = Depends(require_auth)
) -> list[AsanaTaskTemplateItem]:
    rows = (
        get_supabase()
        .table("asana_client_task_templates")
        .select("*")
        .eq("client_id", str(client_id))
        .order("sort_order")
        .execute()
    ).data or []
    return [AsanaTaskTemplateItem(**r) for r in rows]


@router.put(
    "/clients/{client_id}/asana/task-templates",
    response_model=list[AsanaTaskTemplateItem],
)
async def replace_task_templates(
    client_id: UUID,
    body: AsanaTaskTemplateReplaceRequest,
    auth: dict = Depends(require_auth),
) -> list[AsanaTaskTemplateItem]:
    """Replace the client's whole template with the supplied ordered list."""
    # Reject duplicate task names BEFORE the delete+insert: the DB's unique
    # (client_id, lower(trim(name))) index would fail the insert after the
    # delete already wiped the template — a clean 400 instead of data loss.
    dupes = asana_service.duplicate_template_names([item.name for item in body.items])
    if dupes:
        raise HTTPException(status_code=400, detail=f"duplicate_task_name: {', '.join(dupes[:5])}")
    supabase = get_supabase()
    try:
        supabase.table("asana_client_task_templates").delete().eq(
            "client_id", str(client_id)
        ).execute()
        rows = [
            {
                "client_id": str(client_id),
                "name": item.name,
                "assignee_id": item.assignee_id,
                "assignee_gid": item.assignee_gid,
                "assignee_name": item.assignee_name,
                "category_option_gid": item.category_option_gid,
                "category_name": item.category_name,
                "est_hours": item.est_hours,
                "auto_assign": item.auto_assign,
                "sort_order": idx,
                "active": item.active,
            }
            for idx, item in enumerate(body.items)
            if item.name and item.name.strip()
        ]
        if rows:
            supabase.table("asana_client_task_templates").insert(rows).execute()
    except Exception as exc:
        logger.error("asana_replace_template_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return await list_task_templates(client_id, auth)


# ---------------------------------------------------------------------------
# Editor pickers (live from Asana)
# ---------------------------------------------------------------------------
@router.get("/asana/workspace-users", response_model=list[AsanaUser])
async def workspace_users(auth: dict = Depends(require_auth)) -> list[AsanaUser]:
    if not asana_service.is_configured():
        return []
    try:
        users = await asana_service.list_workspace_users()
    except Exception as exc:
        logger.warning("asana_workspace_users_failed", extra={"error": str(exc)})
        return []
    return [AsanaUser(**u) for u in users]


@router.get(
    "/clients/{client_id}/asana/project-task-templates",
    response_model=list[AsanaTaskTemplateRef],
)
async def project_task_templates(
    client_id: UUID, auth: dict = Depends(require_auth)
) -> list[AsanaTaskTemplateRef]:
    """The Asana task templates on this client's project (names matching a
    template row are instantiated with their subtasks)."""
    if not asana_service.is_configured():
        return []
    project_gid = asana_monthly.get_project_gid(str(client_id))
    if not project_gid:
        return []
    try:
        rows = await asana_service.list_project_task_templates(project_gid)
    except Exception as exc:
        logger.warning("asana_project_task_templates_failed", extra={"client_id": str(client_id), "error": str(exc)})
        return []
    return [AsanaTaskTemplateRef(gid=r["gid"], name=r.get("name")) for r in rows if r.get("gid")]


@router.get(
    "/clients/{client_id}/asana/category-options",
    response_model=list[AsanaCategoryOption],
)
async def category_options(
    client_id: UUID, auth: dict = Depends(require_auth)
) -> list[AsanaCategoryOption]:
    if not asana_service.is_configured():
        return []
    project_gid = asana_monthly.get_project_gid(str(client_id))
    if not project_gid:
        return []
    try:
        options = await asana_service.list_project_category_options(project_gid)
    except Exception as exc:
        logger.warning("asana_category_options_failed", extra={"client_id": str(client_id), "error": str(exc)})
        return []
    return [AsanaCategoryOption(**o) for o in options]


# ---------------------------------------------------------------------------
# Manual monthly generation
# ---------------------------------------------------------------------------
def _parse_target_month(raw: str | None) -> date:
    """Parse 'YYYY-MM' or 'YYYY-MM-DD' to the first of that month; default now."""
    if not raw:
        return date.today().replace(day=1)
    raw = raw.strip()
    if len(raw) == 7:  # 'YYYY-MM'
        raw = f"{raw}-01"
    return date.fromisoformat(raw).replace(day=1)


@router.post(
    "/clients/{client_id}/asana/generate-month",
    response_model=GenerateMonthResponse,
)
async def generate_month(
    client_id: UUID,
    body: GenerateMonthRequest,
    auth: dict = Depends(require_auth),
) -> GenerateMonthResponse:
    """Create the target month's section + tasks now (idempotent). Synchronous —
    one client, a handful of Asana calls.

    Manual monthly generation is a PACE PM operation (owner ruling 2026-09-01):
    a named PM or an admin, not any staff."""
    if not pace_auth.is_pace_pm(pace_auth.context_from_auth(auth)):
        raise HTTPException(status_code=403, detail="not_pace_pm")
    try:
        target = _parse_target_month(body.month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_month") from exc
    try:
        result = await asana_monthly.generate_month_for_client(str(client_id), target)
    except Exception as exc:
        logger.error("asana_generate_month_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return GenerateMonthResponse(
        status=result.get("status", "skipped"),
        section=result.get("section", ""),
        created=result.get("created", 0),
        reason=result.get("reason"),
        errors=result.get("errors", []),
    )

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

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.asana import (
    AsanaCategoryOption,
    AsanaProjectMapping,
    AsanaProjectMappingRequest,
    AsanaTaskTemplateItem,
    AsanaTaskTemplateReplaceRequest,
    AsanaUser,
    GenerateMonthRequest,
    GenerateMonthResponse,
)
from services import asana_monthly, asana_service

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
# Client -> project mapping
# ---------------------------------------------------------------------------
@router.get("/clients/{client_id}/asana/project", response_model=AsanaProjectMapping | None)
async def get_project_mapping(
    client_id: UUID, auth: dict = Depends(require_auth)
) -> AsanaProjectMapping | None:
    project_gid = asana_monthly.get_project_gid(str(client_id))
    if not project_gid:
        return None
    return AsanaProjectMapping(client_id=client_id, project_gid=project_gid)


@router.put("/clients/{client_id}/asana/project", response_model=AsanaProjectMapping)
async def set_project_mapping(
    client_id: UUID,
    body: AsanaProjectMappingRequest,
    auth: dict = Depends(require_auth),
) -> AsanaProjectMapping:
    supabase = get_supabase()
    try:
        supabase.table("asana_client_projects").upsert(
            {
                "client_id": str(client_id),
                "project_gid": body.project_gid.strip(),
                "updated_at": "now()",
            }
        ).execute()
    except Exception as exc:
        logger.error("asana_set_mapping_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return AsanaProjectMapping(client_id=client_id, project_gid=body.project_gid.strip())


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
    supabase = get_supabase()
    try:
        supabase.table("asana_client_task_templates").delete().eq(
            "client_id", str(client_id)
        ).execute()
        rows = [
            {
                "client_id": str(client_id),
                "name": item.name,
                "assignee_gid": item.assignee_gid,
                "assignee_name": item.assignee_name,
                "category_option_gid": item.category_option_gid,
                "category_name": item.category_name,
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
    one client, a handful of Asana calls."""
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

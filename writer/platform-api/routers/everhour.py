"""Everhour time-tracking integration router — Phase 1 (read-only pickers + status).

Backs docs/modules/everhour-time-tracking-integration-plan-v1_0.md §9 (Phase 1).

The Everhour join keys themselves are written through the existing surfaces, not
here:
  * asana_team_members.everhour_user_id — via PUT /asana/team-members (the Team
    page's roster editor, next to the Slack/profile links).
  * clients.everhour_project_id — via PATCH /clients/{id} (the client form/
    workspace mapping UI).

This router only serves the two pickers those UIs choose from, plus the
provisioning status the frontend gates on. Every endpoint degrades gracefully
(mirrors the Asana pickers): absent the API key it returns an empty picker /
not-configured, never an error — a missing integration must not 500 the UI.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends

from config import settings
from middleware.auth import require_auth
from models.everhour import EverhourProject, EverhourStatus, EverhourUser
from services import everhour_service

router = APIRouter(tags=["everhour"])
logger = logging.getLogger(__name__)


@router.get("/everhour/status", response_model=EverhourStatus)
async def everhour_status(auth: dict = Depends(require_auth)) -> EverhourStatus:
    """Whether the Everhour integration is provisioned (drives UI gating). The
    pickers work as soon as it's `configured` (a key is present), even while the
    master `enabled` gate is still off, so mappings can be set up ahead of
    turning the sync on."""
    return EverhourStatus(
        configured=everhour_service.is_configured(),
        enabled=settings.everhour_enabled,
    )


@router.get("/everhour/users", response_model=list[EverhourUser])
async def everhour_users(auth: dict = Depends(require_auth)) -> list[EverhourUser]:
    """Everhour team users for the Team-page Everhour-user-link dropdown."""
    if not everhour_service.is_configured():
        return []
    try:
        users = await everhour_service.list_team_users()
    except Exception as exc:  # never 500 a picker
        logger.warning("everhour_users_failed", extra={"error": str(exc)})
        return []
    return [EverhourUser(**everhour_service.parse_user(u)) for u in users]


@router.get("/everhour/projects", response_model=list[EverhourProject])
async def everhour_projects(
    query: Optional[str] = None,
    auth: dict = Depends(require_auth),
) -> list[EverhourProject]:
    """Everhour projects for the client↔project mapping picker. `query` narrows
    the list by name — the `/projects` endpoint has no pagination, so narrowing
    with a query is the intended way to find a project (plan §11.3)."""
    if not everhour_service.is_configured():
        return []
    try:
        projects = await everhour_service.list_projects(query)
    except Exception as exc:  # never 500 a picker
        logger.warning("everhour_projects_failed", extra={"error": str(exc)})
        return []
    return [EverhourProject(**everhour_service.parse_project(p)) for p in projects]

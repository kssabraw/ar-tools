"""Pydantic schemas for the Everhour time-tracking integration (Phase 1).

Only the read-only picker + status shapes so far — the join keys themselves are
written through the existing surfaces (asana_team_members.everhour_user_id via
PUT /asana/team-members, clients.everhour_project_id via PATCH /clients/{id}).
The time_entries / rollup schemas land with Phase 3.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class EverhourStatus(BaseModel):
    """Provisioning status the Everhour pickers gate on."""

    # The API key is present (settings.everhour_api_key) — pickers can load.
    configured: bool
    # The master feature gate (settings.everhour_enabled). A client can be mapped
    # while this is False (provisioning ahead of turning the sync on).
    enabled: bool


class EverhourUser(BaseModel):
    """One Everhour team user, as the roster-link dropdown consumes it
    (`services/everhour_service.parse_user` output)."""

    everhour_user_id: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    capacity_seconds: Optional[float] = None


class EverhourProject(BaseModel):
    """One Everhour project, as the client↔project mapping picker consumes it
    (`services/everhour_service.parse_project` output). The id is an opaque
    string like "ev:123"/"as:123", never numeric."""

    everhour_project_id: Optional[str] = None
    name: Optional[str] = None

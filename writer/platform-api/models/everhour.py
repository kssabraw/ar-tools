"""Pydantic schemas for the Everhour time-tracking integration (Phase 1).

The read-only picker + status shapes (Phase 1), the backfill/sync result shapes
(Phase 2/3), and the Phase-4 read surface (EverhourClientTime — the client
"Time" card). The join keys themselves are written through the existing
surfaces (asana_team_members.everhour_user_id via PUT /asana/team-members,
clients.everhour_project_id via PATCH /clients/{id}); per-member utilization is
surfaced through the workload report, not a schema here.
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


class EverhourBackfillResult(BaseModel):
    """Result of the one-time task-mirror backfill (Phase 2, §3/§8) — how many
    existing open tasks were queued for an Everhour mirror."""

    status: str
    candidates: int = 0
    enqueued: int = 0
    reason: Optional[str] = None


class EverhourSyncResult(BaseModel):
    """Result of enqueuing a manual "Sync now" time pull (Phase 3, §4). The pull
    runs on the worker; this returns the queued job id (or why it was skipped —
    the integration is disabled, or a sync is already in flight)."""

    status: str
    job_id: Optional[str] = None
    reason: Optional[str] = None


class EverhourTimeMember(BaseModel):
    """One roster member's logged hours in a client's Time-card breakdown."""

    member_id: str
    name: Optional[str] = None
    hours: float


class EverhourClientTime(BaseModel):
    """The client "Time" card read (Phase 4): logged hours over a window, the
    billable/non-billable/unknown split, and a per-member breakdown. When the
    integration is off, ``available`` is False and the numeric fields are None
    — the card renders a dark state, never an error."""

    available: bool
    reason: Optional[str] = None
    window_days: Optional[int] = None
    total_hours: Optional[float] = None
    billable_hours: Optional[float] = None
    non_billable_hours: Optional[float] = None
    unknown_hours: Optional[float] = None
    members: list[EverhourTimeMember] = []

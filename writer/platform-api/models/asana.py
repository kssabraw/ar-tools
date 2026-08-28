"""Pydantic schemas for the Asana task integration."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Client -> Asana project mapping
# ---------------------------------------------------------------------------
class AsanaProjectMapping(BaseModel):
    client_id: UUID
    project_gid: str
    auto_assignee_gids: list[str] = []
    # Native identity: the same eligibility list as roster member ids (canonical
    # key; auto_assignee_gids is the dual-written legacy copy).
    auto_assignee_ids: list[str] = []
    # Resolved from Asana at save time (validation) — None on reads / when
    # Asana is unconfigured.
    project_name: Optional[str] = None


class AsanaProjectMappingRequest(BaseModel):
    project_gid: str
    auto_assignee_gids: list[str] = []
    auto_assignee_ids: list[str] = []


# ---------------------------------------------------------------------------
# Per-client task template
# ---------------------------------------------------------------------------
class AsanaTaskTemplateItem(BaseModel):
    """One row of a client's monthly task template (editor in + out)."""
    name: str
    assignee_id: Optional[str] = None  # roster member id (canonical)
    assignee_gid: Optional[str] = None  # legacy Asana gid (dual-written)
    assignee_name: Optional[str] = None
    category_option_gid: Optional[str] = None
    category_name: Optional[str] = None
    est_hours: Optional[float] = None
    auto_assign: bool = False
    sort_order: int = 0
    active: bool = True


class AsanaTaskTemplateReplaceRequest(BaseModel):
    """Replace a client's whole template with this ordered list."""
    items: list[AsanaTaskTemplateItem] = []


# ---------------------------------------------------------------------------
# Editor pickers (populated from Asana)
# ---------------------------------------------------------------------------
class AsanaUser(BaseModel):
    gid: str
    name: Optional[str] = None
    email: Optional[str] = None


class AsanaCategoryOption(BaseModel):
    gid: str
    name: Optional[str] = None


class AsanaTaskTemplateRef(BaseModel):
    """An Asana native task template on a project (instantiated to keep subtasks)."""
    gid: str
    name: Optional[str] = None


# ---------------------------------------------------------------------------
# Team & capacity (Team Workload)
# ---------------------------------------------------------------------------
class AsanaTeamMemberItem(BaseModel):
    # Roster member id (canonical assignee identity). Echoed on reads; on a write
    # it identifies an existing member to update in place (id preserved).
    id: Optional[str] = None
    # Asana user gid — OPTIONAL (Phase 2a): a login-less VA has no gid.
    gid: Optional[str] = None
    name: Optional[str] = None
    weekly_hours: Optional[float] = None
    active: bool = True
    # Native task manager identity bridge: the suite user (profiles.id) this
    # tracked member is, if linked. Nullable — an unlinked member is unchanged.
    profile_id: Optional[str] = None


class AsanaTeamMembersReplaceRequest(BaseModel):
    members: list[AsanaTeamMemberItem] = []


# ---------------------------------------------------------------------------
# Task Library (global standard durations, keyed by name)
# ---------------------------------------------------------------------------
class AsanaLibraryTaskItem(BaseModel):
    name: str
    default_hours: Optional[float] = None
    default_category_name: Optional[str] = None
    active: bool = True
    # Client-facing one-liner ("why this work matters") used by the Weekly
    # Pulse narrative for any task derived from this library entry.
    client_blurb: Optional[str] = None


class AsanaLibraryReplaceRequest(BaseModel):
    items: list[AsanaLibraryTaskItem] = []


# ---------------------------------------------------------------------------
# Monthly generation
# ---------------------------------------------------------------------------
class GenerateMonthRequest(BaseModel):
    month: Optional[str] = None      # 'YYYY-MM' or 'YYYY-MM-DD'; default = current month


class GenerateMonthResponse(BaseModel):
    status: str                      # created | exists | skipped
    section: str
    created: int = 0
    reason: Optional[str] = None
    errors: list[str] = []

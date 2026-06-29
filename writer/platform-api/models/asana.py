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


class AsanaProjectMappingRequest(BaseModel):
    project_gid: str
    auto_assignee_gids: list[str] = []


# ---------------------------------------------------------------------------
# Per-client task template
# ---------------------------------------------------------------------------
class AsanaTaskTemplateItem(BaseModel):
    """One row of a client's monthly task template (editor in + out)."""
    name: str
    assignee_gid: Optional[str] = None
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


# ---------------------------------------------------------------------------
# Team & capacity (Team Workload)
# ---------------------------------------------------------------------------
class AsanaTeamMemberItem(BaseModel):
    gid: str
    name: Optional[str] = None
    weekly_hours: Optional[float] = None
    active: bool = True


class AsanaTeamMembersReplaceRequest(BaseModel):
    members: list[AsanaTeamMemberItem] = []


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

"""Pydantic schemas for campaign goals."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

GoalType = Literal[
    "keyword_position",
    "keywords_in_top",
    "organic_clicks",
    "organic_impressions",
    "ai_visibility",
    "maps_pack_presence",
    "custom",
]


class CampaignGoalCreateRequest(BaseModel):
    goal_type: GoalType
    label: str
    keyword: Optional[str] = None          # keyword_position goals
    target_value: Optional[float] = None   # null only for custom
    target_position: Optional[int] = None  # keywords_in_top: the N in "top N"
    due_date: Optional[date] = None
    notes: Optional[str] = None


class CampaignGoalUpdateRequest(BaseModel):
    label: Optional[str] = None
    target_value: Optional[float] = None
    target_position: Optional[int] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    active: Optional[bool] = None


class CampaignGoalResponse(BaseModel):
    id: UUID
    client_id: UUID
    goal_type: str
    label: str
    keyword: Optional[str] = None
    target_value: Optional[float] = None
    target_position: Optional[int] = None
    due_date: Optional[date] = None
    baseline_value: Optional[float] = None
    baseline_date: Optional[date] = None
    achieved_at: Optional[datetime] = None
    active: bool = True
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    # Computed on read (never stored):
    current_value: Optional[float] = None
    status: Optional[str] = None        # achieved | on_track | behind | overdue | no_data | manual
    progress_pct: Optional[float] = None
    elapsed_pct: Optional[float] = None
    note: Optional[str] = None

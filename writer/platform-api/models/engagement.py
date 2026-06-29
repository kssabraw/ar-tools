"""Pydantic models for the managed engagement spine. Phase 2 / PR-A."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class EngagementCreateRequest(BaseModel):
    autonomy_level: str = "assisted"  # recommend | assisted | autonomous


class TransitionRequest(BaseModel):
    to_status: str


class EngagementResponse(BaseModel):
    id: str
    client_id: str
    status: str
    autonomy_level: str
    config: dict = Field(default_factory=dict)
    current_plan_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

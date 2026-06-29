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


# ── strategy plan / actions (Phase 2 · PR-B) ─────────────────────────────────
class StrategyActionResponse(BaseModel):
    id: str
    module: str
    category: str
    kind: Optional[str] = None
    title: str
    rationale: Optional[str] = None
    target: Optional[dict] = None
    priority: int = 0
    execution_mode: str
    assignee_role: Optional[str] = None
    status: str
    deep_link: Optional[str] = None


class StrategyPlanResponse(BaseModel):
    id: str
    engagement_id: str
    version: int
    status: str
    summary: Optional[dict] = None
    created_at: Optional[str] = None
    actions: list[StrategyActionResponse] = Field(default_factory=list)

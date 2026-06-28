"""Pydantic schemas for the reoptimization planner (Action Plan)."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ReoptAction(BaseModel):
    kind: str                       # rank_drop | quick_win | cannibalization | opportunity
    keyword: str
    diagnosis: str
    recommendation: str
    cta_label: str
    cta_path: str
    severity: str                   # critical | warning | info
    sort: float = 0


class ReoptPlan(BaseModel):
    id: UUID
    client_id: UUID
    trigger: str                    # scheduled | drop | manual
    summary: Optional[str] = None
    items: list[ReoptAction] = []
    action_count: int = 0
    created_at: str


class ReoptPlanEnqueueResponse(BaseModel):
    status: str = "queued"

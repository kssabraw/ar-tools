"""Pydantic schemas for the reoptimization planner (Action Plan)."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ReoptActionDetail(BaseModel):
    """SOP-grounded enrichment for one action (added by enrich_plan; absent until
    a playbook is loaded, in which case the frontend falls back to a static guide)."""
    why: str = ""
    steps: list[str] = []
    sop_refs: list[str] = []


class ReoptAction(BaseModel):
    # rank_drop | quick_win | cannibalization | opportunity
    # | maps_decline | maps_competitor | maps_weak_area
    kind: str
    source: Optional[str] = None    # organic | maps
    keyword: str
    diagnosis: str
    recommendation: str
    cta_label: str
    cta_path: str
    severity: str                   # critical | warning | info
    sort: float = 0
    detail: Optional[ReoptActionDetail] = None
    # Saved SerMaStr strategy steps only: their assistant_plan_actions row id,
    # so the frontend can close one. (Pydantic drops unknown keys, so the
    # passthrough must be declared.)
    assistant_action_id: Optional[str] = None
    # Concrete specifics the frontend renders (the page/link/topic/link-target
    # data the action carries). MUST be declared here or Pydantic strips them
    # from the response_model=ReoptPlan output before they reach the frontend.
    url: Optional[str] = None                       # the page an action targets
    pages: Optional[list[dict]] = None              # cannibalization: competing URLs
    topics: Optional[list[str]] = None              # content gap: missing sections
    target_domains: Optional[list[dict]] = None     # link building: domains to pursue / lost
    target_link_count: Optional[int] = None         # link building: how many to build/replace
    search_volume: Optional[int] = None             # demand for a create-page keyword
    est_value: Optional[float] = None               # est. monthly value
    location: Optional[str] = None                  # maps weak-area: the place to target


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

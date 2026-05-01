"""Pydantic models for Run resources."""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RunCreateRequest(BaseModel):
    client_id: UUID
    keyword: str = Field(..., min_length=1, max_length=150)
    intent_override: Optional[str] = None
    sie_outlier_mode: Literal["safe", "aggressive"] = "safe"
    sie_force_refresh: bool = False


class RunListItem(BaseModel):
    id: UUID
    keyword: str
    client_id: UUID
    client_name: str
    status: str
    sie_cache_hit: Optional[bool] = None
    total_cost_usd: Optional[float] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ModuleOutputSummary(BaseModel):
    status: str
    output_payload: Optional[dict[str, Any]] = None
    cost_usd: Optional[float] = None
    duration_ms: Optional[int] = None
    module_version: Optional[str] = None


class ClientContextSnapshot(BaseModel):
    brand_guide_text: Optional[str] = None
    brand_guide_format: Optional[str] = None
    icp_text: Optional[str] = None
    icp_format: Optional[str] = None
    website_analysis: Optional[dict[str, Any]] = None
    website_analysis_unavailable: bool = False


class RunDetail(BaseModel):
    id: UUID
    keyword: str
    client_id: UUID
    status: str
    sie_cache_hit: Optional[bool] = None
    error_stage: Optional[str] = None
    error_message: Optional[str] = None
    total_cost_usd: Optional[float] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    client_context_snapshot: Optional[ClientContextSnapshot] = None
    module_outputs: dict[str, Optional[ModuleOutputSummary]] = Field(
        default_factory=lambda: {
            "brief": None,
            "sie": None,
            "research": None,
            "writer": None,
            "sources_cited": None,
        }
    )


class RunCreateResponse(BaseModel):
    run_id: UUID
    status: str


class RunPollResponse(BaseModel):
    run_id: UUID
    status: str
    completed_stages: list[str]
    error_stage: Optional[str] = None
    updated_at: str


class RunListResponse(BaseModel):
    data: list[RunListItem]
    total: int
    page: int

"""Pydantic models for the Local SEO module (#2)."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class LocalSeoGenerateRequest(BaseModel):
    """Request to generate a local SEO page for a client.

    The user must explicitly choose whether to run competitor SERP analysis
    (`run_analysis`) — there is no default (plan §2, "force a choice").
    Business data is pulled server-side from the client's stored GBP record.
    """

    keyword: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    run_analysis: bool


class LocalSeoPageDetail(BaseModel):
    id: UUID
    client_id: UUID
    keyword: str
    location: str
    run_analysis: bool
    content_html: str
    schema_json: str
    page_title: Optional[str] = None
    content_gaps: list[dict[str, Any]] = Field(default_factory=list)
    composite_score: Optional[float] = None
    composite_status: Optional[str] = None
    mode: str
    token_usage: Optional[dict[str, Any]] = None
    cost_breakdown: Optional[dict[str, Any]] = None
    created_at: str
    updated_at: str


class LocalSeoPageListItem(BaseModel):
    id: UUID
    client_id: UUID
    keyword: str
    location: str
    page_title: Optional[str] = None
    composite_score: Optional[float] = None
    composite_status: Optional[str] = None
    mode: str
    created_at: str

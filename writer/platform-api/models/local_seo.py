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


class LocalSeoAnalyzeRequest(BaseModel):
    """Run competitor SERP analysis for a keyword + location (standalone)."""

    keyword: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    location_code: Optional[int] = None


class LocalSeoFindPageRequest(BaseModel):
    """Scan the client's website for an existing page targeting the keyword."""

    keyword: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)


class LocalSeoScoreRequest(BaseModel):
    """Score an existing page (by URL or raw HTML) against the 8 engines."""

    keyword: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    location_code: Optional[int] = None
    page_url: Optional[str] = None
    page_content: Optional[str] = None
    serp_analysis: Optional[dict[str, Any]] = None


class LocalSeoRelatedPagesRequest(BaseModel):
    """Discover parent/sibling/child page opportunities for a keyword."""

    keyword: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)


class LocalSeoReoptimizeRequest(BaseModel):
    """Reoptimize an existing page to lift its score, then persist the result.

    Provide either the raw HTML (`existing_page_html`) or a URL to fetch
    (`existing_page_url`). `deficiencies` come from a prior `/score` call.
    """

    keyword: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    existing_page_html: Optional[str] = None
    existing_page_url: Optional[str] = None
    deficiencies: list[dict[str, Any]] = Field(default_factory=list)
    serp_analysis: Optional[dict[str, Any]] = None


class LocalSeoSocialPostsRequest(BaseModel):
    """Generate GBP social posts from a generated page's text."""

    keyword: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    page_content: str = Field(..., min_length=1)
    serp_analysis: Optional[dict[str, Any]] = None


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

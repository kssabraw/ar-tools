"""Pydantic models for the Local SEO module (#2)."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class LocalSeoGenerateRequest(BaseModel):
    """Request to generate a local SEO page for a client.

    Competitor SERP analysis always runs first — it is no longer opt-in.
    Business data is pulled server-side from the client's stored GBP record.
    """

    keyword: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    location_code: Optional[int] = None
    # Bypass the shared SERP-analysis cache and re-scrape competitors.
    force_refresh: bool = False
    # Phase 3 — mirror this reference page's structure. Falls back to the
    # client's saved default when omitted.
    page_template_url: Optional[str] = None


class PageTemplateDefaultRequest(BaseModel):
    """Set/clear the client's default Local SEO page-template URL."""

    page_template_url: Optional[str] = None


class LocationSuggestion(BaseModel):
    """One DataForSEO location suggestion for the area typeahead."""

    location_name: str
    location_code: int
    location_type: str = ""
    country_iso_code: str = ""


class LocalSeoAnalyzeRequest(BaseModel):
    """Run competitor SERP analysis for a keyword + location (standalone)."""

    keyword: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    location_code: Optional[int] = None
    # Bypass the shared SERP-analysis cache and re-scrape competitors.
    force_refresh: bool = False


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
    # Bypass the shared SERP-analysis cache and re-scrape competitors.
    force_refresh: bool = False


class LocalSeoRelatedPagesRequest(BaseModel):
    """Discover parent/sibling/child page opportunities for a keyword."""

    keyword: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)


class LocalSeoSiloPlanRequest(BaseModel):
    """Kick off a Fanout-powered silo plan for a service + area.

    The pipeline (silo discovery → expansion → relevance gate → clustering)
    runs for minutes, so the route enqueues an async job and the client polls
    `GET …/silo-plan/{job_id}`."""

    keyword: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    location_code: Optional[int] = None


class LocalSeoSiloPlanJob(BaseModel):
    """Handle returned when a silo-plan job is enqueued."""

    job_id: str
    status: str


class LocalSeoSiloPlanItem(BaseModel):
    """One candidate page target (a cluster representative) under its silo."""

    keyword: str
    # The silo this target belongs to (free-form label from silo discovery).
    group: str
    status: str  # 'found' (a page already exists) | 'missing'
    url: Optional[str] = None


class LocalSeoSiloPlanResult(BaseModel):
    """Polled state of a silo-plan job."""

    status: str  # async_jobs status: pending | running | complete | failed
    items: list[LocalSeoSiloPlanItem] = Field(default_factory=list)
    degraded_notes: list[str] = Field(default_factory=list)
    error: Optional[str] = None


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


class LocalSeoRankabilityRequest(BaseModel):
    """Map-pack rankability check for a keyword + location.

    The business identity (category, address, review count, lat/lng, place_id)
    is sourced server-side from the client's stored GBP — the frontend only
    supplies the keyword/area and, for a service-area business, the city where
    it's physically located (`sab_city`) so distance can be measured.
    """

    keyword: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    location_code: Optional[int] = None
    # SAB only: the city the GBP is physically located in (SABs hide their address).
    sab_city: Optional[str] = None


class RankabilityCompetitor(BaseModel):
    name: str
    rating: Optional[float] = None
    review_count: Optional[int] = None
    has_keyword_in_name: bool = False


class LocalSeoRankabilityResponse(BaseModel):
    """Passthrough of the nlp service's RankabilityResponse."""

    score: int
    verdict: str
    score_breakdown: dict[str, Any]
    has_map_pack: bool
    competitors: list[RankabilityCompetitor] = Field(default_factory=list)
    ranking_categories: list[dict[str, Any]] = Field(default_factory=list)
    min_reviews_in_pack: Optional[int] = None
    max_reviews_in_pack: Optional[int] = None
    avg_reviews_in_pack: Optional[float] = None
    avg_rating_in_pack: Optional[float] = None
    review_gap: Optional[int] = None
    category_match: str
    distance_miles: Optional[float] = None
    distance_ok: bool = True
    keyword_in_competitor_names: int = 0
    competitor_name_examples: list[str] = Field(default_factory=list)
    in_maps_results: bool = False
    maps_position: Optional[int] = None
    is_sab: bool = False
    sab_pack_mismatch: bool = False
    physical_competitors_in_pack: int = 0
    message: str = ""
    match_count: int = 0
    total_results: int = 0


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
    published_doc_url: Optional[str] = None
    published_doc_id: Optional[str] = None
    published_at: Optional[str] = None
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

"""Pydantic schemas for the Local SEO service × location matrix
(docs/modules/local-seo-matrix-plan-v1_0.md §6).

Every field the store returns is declared here — `GET` responses serialize
through these models, and Pydantic silently strips anything undeclared (the
Action-Plan lesson, CLAUDE.md #844)."""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

PublishDestination = Literal["google_docs", "wordpress", "github"]
PublishStatus = Literal["draft", "publish"]


class MatrixLocationIn(BaseModel):
    """One location on the axis. `location_code` (+ `canonical`, the DataForSEO
    name it resolved to) is the per-row opt-in to generate at that location's own
    code instead of the matrix's metro anchor."""

    name: str = Field(..., min_length=1)
    location_code: Optional[int] = None
    canonical: Optional[str] = None
    source: Optional[str] = None  # 'manual' | 'target_city' | 'suburb' | …


class MatrixCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    # The metro anchor (resolved/validated like every other Local SEO area).
    location: str = Field(..., min_length=1)
    location_code: Optional[int] = None
    services: list[str] = Field(..., min_length=1)
    locations: list[MatrixLocationIn | str] = Field(..., min_length=1)
    url_pattern: Optional[str] = None
    base_url: Optional[str] = None
    page_template_url: Optional[str] = None
    entity_provider: Optional[str] = None
    publish_destination: PublishDestination = "google_docs"
    publish_status: PublishStatus = "draft"


class MatrixUpdateRequest(BaseModel):
    """Every field optional; axes given → gap-filled (plan §3.1)."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    services: Optional[list[str]] = None
    locations: Optional[list[MatrixLocationIn | str]] = None
    url_pattern: Optional[str] = None
    base_url: Optional[str] = None
    page_template_url: Optional[str] = None
    entity_provider: Optional[str] = None
    publish_destination: Optional[PublishDestination] = None
    publish_status: Optional[PublishStatus] = None


class MatrixCell(BaseModel):
    id: UUID
    matrix_id: UUID
    service_label: str
    service_slug: str
    location_name: str
    location_slug: str
    service_order: int = 0
    location_order: int = 0
    keyword: str
    path: str
    status: str
    page_id: Optional[UUID] = None
    job_id: Optional[UUID] = None
    url: Optional[str] = None
    released_at: Optional[str] = None
    link_coverage: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    # Joined from local_seo_pages when the cell has a page (read-only).
    page_title: Optional[str] = None
    composite_score: Optional[float] = None
    composite_status: Optional[str] = None
    published_url: Optional[str] = None
    updated_at: Optional[str] = None


class MatrixSummary(BaseModel):
    id: UUID
    client_id: UUID
    name: str
    location: str
    location_code: Optional[int] = None
    services: list[dict[str, Any]] = Field(default_factory=list)
    locations: list[dict[str, Any]] = Field(default_factory=list)
    url_pattern: str
    base_url: Optional[str] = None
    page_template_url: Optional[str] = None
    entity_provider: Optional[str] = None
    publish_destination: str = "google_docs"
    publish_status: str = "draft"
    release_enabled: bool = False
    release_mode: str = "daily"
    release_weekday: Optional[int] = None
    release_day_of_month: Optional[int] = None
    release_per_count: int = 1
    release_status: str = "active"
    release_next_run_at: Optional[str] = None
    release_last_run_at: Optional[str] = None
    coverage: dict[str, int] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MatrixDetail(MatrixSummary):
    cells: list[MatrixCell] = Field(default_factory=list)
    degraded_notes: list[str] = Field(default_factory=list)


class MatrixGate(BaseModel):
    kind: str
    message: str
    blocking: bool = True


class MatrixEstimate(BaseModel):
    count: int
    est_cost_usd: float
    est_minutes: int
    gates: list[MatrixGate] = Field(default_factory=list)
    cell_ids: list[UUID] = Field(default_factory=list)


class MatrixGenerateRequest(BaseModel):
    cell_ids: Optional[list[UUID]] = None
    include_covered: bool = False
    signoff_acknowledged: bool = False
    force_refresh: bool = False


class MatrixGenerateResult(BaseModel):
    job_ids: list[UUID] = Field(default_factory=list)
    cell_ids: list[UUID] = Field(default_factory=list)
    estimate: MatrixEstimate


class MatrixSuggestRequest(BaseModel):
    axis: Literal["services", "locations"]
    # Services: the service to expand (defaults to the first on the axis).
    seed_service: Optional[str] = None


class MatrixSuggestJob(BaseModel):
    job_id: UUID
    status: str


class MatrixSuggestion(BaseModel):
    label: str
    group: Optional[str] = None  # services: the silo it came from; locations: the source
    source: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class MatrixSuggestResult(BaseModel):
    status: str
    axis: Optional[str] = None
    suggestions: list[MatrixSuggestion] = Field(default_factory=list)
    degraded_notes: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class MatrixRecheckResult(BaseModel):
    changed: int
    coverage: dict[str, int] = Field(default_factory=dict)
    degraded_notes: list[str] = Field(default_factory=list)

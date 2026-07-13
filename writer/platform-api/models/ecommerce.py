"""Pydantic models for the Ecommerce Product & Collection Writer + Reoptimizer."""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

PageType = Literal["product", "collection"]


class EcommerceGenerateRequest(BaseModel):
    """Write a new ecommerce page. Product facts come from a pasted
    `product_input` and/or a scraped `source_url` (either or both)."""

    keyword: str = Field(..., min_length=1)
    page_type: PageType = "product"
    source_url: Optional[str] = None
    product_input: Optional[str] = None
    # Optional per-call override of the client's house PDP template (products
    # only). Omit to use the client's saved default.
    page_template_url: Optional[str] = None


class EcommercePageTemplateRequest(BaseModel):
    """Set/clear the client's house PDP template URL (products mirror it)."""

    page_template_url: Optional[str] = None


class EcommerceGenerateJob(BaseModel):
    job_id: UUID
    status: str


class EcommerceGenerateJobResult(BaseModel):
    status: str  # pending | running | complete | failed
    page_id: Optional[UUID] = None
    error: Optional[str] = None


class EcommerceBulkGenerateRequest(BaseModel):
    """Enqueue background generation for several keywords at once."""

    keywords: list[str] = Field(..., min_length=1)
    page_type: PageType = "product"


class EcommerceBulkGenerateJob(BaseModel):
    job_ids: list[UUID] = Field(default_factory=list)


class EcommerceReoptimizeTarget(BaseModel):
    page_url: str = Field(..., min_length=1)
    keyword: str = ""
    page_type: PageType = "product"


class EcommerceReoptimizeBulkRequest(BaseModel):
    targets: list[EcommerceReoptimizeTarget] = Field(..., min_length=1)
    score_threshold: Optional[float] = None
    publish_to_doc: bool = False


class EcommerceReoptimizeJobHandle(BaseModel):
    job_id: UUID
    page_url: str


class EcommerceReoptimizeBulkJob(BaseModel):
    jobs: list[EcommerceReoptimizeJobHandle] = Field(default_factory=list)


class EcommerceJobsStatusRequest(BaseModel):
    job_ids: list[UUID] = Field(default_factory=list)


class EcommerceJobStatus(BaseModel):
    job_id: UUID
    status: str  # pending | running | complete | failed
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class EcommerceScoreRequest(BaseModel):
    """Score an existing ecommerce page (by URL or raw HTML) against the 8 engines."""

    keyword: str = Field(..., min_length=1)
    page_type: PageType = "product"
    page_url: Optional[str] = None
    page_content: Optional[str] = None


class EcommerceDiscoverItem(BaseModel):
    url: str
    page_type: PageType


class EcommerceDiscoverResult(BaseModel):
    items: list[EcommerceDiscoverItem] = Field(default_factory=list)
    source: str = "none"  # sitemap | google_index | none
    count: int = 0
    note: str = ""


class EcommercePageDetail(BaseModel):
    id: UUID
    client_id: UUID
    keyword: str
    page_type: str
    source_url: Optional[str] = None
    product_input: Optional[str] = None
    content_html: str
    schema_json: str
    page_title: Optional[str] = None
    content_gaps: list[dict[str, Any]] = Field(default_factory=list)
    composite_score: Optional[float] = None
    composite_status: Optional[str] = None
    engine_scores: Optional[dict[str, Any]] = None
    mode: str
    token_usage: Optional[dict[str, Any]] = None
    cost_breakdown: Optional[dict[str, Any]] = None
    published_doc_url: Optional[str] = None
    published_doc_id: Optional[str] = None
    published_url: Optional[str] = None
    published_at: Optional[str] = None
    featured_image_url: Optional[str] = None
    created_at: str
    updated_at: str


class EcommercePageListItem(BaseModel):
    id: UUID
    client_id: UUID
    keyword: str
    page_type: str
    source_url: Optional[str] = None
    page_title: Optional[str] = None
    composite_score: Optional[float] = None
    composite_status: Optional[str] = None
    mode: str
    created_at: str
    deleted_at: Optional[str] = None
    published_doc_url: Optional[str] = None
    published_url: Optional[str] = None
    published_at: Optional[str] = None

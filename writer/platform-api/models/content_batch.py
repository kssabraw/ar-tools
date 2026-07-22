"""Request/response schemas for the Content Scheduler (suite bulk page creation +
scheduling). See services/content_schedule_store.py + services/content_batch.py."""

from __future__ import annotations

from datetime import date, time
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

ContentType = Literal["blog_post", "service_page", "location_page",
                      "local_seo_page", "ecommerce"]
# 'now' = create every page immediately; the rest mirror the Fanout cadence
# vocabulary (planned by the reused fanout schedule_planner).
Mode = Literal["now", "all_at_once", "drip", "weekly", "monthly_date",
               "monthly_weekday", "fixed"]


class ContentBatchItemInput(BaseModel):
    """One requested page. Per-row params (Option B): the same upload can mix
    locations and per-page service sets. Only `keyword` is required."""

    keyword: str
    location: Optional[str] = None
    location_code: Optional[int] = None
    services: list[str] = Field(default_factory=list)
    page_template_url: Optional[str] = None
    # Per-row free-text writing guidance (CSV "Notes" column). Fed into
    # generation for every content type — not just stored.
    notes: Optional[str] = None
    # Per-row publish date (CSV "Date" column, ISO YYYY-MM-DD). When set it
    # overrides the batch cadence for this row: the page is held until this date
    # (at the batch time-of-day) then generated + published. None -> follow the
    # batch cadence / create-now.
    scheduled_date: Optional[date] = None


class _CadenceBody(BaseModel):
    mode: Mode = "now"
    per_day: Optional[int] = None
    start_date: Optional[date] = None
    time_of_day: Optional[time] = None
    timezone: str = "UTC"
    weekday: Optional[int] = None
    weekdays: Optional[list[int]] = None
    day_of_month: Optional[int] = None
    week_of_month: Optional[int] = None


class ContentBatchEstimateRequest(_CadenceBody):
    content_type: ContentType
    items: list[ContentBatchItemInput] = Field(default_factory=list)


class ContentBatchCreateRequest(_CadenceBody):
    content_type: ContentType
    items: list[ContentBatchItemInput] = Field(..., min_length=1)
    auto_publish: bool = False
    wp_publish: bool = False
    wp_status: Literal["draft", "publish"] = "draft"
    # When true, each finished blog_post item auto-publishes to the client's GitHub
    # repo via the blog media SOP (hero + inline images, atomic commit), so a
    # scheduled post is generated AND made live in one flow. Only honoured for
    # blog posts; other content types generate as drafts regardless.
    github_publish: bool = False


class ContentBatchEstimateResponse(BaseModel):
    count: int
    skipped: int = 0
    cost_estimate_usd: float
    content_type: str
    mode: str
    finish_date: Optional[str] = None
    requires_approval: bool = False
    approval_threshold_usd: float


class ContentBatchCreateResponse(BaseModel):
    status: str                       # 'created' | 'requires_approval'
    created: bool
    batch_id: Optional[UUID] = None
    count: int = 0
    skipped: int = 0
    enqueued: int = 0                 # jobs dispatched now (create-now)
    estimate: Optional[ContentBatchEstimateResponse] = None

"""Pydantic request/response schemas for the GBP Posts module."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

TopicType = Literal["standard", "event", "offer"]
CtaType = Literal["book", "order", "shop", "learn_more", "sign_up", "call"]
Cadence = Literal["weekly", "biweekly", "monthly", "disabled"]


# ── requests ────────────────────────────────────────────────────────────────
class GbpPostCreateRequest(BaseModel):
    location_row_id: UUID
    topic_type: TopicType = "standard"
    summary: str
    cta_type: Optional[CtaType] = None
    cta_url: Optional[str] = None
    event: Optional[dict[str, Any]] = None
    offer: Optional[dict[str, Any]] = None
    media: Optional[list[dict[str, Any]]] = None


class GbpPostUpdateRequest(BaseModel):
    """Partial edit of a draft or live post (only provided fields change)."""

    topic_type: Optional[TopicType] = None
    summary: Optional[str] = None
    cta_type: Optional[CtaType] = None
    cta_url: Optional[str] = None
    event: Optional[dict[str, Any]] = None
    offer: Optional[dict[str, Any]] = None
    media: Optional[list[dict[str, Any]]] = None


class GbpPostGenerateRequest(BaseModel):
    """Ask Claude to draft a post for a location. `theme` is a topic/angle; a
    `source_url` seeds the 'announce this content' mode."""

    location_row_id: UUID
    topic_type: TopicType = "standard"
    theme: Optional[str] = None
    source_url: Optional[str] = None
    cta_type: Optional[CtaType] = None
    cta_url: Optional[str] = None


class GbpScheduleUpsertRequest(BaseModel):
    location_row_id: UUID
    cadence: Cadence = "disabled"
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    day_of_month: Optional[int] = Field(None, ge=1, le=28)
    hour_utc: int = Field(9, ge=0, le=23)
    topic_type: TopicType = "standard"
    theme_notes: Optional[str] = None
    cta_type: Optional[CtaType] = None
    cta_url: Optional[str] = None
    auto_publish: bool = False
    is_active: bool = True


class GbpPostScheduleAtRequest(BaseModel):
    """Schedule a specific post to publish at a future time (UTC if naive)."""

    scheduled_at: datetime


class GbpJobsStatusRequest(BaseModel):
    job_ids: list[UUID]


# ── responses ───────────────────────────────────────────────────────────────
class GbpJob(BaseModel):
    job_id: UUID


class GbpJobStatus(BaseModel):
    job_id: UUID
    status: str
    post_id: Optional[UUID] = None
    error: Optional[str] = None


class GbpLocationOption(BaseModel):
    """A registered GBP location the team can post to (access_status='ok')."""

    id: UUID
    location_id: str
    account_id: Optional[str] = None
    title: Optional[str] = None
    access_status: str


class GbpPost(BaseModel):
    id: UUID
    client_id: UUID
    location_row_id: UUID
    schedule_id: Optional[UUID] = None
    source: str
    topic_type: str
    summary: str
    cta_type: Optional[str] = None
    cta_url: Optional[str] = None
    event: Optional[dict[str, Any]] = None
    offer: Optional[dict[str, Any]] = None
    media: Optional[list[dict[str, Any]]] = None
    status: str
    scheduled_at: Optional[str] = None
    published_at: Optional[str] = None
    google_name: Optional[str] = None
    google_state: Optional[str] = None
    search_url: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class GbpSchedule(BaseModel):
    location_row_id: Optional[UUID] = None
    cadence: str
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    hour_utc: int
    topic_type: str
    theme_notes: Optional[str] = None
    cta_type: Optional[str] = None
    cta_url: Optional[str] = None
    auto_publish: bool
    is_active: bool
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None

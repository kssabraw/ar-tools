"""Pydantic request/response schemas for the Social Media module (publish path)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SocialAccountResponse(BaseModel):
    account_id: str
    platform: str
    handle: Optional[str] = None
    reconnect_required: bool = False


class SocialPostCreateRequest(BaseModel):
    platform: str
    account_id: str
    copy: str = ""
    image_urls: list[str] = Field(default_factory=list)
    video_urls: list[str] = Field(default_factory=list)
    platform_specific: Optional[dict] = None
    format: str = "feed"
    scheduled_at: Optional[datetime] = None   # future time to publish; omit = now


class SocialDraftCopyRequest(BaseModel):
    """Ask the AI to draft post copy for one platform from a source + angle."""
    platform: str
    source_type: str = "topic"           # topic | url | blog_run | local_seo_page
    source_id: Optional[str] = None      # run_id (blog_run) or page_id (local_seo_page)
    url: Optional[str] = None            # source_type=url
    text: Optional[str] = None           # source_type=topic — freeform topic/notes
    angle: Optional[str] = None          # optional hook/angle hint
    tone: Optional[str] = None           # optional tone hint
    format: str = "feed"
    include_hashtags: bool = True


class SocialDraftCopyResponse(BaseModel):
    copy: str
    platform: str
    char_count: int
    char_limit: Optional[int] = None
    over_limit: bool = False
    source_title: Optional[str] = None
    source_version: Optional[str] = None
    angle: Optional[str] = None
    voice_warnings: list[str] = Field(default_factory=list)
    spec_warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SocialGenerateImageRequest(BaseModel):
    """Generate one on-brand social image for a platform via Nano Banana Pro."""
    platform: str
    format: str = "feed"
    description: str                       # what the image should show
    aspect_ratio: Optional[str] = None     # override the per-platform default


class SocialGenerateImageResponse(BaseModel):
    url: str
    type: str
    aspect_ratio: str
    cost_usd: float


class SocialMediaUploadResponse(BaseModel):
    url: str
    type: str


class SocialPresignRequest(BaseModel):
    content_type: str


class SocialPresignResponse(BaseModel):
    upload_url: str
    public_url: str
    type: str
    headers: dict = Field(default_factory=dict)


class SocialPostResponse(BaseModel):
    id: UUID
    client_id: UUID
    platform: str
    account_id: Optional[str] = None
    status: str
    status_detail: Optional[str] = None
    provider_post_id: Optional[str] = None
    post_url: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"extra": "ignore"}

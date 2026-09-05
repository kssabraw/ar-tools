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

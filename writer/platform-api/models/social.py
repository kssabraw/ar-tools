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
    format: str = "feed"


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

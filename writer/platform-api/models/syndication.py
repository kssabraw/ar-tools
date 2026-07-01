"""Pydantic schemas for the Content Syndication module."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class SyndicationConfigResponse(BaseModel):
    client_id: str
    enabled: bool
    interval_days: int
    include_blog: bool
    include_pages: bool
    include_products: bool
    share_mode: Literal["public", "link"]
    publish_target: Literal["doc", "sheet", "both"]
    last_scan_date: Optional[str] = None


class SyndicationConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    interval_days: Optional[int] = None
    include_blog: Optional[bool] = None
    include_pages: Optional[bool] = None
    include_products: Optional[bool] = None
    share_mode: Optional[Literal["public", "link"]] = None
    publish_target: Optional[Literal["doc", "sheet", "both"]] = None


class PublishRequest(BaseModel):
    item_ids: list[str]


class PublishResponse(BaseModel):
    queued: int


class SyndicationItem(BaseModel):
    id: str
    source_url: str
    content_type: Literal["blog_post", "page", "product"]
    title: Optional[str] = None
    status: Literal["discovered", "rewriting", "published", "failed", "skipped"]
    rewritten_title: Optional[str] = None
    doc_url: Optional[str] = None
    sheet_url: Optional[str] = None
    error: Optional[str] = None
    first_seen_at: Optional[str] = None
    published_at: Optional[str] = None


class ScanResponse(BaseModel):
    job_id: Optional[str] = None
    status: str


class SyndicationCounts(BaseModel):
    all: int
    published: int
    not_published: int  # discovered + rewriting + skipped
    failed: int


class SyndicationItemsResponse(BaseModel):
    items: list[SyndicationItem]
    counts: SyndicationCounts

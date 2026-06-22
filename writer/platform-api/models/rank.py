"""Pydantic models for the Organic Rank Tracker keyword views (M3)."""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

KeywordStatus = Literal[
    "climbing", "stable", "volatile", "dropping", "deindex_risk", "no_data"
]


class TrackedKeywordCreateRequest(BaseModel):
    # Accept one or many; the UI's bulk-add box splits on newlines/commas.
    keywords: list[str] = Field(..., min_length=1)


class TrackedKeywordUpdateRequest(BaseModel):
    canonical_url: Optional[str] = None
    canonical_url_locked: Optional[bool] = None
    active: Optional[bool] = None


class KeywordSummary(BaseModel):
    id: UUID
    keyword: str
    source: str
    # Which source the row's numbers come from: 'gsc' (rank + clicks/impr),
    # 'dataforseo' (live rank only), or 'none' (awaiting first data).
    primary_source: Literal["gsc", "dataforseo", "none"] = "none"
    canonical_url: Optional[str] = None
    canonical_url_locked: bool
    status: KeywordStatus
    status_updated_at: Optional[str] = None
    # GSC rolling average positions (decimals).
    avg_7: Optional[float] = None
    avg_30: Optional[float] = None
    avg_60: Optional[float] = None
    avg_90: Optional[float] = None
    clicks_30d: int = 0
    impressions_30d: int = 0
    ctr_30d: float = 0.0
    # DataForSEO live integer rank.
    today_rank: Optional[int] = None
    # Keyword market data (DataForSEO Google Ads) + derived ROI estimate.
    cpc: Optional[float] = None
    search_volume: Optional[int] = None
    competition: Optional[str] = None
    est_monthly_value: Optional[float] = None
    # Recent positions (None entries are gaps) for the row sparkline.
    sparkline: list[Optional[float]] = Field(default_factory=list)
    direction: Optional[Literal["up", "down", "flat"]] = None


class TrendPoint(BaseModel):
    date: str
    gsc_position: Optional[float] = None
    tracked_rank: Optional[int] = None
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0.0


class KeywordTrendline(BaseModel):
    id: UUID
    keyword: str
    status: KeywordStatus
    canonical_url: Optional[str] = None
    points: list[TrendPoint] = Field(default_factory=list)


class HeroPoint(BaseModel):
    date: str
    avg_position: Optional[float] = None
    clicks: int = 0
    impressions: int = 0


class OverviewResponse(BaseModel):
    keyword_count: int
    # When false, the client has no verified GSC property: the UI drops the
    # clicks/impressions and average-position views and shows DataForSEO ranks.
    gsc_connected: bool = False
    status_counts: dict[str, int]
    clicks_30d: int
    impressions_30d: int
    avg_position_30d: Optional[float] = None
    at_risk: int
    hero: list[HeroPoint] = Field(default_factory=list)


class MaterializeResponse(BaseModel):
    client_id: UUID
    status: Literal["ok", "failed"]
    keywords: int
    rows: int
    error: Optional[str] = None


class DataForSeoRefreshResponse(BaseModel):
    client_id: UUID
    status: str
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    error: Optional[str] = None

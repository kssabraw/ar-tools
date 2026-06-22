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
    # URL Inspection confirmation for deindex_risk keywords.
    index_status: Optional[Literal["indexed", "not_indexed", "unknown"]] = None
    index_checked_at: Optional[str] = None
    # How many distinct landing pages the keyword surfaces for (the "+N pages"
    # chip); >1 means the keyword is split across pages.
    page_count: int = 0
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


class StrikingKeyword(BaseModel):
    query: str
    avg_position: float
    clicks: int
    impressions: int


class StrikingDistanceResponse(BaseModel):
    gsc_connected: bool
    keywords: list[StrikingKeyword] = Field(default_factory=list)


class PageRow(BaseModel):
    page: str
    clicks: int
    impressions: int
    keywords: int
    avg_position: Optional[float] = None


class PagesResponse(BaseModel):
    gsc_connected: bool
    pages: list[PageRow] = Field(default_factory=list)


class KeywordPageRow(BaseModel):
    page: str
    clicks: int
    impressions: int
    avg_position: Optional[float] = None
    is_canonical: bool = False


class KeywordPagesResponse(BaseModel):
    keyword: str
    canonical_url: Optional[str] = None
    pages: list[KeywordPageRow] = Field(default_factory=list)


class MaterializeResponse(BaseModel):
    client_id: UUID
    status: Literal["ok", "failed"]
    keywords: int
    rows: int
    error: Optional[str] = None


class RankLocation(BaseModel):
    # The per-client DataForSEO tracking location. Both None = auto (national,
    # detected from the client's website TLD).
    location: Optional[str] = None
    location_code: Optional[int] = None


class DataForSeoRefreshResponse(BaseModel):
    client_id: UUID
    status: str
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    error: Optional[str] = None

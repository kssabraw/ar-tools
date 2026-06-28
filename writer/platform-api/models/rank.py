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
    # Unread in-app rank-drop alerts for this client (drives the Alerts tab badge).
    unread_alert_count: int = 0


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


ReportMode = Literal["as_needed", "weekly", "monthly", "interval"]


class ReportSchedule(BaseModel):
    mode: ReportMode = "as_needed"
    day_of_week: Optional[int] = Field(None, ge=0, le=6)      # weekly (0=Mon)
    day_of_month: Optional[int] = Field(None, ge=1, le=31)    # monthly
    interval_days: Optional[int] = Field(None, gt=0)          # every N days
    deliver_google_doc: bool = False
    last_generated_at: Optional[str] = None


class ReportListItem(BaseModel):
    id: UUID
    title: str
    created_at: str
    doc_url: Optional[str] = None


class GeneratedReport(BaseModel):
    id: UUID
    title: str
    created_at: str
    snapshot: dict
    doc_url: Optional[str] = None


class ReportPublishResponse(BaseModel):
    doc_url: Optional[str] = None
    doc_id: Optional[str] = None


class RankLocation(BaseModel):
    # The per-client DataForSEO tracking location. Both None = auto (national,
    # detected from the client's website TLD).
    location: Optional[str] = None
    location_code: Optional[int] = None
    # Provenance (response-only; the PUT body ignores it). 'manual' = a user
    # picked it (never auto-overwritten); 'auto' = derived from the client's GBP;
    # None = never set / national fallback.
    source: Optional[Literal["auto", "manual"]] = None


# Per-client DataForSEO rank-DATA refresh cadence. 'off' = manual only (the
# "Refresh live ranks" button still works); absent row = the legacy default
# (weekly on the global dataforseo_rank_weekday), surfaced by the GET endpoint.
FetchMode = Literal["off", "weekly", "monthly", "interval"]


class FetchSchedule(BaseModel):
    mode: FetchMode = "weekly"
    day_of_week: Optional[int] = Field(None, ge=0, le=6)      # weekly (0=Mon)
    day_of_month: Optional[int] = Field(None, ge=1, le=31)    # monthly
    interval_days: Optional[int] = Field(None, gt=0)          # every N days
    last_fetched_at: Optional[str] = None


class DataForSeoRefreshResponse(BaseModel):
    client_id: UUID
    status: str
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    error: Optional[str] = None


# --- Competitive SERP Snapshot (diagnostic store) ---------------------------
class SerpSnapshotListItem(BaseModel):
    id: UUID
    captured_at: str
    status: str
    query_intent: Optional[str] = None
    aio_present: bool = False
    client_rank: Optional[int] = None
    result_count: int = 0


class SerpSnapshotResultRow(BaseModel):
    position: Optional[int] = None
    url: Optional[str] = None
    domain: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    is_client: bool = False
    referring_domains: Optional[int] = None
    url_rating: Optional[int] = None  # DataForSEO page rank (0–1000), UR-equivalent
    backlinks: Optional[int] = None
    backlinks_status: str = "pending"


class SerpSnapshotDomainRow(BaseModel):
    domain: Optional[str] = None
    is_client: bool = False
    domain_rating: Optional[int] = None  # DataForSEO domain rank (0–1000), DR-equivalent
    referring_domains: Optional[int] = None
    backlinks: Optional[int] = None
    backlinks_status: str = "pending"


class SerpSnapshotDetail(BaseModel):
    id: UUID
    keyword_id: UUID
    client_id: UUID
    keyword: str
    captured_at: str
    status: str
    location_code: Optional[int] = None
    language_code: Optional[str] = None
    query_intent: Optional[str] = None
    intent_probabilities: Optional[dict] = None
    local_intent: bool = False
    intent_signals: Optional[list[str]] = None
    aio_present: bool = False
    aio_text: Optional[str] = None
    aio_sources: Optional[list] = None
    serp_features: Optional[dict] = None
    client_rank: Optional[int] = None
    client_url: Optional[str] = None
    error: Optional[str] = None
    results: list[SerpSnapshotResultRow] = []
    domains: list[SerpSnapshotDomainRow] = []


class SerpSnapshotCaptureResponse(BaseModel):
    keyword_id: UUID
    status: str  # 'enqueued'


# --- SERP Landscape Trends (over-time + cross-keyword) ----------------------
class SerpTimelinePoint(BaseModel):
    snapshot_id: UUID
    captured_at: str
    status: str
    query_intent: Optional[str] = None
    local_intent: bool = False
    intent_signals: list[str] = []
    aio_present: bool = False
    client_rank: Optional[int] = None
    client_rd: Optional[int] = None  # client's page referring-domains count
    client_ur: Optional[int] = None  # client's page URL Rating (raw 0–1000; UI shows /10)
    client_dr: Optional[int] = None  # client's domain Domain Rating (raw 0–1000; UI shows /10)
    signals_added: list[str] = []
    signals_removed: list[str] = []
    client_rank_delta: Optional[int] = None  # vs previous snapshot (− = improved)
    client_rd_delta: Optional[int] = None     # vs previous snapshot (+ = stronger)
    client_dr_delta: Optional[int] = None     # vs previous snapshot (+ = stronger)


class SerpTimelineResponse(BaseModel):
    keyword_id: UUID
    keyword: str
    points: list[SerpTimelinePoint] = []


class SerpTrendSeries(BaseModel):
    signal: str
    counts: list[int] = []
    pct: list[Optional[float]] = []  # fraction 0–1 of keywords-with-data per week


class SerpChangeItem(BaseModel):
    keyword_id: UUID
    keyword: str
    captured_at: str
    added: list[str] = []
    removed: list[str] = []
    client_rank_delta: Optional[int] = None


class SerpTrendsResponse(BaseModel):
    week_ends: list[str] = []
    keyword_counts: list[int] = []
    series: list[SerpTrendSeries] = []
    changes: list[SerpChangeItem] = []


# --- In-app rank-drop alerts ------------------------------------------------
class RankAlert(BaseModel):
    id: UUID
    keyword_id: UUID
    keyword: str
    alert_type: Literal["weekly_drop", "page_one_exit", "thirty_day_drop", "deindexed"]
    source: Optional[str] = None
    from_position: Optional[float] = None
    to_position: Optional[float] = None
    delta: Optional[float] = None
    message: str
    status: Literal["unread", "read", "dismissed"]
    triggered_on: Optional[str] = None
    resolved_at: Optional[str] = None
    created_at: str


class RankAlertsResponse(BaseModel):
    alerts: list[RankAlert] = Field(default_factory=list)
    unread_count: int = 0

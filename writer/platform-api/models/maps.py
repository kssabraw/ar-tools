"""Pydantic models for the Maps / local-pack geo-grid ranker (Module #5)."""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MapsConfig(BaseModel):
    client_id: UUID
    google_place_id: Optional[str] = None
    business_name: Optional[str] = None
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    radius_miles: Literal[3, 5, 7] = 5
    shape: Literal["circle", "square"] = "circle"
    resource_category: Literal["googleMaps", "googleLocalFinder"] = "googleMaps"
    serp_device: Literal["desktop", "mobile", "both"] = "desktop"
    cadence: Literal["off", "weekly"] = "weekly"
    weekday: int = 1
    active: bool = True
    last_scanned_at: Optional[str] = None
    # True when the row is persisted; False = a default prefilled from the client.
    configured: bool = False


class MapsConfigUpdate(BaseModel):
    google_place_id: Optional[str] = None
    business_name: Optional[str] = None
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    radius_miles: Optional[Literal[3, 5, 7]] = None
    shape: Optional[Literal["circle", "square"]] = None
    resource_category: Optional[Literal["googleMaps", "googleLocalFinder"]] = None
    serp_device: Optional[Literal["desktop", "mobile", "both"]] = None
    cadence: Optional[Literal["off", "weekly"]] = None
    weekday: Optional[int] = None
    active: Optional[bool] = None


class MapsKeyword(BaseModel):
    id: UUID
    keyword: str
    active: bool


class MapsKeywordCreate(BaseModel):
    keywords: list[str] = Field(..., min_length=1)


class MapsScanResultRow(BaseModel):
    keyword: str
    average_rank: Optional[float] = None
    found_pins: int = 0
    total_pins: int = 0
    top3_pins: int = 0
    top10_pins: int = 0
    rank_grid: Optional[list] = None  # 1-based rank per pin (null where not ranked)
    heatmap_image_url: Optional[str] = None  # Local Dominator's rendered map heatmap
    dynamic_url: Optional[str] = None        # interactive heatmap page
    competitors: Optional[list] = None       # per-keyword competitor leaderboard (top ~25)
    competitors_above: Optional[dict] = None  # per-pin businesses ranking above the client
    # Local Rank Analysis report (auto-generated when the scan completes).
    report_status: Optional[str] = None       # 'pending' | 'complete' | 'failed' | null
    report_md: Optional[str] = None           # the full client-facing report (Markdown)
    report_weak_directions: Optional[str] = None
    report_top_competitors: Optional[list] = None
    report_octant_pins: Optional[dict] = None  # hyper-local pin suggestions {ok, points, debug}
    # Geocoded weak zones: octant pins labelled with their nearest city + weak
    # grid cells aggregated into nearby localities ({geocoded, octant_pins, weak_areas}).
    report_weak_locations: Optional[dict] = None
    report_analytics: Optional[dict] = None    # ring/sector rollups (for the printable report)
    report_doc_url: Optional[str] = None
    report_generated_at: Optional[str] = None


class MapsScanSummary(BaseModel):
    id: UUID
    scan_uuid: Optional[str] = None
    status: str
    trigger: str
    radius_miles: Optional[int] = None
    grid_size: Optional[int] = None
    search_terms: Optional[list] = None  # keywords scanned (for the history list)
    requested_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


class MapsScanDetail(MapsScanSummary):
    shape: Optional[str] = None
    distance: Optional[int] = None
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    resource_category: Optional[str] = None
    serp_device: Optional[str] = None
    results: list[MapsScanResultRow] = Field(default_factory=list)


class MapsRunResponse(BaseModel):
    client_id: UUID
    status: str  # 'enqueued' | 'failed'
    error: Optional[str] = None


class MapsTrendPoint(BaseModel):
    """One keyword's metrics at a single completed scan (a point on the trend)."""
    scan_id: UUID
    completed_at: Optional[str] = None
    trigger: str = "scheduled"
    total_pins: int = 0
    found_pins: int = 0
    top3_pins: int = 0
    top10_pins: int = 0
    average_rank: Optional[float] = None
    found_pct: Optional[float] = None   # % of pins where the business appears
    top3_pct: Optional[float] = None    # % of pins ranking in the local pack (<= 3)
    top10_pct: Optional[float] = None   # % of pins ranking <= 10


class MapsKeywordTrend(BaseModel):
    keyword: str
    points: list[MapsTrendPoint] = Field(default_factory=list)  # oldest → newest


class MapsTrendsResponse(BaseModel):
    keywords: list[MapsKeywordTrend] = Field(default_factory=list)


class MapsCompetitorTrendPoint(BaseModel):
    """One competitor's pressure at a single completed scan."""
    scan_id: UUID
    completed_at: Optional[str] = None
    beats_pins: int = 0          # in-circle pins (across keywords) where it outranks the client
    total_slots: int = 0         # total in-circle pins that scan
    beats_pct: Optional[float] = None   # beats_pins / total_slots, 0–100
    avg_rank_above: Optional[float] = None


class MapsCompetitorTrend(BaseModel):
    place_id: str
    name: Optional[str] = None
    latest_pct: Optional[float] = None
    delta_pct: Optional[float] = None   # latest − earliest beats_pct; positive = gaining on us
    points: list[MapsCompetitorTrendPoint] = Field(default_factory=list)  # oldest → newest


class MapsCompetitorTrendsResponse(BaseModel):
    scan_count: int = 0          # number of scans that carry competitor data
    competitors: list[MapsCompetitorTrend] = Field(default_factory=list)


# --- Share of Local Voice (SoLV) --------------------------------------------
class MapsSolvCompetitorShare(BaseModel):
    """One business's local-pack presence share (Top-3 pins / total pins)."""
    place_id: Optional[str] = None
    name: Optional[str] = None
    top3_pins: int = 0
    share_pct: Optional[float] = None


class MapsSolvPoint(BaseModel):
    """The client's overall Top-3 local-pack coverage at one completed scan."""
    scan_id: UUID
    completed_at: Optional[str] = None
    trigger: str = "scheduled"
    total_pins: int = 0
    client_top3_pins: int = 0
    client_coverage_pct: Optional[float] = None       # Top-3 presence %
    client_coverage_top10_pct: Optional[float] = None


class MapsSolvKeyword(BaseModel):
    keyword: Optional[str] = None
    total_pins: int = 0
    client_top3_pins: int = 0
    client_coverage_pct: Optional[float] = None
    competitor_shares: list[MapsSolvCompetitorShare] = Field(default_factory=list)


class MapsSolvResponse(BaseModel):
    series: list[MapsSolvPoint] = Field(default_factory=list)              # oldest → newest
    competitors: list[MapsSolvCompetitorShare] = Field(default_factory=list)  # latest scan, top N
    keywords: list[MapsSolvKeyword] = Field(default_factory=list)         # latest scan per-keyword


# --- Competitor GBP intelligence (Tier B / B1) ------------------------------
class MapsCompetitorProfile(BaseModel):
    place_id: Optional[str] = None
    name: Optional[str] = None
    primary_category: Optional[str] = None
    gbp_categories: list[str] = Field(default_factory=list)
    rating: Optional[float] = None
    review_count: Optional[int] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    photo: Optional[str] = None
    has_hours: Optional[bool] = None
    found_pins: Optional[int] = None
    top3_pins: Optional[int] = None
    captured_at: Optional[str] = None


class MapsCompetitorIntelResponse(BaseModel):
    profiles: list[MapsCompetitorProfile] = Field(default_factory=list)
    captured_at: Optional[str] = None    # most recent capture timestamp


# --- Backlink profiling (Tier B / B4) ---------------------------------------
class MapsBacklinkStats(BaseModel):
    domain: Optional[str] = None
    domain_rating: Optional[float] = None
    referring_domains: Optional[int] = None
    backlinks: Optional[int] = None


class MapsBacklinkComparison(BaseModel):
    competitor_median_dr: Optional[float] = None
    competitor_median_referring_domains: Optional[float] = None
    dr_behind: Optional[float] = None
    referring_domains_behind: Optional[float] = None


class MapsBacklinkIntelResponse(BaseModel):
    client: MapsBacklinkStats = Field(default_factory=MapsBacklinkStats)
    competitors: list[MapsBacklinkStats] = Field(default_factory=list)
    comparison: MapsBacklinkComparison = Field(default_factory=MapsBacklinkComparison)


# --- Review analytics (Tier B / B3) -----------------------------------------
class MapsReviewStats(BaseModel):
    place_id: Optional[str] = None
    name: Optional[str] = None
    count: int = 0
    avg_rating: Optional[float] = None
    rating_distribution: dict[str, int] = Field(default_factory=dict)
    velocity_per_month: float = 0
    recent_negatives: int = 0
    last_review_date: Optional[str] = None


class MapsReviewComparison(BaseModel):
    competitor_median_velocity: Optional[float] = None
    competitor_median_rating: Optional[float] = None
    velocity_behind: Optional[float] = None


class MapsReviewIntelResponse(BaseModel):
    client: MapsReviewStats = Field(default_factory=MapsReviewStats)
    competitors: list[MapsReviewStats] = Field(default_factory=list)
    comparison: MapsReviewComparison = Field(default_factory=MapsReviewComparison)


# --- GBP profile audit / gaps (Tier B / B2) ---------------------------------
class MapsGbpAuditCheck(BaseModel):
    key: str
    label: str
    ok: bool
    detail: str = ""


class MapsGbpReviewGap(BaseModel):
    client: int = 0
    competitor_median: int = 0
    deficit: int = 0


class MapsGbpAuditResponse(BaseModel):
    score: Optional[int] = None              # 0–100 completeness
    competitor_count: int = 0
    checks: list[MapsGbpAuditCheck] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)            # failed-check labels
    category_gaps: list[str] = Field(default_factory=list)   # categories competitors have, client lacks
    review_gap: Optional[MapsGbpReviewGap] = None


class MapsThreat(BaseModel):
    """One top-threat competitor for a dashboard tile."""
    name: Optional[str] = None
    beats_pct: Optional[float] = None   # latest "beats you %"
    delta_pct: Optional[float] = None   # change vs first scan; positive = gaining


class MapsClientThreats(BaseModel):
    client_id: UUID
    scan_count: int = 0
    threats: list[MapsThreat] = Field(default_factory=list)


class MapsThreatsResponse(BaseModel):
    clients: list[MapsClientThreats] = Field(default_factory=list)


# --- Scan-over-scan analyzer ("What changed") -------------------------------
class MapsOctantChange(BaseModel):
    """One compass octant that weakened vs the previous scan."""
    sector: str
    avg_rank_now: Optional[float] = None
    avg_rank_prev: Optional[float] = None
    top3_pct_now: Optional[float] = None
    top3_pct_prev: Optional[float] = None


class MapsKeywordChange(BaseModel):
    keyword: str
    average_rank_now: Optional[float] = None
    average_rank_prev: Optional[float] = None
    average_rank_delta: Optional[float] = None   # now − prev; positive = worse
    found_pct_now: Optional[float] = None
    found_pct_prev: Optional[float] = None
    top3_pct_now: Optional[float] = None
    top3_pct_prev: Optional[float] = None
    top10_pct_now: Optional[float] = None
    top10_pct_prev: Optional[float] = None
    octants: list[MapsOctantChange] = Field(default_factory=list)   # weakened octants, worst first
    alert_types: list[str] = Field(default_factory=list)            # decline rules that fired


class MapsChangesResponse(BaseModel):
    has_previous: bool = False
    current_scan_id: Optional[UUID] = None
    previous_scan_id: Optional[UUID] = None
    keywords: list[MapsKeywordChange] = Field(default_factory=list)


# --- In-app geo-grid alerts -------------------------------------------------
class MapsAlert(BaseModel):
    id: UUID
    keyword: str
    alert_type: Literal[
        "grid_rank_drop", "coverage_drop", "lost_pack", "area_decline", "competitor_surge"
    ]
    sector: Optional[str] = None
    from_value: Optional[float] = None
    to_value: Optional[float] = None
    delta: Optional[float] = None
    message: str
    severity: str = "warning"   # derived: 'critical' for lost_pack, else 'warning'
    status: Literal["unread", "read", "dismissed"]
    triggered_on: Optional[str] = None
    resolved_at: Optional[str] = None
    created_at: str


class MapsAlertsResponse(BaseModel):
    alerts: list[MapsAlert] = Field(default_factory=list)
    unread_count: int = 0


# --- Multi-window period summary (7/30/90/since-start) -----------------------
class MapsPeriodDelta(BaseModel):
    from_value: Optional[float] = None   # the baseline value for this window
    now: Optional[float] = None
    delta: Optional[float] = None        # now − from_value (sign meaning is per-metric)
    baseline_at: Optional[str] = None    # date of the baseline scan


class MapsPeriodMetric(BaseModel):
    metric: str                          # 'average_rank' | 'top3_pct' | 'top10_pct' | 'found_pct'
    label: str
    now: Optional[float] = None
    windows: dict[str, MapsPeriodDelta] = Field(default_factory=dict)  # keys: 7d/30d/90d/start


class MapsPeriodScope(BaseModel):
    keyword: Optional[str] = None        # None = overall client rollup
    metrics: list[MapsPeriodMetric] = Field(default_factory=list)


class MapsPeriodsResponse(BaseModel):
    as_of: Optional[str] = None
    scan_count: int = 0
    overall: Optional[MapsPeriodScope] = None
    keywords: list[MapsPeriodScope] = Field(default_factory=list)


# --- Area-level (compass octant) trends + narrative -------------------------
class MapsAreaTrend(BaseModel):
    sector: str                          # N / NE / E / … / NW
    sector_full: str                     # "Southwest"
    city: Optional[str] = None           # nearest town for this octant (best-effort)
    now_top3_pct: Optional[float] = None
    now_avg_rank: Optional[float] = None
    windows: dict[str, MapsPeriodDelta] = Field(default_factory=dict)  # Top-3 coverage deltas


class MapsAreaTrendsResponse(BaseModel):
    as_of: Optional[str] = None
    scan_count: int = 0
    areas: list[MapsAreaTrend] = Field(default_factory=list)
    narrative: list[str] = Field(default_factory=list)

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

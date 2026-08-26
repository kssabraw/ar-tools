"""Pydantic models for Google Business Profile performance-metrics resources.

GBP metrics ingestion. Mirrors models/gsc.py — a registered location (with an
access state), a live "resolve locations" discovery result, verify + ingest +
sync-run views. See models/clients.py for conventions.
"""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class GbpLocation(BaseModel):
    id: UUID
    client_id: UUID
    location_id: str
    account_id: Optional[str] = None
    place_id: Optional[str] = None
    title: Optional[str] = None
    access_status: Literal["ok", "no_access", "pending", "error"]
    last_verified_at: Optional[str] = None
    last_synced_at: Optional[str] = None
    created_at: str
    updated_at: str


class GbpLocationCreateRequest(BaseModel):
    location_id: str = Field(..., min_length=1)
    account_id: Optional[str] = None
    place_id: Optional[str] = None
    title: Optional[str] = None


class ResolvedLocation(BaseModel):
    """A location discoverable via the Business Information API for the agency
    service account — offered to the user to register."""

    location_id: str
    account_id: Optional[str] = None
    title: Optional[str] = None
    address: Optional[str] = None
    place_id: Optional[str] = None


class ResolveLocationsResponse(BaseModel):
    locations: list[ResolvedLocation]
    detail: Optional[str] = None


class GbpVerifyResponse(BaseModel):
    location_row_id: UUID
    access_status: Literal["ok", "no_access", "pending", "error"]
    detail: Optional[str] = None
    last_verified_at: Optional[str] = None


class GbpServiceAccountInfo(BaseModel):
    email: str


class GbpIngestResponse(BaseModel):
    location_row_id: UUID
    status: Literal["ok", "failed"]
    rows: int
    error: Optional[str] = None


class GbpBackfillResponse(BaseModel):
    location_row_id: UUID
    status: str
    start_date: str
    end_date: str


class GbpSyncRun(BaseModel):
    id: UUID
    location_row_id: UUID
    run_at: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    rows: int
    status: Literal["ok", "failed"]
    error: Optional[str] = None


class GbpDiagnosticStep(BaseModel):
    step: str
    ok: bool
    detail: Optional[str] = None


class GbpPerformanceDiagnostic(BaseModel):
    """Result of the admin GBP Performance API access probe (ungated by the
    ``gbp_metrics_enabled`` flag — it's what you run to decide whether to set it)."""

    ok: bool
    auth_mode: Optional[str] = None
    accounts_visible: Optional[int] = None
    locations_visible: Optional[int] = None
    location: Optional[str] = None
    location_title: Optional[str] = None
    performance_status: Optional[int] = None
    detail: Optional[str] = None
    steps: list[GbpDiagnosticStep] = []


# ── Reporting dashboard ──────────────────────────────────────────────────────
class GbpMetricGrowth(BaseModel):
    """One headline metric's period-over-period growth (a dashboard KPI tile)."""

    metric: str  # folded key ("profile_views") or raw Performance metric name
    label: str
    group: str = ""  # "visibility" | "actions" (which dashboard section it belongs to)
    current: int
    previous: int
    delta: int
    pct: Optional[float] = None  # None when the prior window was zero


class GbpBreakdownItem(BaseModel):
    """One slice of the profile-views breakout (e.g. Search, or Mobile)."""

    label: str
    current: int
    previous: int
    pct: Optional[float] = None
    share: float = 0.0  # % of the current-period total


class GbpBreakdown(BaseModel):
    surface: list[GbpBreakdownItem] = []  # Search vs Maps
    device: list[GbpBreakdownItem] = []  # Desktop vs Mobile


class GbpActionsSummary(BaseModel):
    """Total customer actions (calls + website + directions + messages) and the
    engagement rate (actions ÷ profile views), current vs prior."""

    current: int
    previous: int
    delta: int
    pct: Optional[float] = None
    engagement_current: Optional[float] = None
    engagement_previous: Optional[float] = None


class GbpReviewItem(BaseModel):
    reviewer: str = ""
    rating: Optional[float] = None
    text: str = ""
    date: str = ""
    has_reply: bool = False  # whether the business has replied (v4 reviews only)


class GbpPeriodReviews(BaseModel):
    """Reviews posted within the dashboard's reporting window (first-party v4),
    plus the all-time rating/count for context."""

    count: int = 0
    average_rating: Optional[float] = None
    items: list[GbpReviewItem] = []
    overall_rating: Optional[float] = None
    overall_count: int = 0
    start: Optional[str] = None
    end: Optional[str] = None


class GbpReviews(BaseModel):
    """Profile-health review summary from the client's captured GBP."""

    rating: Optional[float] = None
    review_count: int = 0
    items: list[GbpReviewItem] = []


class GbpSearchKeyword(BaseModel):
    keyword: str
    value: int
    is_threshold: bool = False  # true = Google privacy floor ("fewer than N")
    previous: Optional[int] = None  # prior-period impressions (None = no comparison)
    delta: Optional[int] = None  # value - previous


class GbpSearchKeywordsResponse(BaseModel):
    """Top search terms that drove impressions for a client's locations in a
    calendar month (``month`` = YYYY-MM-01); ``months`` lists the available ones."""

    month: Optional[str] = None
    months: list[str] = []
    keywords: list[GbpSearchKeyword] = []
    total: int = 0
    range_months: int = 1  # months aggregated (1 = single month; N = a range view)
    prev_total: int = 0  # prior-period total impressions (for the header comparison)
    compared: bool = False  # whether a full prior period existed to compare against


class GbpSeriesPoint(BaseModel):
    """A single day of the dashboard time series; ``values`` carries every
    dashboard metric's value for that day (zero-filled)."""

    date: str
    values: dict[str, int]


class GbpDashboardResponse(BaseModel):
    """Everything the GBP Insights page needs in one read: connection state,
    the client's registered locations, growth KPI tiles, and a daily series.

    ``enabled`` is the server ``gbp_metrics_enabled`` flag; ``connected`` is true
    once at least one location has verified (``ok``) access. When not connected
    the metric/series lists are empty and the UI shows the connect flow."""

    enabled: bool
    connected: bool
    locations: list[GbpLocation] = []
    window_days: int
    date_start: str
    date_end: str
    compare_start: str  # start of the prior equal-length comparison window
    compare_end: str  # end of the prior equal-length comparison window
    last_synced_at: Optional[str] = None
    metrics: list[GbpMetricGrowth] = []
    breakdown: GbpBreakdown = GbpBreakdown()
    actions: Optional[GbpActionsSummary] = None
    insights: list[str] = []
    reviews: GbpReviews = GbpReviews()
    series: list[GbpSeriesPoint] = []
    compare_series: list[GbpSeriesPoint] = []  # prior-window daily, for the overlay

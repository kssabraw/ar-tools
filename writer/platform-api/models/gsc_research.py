"""Pydantic models for the GSC Research module.

On-demand opportunity analysis off the ingested GSC query×page data. A run
produces three result sets — cannibalization, quick wins, hidden wins — each
rendered as an in-app table and CSV-exportable. Ported from the "GSC Research"
n8n workflow.
"""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel


class CannibalizationPage(BaseModel):
    """One competing URL for a cannibalized query."""

    page: str
    clicks: int
    impressions: int
    position: Optional[float] = None


class CannibalizationRow(BaseModel):
    """A query whose ranking is split across multiple URLs (all ranking well,
    impressions not clustered → Google can't decide which page to favor)."""

    query: str
    page_count: int
    total_clicks: int
    total_impressions: int
    pages: list[CannibalizationPage]


class OpportunityRow(BaseModel):
    """A query×page opportunity (quick win or hidden win), enriched with
    DataForSEO market data where available."""

    keyword: str
    page: str
    position: float
    impressions: int
    clicks: int
    search_volume: Optional[int] = None
    cpc: Optional[float] = None
    competition: Optional[str] = None  # LOW / MEDIUM / HIGH or None


class GscResearchRunSummary(BaseModel):
    """List-view row for a client's research-run history."""

    id: UUID
    status: Literal["pending", "running", "complete", "failed"]
    trigger: str
    gsc_connected: bool
    cannibalization_count: int
    quick_wins_count: int
    hidden_wins_count: int
    error: Optional[str] = None
    requested_at: Optional[str] = None
    completed_at: Optional[str] = None


class GscResearchRunDetail(GscResearchRunSummary):
    """Full run detail with the three result sets."""

    date_from: Optional[str] = None
    date_to: Optional[str] = None
    cannibalization: list[CannibalizationRow] = []
    quick_wins: list[OpportunityRow] = []
    hidden_wins: list[OpportunityRow] = []


class GscResearchRunResponse(BaseModel):
    """Returned when a run is enqueued (or short-circuited)."""

    run_id: Optional[UUID] = None
    status: str
    error: Optional[str] = None

"""Pydantic schemas for the Content Gap Analyzer API (routers/content_gap.py).

Request models + the flat response shapes. The per-run DETAIL (run + keyword
rows) is deliberately returned as a plain dict from the router, NOT through a
strict response_model — its `gap`/`onpage_diff`/`competitors` jsonb carries
open-ended per-dimension fields that a strict model would silently strip (the
Phase-1 ReoptAction lesson, CLAUDE.md).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ContentGapScanRequest(BaseModel):
    """Ad-hoc scan trigger. The API always runs as `manual`; a body is optional."""

    force: bool = False


class ScopeItem(BaseModel):
    keyword: str
    page_url: Optional[str] = None
    keyword_id: Optional[str] = None


class EstimateResponse(BaseModel):
    enabled: bool
    keyword_count: int
    money_page_count: int
    scope: list[ScopeItem]
    estimated_max_calls: int
    budget_remaining: int
    max_competitors: int
    snapshot_max_age_days: int


class RunSummary(BaseModel):
    id: str
    trigger: str
    status: str
    keywords_analyzed: Optional[int] = None
    wins: Optional[int] = None
    gaps: Optional[int] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class ContentGapStatus(BaseModel):
    """Page bootstrap: the module's dark-state gate + budget + run history."""

    enabled: bool
    auto_enabled: bool
    budget_remaining: int
    runs: list[RunSummary]


class ScanResponse(BaseModel):
    run_id: str
    status: str

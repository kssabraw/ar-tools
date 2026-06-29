"""Pydantic request/response models for the AI Visibility (Brand Strength) module."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── keywords ─────────────────────────────────────────────────────────────────
class BrandKeywordCreateRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=200)
    category: Optional[str] = None


class BrandKeywordUpdateRequest(BaseModel):
    is_active: Optional[bool] = None
    category: Optional[str] = None


class BrandKeywordResponse(BaseModel):
    id: str
    keyword: str
    category: Optional[str] = None
    is_active: bool
    created_at: Optional[str] = None


# ── competitors ──────────────────────────────────────────────────────────────
class BrandCompetitorCreateRequest(BaseModel):
    competitor_name: str = Field(min_length=1, max_length=200)
    competitor_website: Optional[str] = None
    google_place_id: Optional[str] = None


class BrandCompetitorResponse(BaseModel):
    id: str
    competitor_name: str
    competitor_website: Optional[str] = None
    google_place_id: Optional[str] = None
    created_at: Optional[str] = None


# ── scans ────────────────────────────────────────────────────────────────────
class BrandScanRequest(BaseModel):
    # Omit keyword_ids to scan all active keywords; omit engines to scan all six.
    keyword_ids: Optional[list[str]] = None
    engines: Optional[list[str]] = None
    include_competitors: bool = False


class BrandScanStartResponse(BaseModel):
    job_id: str
    scan_batch_id: str
    status: str = "pending"


class BrandScanStatusResponse(BaseModel):
    status: str
    total: int = 0
    completed: int = 0
    failed: int = 0
    scan_batch_id: Optional[str] = None
    error: Optional[str] = None


# ── schedule ─────────────────────────────────────────────────────────────────
class BrandScheduleUpdateRequest(BaseModel):
    cadence: str = "weekly"  # weekly | monthly | disabled
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)   # Monday=0 … Sunday=6
    day_of_month: Optional[int] = Field(default=None, ge=1, le=28)
    hour_utc: int = Field(default=9, ge=0, le=23)
    selected_engines: Optional[list[str]] = None
    include_competitors: bool = False
    is_active: bool = True


class BrandScheduleResponse(BaseModel):
    cadence: str
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    hour_utc: int
    selected_engines: list[str] = Field(default_factory=list)
    include_competitors: bool = False
    is_active: bool = False
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None


# ── history / trends ─────────────────────────────────────────────────────────
class BrandMentionResponse(BaseModel):
    id: str
    keyword_id: Optional[str] = None
    scan_batch_id: Optional[str] = None
    engine: str
    status: str
    mention_found: Optional[bool] = None
    mention_type: Optional[str] = None
    sentiment: Optional[float] = None
    confidence_score: Optional[float] = None
    citations: list = Field(default_factory=list)
    competitor_results: Optional[list] = None
    reasoning: Optional[str] = None
    snippet: Optional[str] = None
    invisibility_diagnosis: Optional[str] = None
    response_analysis: Optional[dict] = None
    failure_reason: Optional[str] = None
    created_at: Optional[str] = None

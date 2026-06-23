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


class MapsScanSummary(BaseModel):
    id: UUID
    scan_uuid: Optional[str] = None
    status: str
    trigger: str
    radius_miles: Optional[int] = None
    grid_size: Optional[int] = None
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

"""Pydantic models for the Unified Keyword Portal.

Phase 1 / PR1 of the managed-engagement build plan: one entry point that fans a
single keyword list out to the three trackers (organic rank, Maps geo-grid,
AI-Visibility/brand) and optionally kicks off the first scans.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class KeywordPortalRequest(BaseModel):
    keywords: list[str] = Field(min_length=1)
    # Subset of: "organic" | "maps" | "brand". Unknown values are ignored.
    targets: list[str] = Field(min_length=1)
    run_scans: bool = True
    # Reserved for the Phase-1 intake wiring (PR4) — not used yet.
    engagement_id: Optional[str] = None


class TargetResult(BaseModel):
    added: int = 0
    skipped_duplicates: int = 0
    # enqueued | skipped | blocked | error | n/a
    scan: str = "n/a"
    blocker: Optional[str] = None


class KeywordPortalResponse(BaseModel):
    organic: Optional[TargetResult] = None
    maps: Optional[TargetResult] = None
    brand: Optional[TargetResult] = None

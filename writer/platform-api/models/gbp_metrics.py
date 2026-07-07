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

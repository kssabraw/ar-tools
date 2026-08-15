"""Pydantic models for Google Analytics (GA4) property resources.

Client Reporting Phase 2. Mirrors models/gsc.py conventions.
"""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class Ga4Property(BaseModel):
    id: UUID
    client_id: UUID
    property_id: str  # "properties/123456789"
    display_name: Optional[str] = None
    access_status: Literal["ok", "no_access", "pending"]
    last_verified_at: Optional[str] = None
    created_at: str
    updated_at: str


class Ga4PropertyCreateRequest(BaseModel):
    # Accepts "properties/123456789" or a bare numeric id (normalized server-side).
    property_id: str = Field(..., min_length=1)
    display_name: Optional[str] = None


class Ga4VerifyResponse(BaseModel):
    property_id: UUID
    access_status: Literal["ok", "no_access", "pending"]
    detail: Optional[str] = None
    last_verified_at: Optional[str] = None


class Ga4PropertySummary(BaseModel):
    """A GA4 property the service account can see (Admin API discovery)."""

    property_id: str
    display_name: str
    account_name: str = ""


class Ga4IngestResponse(BaseModel):
    property_id: UUID
    status: str  # "queued" | "ok" | "failed"
    job_id: Optional[UUID] = None
    rows: int = 0
    error: Optional[str] = None


class Ga4IngestJobStatus(BaseModel):
    job_id: UUID
    status: str  # pending | running | complete | failed
    rows: int = 0
    error: Optional[str] = None


class Ga4SyncRun(BaseModel):
    id: UUID
    property_id: UUID
    job_type: str
    run_at: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    rows: int
    status: Literal["ok", "failed"]
    error: Optional[str] = None

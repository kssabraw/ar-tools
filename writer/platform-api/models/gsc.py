"""Pydantic models for Google Search Console property resources.

Organic Rank Tracker (Module #4), M1. See models/clients.py for conventions.
"""

from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class GscProperty(BaseModel):
    id: UUID
    client_id: UUID
    site_url: str
    property_type: Literal["url_prefix", "domain"]
    access_status: Literal["ok", "no_access", "pending"]
    last_verified_at: Optional[str] = None
    created_at: str
    updated_at: str


class GscPropertyCreateRequest(BaseModel):
    site_url: str = Field(..., min_length=1)
    # Optional — inferred from the site_url's "sc-domain:" prefix when omitted.
    property_type: Optional[Literal["url_prefix", "domain"]] = None


class VerifyAccessResponse(BaseModel):
    property_id: UUID
    access_status: Literal["ok", "no_access", "pending"]
    detail: Optional[str] = None
    last_verified_at: Optional[str] = None


class ServiceAccountInfo(BaseModel):
    email: str


class BackfillResponse(BaseModel):
    property_id: UUID
    status: str
    start_date: str
    end_date: str


class SyncRun(BaseModel):
    id: UUID
    property_id: UUID
    job_type: str
    run_at: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    rows: int
    status: Literal["ok", "failed"]
    error: Optional[str] = None


class IngestResponse(BaseModel):
    property_id: UUID
    status: str  # "queued" (enqueued) | "ok" | "failed"
    job_id: Optional[UUID] = None
    rows: int = 0
    error: Optional[str] = None


class IngestJobStatus(BaseModel):
    """Poll payload for an enqueued GSC ingest so the UI can track it to
    completion (mirrors the async_jobs row)."""
    job_id: UUID
    status: str  # pending | running | complete | failed
    rows: int = 0
    error: Optional[str] = None

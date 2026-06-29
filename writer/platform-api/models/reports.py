"""Pydantic schemas for the Client Reporting module."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ClientReport(BaseModel):
    id: UUID
    client_id: UUID
    report_type: str
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    status: str
    storage_path: Optional[str] = None
    pdf_url: Optional[str] = None
    drive_doc_id: Optional[str] = None
    sections: Optional[dict] = None
    title: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class GenerateReportRequest(BaseModel):
    report_type: str = "monthly"          # monthly | weekly
    period_start: Optional[str] = None    # ISO date; defaults to last 30 days
    period_end: Optional[str] = None

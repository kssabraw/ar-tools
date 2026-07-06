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
    delivery: Optional[dict] = None       # Phase 5: {email, drive} → ok/failed/skipped
    title: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class GenerateReportRequest(BaseModel):
    report_type: str = "monthly"          # monthly | weekly | ai_visibility
    period: Optional[str] = None          # 30d | 60d | 90d | 120d | 1y | all (since campaign start)
    period_start: Optional[str] = None    # explicit ISO dates win over `period`
    period_end: Optional[str] = None
    deliver: bool = False                 # Phase 5: email + Drive copy after render


class ReportSettings(BaseModel):
    client_id: UUID
    recipients: list[str] = []
    cadence: str = "disabled"             # disabled | weekly | monthly
    day_of_week: Optional[int] = None     # 0=Monday..6 (weekly)
    day_of_month: Optional[int] = None    # 1..28 (monthly)
    hour_utc: int = 8
    period: str = "auto"                  # auto | 30d | 60d | 90d | 120d | 1y | all
    email_enabled: bool = True
    drive_enabled: bool = True
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None


class ReportSettingsUpdateRequest(BaseModel):
    recipients: list[str] | str = []      # list or comma-separated string
    cadence: str = "disabled"
    day_of_week: Optional[int] = None
    day_of_month: Optional[int] = None
    hour_utc: int = 8
    period: str = "auto"                  # auto = 7d (weekly) / 30d (monthly)
    email_enabled: bool = True
    drive_enabled: bool = True

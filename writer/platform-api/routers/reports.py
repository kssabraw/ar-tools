"""Client Reporting router — generate + list per-client PDF reports.

Generation runs as an async `client_report` job (PDF render can take a few
seconds); this router enqueues it and lists results. The stored signed PDF URL
expires, so detail reads re-sign on the fly.
"""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.reports import ClientReport, GenerateReportRequest
from services import client_report

router = APIRouter(tags=["reports"])
logger = logging.getLogger(__name__)


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_date") from exc


@router.post("/clients/{client_id}/reports", response_model=ClientReport)
async def generate_report(
    client_id: UUID, body: GenerateReportRequest, auth: dict = Depends(require_auth)
) -> ClientReport:
    """Enqueue a report build; returns the pending row (poll the detail endpoint)."""
    if body.report_type not in ("monthly", "weekly"):
        raise HTTPException(status_code=422, detail="invalid_report_type")
    report_id = client_report.enqueue_client_report(
        str(client_id), body.report_type, _parse_date(body.period_start), _parse_date(body.period_end)
    )
    row = (
        get_supabase().table("client_reports").select("*").eq("id", report_id).limit(1).execute()
    ).data
    if not row:
        raise HTTPException(status_code=500, detail="internal_error")
    return ClientReport(**row[0])


@router.get("/clients/{client_id}/reports", response_model=list[ClientReport])
async def list_reports(client_id: UUID, auth: dict = Depends(require_auth)) -> list[ClientReport]:
    rows = (
        get_supabase().table("client_reports").select("*")
        .eq("client_id", str(client_id)).order("created_at", desc=True).limit(50).execute()
    ).data or []
    return [ClientReport(**r) for r in rows]


@router.get("/clients/{client_id}/reports/{report_id}", response_model=ClientReport)
async def get_report(
    client_id: UUID, report_id: UUID, auth: dict = Depends(require_auth)
) -> ClientReport:
    rows = (
        get_supabase().table("client_reports").select("*").eq("id", str(report_id)).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="not_found")
    row = rows[0]
    # Re-sign the (expiring) PDF URL on read so a stale link never 404s.
    if row.get("status") == "complete" and row.get("storage_path"):
        fresh = client_report._signed_url(row["storage_path"])
        if fresh:
            row["pdf_url"] = fresh
    return ClientReport(**row)

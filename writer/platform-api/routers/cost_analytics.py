"""Admin Cost & Usage Report API — agency-wide spend + LLM token analytics.

Admin-only (Depends(require_admin)): sums of cost (USD) and LLM tokens across
the suite, broken down by type / client / team member over a date range, with a
previous-period comparison. Reads the normalized cost_events view via
services.cost_analytics. Sibling of routers/deliverables_analytics.py.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from middleware.auth import require_admin
from services import cost_analytics

router = APIRouter(prefix="/admin", tags=["admin-cost"])
logger = logging.getLogger(__name__)


@router.get("/cost-report")
async def get_cost_report(
    date_from: str | None = Query(default=None, description="ISO date (inclusive). Defaults to 30 days ago."),
    date_to: str | None = Query(default=None, description="ISO date (inclusive). Defaults to today."),
    client_id: str | None = Query(default=None, description="Optional: scope to one client."),
    compare: bool = Query(default=True, description="Include a delta vs the previous equal-length period."),
    auth: dict = Depends(require_admin),
) -> dict:
    """Cost + token usage across the agency, broken down by type, client, and
    team member, plus a per-day series — over the given range (default last 30
    days), with a previous-period comparison when compare (default)."""
    try:
        return cost_analytics.build_report(
            date_from=date_from, date_to=date_to, client_id=client_id, compare=compare
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("cost_report_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc

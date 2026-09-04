"""Admin Activity Report API — agency-wide deliverables analytics.

Admin-only (Depends(require_admin)): counts of produced deliverables across the
whole suite, broken down by type / client / team member over a date range.
Reads the normalized deliverable_events view via services.deliverables_analytics.
Suite-level (not client-scoped), though an optional client_id narrows it.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from middleware.auth import require_admin
from services import deliverables_analytics

router = APIRouter(prefix="/admin", tags=["admin-activity"])
logger = logging.getLogger(__name__)


@router.get("/activity-report")
async def get_activity_report(
    date_from: str | None = Query(default=None, description="ISO date (inclusive). Defaults to 30 days ago."),
    date_to: str | None = Query(default=None, description="ISO date (inclusive). Defaults to today."),
    client_id: str | None = Query(default=None, description="Optional: scope to one client."),
    compare: bool = Query(default=True, description="Include a delta vs the previous equal-length period."),
    auth: dict = Depends(require_admin),
) -> dict:
    """Deliverables produced across the agency, broken down by type, client, and
    team member, plus a per-day series — over the given range (default last 30
    days). With compare (default), each count carries a delta vs the equal-length
    window immediately before the range."""
    try:
        return deliverables_analytics.build_report(
            date_from=date_from, date_to=date_to, client_id=client_id, compare=compare
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("activity_report_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc

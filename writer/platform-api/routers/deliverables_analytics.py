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
from services import deliverables_analytics, overdue_tasks

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


@router.get("/overdue-tasks")
async def get_overdue_tasks(
    client_id: str | None = Query(default=None, description="Optional: scope to one client."),
    auth: dict = Depends(require_admin),
) -> dict:
    """Current open, past-due tasks broken down by age (1–2d/3–4d/5–6d/7+d) and
    by cause (internal vs external — waiting on the client). A live snapshot."""
    try:
        return overdue_tasks.build_overdue_report(client_id=client_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("overdue_tasks_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc

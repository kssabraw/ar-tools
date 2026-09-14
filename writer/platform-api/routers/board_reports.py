"""Board reports — on-demand "generate now" + status (services/board_reports/).

The weekly department-head board reports (PACE / DORA / Client Health) normally
fire on the shared scheduler (Monday ~08:00 UTC). This adds a staff trigger so a
report can be produced on demand — e.g. right before a meeting — without waiting
for the weekly run. Delivery is whatever the config dictates: a PDF to the Drive
folder, and Slack/in-app only when ``board_reports_slack_enabled`` is on.

`POST /board-reports/run` is admin-only; `GET /board-reports/status` (any staff)
feeds the sidebar gate + the page header.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from config import settings
from middleware.auth import require_auth

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/board-reports/status")
async def board_reports_status(auth: dict = Depends(require_auth)) -> dict:
    """Feature + delivery config — drives the sidebar gate and the page header."""
    folder = settings.board_reports_drive_folder_id
    return {
        "enabled": settings.board_reports_enabled,
        "slack_enabled": settings.board_reports_slack_enabled,
        "drive_folder_id": folder or None,
        "drive_folder_url": (
            f"https://drive.google.com/drive/folders/{folder}" if folder else None
        ),
        "pdf_configured": bool(folder and settings.google_apps_script_url),
        "weekday": settings.board_reports_weekday,
    }


@router.post("/board-reports/run")
async def run_board_reports(auth: dict = Depends(require_auth)) -> dict:
    """Generate the three board reports on demand (admin-only). Runs off the event
    loop — the reports do blocking DB reads + a WeasyPrint render + a Drive upload
    driven by ``asyncio.run``, exactly as they do in the scheduler's worker
    thread. ``force=True`` runs regardless of the weekly schedule flag."""
    if auth.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin_only")
    from services.board_reports import run_weekly_board_reports

    result = await asyncio.to_thread(run_weekly_board_reports, date.today(), True)
    logger.info("board_reports.on_demand_run", extra={"user_id": auth.get("user_id")})
    return result

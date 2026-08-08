"""Keyword Research report endpoints.

Generate a PDF report for a session (topic silos, search demand, top
opportunities, content plan + a per-silo keyword appendix), save it to the
client's Drive folder + the private `reports` bucket, and record it. List past
reports and re-issue a download URL. Available to both roles (like CSV export,
PRD §11.2); scoped to sessions the caller can see via RLS (`_require_session`).

Generation is synchronous (one Claude call + a WeasyPrint render + two uploads)
— see fanout/report_runner.py.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from fanout import report_runner
from fanout.auth import AuthedUser, require_user
from fanout.logging import bind_session_id
from fanout.storage import silo as store
from fanout.storage.supabase_client import get_service_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["reports"])


def _require_session(user: AuthedUser, session_id: str) -> dict:
    session = store.session_visible_to_user(user.access_token, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


@router.post("/sessions/{session_id}/report")
def create_report(session_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    """Enqueue a keyword-research PDF report as a background job, so the user can
    navigate away while it renders (and gets a completion notification in the
    activity sidebar when the session is client-linked). Returns the pending row;
    poll `.../report/{report_id}` for the download link."""
    _require_session(user, session_id)
    bind_session_id(session_id)
    try:
        return report_runner.enqueue_report(session_id, user.id)
    except ValueError as exc:
        reason = str(exc)
        if reason == "no_keywords":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This session has no keywords to report on yet. Run keyword "
                "research first.",
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=reason)


@router.get("/sessions/{session_id}/report/{report_id}")
def report_status(session_id: str, report_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    """Poll a background report render — status + a fresh download URL when done."""
    _require_session(user, session_id)
    result = report_runner.get_report_status(session_id, report_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return result


@router.get("/sessions/{session_id}/reports")
def list_reports(session_id: str, user: AuthedUser = Depends(require_user)) -> list[dict]:
    """Past reports for a session, newest first."""
    _require_session(user, session_id)
    rows = (
        get_service_client().table("keyword_reports")
        .select("id, session_id, title, storage_path, drive_url, status, generated_at")
        .eq("session_id", session_id)
        .order("generated_at", desc=True)
        .limit(50)
        .execute()
    ).data or []
    # Don't leak the raw storage path to the client; expose only whether a
    # download is available (a fresh URL is minted on demand via /download).
    for r in rows:
        r["has_download"] = bool(r.pop("storage_path", None))
    return rows


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    """Re-issue a fresh signed download URL for a past report PDF."""
    row = (
        get_service_client().table("keyword_reports")
        .select("id, session_id, storage_path")
        .eq("id", report_id).limit(1).execute()
    ).data
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    report = row[0]
    # Enforce that the caller can see the report's parent session (RLS).
    _require_session(user, report["session_id"])
    url = report_runner.signed_download_url(report.get("storage_path"))
    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This report has no stored PDF to download.",
        )
    return {"report_id": report_id, "download_url": url}

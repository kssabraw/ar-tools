"""Notifications router — the in-app surface for the notifications service.

Drives the per-client-card unread badge (unread-counts), the per-client feed, and
read/dismiss state. Email + Slack delivery happens out of band in the
notification_dispatch job; this router is the in-app channel. Service-role DB
access; any authenticated user can read/act.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.notifications import Notification, OkResponse, UnreadCount, UnreadCountsResponse

router = APIRouter(tags=["notifications"])
logger = logging.getLogger(__name__)


@router.get("/notifications/unread-counts", response_model=UnreadCountsResponse)
async def unread_counts(auth: dict = Depends(require_auth)) -> UnreadCountsResponse:
    """Unread notification count per client — for the dashboard card badges."""
    supabase = get_supabase()
    rows = (
        supabase.table("notifications")
        .select("client_id")
        .eq("status", "unread")
        .not_.is_("client_id", "null")
        .execute()
    ).data or []
    by_client: dict[str, int] = {}
    for r in rows:
        cid = r["client_id"]
        by_client[cid] = by_client.get(cid, 0) + 1
    return UnreadCountsResponse(
        counts=[UnreadCount(client_id=cid, count=n) for cid, n in by_client.items()],
        total=len(rows),
    )


@router.get("/clients/{client_id}/notifications", response_model=list[Notification])
async def list_notifications(
    client_id: UUID, status: Optional[str] = None, auth: dict = Depends(require_auth)
) -> list[Notification]:
    """A client's notification feed (newest first), optionally filtered by status."""
    supabase = get_supabase()
    query = (
        supabase.table("notifications")
        .select("*")
        .eq("client_id", str(client_id))
        .order("created_at", desc=True)
        .limit(100)
    )
    if status:
        query = query.eq("status", status)
    rows = (query.execute()).data or []
    return [Notification(**r) for r in rows]


def _set_status(notification_id: UUID, status: str) -> OkResponse:
    supabase = get_supabase()
    update: dict = {"status": status}
    if status == "read":
        update["read_at"] = "now()"
    res = (
        supabase.table("notifications").update(update).eq("id", str(notification_id)).execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="not_found")
    return OkResponse()


@router.post("/notifications/{notification_id}/read", response_model=OkResponse)
async def mark_read(notification_id: UUID, auth: dict = Depends(require_auth)) -> OkResponse:
    return _set_status(notification_id, "read")


@router.post("/notifications/{notification_id}/dismiss", response_model=OkResponse)
async def dismiss(notification_id: UUID, auth: dict = Depends(require_auth)) -> OkResponse:
    return _set_status(notification_id, "dismissed")


@router.post("/clients/{client_id}/notifications/read-all", response_model=OkResponse)
async def mark_all_read(client_id: UUID, auth: dict = Depends(require_auth)) -> OkResponse:
    """Mark every unread notification for a client as read."""
    supabase = get_supabase()
    supabase.table("notifications").update({"status": "read", "read_at": "now()"}).eq(
        "client_id", str(client_id)
    ).eq("status", "unread").execute()
    return OkResponse()

"""Pydantic schemas for the notifications service."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class Notification(BaseModel):
    id: UUID
    client_id: Optional[UUID] = None
    recipient_profile_id: Optional[UUID] = None
    kind: str
    severity: str
    title: str
    summary: Optional[str] = None
    payload: Optional[dict] = None
    status: str
    channels_sent: Optional[dict] = None
    created_at: str
    read_at: Optional[str] = None


class MyNotificationsResponse(BaseModel):
    """The logged-in user's personal notification feed + unread count — the
    header bell."""
    items: list[Notification] = []
    unread: int = 0


class UnreadCount(BaseModel):
    client_id: UUID
    count: int


class UnreadCountsResponse(BaseModel):
    counts: list[UnreadCount] = []
    total: int = 0


class DeleteRequest(BaseModel):
    """Bulk-delete body. When `ids` is omitted (or empty), every notification for
    the client is deleted (the "select all → delete" path)."""
    ids: Optional[list[UUID]] = None


class OkResponse(BaseModel):
    status: str = "ok"

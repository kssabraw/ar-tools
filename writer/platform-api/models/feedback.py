"""Pydantic schemas for the internal Feedback Board (bugs + wishlist).

Admin-only. Items carry a shared status workflow (new → triaged → in_progress →
done / declined), a priority, free-text labels, and threaded comments.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

FeedbackKind = Literal["bug", "wishlist"]
FeedbackStatus = Literal["new", "triaged", "in_progress", "done", "declined"]
FeedbackPriority = Literal["low", "medium", "high", "critical"]


class FeedbackCreateRequest(BaseModel):
    kind: FeedbackKind
    title: str
    body: Optional[str] = None
    priority: FeedbackPriority = "medium"
    labels: list[str] = []


class FeedbackUpdateRequest(BaseModel):
    # exclude_unset in the router so an explicit null CLEARS a field, and only
    # provided fields change (inline board edits touch one thing at a time).
    title: Optional[str] = None
    body: Optional[str] = None
    status: Optional[FeedbackStatus] = None
    priority: Optional[FeedbackPriority] = None
    labels: Optional[list[str]] = None


class FeedbackCommentResponse(BaseModel):
    id: UUID
    item_id: UUID
    author_id: Optional[UUID] = None
    author_name: Optional[str] = None
    body: str
    created_at: datetime


class FeedbackCommentCreateRequest(BaseModel):
    body: str


class FeedbackItemResponse(BaseModel):
    id: UUID
    kind: str
    title: str
    body: Optional[str] = None
    status: str
    priority: str
    labels: list[str] = []
    created_by: Optional[UUID] = None
    created_by_name: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    comment_count: int = 0


class FeedbackItemDetailResponse(FeedbackItemResponse):
    comments: list[FeedbackCommentResponse] = []

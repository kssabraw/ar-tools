"""Feedback Board API — internal, ADMIN-ONLY board for bugs + a wishlist of
new modules / capabilities.

Every route depends on require_admin, so only admin-role users can view, add,
edit, or comment. Suite-level (not client-scoped).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from middleware.auth import require_admin
from models.feedback import (
    FeedbackCommentCreateRequest,
    FeedbackCommentResponse,
    FeedbackCreateRequest,
    FeedbackItemDetailResponse,
    FeedbackItemResponse,
    FeedbackUpdateRequest,
)
from services import feedback_service

router = APIRouter(prefix="/feedback", tags=["feedback"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[FeedbackItemResponse])
async def list_feedback(
    kind: str | None = Query(default=None, pattern="^(bug|wishlist)$"),
    status: str | None = Query(default=None),
    include_resolved: bool = True,
    auth: dict = Depends(require_admin),
) -> list[FeedbackItemResponse]:
    try:
        rows = feedback_service.list_items(
            kind=kind, status=status, include_resolved=include_resolved
        )
    except Exception as exc:
        logger.error("feedback_list_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return [FeedbackItemResponse(**r) for r in rows]


@router.post("", response_model=FeedbackItemResponse)
async def create_feedback(
    body: FeedbackCreateRequest,
    auth: dict = Depends(require_admin),
) -> FeedbackItemResponse:
    if not body.title.strip():
        raise HTTPException(status_code=422, detail="title_required")
    try:
        row = feedback_service.create_item(body.model_dump(), created_by=auth["user_id"])
    except Exception as exc:
        logger.error("feedback_create_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return FeedbackItemResponse(**row)


@router.get("/{item_id}", response_model=FeedbackItemDetailResponse)
async def get_feedback(
    item_id: UUID,
    auth: dict = Depends(require_admin),
) -> FeedbackItemDetailResponse:
    try:
        item = feedback_service.get_item(str(item_id))
    except Exception as exc:
        logger.error("feedback_get_failed", extra={"item_id": str(item_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not item:
        raise HTTPException(status_code=404, detail="feedback_not_found")
    return FeedbackItemDetailResponse(**item)


@router.put("/{item_id}", response_model=FeedbackItemDetailResponse)
async def update_feedback(
    item_id: UUID,
    body: FeedbackUpdateRequest,
    auth: dict = Depends(require_admin),
) -> FeedbackItemDetailResponse:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="nothing_to_update")
    if changes.get("title") is not None and not str(changes["title"]).strip():
        raise HTTPException(status_code=422, detail="title_required")
    try:
        item = feedback_service.update_item(str(item_id), changes)
    except Exception as exc:
        logger.error("feedback_update_failed", extra={"item_id": str(item_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not item:
        raise HTTPException(status_code=404, detail="feedback_not_found")
    return FeedbackItemDetailResponse(**item)


@router.delete("/{item_id}")
async def delete_feedback(
    item_id: UUID,
    auth: dict = Depends(require_admin),
) -> dict:
    try:
        ok = feedback_service.delete_item(str(item_id))
    except Exception as exc:
        logger.error("feedback_delete_failed", extra={"item_id": str(item_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not ok:
        raise HTTPException(status_code=404, detail="feedback_not_found")
    return {"status": "deleted"}


@router.post("/{item_id}/comments", response_model=FeedbackCommentResponse)
async def add_feedback_comment(
    item_id: UUID,
    body: FeedbackCommentCreateRequest,
    auth: dict = Depends(require_admin),
) -> FeedbackCommentResponse:
    if not body.body.strip():
        raise HTTPException(status_code=422, detail="comment_required")
    try:
        comment = feedback_service.add_comment(str(item_id), body.body, author_id=auth["user_id"])
    except Exception as exc:
        logger.error("feedback_comment_failed", extra={"item_id": str(item_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not comment:
        raise HTTPException(status_code=404, detail="feedback_not_found")
    return FeedbackCommentResponse(**comment)


@router.delete("/{item_id}/comments/{comment_id}")
async def delete_feedback_comment(
    item_id: UUID,
    comment_id: UUID,
    auth: dict = Depends(require_admin),
) -> dict:
    try:
        ok = feedback_service.delete_comment(str(item_id), str(comment_id))
    except Exception as exc:
        logger.error("feedback_comment_delete_failed", extra={"comment_id": str(comment_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    if not ok:
        raise HTTPException(status_code=404, detail="comment_not_found")
    return {"status": "deleted"}

"""Social Media module — publish-path routes (PRD §9).

Backend publish path only (v1): list a client's manually-connected accounts (live
from PostPeer), compose a post, and publish it through the freeze-gated async job.
Gated on ``settings.social_enabled`` (503 until flipped), like the other modules.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends

from middleware.auth import require_auth, require_staff
from models.social import (
    SocialAccountResponse,
    SocialPostCreateRequest,
    SocialPostResponse,
)
from services.freeze import assert_not_frozen
from services.social import publish as social_publish

logger = logging.getLogger(__name__)

router = APIRouter(tags=["social"])


@router.get("/clients/{client_id}/social/accounts", response_model=list[SocialAccountResponse])
async def list_social_accounts(client_id: UUID, auth: dict = Depends(require_auth)):
    """The client's connected social accounts, live from PostPeer (scoped to their
    Social group when set). Use an account_id here as the publish target."""
    return social_publish.list_accounts(str(client_id))


@router.post("/clients/{client_id}/social/posts", response_model=SocialPostResponse)
async def create_social_post(
    client_id: UUID, body: SocialPostCreateRequest, auth: dict = Depends(require_staff)
):
    """Compose one platform-native post and publish it (freeze-gated async job)."""
    social_publish._assert_enabled()
    assert_not_frozen(str(client_id))
    return social_publish.create_post(
        str(client_id), body.platform, body.account_id,
        copy=body.copy, image_urls=body.image_urls, fmt=body.format,
    )


@router.get("/clients/{client_id}/social/posts", response_model=list[SocialPostResponse])
async def list_social_posts(client_id: UUID, auth: dict = Depends(require_auth)):
    social_publish._assert_enabled()
    return social_publish.list_posts(str(client_id))


@router.get("/social/posts/{post_id}", response_model=SocialPostResponse)
async def get_social_post(post_id: UUID, auth: dict = Depends(require_auth)):
    social_publish._assert_enabled()
    return social_publish.get_post(str(post_id))

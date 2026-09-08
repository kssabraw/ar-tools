"""Social Media module — publish-path routes (PRD §9).

Backend publish path only (v1): list a client's manually-connected accounts (live
from PostPeer), compose a post, and publish it through the freeze-gated async job.
Gated on ``settings.social_enabled`` (503 until flipped), like the other modules.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile

from middleware.auth import require_auth, require_staff
from models.social import (
    SocialAccountResponse,
    SocialAngle,
    SocialAnglesRequest,
    SocialDraftCopyRequest,
    SocialDraftCopyResponse,
    SocialDraftPublishRequest,
    SocialDraftResponse,
    SocialDraftUpdateRequest,
    SocialFanoutRequest,
    SocialFanoutResponse,
    SocialGenerateImageRequest,
    SocialGenerateImageResponse,
    SocialJobStatusResponse,
    SocialMediaUploadResponse,
    SocialPostCreateRequest,
    SocialPostResponse,
    SocialPresignRequest,
    SocialPresignResponse,
)
from services.freeze import assert_not_frozen
from services.social import creator as social_creator
from services.social import fanout as social_fanout
from services.social import image as social_image
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
        copy=body.copy, image_urls=body.image_urls, video_urls=body.video_urls,
        platform_specific=body.platform_specific, fmt=body.format,
        scheduled_at=body.scheduled_at,
    )


@router.post("/clients/{client_id}/social/draft-copy", response_model=SocialDraftCopyResponse)
async def draft_social_copy(
    client_id: UUID, body: SocialDraftCopyRequest, auth: dict = Depends(require_staff)
):
    """AI-draft platform-native post copy from a source (topic / URL / blog run /
    saved page) for the composer to review and edit. Stateless — nothing is
    published or persisted; the human still approves and publishes."""
    social_publish._assert_enabled()
    return await social_creator.generate_copy(
        str(client_id), body, user_id=auth.get("user_id")
    )


@router.post("/clients/{client_id}/social/angles", response_model=list[SocialAngle])
async def propose_social_angles(
    client_id: UUID, body: SocialAnglesRequest, auth: dict = Depends(require_staff)
):
    """Propose distinct editorial angles for a Source (the Creator's Angle step)."""
    social_publish._assert_enabled()
    return await social_creator.propose_angles(str(client_id), body, user_id=auth.get("user_id"))


@router.post("/clients/{client_id}/social/fan-out", response_model=SocialFanoutResponse)
async def fan_out_social(
    client_id: UUID, body: SocialFanoutRequest, auth: dict = Depends(require_staff)
):
    """Fan one angle out across the selected platforms into reviewable Drafts
    (background job). Freeze-gated (it can generate paid images)."""
    social_publish._assert_enabled()
    assert_not_frozen(str(client_id))
    return social_fanout.enqueue_fanout(str(client_id), body, user_id=auth.get("user_id"))


@router.get("/clients/{client_id}/social/fan-out/{job_id}", response_model=SocialJobStatusResponse)
async def get_fanout_status(client_id: UUID, job_id: UUID, auth: dict = Depends(require_auth)):
    social_publish._assert_enabled()
    return social_fanout.get_fanout_job(str(job_id))


@router.get("/clients/{client_id}/social/drafts", response_model=list[SocialDraftResponse])
async def list_social_drafts(
    client_id: UUID, angle_set_id: UUID | None = None, auth: dict = Depends(require_auth)
):
    social_publish._assert_enabled()
    return social_fanout.list_drafts(
        str(client_id), angle_set_id=str(angle_set_id) if angle_set_id else None
    )


@router.get("/social/drafts/{draft_id}", response_model=SocialDraftResponse)
async def get_social_draft(draft_id: UUID, auth: dict = Depends(require_auth)):
    social_publish._assert_enabled()
    return social_fanout.get_draft(str(draft_id))


@router.patch("/social/drafts/{draft_id}", response_model=SocialDraftResponse)
async def update_social_draft(
    draft_id: UUID, body: SocialDraftUpdateRequest, auth: dict = Depends(require_staff)
):
    social_publish._assert_enabled()
    return social_fanout.update_draft(
        str(draft_id), copy=body.copy, image_urls=body.image_urls,
        platform_metadata=body.platform_metadata,
    )


@router.delete("/social/drafts/{draft_id}")
async def delete_social_draft(draft_id: UUID, auth: dict = Depends(require_staff)):
    social_publish._assert_enabled()
    return social_fanout.delete_draft(str(draft_id))


@router.post("/social/drafts/{draft_id}/publish", response_model=SocialPostResponse)
async def publish_social_draft(
    draft_id: UUID, body: SocialDraftPublishRequest, auth: dict = Depends(require_staff)
):
    """Approve & publish a Draft to one connected account (freeze-gated)."""
    social_publish._assert_enabled()
    draft = social_fanout.get_draft(str(draft_id))
    assert_not_frozen(str(draft["client_id"]))
    return social_fanout.publish_existing_draft(str(draft_id), body.account_id, body.scheduled_at)


@router.post("/clients/{client_id}/social/generate-image", response_model=SocialGenerateImageResponse)
async def generate_social_image(
    client_id: UUID, body: SocialGenerateImageRequest, auth: dict = Depends(require_staff)
):
    """Generate one on-brand, per-platform social image (Nano Banana Pro) and store
    it; returns a media URL to drop into a post's image_urls. Freeze-gated + budget-
    metered (it's a paid external call)."""
    social_publish._assert_enabled()
    assert_not_frozen(str(client_id))
    return await social_image.generate_image(str(client_id), body, user_id=auth.get("user_id"))


@router.post("/clients/{client_id}/social/media", response_model=SocialMediaUploadResponse)
async def upload_social_media(
    client_id: UUID, file: UploadFile = File(...), auth: dict = Depends(require_staff)
):
    """Upload an image or video to the public bucket; returns a public URL to drop
    into a post's image_urls/video_urls (PostPeer fetches media by URL)."""
    social_publish._assert_enabled()
    data = await file.read()
    return social_publish.upload_media(data, file.content_type or "")


@router.post("/clients/{client_id}/social/media/presign", response_model=SocialPresignResponse)
async def presign_social_media(
    client_id: UUID, body: SocialPresignRequest, auth: dict = Depends(require_staff)
):
    """A short-lived direct-upload URL for a big image/video: the browser PUTs the
    file to upload_url, then passes public_url into a post's image_urls/video_urls
    (keeps large bytes out of the API)."""
    social_publish._assert_enabled()
    return social_publish.presign_upload(body.content_type)


@router.get("/clients/{client_id}/social/posts", response_model=list[SocialPostResponse])
async def list_social_posts(client_id: UUID, auth: dict = Depends(require_auth)):
    social_publish._assert_enabled()
    return social_publish.list_posts(str(client_id))


@router.get("/social/posts/{post_id}", response_model=SocialPostResponse)
async def get_social_post(post_id: UUID, auth: dict = Depends(require_auth)):
    social_publish._assert_enabled()
    return social_publish.get_post(str(post_id))

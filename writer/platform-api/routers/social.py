"""Social Media module — publish-path routes (PRD §9).

Backend publish path only (v1): list a client's manually-connected accounts (live
from PostPeer), compose a post, and publish it through the freeze-gated async job.
Gated on ``settings.social_enabled`` (503 until flipped), like the other modules.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from middleware.auth import require_auth, require_staff
from models.social import (
    SocialAccountResponse,
    SocialAddHandleRequest,
    SocialAngle,
    SocialAnglesRequest,
    SocialAutonomyRunResponse,
    SocialBatchPublishRequest,
    SocialBatchPublishResult,
    SocialCompetitorHandle,
    SocialCompetitorResponse,
    SocialCompetitorSignalResponse,
    SocialConnectUrlResponse,
    SocialCredentialStatusResponse,
    SocialDraftCopyRequest,
    SocialDraftCopyResponse,
    SocialDraftPublishRequest,
    SocialDraftResponse,
    SocialDraftUpdateRequest,
    SocialEditPostRequest,
    SocialFanoutRequest,
    SocialFanoutResponse,
    SocialGenerateImageRequest,
    SocialGenerateImageResponse,
    SocialJobStatusResponse,
    SocialMediaUploadResponse,
    SocialPolicyResponse,
    SocialPolicyUpdateRequest,
    SocialPostCreateRequest,
    SocialPostResponse,
    SocialPresignRequest,
    SocialPresignResponse,
    SocialProfileResponse,
    SocialRescheduleRequest,
    SocialResearchTriggerResponse,
    SocialScheduleUpsertRequest,
    SocialSchedulesResponse,
    SocialSetCredentialRequest,
    SocialStoryboardRequest,
    SocialStoryboardResponse,
    SocialStoryboardUpdateRequest,
)
from services.freeze import assert_not_frozen
from services.social import credentials as social_credentials
from services.social import competitor_research as social_research
from services.social import creator as social_creator
from services.social import fanout as social_fanout
from services.social import image as social_image
from services.social import manager as social_manager
from services.social import policy as social_policy
from services.social import publish as social_publish
from services.social import schedules as social_schedules
from services.social import storyboard as social_storyboard

logger = logging.getLogger(__name__)

router = APIRouter(tags=["social"])


@router.get("/clients/{client_id}/social/accounts", response_model=list[SocialAccountResponse])
async def list_social_accounts(client_id: UUID, auth: dict = Depends(require_auth)):
    """The client's connected social accounts, live from PostPeer (scoped to their
    Social group). Empty until the client has a Social group with connected
    accounts. Use an account_id here as the publish target."""
    return social_publish.list_accounts(str(client_id))


@router.post("/clients/{client_id}/social/profile", response_model=SocialProfileResponse)
async def ensure_social_profile(client_id: UUID, auth: dict = Depends(require_staff)):
    """Create (or return) this client's PostPeer profile (Social group) — the
    isolation boundary every account and post is scoped to. Idempotent."""
    social_publish._assert_enabled()
    return {"profile_id": social_publish.ensure_profile_for_client(str(client_id))}


@router.get(
    "/clients/{client_id}/social/credentials", response_model=SocialCredentialStatusResponse
)
async def get_social_credentials(client_id: UUID, auth: dict = Depends(require_auth)):
    """Whether the client's PostForMe project API key is configured (never the key itself)."""
    social_publish._assert_enabled()
    return social_credentials.status(str(client_id))


@router.put(
    "/clients/{client_id}/social/credentials", response_model=SocialCredentialStatusResponse
)
async def set_social_credentials(
    client_id: UUID, body: SocialSetCredentialRequest, auth: dict = Depends(require_staff)
):
    """Store the client's PostForMe project API key (validated live before storing; a bad key
    is rejected and nothing is saved). The key is a secret — kept service-role only and never
    returned. Manual provisioning: an admin creates the client's PostForMe Project + key in the
    PostForMe dashboard, then pastes it here (PostForMe has no project/key API)."""
    social_publish._assert_enabled()
    return await run_in_threadpool(
        social_credentials.set_client_key, str(client_id), body.api_key
    )


@router.delete(
    "/clients/{client_id}/social/credentials", response_model=SocialCredentialStatusResponse
)
async def delete_social_credentials(client_id: UUID, auth: dict = Depends(require_staff)):
    """Remove the client's PostForMe key (disconnects the client's Social integration)."""
    social_publish._assert_enabled()
    return social_credentials.delete_client_key(str(client_id))


@router.get("/clients/{client_id}/social/connect-url", response_model=SocialConnectUrlResponse)
async def social_connect_url(
    client_id: UUID, platform: str, redirect_uri: str | None = None,
    auth: dict = Depends(require_staff),
):
    """A per-client OAuth connect URL for one platform, scoped to the client's
    Social group so the authorized account lands in the right profile. 409 if the
    client has no Social group yet (call POST …/social/profile first)."""
    social_publish._assert_enabled()
    return {
        "platform": (platform or "").lower(),
        "url": social_publish.connect_url_for_client(str(client_id), platform, redirect_uri),
    }


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
        title=body.title, board_id=body.board_id, scheduled_at=body.scheduled_at,
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
        platform_metadata=body.platform_metadata, board_id=body.board_id,
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
    return social_fanout.publish_existing_draft(
        str(draft_id), body.account_id, body.scheduled_at, force_qa=body.force_qa
    )


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


# ── P3 Manager: Calendar + edit / cancel / reschedule ─────────────────────────

@router.get("/clients/{client_id}/social/calendar", response_model=list[SocialPostResponse])
async def social_calendar(
    client_id: UUID,
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    auth: dict = Depends(require_auth),
):
    """The Calendar feed: scheduled + published posts, optionally windowed by
    ``from``/``to`` (matches ``scheduled_at`` for upcoming or ``published_at`` for
    history). Cross-platform, read-only."""
    social_publish._assert_enabled()
    return social_publish.list_calendar(str(client_id), from_, to)


@router.post("/social/posts/{post_id}/cancel", response_model=SocialPostResponse)
async def cancel_social_post(post_id: UUID, auth: dict = Depends(require_staff)):
    """Cancel a scheduled post (only before it starts publishing)."""
    social_publish._assert_enabled()
    return social_publish.cancel_post(str(post_id))


@router.post("/social/posts/{post_id}/reschedule", response_model=SocialPostResponse)
async def reschedule_social_post(
    post_id: UUID, body: SocialRescheduleRequest, auth: dict = Depends(require_staff)
):
    """Move a scheduled post to a new future time."""
    social_publish._assert_enabled()
    return social_publish.reschedule_post(str(post_id), body.scheduled_at)


@router.patch("/social/posts/{post_id}", response_model=SocialPostResponse)
async def edit_social_post(
    post_id: UUID, body: SocialEditPostRequest, auth: dict = Depends(require_staff)
):
    """Edit a scheduled post's copy and/or images before it publishes (re-validated
    against the Platform Spec at publish)."""
    social_publish._assert_enabled()
    return social_publish.edit_scheduled_post(
        str(post_id), copy=body.copy, image_urls=body.image_urls
    )


# ── P3 Manager: approval queue (batch publish + cadence queue enroll) ─────────

@router.post(
    "/clients/{client_id}/social/drafts/publish-batch",
    response_model=list[SocialBatchPublishResult],
)
async def publish_social_drafts_batch(
    client_id: UUID, body: SocialBatchPublishRequest, auth: dict = Depends(require_staff)
):
    """Approve & publish/schedule several Drafts at once (partial success — each item
    is independent). Freeze-gated."""
    social_publish._assert_enabled()
    assert_not_frozen(str(client_id))
    return social_fanout.publish_drafts_batch(str(client_id), body.items)


@router.post("/social/drafts/{draft_id}/queue", response_model=SocialDraftResponse)
async def queue_social_draft(draft_id: UUID, auth: dict = Depends(require_staff)):
    """Enroll a ready Draft in the cadence drip queue (approved, waiting for its slot)."""
    social_publish._assert_enabled()
    return social_fanout.enqueue_draft(str(draft_id))


@router.post("/social/drafts/{draft_id}/unqueue", response_model=SocialDraftResponse)
async def unqueue_social_draft(draft_id: UUID, auth: dict = Depends(require_staff)):
    """Remove a Draft from the cadence queue (queued → ready)."""
    social_publish._assert_enabled()
    return social_fanout.dequeue_draft(str(draft_id))


# ── P3 Manager: Social Policy + cadence schedules ─────────────────────────────

@router.get("/clients/{client_id}/social/policy", response_model=SocialPolicyResponse)
async def get_social_policy(client_id: UUID, auth: dict = Depends(require_auth)):
    social_publish._assert_enabled()
    return social_policy.get_policy(str(client_id))


@router.put("/clients/{client_id}/social/policy", response_model=SocialPolicyResponse)
async def put_social_policy(
    client_id: UUID, body: SocialPolicyUpdateRequest, auth: dict = Depends(require_staff)
):
    """Set the Social Policy: consumer fields (ceiling + prompt templates) and the P4
    planning fields (autonomy_tier + topic bank + tone/competitor focus). Only fields
    present in the request change (an explicit null clears)."""
    social_publish._assert_enabled()
    return social_policy.upsert_policy(str(client_id), body.model_dump(exclude_unset=True))


@router.get("/clients/{client_id}/social/schedule", response_model=SocialSchedulesResponse)
async def get_social_schedules(client_id: UUID, auth: dict = Depends(require_auth)):
    social_publish._assert_enabled()
    return social_schedules.get_schedules(str(client_id))


@router.put("/clients/{client_id}/social/schedule", response_model=SocialSchedulesResponse)
async def put_social_schedule(
    client_id: UUID, body: SocialScheduleUpsertRequest, auth: dict = Depends(require_staff)
):
    """Create/replace one platform's cadence schedule (recomputes next_run_at)."""
    social_publish._assert_enabled()
    return social_schedules.upsert_schedule(
        str(client_id), body.model_dump(), auth.get("user_id")
    )


@router.delete("/clients/{client_id}/social/schedule", response_model=SocialSchedulesResponse)
async def delete_social_schedule(
    client_id: UUID, platform: str, auth: dict = Depends(require_staff)
):
    """Remove a platform's cadence schedule."""
    social_publish._assert_enabled()
    return social_schedules.delete_schedule(str(client_id), platform)


# ── P1 competitor research (analyze-in-place; ADR-0002) ───────────────────────

@router.get(
    "/clients/{client_id}/social/competitors",
    response_model=list[SocialCompetitorResponse],
)
async def list_social_competitors(client_id: UUID, auth: dict = Depends(require_auth)):
    """The client's competitors + their per-platform social handles (Competitors tab)."""
    social_publish._assert_enabled()
    return social_research.list_competitors_with_handles(str(client_id))


@router.post(
    "/clients/{client_id}/social/competitors/{competitor_id}/handles",
    response_model=SocialCompetitorHandle,
)
async def add_social_competitor_handle(
    client_id: UUID, competitor_id: UUID,
    body: SocialAddHandleRequest, auth: dict = Depends(require_staff),
):
    """Add a per-platform social handle to one of the client's competitors."""
    social_publish._assert_enabled()
    return social_research.add_handle(
        str(client_id), str(competitor_id), body.platform, body.handle
    )


@router.delete("/social/competitor-handles/{handle_id}")
async def delete_social_competitor_handle(
    handle_id: UUID, client_id: UUID, auth: dict = Depends(require_staff)
):
    """Remove a competitor social handle (client_id scopes the ownership check)."""
    social_publish._assert_enabled()
    return social_research.delete_handle(str(client_id), str(handle_id))


@router.post(
    "/clients/{client_id}/social/competitor-research",
    response_model=SocialResearchTriggerResponse,
)
async def trigger_social_competitor_research(
    client_id: UUID, auth: dict = Depends(require_staff)
):
    """Run competitor research now (background job). NOT freeze-gated — research
    keeps running under freeze (PRD §3). 503 until the P1 gate is open
    (social_enabled + social_competitor_research_enabled + APIFY_API_TOKEN)."""
    social_publish._assert_enabled()
    return social_research.enqueue_social_competitor_research(
        str(client_id), user_id=auth.get("user_id")
    )


@router.get(
    "/clients/{client_id}/social/competitor-research/{job_id}",
    response_model=SocialJobStatusResponse,
)
async def get_social_competitor_research_status(
    client_id: UUID, job_id: UUID, auth: dict = Depends(require_auth)
):
    social_publish._assert_enabled()
    return social_research.get_research_job(str(job_id))


@router.get(
    "/clients/{client_id}/social/competitor-signals",
    response_model=list[SocialCompetitorSignalResponse],
)
async def list_social_competitor_signals(client_id: UUID, auth: dict = Depends(require_auth)):
    """Stored competitor signals for a client, most-recent first."""
    social_publish._assert_enabled()
    return social_research.list_signals(str(client_id))


@router.get(
    "/clients/{client_id}/social/autonomy-runs",
    response_model=list[SocialAutonomyRunResponse],
)
async def list_social_autonomy_runs(client_id: UUID, auth: dict = Depends(require_auth)):
    """Recent Social Manager (autonomy loop) runs for this client — produced /
    auto-queued / proposed + cost, most-recent first. Empty until the loop has
    run (ships dark behind social_autonomy_enabled). Reads the shared
    autonomy_runs ledger scoped to domain='social'."""
    social_publish._assert_enabled()
    return social_manager.list_autonomy_runs(str(client_id))


# ── P5 (slice a): Video Storyboard — a shoot-ready brief (NO rendered video) ──

@router.post(
    "/clients/{client_id}/social/storyboard",
    response_model=SocialStoryboardResponse,
)
async def generate_social_storyboard(
    client_id: UUID, body: SocialStoryboardRequest, auth: dict = Depends(require_staff)
):
    """Generate a shot-by-shot video storyboard (a brief the client shoots) from a
    Source for a Reel / Short. Freeze-gated (a later thumbnail can spend); the
    storyboard text itself is not metered. No video is generated."""
    social_publish._assert_enabled()
    assert_not_frozen(str(client_id))
    return await social_storyboard.generate_storyboard(
        str(client_id), body, user_id=auth.get("user_id")
    )


@router.get(
    "/clients/{client_id}/social/storyboards",
    response_model=list[SocialStoryboardResponse],
)
async def list_social_storyboards(client_id: UUID, auth: dict = Depends(require_auth)):
    social_publish._assert_enabled()
    return social_storyboard.list_storyboards(str(client_id))


@router.get("/social/storyboards/{storyboard_id}", response_model=SocialStoryboardResponse)
async def get_social_storyboard(storyboard_id: UUID, auth: dict = Depends(require_auth)):
    social_publish._assert_enabled()
    return social_storyboard.get_storyboard(str(storyboard_id))


@router.patch("/social/storyboards/{storyboard_id}", response_model=SocialStoryboardResponse)
async def update_social_storyboard(
    storyboard_id: UUID, body: SocialStoryboardUpdateRequest, auth: dict = Depends(require_staff)
):
    """Human edit of a storyboard (title / the shot-list body / thumbnail)."""
    social_publish._assert_enabled()
    return social_storyboard.update_storyboard(
        str(storyboard_id),
        title=body.title,
        storyboard=body.storyboard.model_dump() if body.storyboard is not None else None,
        thumbnail_url=body.thumbnail_url,
    )


@router.delete("/social/storyboards/{storyboard_id}")
async def delete_social_storyboard(storyboard_id: UUID, auth: dict = Depends(require_staff)):
    social_publish._assert_enabled()
    return social_storyboard.delete_storyboard(str(storyboard_id))


@router.post(
    "/clients/{client_id}/social/storyboards/{storyboard_id}/thumbnail",
    response_model=SocialStoryboardResponse,
)
async def generate_social_storyboard_thumbnail(
    client_id: UUID, storyboard_id: UUID, auth: dict = Depends(require_staff)
):
    """Generate + attach a 9:16 thumbnail for a storyboard (reuses the freeze-gated,
    fail-closed-budget-metered image path)."""
    social_publish._assert_enabled()
    assert_not_frozen(str(client_id))
    return await social_storyboard.generate_thumbnail(
        str(client_id), str(storyboard_id), user_id=auth.get("user_id")
    )

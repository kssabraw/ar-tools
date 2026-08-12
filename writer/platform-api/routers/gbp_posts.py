"""Google Business Profile **Posts** module router.

Compose (manual + AI-drafted), publish, edit, schedule, and reconcile GBP posts
on a client's Business Profile via the v4 localPosts API. Auth follows the suite
model (any authenticated user manages, like clients). Publishing is content
output, so it's Freeze-gated (assert_not_frozen); drafting/sync are not.

The whole surface returns 503 (gbp_posts_not_enabled) until both
``gbp_api_enabled`` and ``gbp_posts_enabled`` are set. Long-running actions
(publish / generate / sync) are async jobs — the UI polls .../jobs/status.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile

from middleware.auth import require_auth, require_staff
from models.gbp_posts import (
    GbpAvailableLocationsResponse,
    GbpBulkGenerateResponse,
    GbpGenerateFromUrlRequest,
    GbpGenerateImageRequest,
    GbpImageFromUrlRequest,
    GbpImageUploadResponse,
    GbpMatchLocationResponse,
    GbpJob,
    GbpJobsStatusRequest,
    GbpJobStatus,
    GbpLocationOption,
    GbpPost,
    GbpPostCreateRequest,
    GbpPostGenerateRequest,
    GbpPostScheduleAtRequest,
    GbpPostUpdateRequest,
    GbpRegisterLocationRequest,
    GbpReusableImage,
    GbpSchedule,
    GbpScheduleUpsertRequest,
    GbpTimezoneResponse,
    GbpTrashPurgeResponse,
)
from services import gbp_locations_service as loc_svc
from services import gbp_posts_service as svc
from services import gbp_timezone
from services.freeze import assert_not_frozen

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gbp-posts"])


# ── locations picker ─────────────────────────────────────────────────────────
@router.get("/clients/{client_id}/gbp/post-locations", response_model=list[GbpLocationOption])
async def list_post_locations(client_id: UUID, auth: dict = Depends(require_auth)):
    """Registered GBP locations for this client (only 'ok' ones can be posted to)."""
    svc._assert_enabled()
    return svc.list_ok_locations(str(client_id))


@router.get("/clients/{client_id}/gbp/match-location", response_model=GbpMatchLocationResponse)
async def match_location(client_id: UUID, auth: dict = Depends(require_staff)):
    """The one listing that is this client's Google Business Profile, auto-matched
    from the client's captured GBP (business name + Maps pin) against the connected
    account's managed listings. `candidates` is the ranked fallback."""
    return loc_svc.match_client_location(str(client_id))


@router.get("/gbp/available-locations", response_model=GbpAvailableLocationsResponse)
async def available_locations(auth: dict = Depends(require_staff)):
    """Every listing the connected agency account manages (from Google), flagged
    with the client each is already registered to. Agency-wide fallback browse."""
    return loc_svc.resolve_connected_locations()


@router.post("/clients/{client_id}/gbp/register-location", response_model=GbpLocationOption)
async def register_location(
    client_id: UUID, body: GbpRegisterLocationRequest, auth: dict = Depends(require_staff)
):
    """Assign one resolved listing to this client so it appears in Compose."""
    return loc_svc.register_location(
        str(client_id), body.location_id, body.account_id, body.place_id,
        body.title, auth["user_id"],
    )


@router.delete("/clients/{client_id}/gbp/locations/{row_id}")
async def unregister_location(
    client_id: UUID, row_id: UUID, auth: dict = Depends(require_staff)
):
    """Remove a registered location (its posts cascade-delete)."""
    loc_svc.unregister_location(str(client_id), str(row_id))
    return {"ok": True}


# ── images (validated upload + reuse existing client assets) ─────────────────
@router.post("/clients/{client_id}/gbp/posts/image", response_model=GbpImageUploadResponse)
async def upload_post_image(
    client_id: UUID, file: UploadFile = File(...), auth: dict = Depends(require_auth)
):
    """Upload a JPG/PNG (>=250x250, 10 KB-25 MB) to the public bucket and return
    its URL to drop into a post's media. Validated against Google's floor so a
    bad image fails here, not as a rejected post."""
    data = await file.read()
    url = svc.upload_post_image(data, file.content_type or "")
    return GbpImageUploadResponse(url=url)


@router.post("/clients/{client_id}/gbp/posts/generate-image", response_model=GbpImageUploadResponse)
async def generate_post_image(
    client_id: UUID, body: GbpGenerateImageRequest, auth: dict = Depends(require_auth)
):
    """Generate a post image from a text prompt with Nano Banana (Gemini 2.5 Flash
    Image), store it in the public bucket, and return its URL to drop into media."""
    url = await svc.generate_post_image(body.prompt)
    return GbpImageUploadResponse(url=url)


@router.post("/clients/{client_id}/gbp/posts/image-from-url", response_model=GbpImageUploadResponse)
async def image_from_url(
    client_id: UUID, body: GbpImageFromUrlRequest, auth: dict = Depends(require_auth)
):
    """Fetch a public image URL, validate it against Google's floor, and re-host
    it in the public bucket. Returns the hosted URL to drop into a post's media."""
    url = await svc.import_post_image_from_url(body.url)
    return GbpImageUploadResponse(url=url)


@router.get("/clients/{client_id}/gbp/posts/reusable-images", response_model=list[GbpReusableImage])
async def reusable_images(client_id: UUID, auth: dict = Depends(require_auth)):
    """Existing public client images (blog + Local SEO featured images) to reuse."""
    svc._assert_enabled()
    return svc.list_reusable_images(str(client_id))


# ── posts CRUD ───────────────────────────────────────────────────────────────
@router.get("/clients/{client_id}/gbp/posts", response_model=list[GbpPost])
async def list_posts(
    client_id: UUID, deleted: bool = Query(False), auth: dict = Depends(require_auth)
):
    svc._assert_enabled()
    return svc.list_posts(str(client_id), deleted=deleted)


@router.post("/clients/{client_id}/gbp/posts", response_model=GbpPost)
async def create_post(
    client_id: UUID, body: GbpPostCreateRequest, auth: dict = Depends(require_auth)
):
    return svc.create_post(str(client_id), body.model_dump(mode="json"), auth["user_id"])


@router.delete("/clients/{client_id}/gbp/posts/trash", response_model=GbpTrashPurgeResponse)
async def empty_trash(client_id: UUID, auth: dict = Depends(require_auth)):
    """Permanently delete all trashed posts. Posts still live on Google are
    skipped (remove-from-google them first) and reported as skipped_live."""
    return svc.purge_trash(str(client_id))


@router.get("/gbp/posts/{post_id}", response_model=GbpPost)
async def get_post(post_id: UUID, auth: dict = Depends(require_auth)):
    svc._assert_enabled()
    return svc.get_post(str(post_id))


@router.patch("/gbp/posts/{post_id}", response_model=GbpPost)
async def update_post(
    post_id: UUID, body: GbpPostUpdateRequest, auth: dict = Depends(require_auth)
):
    return svc.update_post(str(post_id), body.model_dump(mode="json", exclude_unset=True))


@router.delete("/gbp/posts/{post_id}")
async def delete_post(post_id: UUID, auth: dict = Depends(require_auth)):
    """Soft-delete (move to trash). Leaves any live Google post in place."""
    svc.delete_post(str(post_id))
    return {"ok": True}


@router.post("/gbp/posts/{post_id}/restore", response_model=GbpPost)
async def restore_post(post_id: UUID, auth: dict = Depends(require_auth)):
    return svc.restore_post(str(post_id))


@router.delete("/gbp/posts/{post_id}/permanent")
async def purge_post(post_id: UUID, auth: dict = Depends(require_auth)):
    svc.purge_post(str(post_id))
    return {"ok": True}


@router.post("/gbp/posts/{post_id}/remove-from-google")
async def remove_from_google(post_id: UUID, auth: dict = Depends(require_auth)):
    """Delete the live post from Google (if published) and trash the row."""
    return await svc.remove_from_google(str(post_id))


# ── publish / generate / sync (async jobs) ───────────────────────────────────
@router.post("/clients/{client_id}/gbp/posts/{post_id}/publish", response_model=GbpJob)
async def publish_post(client_id: UUID, post_id: UUID, auth: dict = Depends(require_auth)):
    assert_not_frozen(str(client_id))  # Freeze Protocol: content output paused
    job_id = svc.enqueue_publish(str(post_id), str(client_id))
    return GbpJob(job_id=job_id)


@router.post("/clients/{client_id}/gbp/posts/{post_id}/schedule", response_model=GbpPost)
async def schedule_post(
    client_id: UUID, post_id: UUID, body: GbpPostScheduleAtRequest,
    auth: dict = Depends(require_auth),
):
    """Schedule a specific post to publish at a future time. The per-tick due
    sweep publishes it when due (and honours the Freeze Protocol then)."""
    return svc.schedule_post(str(post_id), str(client_id), body.scheduled_at)


@router.post("/clients/{client_id}/gbp/posts/{post_id}/unschedule", response_model=GbpPost)
async def unschedule_post(client_id: UUID, post_id: UUID, auth: dict = Depends(require_auth)):
    """Cancel a future schedule — the post reverts to a plain draft."""
    return svc.unschedule_post(str(post_id), str(client_id))


@router.post("/clients/{client_id}/gbp/posts/generate", response_model=GbpJob)
async def generate_post(
    client_id: UUID, body: GbpPostGenerateRequest, auth: dict = Depends(require_auth)
):
    """AI-draft a post (lands as a draft for review — never auto-publishes here)."""
    job_id = svc.enqueue_generate(str(client_id), body.model_dump(mode="json"), auth["user_id"])
    return GbpJob(job_id=job_id)


@router.post("/clients/{client_id}/gbp/posts/generate-from-url", response_model=GbpBulkGenerateResponse)
async def generate_from_url(
    client_id: UUID, body: GbpGenerateFromUrlRequest, auth: dict = Depends(require_auth)
):
    """Read a page URL and draft 0–99 DISTINCT posts from its content (each lands
    as a draft for review). Returns the enqueued job ids to poll."""
    return await svc.enqueue_generate_from_url(
        str(client_id), str(body.location_row_id), body.url, body.count,
        body.topic_type, body.cta_type, body.cta_url, auth["user_id"],
    )


@router.post("/clients/{client_id}/gbp/posts/jobs/status", response_model=list[GbpJobStatus])
async def jobs_status(
    client_id: UUID, body: GbpJobsStatusRequest, auth: dict = Depends(require_auth)
):
    svc._assert_enabled()
    return svc.get_jobs_status(str(client_id), [str(j) for j in body.job_ids])


@router.post("/clients/{client_id}/gbp/posts/sync", response_model=GbpJob)
async def sync_posts(client_id: UUID, auth: dict = Depends(require_auth)):
    """Reconcile live/rejected state from Google + import external posts."""
    job_id = svc.enqueue_sync(str(client_id))
    return GbpJob(job_id=job_id)


# ── schedule ─────────────────────────────────────────────────────────────────
@router.get("/clients/{client_id}/gbp/timezone", response_model=GbpTimezoneResponse)
async def get_client_timezone(client_id: UUID, auth: dict = Depends(require_auth)):
    """The client's local timezone GBP scheduling is expressed in (derived from
    the GBP location, cached on the client). None → the UI falls back to UTC.
    Ungated: harmless read the compose + schedule tabs use to label times."""
    return GbpTimezoneResponse(timezone=gbp_timezone.resolve_client_timezone(str(client_id)))


@router.get("/clients/{client_id}/gbp/post-schedule", response_model=GbpSchedule)
async def get_schedule(client_id: UUID, auth: dict = Depends(require_auth)):
    svc._assert_enabled()
    return svc.get_schedule(str(client_id))


@router.put("/clients/{client_id}/gbp/post-schedule", response_model=GbpSchedule)
async def upsert_schedule(
    client_id: UUID, body: GbpScheduleUpsertRequest, auth: dict = Depends(require_auth)
):
    return svc.upsert_schedule(str(client_id), body.model_dump(mode="json"), auth["user_id"])

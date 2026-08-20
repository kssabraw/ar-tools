"""GBP Posts module — service layer.

Owns the post lifecycle (draft → publishing → live | rejected | failed),
AI drafting, publish/sync async jobs, and the recurring-post scheduler tick.
Publishing goes through the v4 wrapper (``gbp_posts_api``); Google identity +
location resolution reuse the dormant GBP connection layer
(``gbp_performance_service`` + ``gbp_locations``).

Freeze Protocol: publishing is content *output* and pauses under a freeze
(``gbp_post_publish`` is in ``FREEZE_GATED_JOB_TYPES``; the router asserts too).
Drafting/sync keep running — the SOP pauses output, not observation.

Pure helpers (``compute_next_run_at``, ``build_client_context``) are unit-tested.

See: docs/modules/gbp-posts-module-prd-v1_0.md.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import gbp_posts_api as api
from services import gbp_timezone
from services import notifications

logger = logging.getLogger(__name__)

_POST_COLUMNS = (
    "id, client_id, location_row_id, schedule_id, source, topic_type, summary, "
    "cta_type, cta_url, event, offer, media, status, scheduled_at, published_at, "
    "google_name, google_state, search_url, error, created_at, updated_at"
)
_VALID_CADENCES = {"weekly", "biweekly", "monthly", "disabled"}
# Statuses a post can be published from (a draft, a scheduled row, or a retry).
_PUBLISHABLE = {"draft", "scheduled", "failed"}

# Post images go to the public wordpress_images bucket (reused — Google fetches
# the sourceUrl at publish, so it must be public), under a gbp-posts/ key prefix.
# Google's local-post media floor: JPG/PNG only, >=250x250 px, 10 KB-25 MB. We
# validate up front so a bad image fails at upload, not as a rejected post.
_IMAGE_BUCKET = "wordpress_images"
GBP_IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png"}
GBP_IMAGE_MIN_PX = 250
GBP_IMAGE_MIN_BYTES = 10 * 1024
GBP_IMAGE_MAX_BYTES = 25 * 1024 * 1024


# ───────────────────────────────────────────────────────────────────────────
# Gate + location resolution
# ───────────────────────────────────────────────────────────────────────────
def _assert_enabled() -> None:
    if not (settings.gbp_api_enabled and settings.gbp_posts_enabled):
        raise HTTPException(status_code=503, detail="gbp_posts_not_enabled")


def _client(client_id: str) -> dict:
    res = get_supabase().table("clients").select("*").eq("id", client_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    return res.data[0]


def _client_slug(client: dict) -> str:
    return (client.get("name") or "client").strip() or "client"


def list_ok_locations(client_id: str) -> list[dict]:
    """The client's registered GBP locations that the SA can post to."""
    res = (
        get_supabase().table("gbp_locations")
        .select("id, location_id, account_id, title, access_status")
        .eq("client_id", client_id)
        .order("created_at")
        .execute()
    )
    return res.data or []


def _location(location_row_id: str, client_id: str) -> dict:
    res = (
        get_supabase().table("gbp_locations")
        .select("id, client_id, location_id, account_id, title, access_status")
        .eq("id", location_row_id)
        .limit(1)
        .execute()
    )
    if not res.data or res.data[0].get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="gbp_location_not_found")
    return res.data[0]


def _parent_for(location: dict) -> str:
    try:
        return api.v4_parent(location.get("account_id") or "", location["location_id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ───────────────────────────────────────────────────────────────────────────
# CRUD
# ───────────────────────────────────────────────────────────────────────────
def _validate_body_fields(row: dict) -> None:
    """Validate a post row's content by building the v4 body (raises 400)."""
    try:
        api.build_local_post_body(
            summary=row.get("summary") or "",
            topic_type=row.get("topic_type") or "standard",
            cta_type=row.get("cta_type"),
            cta_url=row.get("cta_url"),
            event=row.get("event"),
            offer=row.get("offer"),
            media=row.get("media"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def create_post(client_id: str, body: dict, user_id: str, source: str = "manual") -> dict:
    """Create a draft post row (validated). Does NOT publish."""
    _assert_enabled()
    location = _location(str(body["location_row_id"]), client_id)
    row = {
        "client_id": client_id,
        "location_row_id": location["id"],
        "source": source,
        "topic_type": body.get("topic_type") or "standard",
        "summary": (body.get("summary") or "").strip(),
        "cta_type": body.get("cta_type"),
        "cta_url": body.get("cta_url"),
        "event": body.get("event"),
        "offer": body.get("offer"),
        "media": body.get("media"),
        "status": "draft",
        "created_by": user_id,
    }
    _validate_body_fields(row)
    res = get_supabase().table("gbp_posts").insert(row).execute()
    return res.data[0]


def update_post(post_id: str, patch: dict) -> dict:
    """Update a draft/live post's content fields (validated)."""
    _assert_enabled()
    current = get_post(post_id)
    if current["status"] in ("publishing",):
        raise HTTPException(status_code=409, detail="post_publishing")
    fields = {k: v for k, v in patch.items() if v is not None}
    if not fields:
        return current
    merged = {**current, **fields}
    _validate_body_fields(merged)
    fields["updated_at"] = "now()"
    res = get_supabase().table("gbp_posts").update(fields).eq("id", post_id).execute()
    return res.data[0]


def list_posts(client_id: str, deleted: bool = False) -> list[dict]:
    """List a client's posts. deleted=False → active; deleted=True → Drafts (trash)."""
    query = (
        get_supabase().table("gbp_posts").select(_POST_COLUMNS).eq("client_id", client_id)
    )
    if deleted:
        query = query.not_.is_("deleted_at", "null").order("deleted_at", desc=True)
    else:
        query = query.is_("deleted_at", "null").order("created_at", desc=True)
    return query.execute().data or []


def get_post(post_id: str) -> dict:
    res = get_supabase().table("gbp_posts").select("*").eq("id", post_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="gbp_post_not_found")
    return res.data[0]


def delete_post(post_id: str) -> None:
    """Soft-delete (move to trash). The live Google post, if any, is left as-is —
    deleting from Google is an explicit action (see ``remove_from_google``)."""
    res = (
        get_supabase().table("gbp_posts")
        .update({"deleted_at": "now()", "updated_at": "now()"})
        .eq("id", post_id)
        .is_("deleted_at", "null")
        .execute()
    )
    if not res.data:
        existing = get_supabase().table("gbp_posts").select("id").eq("id", post_id).execute().data
        if not existing:
            raise HTTPException(status_code=404, detail="gbp_post_not_found")


def restore_post(post_id: str) -> dict:
    res = (
        get_supabase().table("gbp_posts")
        .update({"deleted_at": None, "updated_at": "now()"})
        .eq("id", post_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="gbp_post_not_found")
    return res.data[0]


def purge_post(post_id: str) -> None:
    res = get_supabase().table("gbp_posts").delete().eq("id", post_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="gbp_post_not_found")


def is_live_on_google(post: dict) -> bool:
    """True if a post is currently published + live on Google. Pure (unit-tested).
    Purging such a row would orphan a live post, so empty-trash skips these."""
    return post.get("status") == "live" and bool(post.get("google_name"))


def purge_trash(client_id: str) -> dict:
    """Empty the trash: permanently delete all a client's trashed posts. Posts
    still LIVE on Google are skipped (remove-from-google them first, else the row
    is gone but the post stays up). Returns {purged, skipped_live}."""
    _assert_enabled()
    supabase = get_supabase()
    trashed = (
        supabase.table("gbp_posts").select("id, status, google_name")
        .eq("client_id", client_id).not_.is_("deleted_at", "null")
        .execute().data or []
    )
    purge_ids = [r["id"] for r in trashed if not is_live_on_google(r)]
    skipped = len(trashed) - len(purge_ids)
    if purge_ids:
        supabase.table("gbp_posts").delete().in_("id", purge_ids).execute()
    logger.info("gbp_posts.trash_purged",
                extra={"client_id": client_id, "purged": len(purge_ids), "skipped_live": skipped})
    return {"purged": len(purge_ids), "skipped_live": skipped}


async def remove_from_google(post_id: str) -> dict:
    """Delete the live post from Google (if published) and mark the row deleted."""
    _assert_enabled()
    post = get_post(post_id)
    if post.get("google_name"):
        try:
            await asyncio.to_thread(api.delete_post, post["google_name"])
        except HTTPException:
            raise
    get_supabase().table("gbp_posts").update(
        {"status": "deleted", "deleted_at": "now()", "updated_at": "now()"}
    ).eq("id", post_id).execute()
    return {"ok": True}


# ───────────────────────────────────────────────────────────────────────────
# Images — validated upload to the public bucket + reuse of existing assets
# ───────────────────────────────────────────────────────────────────────────
def image_rejection_reason(
    content_type: str, width: int, height: int, size_bytes: int
) -> Optional[str]:
    """Why an image would be rejected as GBP post media, or None if it's fine.
    Pure (unit-tested) — enforces Google's local-post floor so a bad image fails
    at upload instead of getting the whole post rejected."""
    if (content_type or "").lower() not in GBP_IMAGE_TYPES:
        return "unsupported_image_type"  # JPG/PNG only for GBP local posts
    if size_bytes < GBP_IMAGE_MIN_BYTES:
        return "image_too_small_bytes"
    if size_bytes > GBP_IMAGE_MAX_BYTES:
        return "image_too_large"
    if width < GBP_IMAGE_MIN_PX or height < GBP_IMAGE_MIN_PX:
        return "image_dimensions_too_small"
    return None


def upload_post_image(data: bytes, content_type: str) -> str:
    """Validate an uploaded image against Google's floor and store it in the
    public bucket. Returns the public sourceUrl to drop into a post's media."""
    _assert_enabled()
    ct = (content_type or "").lower()
    if not data:
        raise HTTPException(status_code=422, detail="empty_file")
    if ct not in GBP_IMAGE_TYPES:
        raise HTTPException(status_code=422, detail="unsupported_image_type")
    try:
        import io  # lazy

        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
    except Exception:  # noqa: BLE001 — a non-decodable upload is a bad image
        raise HTTPException(status_code=422, detail="invalid_image")
    reason = image_rejection_reason(ct, width, height, len(data))
    if reason:
        raise HTTPException(status_code=413 if reason == "image_too_large" else 422, detail=reason)

    path = f"gbp-posts/{uuid4()}.{GBP_IMAGE_TYPES[ct]}"
    supabase = get_supabase()
    try:
        supabase.storage.from_(_IMAGE_BUCKET).upload(
            path, data, {"content-type": ct, "upsert": "true"}
        )
        return supabase.storage.from_(_IMAGE_BUCKET).get_public_url(path).rstrip("?")
    except Exception as exc:  # noqa: BLE001
        logger.error("gbp_posts.image_upload_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=502, detail="image_upload_failed")


def build_image_prompt(prompt: str, business_name: Optional[str] = None) -> str:
    """A brand-safe image prompt for Nano Banana from the user's idea. Appends a
    photographic, text-free style tail so the render suits a Business Profile post
    and can't stamp a fake sign/logo. Pure (unit-tested)."""
    base = (prompt or "").strip()
    who = f" for {business_name.strip()}" if business_name and business_name.strip() else ""
    return (
        f"{base}. A professional, high-quality photograph{who} suitable for a Google "
        "Business Profile post — natural lighting, realistic, sharp focus, no text, "
        "no words, no letters, no logos, no watermarks."
    )


async def generate_post_image(prompt: str, business_name: Optional[str] = None) -> str:
    """Generate a GBP post image with Nano Banana (Gemini 2.5 Flash Image),
    validate it against Google's floor, store it in the public bucket, and return
    the sourceUrl. Interactive — raises HTTPException on failure."""
    _assert_enabled()
    from services import nano_banana  # lazy

    if not nano_banana.is_configured():
        raise HTTPException(status_code=503, detail="image_gen_not_configured")
    if not (prompt or "").strip():
        raise HTTPException(status_code=422, detail="prompt_required")
    png = await nano_banana.generate_image(build_image_prompt(prompt, business_name))
    if not png:
        raise HTTPException(status_code=502, detail="image_gen_failed")
    # Reuse the upload path: same bucket, same Google-floor validation as an
    # uploaded image (Nano Banana returns PNG, comfortably above the floor).
    return upload_post_image(png, "image/png")


def content_type_for_image_format(fmt: Optional[str]) -> Optional[str]:
    """Map a Pillow image format to a GBP-allowed content type, or None if Google
    rejects it (WebP/GIF/etc.). Pure (unit-tested)."""
    return {"JPEG": "image/jpeg", "PNG": "image/png"}.get((fmt or "").upper())


async def import_post_image_from_url(url: str) -> str:
    """Fetch an image from a public URL, validate it against Google's floor, and
    re-host it in the public bucket — so the post's media is a stable URL Google
    can fetch at publish (an external URL may be private/hotlink-blocked/dead).
    Returns the hosted sourceUrl. Raises HTTPException on failure."""
    _assert_enabled()
    import io  # lazy

    import httpx

    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="invalid_image_url")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
            resp = await http.get(u, headers={"User-Agent": "Mozilla/5.0 (compatible; ar-tools/1.0)"})
    except Exception as exc:  # noqa: BLE001
        logger.info("gbp_posts.image_url_fetch_failed", extra={"url": u[:200], "error": str(exc)[:200]})
        raise HTTPException(status_code=502, detail="image_fetch_failed")
    if resp.status_code != 200 or not resp.content:
        raise HTTPException(status_code=502, detail="image_fetch_failed")
    data = resp.content
    # Sniff the real format (a wrong/missing Content-Type header is common) and
    # map it to a Google-allowed type; upload_post_image re-validates dims/size.
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            ct = content_type_for_image_format(im.format)
    except Exception:  # noqa: BLE001 — not a decodable image
        raise HTTPException(status_code=422, detail="invalid_image")
    if not ct:
        raise HTTPException(status_code=422, detail="unsupported_image_type")
    return upload_post_image(data, ct)


def list_reusable_images(client_id: str) -> list[dict]:
    """The client's existing public images (blog featured images + Local SEO page
    images) so a post can reuse an asset already generated for the client — the
    'reuse suite images' half of the media picker (locked decision 3)."""
    supabase = get_supabase()
    out: list[dict] = []
    seen: set[str] = set()

    def _collect(table: str, source: str, extra_filter=None) -> None:
        query = (
            supabase.table(table).select("featured_image_url, keyword, created_at")
            .eq("client_id", client_id).not_.is_("featured_image_url", "null")
        )
        if extra_filter:
            query = extra_filter(query)
        rows = query.order("created_at", desc=True).limit(50).execute().data or []
        for r in rows:
            url = r.get("featured_image_url")
            if url and url not in seen:
                seen.add(url)
                out.append({"url": url, "source": source, "label": r.get("keyword")})

    try:
        _collect("runs", "blog")
    except Exception as exc:  # noqa: BLE001 — a missing column / table never breaks the picker
        logger.info("gbp_posts.reusable_runs_failed", extra={"error": str(exc)})
    try:
        _collect("local_seo_pages", "local_seo", lambda q: q.is_("deleted_at", "null"))
    except Exception as exc:  # noqa: BLE001
        logger.info("gbp_posts.reusable_localseo_failed", extra={"error": str(exc)})
    return out


# ───────────────────────────────────────────────────────────────────────────
# Publish (async job; freeze-gated)
# ───────────────────────────────────────────────────────────────────────────
def _insert_publish_job(client_id: str, post_id: str) -> str:
    """Insert a ``gbp_post_publish`` async job (no status/validation side effects).
    Shared by the interactive publish-now path and the due-scheduled sweep.

    ``max_attempts`` is raised above the queue default so a transient Google
    publish error (see ``gbp_posts_api.is_transient_post_error``) is re-queued on
    the shared retry ladder instead of failing the post on the first blip."""
    res = (
        get_supabase().table("async_jobs")
        .insert({"job_type": "gbp_post_publish", "entity_id": client_id,
                 "max_attempts": settings.gbp_post_publish_max_attempts,
                 "payload": {"client_id": client_id, "post_id": post_id}})
        .execute()
    )
    return res.data[0]["id"]


def _has_active_publish_job(client_id: str, post_id: str) -> bool:
    """True if a pending/running publish job already exists for this post — the
    idempotency guard that stops the due sweep re-enqueuing every tick."""
    rows = (
        get_supabase().table("async_jobs").select("id, payload")
        .eq("job_type", "gbp_post_publish").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).execute().data or []
    )
    return any((r.get("payload") or {}).get("post_id") == post_id for r in rows)


def ensure_future_utc(when: datetime, now: datetime, tz: Optional[str] = None) -> str:
    """Normalize a scheduled time to a UTC ISO string, or raise if not future.

    Pure (unit-tested). A **naive** ``when`` is interpreted as a wall-clock in
    ``tz`` (the client's IANA timezone) and converted to UTC — so the operator
    picks the time in the client's local time. ``tz=None`` treats naive as UTC
    (back-compat). An **aware** ``when`` is just converted to UTC (the frontend
    already resolved it)."""
    w = when.astimezone(timezone.utc) if when.tzinfo else when.replace(tzinfo=_zone(tz)).astimezone(timezone.utc)
    if w <= now:
        raise HTTPException(status_code=400, detail="scheduled_at_must_be_future")
    return w.isoformat()


def enqueue_publish(post_id: str, client_id: str) -> str:
    """Publish a post NOW: mark it scheduled (no future time) + enqueue the job.
    Returns the job id."""
    _assert_enabled()
    post = get_post(post_id)
    if post.get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="gbp_post_not_found")
    if post["status"] not in _PUBLISHABLE:
        raise HTTPException(status_code=409, detail=f"post_not_publishable:{post['status']}")
    _validate_body_fields(post)
    get_supabase().table("gbp_posts").update(
        {"status": "scheduled", "scheduled_at": None, "error": None, "updated_at": "now()"}
    ).eq("id", post_id).execute()
    return _insert_publish_job(client_id, post_id)


def schedule_post(post_id: str, client_id: str, scheduled_at: datetime) -> dict:
    """Schedule a specific post to publish at a future time. It stays 'scheduled'
    with a `scheduled_at`; the per-tick due sweep publishes it when the time comes
    (a future-dated async job would be claimed immediately, so we can't defer via
    the job queue). Validates content + a future time up front."""
    _assert_enabled()
    post = get_post(post_id)
    if post.get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="gbp_post_not_found")
    if post["status"] not in _PUBLISHABLE:
        raise HTTPException(status_code=409, detail=f"post_not_publishable:{post['status']}")
    _validate_body_fields(post)
    tz = gbp_timezone.resolve_client_timezone(client_id)
    when_iso = ensure_future_utc(scheduled_at, datetime.now(timezone.utc), tz=tz)
    get_supabase().table("gbp_posts").update(
        {"status": "scheduled", "scheduled_at": when_iso, "error": None, "updated_at": "now()"}
    ).eq("id", post_id).execute()
    return get_post(post_id)


def unschedule_post(post_id: str, client_id: str) -> dict:
    """Cancel a future schedule — back to a plain draft."""
    _assert_enabled()
    post = get_post(post_id)
    if post.get("client_id") != client_id:
        raise HTTPException(status_code=404, detail="gbp_post_not_found")
    if post.get("scheduled_at") is None:
        return post
    get_supabase().table("gbp_posts").update(
        {"status": "draft", "scheduled_at": None, "updated_at": "now()"}
    ).eq("id", post_id).execute()
    return get_post(post_id)


def enqueue_due_gbp_scheduled_posts() -> int:
    """Per-tick sweep: publish any post whose scheduled_at has come due. Skips
    frozen clients (publish is paused — it fires once the freeze lifts) and posts
    that already have an active publish job. No-op until the module is enabled."""
    if not (settings.gbp_api_enabled and settings.gbp_posts_enabled):
        return 0
    from services.freeze import is_frozen

    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    due = (
        supabase.table("gbp_posts").select("id, client_id")
        .eq("status", "scheduled").not_.is_("scheduled_at", "null")
        .lte("scheduled_at", now.isoformat()).is_("deleted_at", "null")
        .execute().data or []
    )
    count = 0
    for post in due:
        cid, pid = post["client_id"], post["id"]
        if is_frozen(cid) or _has_active_publish_job(cid, pid):
            continue
        try:
            _insert_publish_job(cid, pid)
            count += 1
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning("gbp_posts.scheduled_enqueue_failed",
                           extra={"post_id": pid, "error": str(getattr(exc, "detail", exc))})
    if count:
        logger.info("gbp_posts.scheduled_published", extra={"posts": count})
    return count


def publish_failure_is_transient(exc: Exception) -> bool:
    """Whether a publish failure should be retried rather than failing the post.

    A v4-wrapper error is an ``HTTPException`` whose ``detail`` is a classified
    code (``gbp_posts_api.classify_post_error``) — the code decides (see
    ``is_transient_post_error``; note the wrapper maps EVERY non-2xx to a 502, so
    the HTTP status can't classify — the detail code must). A raw transport error
    (connection reset / timeout with no response) is transient too. Pure."""
    detail = getattr(exc, "detail", None)
    if detail is not None:
        return api.is_transient_post_error(str(detail))
    return isinstance(exc, (httpx.HTTPError, ConnectionError, TimeoutError, asyncio.TimeoutError))


async def run_publish_job(job: dict) -> None:
    """Handler for job_type='gbp_post_publish'. Builds the v4 body, creates the
    post on Google, persists the result, and schedules a state re-check.

    Transient Google failures (a propagation-flake 403 / quota 429 / 5xx / a
    transport blip) are re-queued on the shared retry ladder with backoff while
    attempts remain — only a terminal failure or an exhausted retry budget marks
    the post ``failed`` and alerts the team (see ``publish_failure_is_transient``)."""
    payload = job.get("payload") or {}
    post_id = payload.get("post_id")
    client_id = payload.get("client_id")
    supabase = get_supabase()
    try:
        post = get_post(post_id)
        # Idempotency: a prior attempt may have created the post on Google but
        # failed to settle its row (e.g. a transport timeout AFTER creation),
        # leaving google_name set. Re-creating would duplicate it — reconcile the
        # existing post instead and let the sync job confirm its live state.
        if post.get("google_name"):
            supabase.table("gbp_posts").update({
                "status": api.state_to_status(post.get("google_state")),
                "error": None, "updated_at": "now()",
            }).eq("id", post_id).execute()
            supabase.table("async_jobs").update(
                {"status": "complete", "result": {"post_id": post_id, "already_published": True},
                 "completed_at": "now()"}
            ).eq("id", job["id"]).execute()
            _enqueue_sync(client_id, delay_seconds=60)
            logger.info("gbp_posts.publish_already_created", extra={"post_id": post_id})
            return
        location = _location(post["location_row_id"], client_id)
        if location.get("access_status") != "ok":
            raise HTTPException(status_code=409, detail="gbp_location_not_verified")
        parent = _parent_for(location)
        client = _client(client_id)
        cta_url = post.get("cta_url")
        if cta_url and settings.gbp_post_default_utm:
            cta_url = api.append_utm(cta_url, _client_slug(client))
        body = api.build_local_post_body(
            summary=post["summary"], topic_type=post["topic_type"],
            cta_type=post.get("cta_type"), cta_url=cta_url,
            event=post.get("event"), offer=post.get("offer"), media=post.get("media"),
        )
        supabase.table("gbp_posts").update({"status": "publishing", "updated_at": "now()"}).eq("id", post_id).execute()
        created = await asyncio.to_thread(api.create_post, parent, body)
        supabase.table("gbp_posts").update({
            "status": created["status"], "google_name": created.get("google_name"),
            "google_state": created.get("google_state"), "search_url": created.get("search_url"),
            "published_at": "now()", "scheduled_at": None, "error": None, "updated_at": "now()",
        }).eq("id", post_id).execute()
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"post_id": post_id, "state": created.get("google_state")},
             "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
        # Re-check state shortly after (catches an async REJECTED verdict).
        _enqueue_sync(client_id, delay_seconds=900)
        logger.info("gbp_posts.published", extra={"post_id": post_id, "state": created.get("google_state")})
    except Exception as exc:  # noqa: BLE001 — retry a transient blip, else fail + alert
        from services.job_worker import plan_job_retry  # lazy: avoids import cycle

        detail = str(getattr(exc, "detail", None) or exc)
        attempts = int(job.get("attempts") or 1)
        max_attempts = int(job.get("max_attempts") or settings.gbp_post_publish_max_attempts)
        job_update, outcome = plan_job_retry(
            attempts, max_attempts, publish_failure_is_transient(exc), detail
        )
        supabase.table("async_jobs").update(job_update).eq("id", job["id"]).execute()
        if outcome == "requeued":
            # Keep the post in-flight (no scary 'failed', no alert) while it retries.
            supabase.table("gbp_posts").update(
                {"status": "publishing",
                 "error": f"Transient publish error; retrying automatically ({attempts}/{max_attempts}).",
                 "updated_at": "now()"}
            ).eq("id", post_id).execute()
            logger.info("gbp_posts.publish_retry",
                        extra={"post_id": post_id, "attempt": attempts,
                               "max_attempts": max_attempts, "error": detail[:200]})
            return
        supabase.table("gbp_posts").update(
            {"status": "failed", "error": detail[:500], "updated_at": "now()"}
        ).eq("id", post_id).execute()
        notifications.emit(
            client_id, "gbp_post_failed", "GBP post failed to publish",
            summary=detail[:200], severity="warning", payload={"post_id": post_id},
        )
        logger.warning("gbp_posts.publish_failed", extra={"post_id": post_id, "error": detail})


# ───────────────────────────────────────────────────────────────────────────
# AI drafting (async job)
# ───────────────────────────────────────────────────────────────────────────
def build_client_context(client: dict) -> str:
    """Compact client context for the draft prompt (name, services, voice, ICP)."""
    lines = [f"Business: {client.get('name') or 'the business'}"]
    if client.get("website_url"):
        lines.append(f"Website: {client['website_url']}")
    loc = client.get("business_location")
    if loc:
        lines.append(f"Location: {loc}")
    voice = (client.get("brand_voice") or {})
    if isinstance(voice, dict) and voice.get("raw_text"):
        lines.append(f"Brand voice: {str(voice['raw_text'])[:600]}")
    icp = client.get("detected_icp")
    if icp:
        lines.append(f"Ideal customer: {str(icp)[:400]}")
    diff = client.get("differentiators")
    if diff:
        lines.append(f"Differentiators: {str(diff)[:400]}")
    return "\n".join(lines)


_DRAFT_SYSTEM = (
    "You write Google Business Profile posts for a local business — short, warm, "
    "plain-English updates a real owner would post. Rules you must follow:\n"
    "- Keep it under 1500 characters; aim for 2–4 short sentences.\n"
    "- Match the business's brand voice when given.\n"
    "- NEVER invent offers, prices, discounts, dates, or guarantees.\n"
    "- NEVER put a phone number in the post body (it gets the post rejected) — "
    "the call button handles that.\n"
    "- No medical, legal, or other regulated claims.\n"
    "- End with a light, natural nudge to act; the call-to-action button carries "
    "the link, so don't paste raw URLs.\n"
    "Return ONLY the post text — no preamble, no quotes, no markdown."
)

# Per-type drafting guidance. 'product' is a product-framed Update (Google has no
# product-post API), so it spotlights one product without inventing price/specs.
_TYPE_GUIDE = {
    "standard": "This is a general update or piece of news about the business.",
    "product": (
        "Spotlight ONE product or service: what it is, who it's for, and its main "
        "benefit. Do NOT invent a price, discount, or specs. Nudge the reader to "
        "shop or browse."
    ),
    "offer": (
        "Describe the offer plainly. Do NOT invent a discount amount, coupon code, "
        "or dates — use only what's provided in the topic/angle."
    ),
    "event": (
        "Describe the event and why it's worth attending. Do NOT invent a date or "
        "time — use only what's provided in the topic/angle."
    ),
}


# Rotating angles so N posts drawn from one page read distinctly instead of
# paraphrasing each other. Cycled by the post's index within the batch.
_VARIATION_ANGLES = [
    "Lead with the single biggest benefit or takeaway from the page.",
    "Highlight one specific tip, step, or detail from the page.",
    "Answer a common customer question the page addresses.",
    "Focus on a problem the page solves and how it's solved.",
    "Share a 'did you know' fact from the page — only if it's actually stated there.",
    "Emphasize the outcome or result the reader gets.",
    "Frame it as a quick how-to based on the page.",
    "Take a timely or seasonal angle tied to the page's topic.",
]


def variation_instruction(index: int, total: int) -> Optional[str]:
    """A distinct-angle instruction for post `index` of `total` from one page, or
    None for a single post. Pure (unit-tested)."""
    if not total or total <= 1:
        return None
    angle = _VARIATION_ANGLES[(max(1, index) - 1) % len(_VARIATION_ANGLES)]
    return (
        f"This is post {index} of {total} drawn from the SAME page — make it clearly "
        f"DISTINCT from the others: {angle} Vary the opening line and wording so the "
        "posts don't repeat each other."
    )


def render_voice_card_block(card: Optional[dict]) -> str:
    """The distilled Voice & Audience Card as a late, high-priority prompt block
    for a GBP post — the same enforceable card the page writers use, rendered
    compactly for a short post. Empty string when there's no card. Pure."""
    if not isinstance(card, dict) or not any(card.values()):
        return ""
    lines = [
        "BRAND VOICE & AUDIENCE — THE CLIENT'S OWN GUIDE (HIGHEST PRIORITY).",
        "Where anything above conflicts on tone, word choice, grammatical person, or "
        "CTA wording, THESE RULES WIN.",
    ]
    if card.get("tone_adjectives"):
        lines.append(f"Tone (the post must read this way): {', '.join(card['tone_adjectives'])}")
    person = card.get("person")
    if person == "first":
        lines.append('Grammatical person: FIRST PERSON — write as "we/our".')
    elif person == "third":
        lines.append('Grammatical person: THIRD PERSON — name the business, not "we/our".')
    if card.get("voice_directives"):
        lines.append("Voice rules: " + "; ".join(card["voice_directives"]))
    if card.get("must_use_terms"):
        lines.append("Use these terms verbatim where they fit: " + ", ".join(f'"{t}"' for t in card["must_use_terms"]))
    if card.get("never_use_terms"):
        lines.append("FORBIDDEN — never use these words/phrases: " + ", ".join(f'"{t}"' for t in card["never_use_terms"]))
    if card.get("discouraged_terms"):
        lines.append("Avoid where possible: " + ", ".join(f'"{t}"' for t in card["discouraged_terms"]))
    aud: list[str] = []
    if card.get("audience_label"):
        aud.append(f"Primary customer: {card['audience_label']}.")
    if card.get("audience_pain_points"):
        aud.append("Worried about: " + "; ".join(card["audience_pain_points"]) + ".")
    if card.get("audience_motivations"):
        aud.append("They want: " + "; ".join(card["audience_motivations"]) + ".")
    if card.get("audience_objections"):
        aud.append("They hesitate because: " + "; ".join(card["audience_objections"]) + ".")
    if aud:
        lines.append("Write to this customer — " + " ".join(aud))
    if card.get("cta_language"):
        lines.append("CTA wording — use the client's phrasing: " + " / ".join(f'"{c}"' for c in card["cta_language"]))
    return "\n".join(lines)


def voice_forbidden_hits(text: str, card: Optional[dict]) -> list[str]:
    """The card's never-use terms that appear in `text` (word-boundary,
    case-insensitive). Pure (unit-tested) — the enforcement trigger."""
    terms = (card or {}).get("never_use_terms") or []
    hits: list[str] = []
    for term in terms:
        t = (term or "").strip()
        if t and re.search(r"\b" + re.escape(t) + r"\b", text or "", re.IGNORECASE):
            hits.append(t)
    return hits


async def draft_summary(
    client: dict, topic_type: str, theme: Optional[str], source_url: Optional[str],
    *, page_content: Optional[str] = None, page_title: Optional[str] = None,
    variation: Optional[str] = None, card: Optional[dict] = None,
) -> str:
    """One bounded Claude call returning post body text, grounded in the client's
    distilled Voice & Audience Card when present (with a corrective pass if a
    forbidden term slips through). Raises on hard failure."""
    from services import anthropic_failover  # lazy

    from services.report_llm import retry_transient

    type_label = {"product": "product spotlight", "offer": "offer", "event": "event"}.get(
        topic_type, "update"
    )
    ask = [f"Write a Google Business Profile {type_label} post."]
    ask.append(_TYPE_GUIDE.get(topic_type, _TYPE_GUIDE["standard"]))
    if theme:
        ask.append(f"Topic / angle: {theme}")
    if page_content:
        ask.append(
            "Base the post ONLY on this page's actual content (do not invent facts, "
            f"prices, dates, or claims not present here). Page title: {page_title or 'n/a'}.\n"
            f"--- PAGE CONTENT ---\n{page_content}\n--- END PAGE CONTENT ---"
        )
    if source_url:
        ask.append(f"Feature this page and point the call-to-action at it: {source_url}")
    if variation:
        ask.append(variation)
    user = build_client_context(client) + "\n\n" + "\n".join(ask)
    # The distilled card is the late, high-priority block — it wins on expression.
    voice_block = render_voice_card_block(card)
    if voice_block:
        user += "\n\n" + voice_block

    # Same-model failover to the secondary Anthropic account on a transient limit.
    api_client = anthropic_failover.FailoverAsyncAnthropic(timeout=60)

    async def _one_call(content: str) -> str:
        resp = await retry_transient(
            lambda: api_client.messages.create(
                model=settings.gbp_post_model, max_tokens=settings.gbp_post_max_tokens,
                system=_DRAFT_SYSTEM, messages=[{"role": "user", "content": content}],
            ),
            max_retries=2, log_tag="gbp_post_draft",
        )
        return "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()

    text = (await _one_call(user))[: settings.gbp_post_max_chars]

    # Enforcement: a forbidden term is provable — one corrective rewrite to remove
    # it (mirrors the page writers' critical-finding → corrective pass). Keep the
    # version with fewer forbidden hits so a rewrite can never make it worse.
    hits = voice_forbidden_hits(text, card)
    if hits:
        fix = (
            "Rewrite this Google Business Profile post to REMOVE these forbidden words/"
            f"phrases entirely (and any close variant): {', '.join(hits)}. Keep the same "
            "meaning, the same brand voice, and under 1500 characters. Return ONLY the post.\n\n"
            + text
        )
        if voice_block:
            fix = voice_block + "\n\n" + fix
        try:
            rewritten = (await _one_call(fix))[: settings.gbp_post_max_chars]
            if rewritten and len(voice_forbidden_hits(rewritten, card)) < len(hits):
                text = rewritten
        except Exception as exc:  # noqa: BLE001 — enforcement is best-effort
            logger.info("gbp_posts.voice_correction_failed", extra={"error": str(exc)[:200]})
    return text


def enqueue_generate(client_id: str, req: dict, user_id: str) -> str:
    """Enqueue a ``gbp_post_generate`` job (drafts a post row). Returns job id."""
    _assert_enabled()
    location = _location(str(req["location_row_id"]), client_id)
    res = (
        get_supabase().table("async_jobs")
        .insert({"job_type": "gbp_post_generate", "entity_id": client_id, "payload": {
            "client_id": client_id, "location_row_id": location["id"],
            "topic_type": req.get("topic_type") or "standard", "theme": req.get("theme"),
            "source_url": req.get("source_url"), "cta_type": req.get("cta_type"),
            "cta_url": req.get("cta_url"), "user_id": user_id, "source": "ai",
            "auto_publish": bool(req.get("auto_publish")),
            "schedule_id": req.get("schedule_id"),
        }})
        .execute()
    )
    return res.data[0]["id"]


async def enqueue_regenerate(post_id: str, client_id: str, user_id: str) -> str:
    """Re-draft one AI post in place (async ``gbp_post_generate`` job). Reuses the
    post's stored gen_context — a URL-sourced post re-fetches its page and keeps
    its distinct angle. Raises if the post can't be regenerated (manual/no context)."""
    _assert_enabled()
    supabase = get_supabase()
    rows = (
        supabase.table("gbp_posts")
        .select("id, client_id, location_row_id, source, cta_type, cta_url, gen_context")
        .eq("id", post_id).eq("client_id", client_id).is_("deleted_at", "null")
        .limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="post_not_found")
    post = rows[0]
    ctx = post.get("gen_context") or {}
    if post.get("source") not in ("ai", "schedule"):
        raise HTTPException(status_code=422, detail="post_not_ai_generated")

    src = ctx.get("source_url")
    page_content = page_title = None
    if src:
        from services.syndication_rewrite import extract_source_content  # lazy

        try:
            page_title, markdown = await extract_source_content(src)
            page_content = (markdown or "")[: settings.gbp_post_source_chars]
        except Exception as exc:  # noqa: BLE001 — regenerate without the page rather than fail
            logger.info("gbp_posts.regen_source_fetch_failed", extra={"url": src, "error": str(exc)[:200]})

    res = (
        supabase.table("async_jobs")
        .insert({"job_type": "gbp_post_generate", "entity_id": client_id, "payload": {
            "client_id": client_id, "location_row_id": post["location_row_id"],
            "topic_type": ctx.get("topic_type") or "standard", "theme": ctx.get("theme"),
            "source_url": src, "page_content": page_content, "page_title": page_title,
            "variation_index": ctx.get("variation_index"), "variation_total": ctx.get("variation_total"),
            "cta_type": post.get("cta_type"), "cta_url": post.get("cta_url"),
            "user_id": user_id, "source": post.get("source") or "ai",
            "regenerate": True, "regenerate_post_id": post_id,
        }})
        .execute()
    )
    return res.data[0]["id"]


def clamp_bulk_count(count) -> int:
    """Clamp a requested bulk-post count to [0, gbp_post_max_bulk]. Pure."""
    try:
        n = int(count)
    except (TypeError, ValueError):
        return 0
    return max(0, min(n, settings.gbp_post_max_bulk))


async def enqueue_generate_from_url(
    client_id: str, location_row_id: str, url: str, count, topic_type: Optional[str],
    cta_type: Optional[str], cta_url: Optional[str], user_id: str,
) -> dict:
    """Fetch a page once and enqueue N ``gbp_post_generate`` jobs that each draft a
    DISTINCT GBP post from its content (staggered so they run at background
    priority). Returns {count, job_ids}. Drafts only — never auto-publishes."""
    _assert_enabled()
    location = _location(location_row_id, client_id)
    n = clamp_bulk_count(count)
    if n == 0:
        return {"count": 0, "job_ids": []}
    src = (url or "").strip()
    if not src:
        raise HTTPException(status_code=422, detail="url_required")

    from services.syndication_rewrite import extract_source_content  # lazy

    try:
        page_title, markdown = await extract_source_content(src)
    except Exception as exc:  # noqa: BLE001 — surface a clean, actionable error
        logger.warning("gbp_posts.source_fetch_failed", extra={"url": src, "error": str(exc)[:200]})
        raise HTTPException(status_code=502, detail="source_fetch_failed")
    content = (markdown or "")[: settings.gbp_post_source_chars]

    topic = topic_type or "standard"
    # Default the CTA at the page it's announcing (unless it's a Call button).
    cta_t = cta_type or "learn_more"
    cta_u = None if cta_t == "call" else (cta_url or src)

    now = datetime.now(timezone.utc)
    rows = [
        {
            "job_type": "gbp_post_generate", "entity_id": client_id,
            "scheduled_at": (now + timedelta(seconds=i * settings.gbp_post_bulk_spacing_seconds)).isoformat(),
            "payload": {
                "client_id": client_id, "location_row_id": location["id"],
                "topic_type": topic, "theme": None, "source_url": src,
                "page_content": content, "page_title": page_title,
                "variation_index": i + 1, "variation_total": n,
                "cta_type": cta_t, "cta_url": cta_u,
                "user_id": user_id, "source": "ai",
            },
        }
        for i in range(n)
    ]
    res = get_supabase().table("async_jobs").insert(rows).execute()
    logger.info("gbp_posts.bulk_from_url", extra={"client_id": client_id, "count": n, "url": src})
    return {"count": n, "job_ids": [r["id"] for r in res.data]}


async def run_generate_job(job: dict) -> None:
    """Handler for job_type='gbp_post_generate'. Drafts copy, creates a draft
    post row, and (for auto-publish schedules, if not frozen) chains publish."""
    from services.freeze import is_frozen

    payload = job.get("payload") or {}
    client_id = payload["client_id"]
    supabase = get_supabase()
    try:
        client = _client(client_id)
        vt = payload.get("variation_total")
        variation = variation_instruction(int(payload.get("variation_index") or 1), int(vt)) if vt else None
        if payload.get("regenerate"):
            # A per-post re-draft — nudge for a genuinely fresh take.
            regen = "Produce a FRESH, different version — vary the opening and wording from any earlier draft."
            variation = f"{variation} {regen}" if variation else regen
        # The distilled Voice & Audience Card (cached on clients.voice_card;
        # distilled once per guide revision — the first bulk job pays it, the
        # rest hit the cache). Best-effort: {} when no guide/ICP → prior behaviour.
        from services import voice_card_service  # lazy (avoids import cycle)

        card = await voice_card_service.get_voice_card(client, user_id=payload.get("user_id"))
        summary = await draft_summary(
            client, payload.get("topic_type") or "standard",
            payload.get("theme"), payload.get("source_url"),
            page_content=payload.get("page_content"), page_title=payload.get("page_title"),
            variation=variation, card=card,
        )
        if not summary:
            raise HTTPException(status_code=502, detail="empty_draft")

        # Regenerate: rewrite the existing post's text in place instead of adding
        # a new row (keeps its image, schedule slot, CTA, and gen_context).
        regen_id = payload.get("regenerate_post_id")
        if regen_id:
            post = (
                supabase.table("gbp_posts")
                .update({"summary": summary, "status": "draft", "error": None, "updated_at": "now()"})
                .eq("id", regen_id).eq("client_id", client_id).execute().data
            )
            post = post[0] if post else {"id": regen_id}
            supabase.table("async_jobs").update(
                {"status": "complete", "result": {"post_id": regen_id, "regenerated": True},
                 "completed_at": "now()"}
            ).eq("id", job["id"]).execute()
            return

        gen_context = {
            "topic_type": payload.get("topic_type") or "standard",
            "theme": payload.get("theme"), "source_url": payload.get("source_url"),
            "variation_index": payload.get("variation_index"),
            "variation_total": payload.get("variation_total"),
        }
        row = {
            "client_id": client_id, "location_row_id": payload["location_row_id"],
            "schedule_id": payload.get("schedule_id"),
            "source": payload.get("source") or "ai",
            "topic_type": payload.get("topic_type") or "standard", "summary": summary,
            "cta_type": payload.get("cta_type"), "cta_url": payload.get("cta_url"),
            "status": "draft", "created_by": payload.get("user_id"),
            "gen_context": gen_context,
        }
        post = supabase.table("gbp_posts").insert(row).execute().data[0]
        auto = bool(payload.get("auto_publish"))
        published = False
        if auto and not is_frozen(client_id):
            try:
                enqueue_publish(post["id"], client_id)
                published = True
            except HTTPException as exc:
                logger.warning("gbp_posts.auto_publish_skip", extra={"post_id": post["id"], "detail": exc.detail})
        elif payload.get("source") == "schedule":
            note = "held by freeze" if (auto and is_frozen(client_id)) else "ready for review"
            notifications.emit(
                client_id, "gbp_post_drafted", "New GBP post drafted",
                summary=f"A scheduled post was drafted ({note}).", severity="info",
                payload={"post_id": post["id"]},
            )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"post_id": post["id"], "published": published},
             "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None) or str(exc)
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
        logger.warning("gbp_posts.generate_failed", extra={"job_id": job["id"], "error": str(detail)})


# ───────────────────────────────────────────────────────────────────────────
# Live-state sync (async job) — reconcile LIVE/REJECTED, import external posts
# ───────────────────────────────────────────────────────────────────────────
def _enqueue_sync(client_id: str, delay_seconds: int = 0) -> Optional[str]:
    scheduled = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
    existing = (
        get_supabase().table("async_jobs").select("id")
        .eq("job_type", "gbp_posts_sync").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return None
    res = (
        get_supabase().table("async_jobs")
        .insert({"job_type": "gbp_posts_sync", "entity_id": client_id,
                 "payload": {"client_id": client_id}, "scheduled_at": scheduled})
        .execute()
    )
    return res.data[0]["id"]


def enqueue_sync(client_id: str) -> Optional[str]:
    _assert_enabled()
    return _enqueue_sync(client_id)


def post_needs_update(row: dict, live: dict) -> bool:
    """True if a synced live post differs from our stored row. Pure (unit-tested).

    Catches not just a status change but a newly-arrived ``search_url`` (Google
    populates the public post URL a short while AFTER the post goes live, often
    with the status unchanged at 'live') or a google_state change — otherwise a
    URL that lands post-publish would never be saved."""
    if row.get("status") != live.get("status"):
        return True
    if live.get("search_url") and row.get("search_url") != live.get("search_url"):
        return True
    if live.get("google_state") and row.get("google_state") != live.get("google_state"):
        return True
    return False


async def run_sync_job(job: dict) -> None:
    """Handler for job_type='gbp_posts_sync'. Reconciles each ok location's live
    posts into our rows (catches async REJECTED) and imports external posts."""
    payload = job.get("payload") or {}
    client_id = payload["client_id"]
    supabase = get_supabase()
    reconciled = imported = 0
    try:
        for location in list_ok_locations(client_id):
            if location.get("access_status") != "ok":
                continue
            try:
                parent = api.v4_parent(location.get("account_id") or "", location["location_id"])
                live = await asyncio.to_thread(api.list_posts, parent)
            except Exception as exc:  # noqa: BLE001 — one location failing must not abort the rest
                logger.info("gbp_posts.sync_location_failed",
                            extra={"location_row_id": location["id"], "error": str(getattr(exc, "detail", exc))})
                continue
            existing = {
                r["google_name"]: r for r in (
                    supabase.table("gbp_posts").select("id, google_name, status, search_url, google_state")
                    .eq("location_row_id", location["id"]).not_.is_("google_name", "null")
                    .execute().data or []
                )
            }
            for lp in live:
                name = lp.get("google_name")
                if not name:
                    continue
                row = existing.get(name)
                if row:
                    if post_needs_update(row, lp):
                        newly_rejected = (
                            row.get("status") != "rejected" and lp["status"] == "rejected"
                        )
                        supabase.table("gbp_posts").update({
                            "status": lp["status"], "google_state": lp.get("google_state"),
                            "search_url": lp.get("search_url"), "updated_at": "now()",
                        }).eq("id", row["id"]).execute()
                        reconciled += 1
                        if newly_rejected:
                            notifications.emit(
                                client_id, "gbp_post_rejected", "GBP post rejected by Google",
                                summary="A published post was rejected (likely a content-policy issue).",
                                severity="warning", payload={"post_id": row["id"]},
                            )
                else:
                    supabase.table("gbp_posts").insert({
                        "client_id": client_id, "location_row_id": location["id"],
                        "source": "external", "topic_type": lp.get("topic_type") or "standard",
                        "summary": lp.get("summary") or "", "status": lp["status"],
                        "google_name": name, "google_state": lp.get("google_state"),
                        "search_url": lp.get("search_url"), "published_at": "now()",
                    }).execute()
                    imported += 1
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"reconciled": reconciled, "imported": imported},
             "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None) or str(exc)
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
        logger.warning("gbp_posts.sync_failed", extra={"job_id": job["id"], "error": str(detail)})


# ───────────────────────────────────────────────────────────────────────────
# Job status poll
# ───────────────────────────────────────────────────────────────────────────
def get_jobs_status(client_id: str, job_ids: list[str]) -> list[dict]:
    if not job_ids:
        return []
    rows = (
        get_supabase().table("async_jobs")
        .select("id, status, result, error, entity_id")
        .in_("id", job_ids).execute().data or []
    )
    out = []
    for r in rows:
        if r.get("entity_id") != client_id:
            continue
        result = r.get("result") or {}
        out.append({"job_id": r["id"], "status": r["status"],
                    "post_id": result.get("post_id"), "error": r.get("error")})
    return out


# ───────────────────────────────────────────────────────────────────────────
# Schedules (self-clocked on the shared scheduler)
# ───────────────────────────────────────────────────────────────────────────
def _zone(tz: Optional[str]):
    """The tzinfo for an IANA name; UTC when unset or unknown (never raises)."""
    if not tz:
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        return ZoneInfo(tz)
    except Exception:  # noqa: BLE001 — a bad name degrades to UTC, never breaks
        return timezone.utc


def compute_next_run_at(
    now: datetime, cadence: str, day_of_week: Optional[int],
    day_of_month: Optional[int], hour_local: int, prev: Optional[datetime] = None,
    tz: Optional[str] = None,
) -> Optional[datetime]:
    """Next fire time (UTC-aware) strictly after ``now`` (UTC). None when disabled.

    ``hour_local`` is the hour in ``tz`` (an IANA name); ``tz=None`` means UTC
    (back-compat). The wall-clock is built in-zone and then converted to UTC, so
    it is **DST-correct** — e.g. 9am client-local stays 9am across a DST boundary
    (the UTC offset shifts, the local hour doesn't). Pure.

    weekly/monthly recompute from ``now`` (robust to missed ticks). biweekly
    steps 14 days from ``prev`` (the prior next_run) to preserve its phase; with
    no ``prev`` it seeds on the next matching weekday like weekly.
    """
    if cadence == "disabled":
        return None
    zone = _zone(tz)
    now_local = now.astimezone(zone)
    if cadence in ("weekly", "biweekly"):
        dow = day_of_week if day_of_week is not None else 0
        if cadence == "biweekly" and prev is not None:
            candidate = prev.astimezone(zone)
            while candidate <= now_local:
                candidate += timedelta(days=14)
            candidate = candidate.replace(hour=hour_local, minute=0, second=0, microsecond=0)
            return candidate.astimezone(timezone.utc)
        days_ahead = (dow - now_local.weekday()) % 7
        candidate = (now_local + timedelta(days=days_ahead)).replace(
            hour=hour_local, minute=0, second=0, microsecond=0
        )
        if candidate <= now_local:
            candidate += timedelta(days=7)
        return candidate.astimezone(timezone.utc)
    if cadence == "monthly":
        dom = day_of_month if day_of_month is not None else 1
        candidate = now_local.replace(day=dom, hour=hour_local, minute=0, second=0, microsecond=0)
        if candidate <= now_local:
            year = now_local.year + (1 if now_local.month == 12 else 0)
            month = 1 if now_local.month == 12 else now_local.month + 1
            candidate = candidate.replace(year=year, month=month)
        return candidate.astimezone(timezone.utc)
    raise HTTPException(status_code=400, detail="invalid_cadence")


def _default_schedule(location_row_id: Optional[str] = None) -> dict:
    return {
        "location_row_id": location_row_id, "cadence": "disabled", "day_of_week": None,
        "day_of_month": None, "hour_local": 9, "topic_type": "standard", "theme_notes": None,
        "cta_type": None, "cta_url": None, "auto_publish": False, "is_active": False,
        "next_run_at": None, "last_run_at": None,
    }


def get_schedule(client_id: str) -> dict:
    res = (
        get_supabase().table("gbp_post_schedules")
        .select("location_row_id, cadence, day_of_week, day_of_month, hour_local, topic_type, "
                "theme_notes, cta_type, cta_url, auto_publish, is_active, next_run_at, last_run_at")
        .eq("client_id", client_id).limit(1).execute().data
    )
    sched = res[0] if res else _default_schedule()
    # The client's local timezone the hour + next_run are expressed in (None → UTC).
    sched["timezone"] = gbp_timezone.resolve_client_timezone(client_id)
    return sched


def upsert_schedule(client_id: str, req: dict, user_id: str) -> dict:
    _assert_enabled()
    cadence = req.get("cadence") or "disabled"
    if cadence not in _VALID_CADENCES:
        raise HTTPException(status_code=400, detail="invalid_cadence")
    location = _location(str(req["location_row_id"]), client_id)
    hour_local = int(req.get("hour_local", 9))
    day_of_week = req.get("day_of_week")
    day_of_month = req.get("day_of_month")
    if cadence in ("weekly", "biweekly") and day_of_week is None:
        day_of_week = 0
    if cadence == "monthly" and day_of_month is None:
        day_of_month = 1
    is_active = bool(req.get("is_active", True))
    now = datetime.now(timezone.utc)
    tz = gbp_timezone.resolve_client_timezone(client_id)
    next_run = compute_next_run_at(now, cadence, day_of_week, day_of_month, hour_local, tz=tz)
    next_run_iso = next_run.isoformat() if (next_run and is_active and cadence != "disabled") else None
    row = {
        "client_id": client_id, "location_row_id": location["id"], "cadence": cadence,
        "day_of_week": day_of_week, "day_of_month": day_of_month, "hour_local": hour_local,
        "topic_type": req.get("topic_type") or "standard", "theme_notes": req.get("theme_notes"),
        "cta_type": req.get("cta_type"), "cta_url": req.get("cta_url"),
        "auto_publish": bool(req.get("auto_publish", False)), "is_active": is_active,
        "next_run_at": next_run_iso, "created_by": user_id, "updated_at": "now()",
    }
    get_supabase().table("gbp_post_schedules").upsert(row, on_conflict="client_id,location_row_id").execute()
    return get_schedule(client_id)


def enqueue_due_gbp_post_schedules() -> int:
    """Scheduler tick: for each active due schedule, enqueue a generate job
    (which drafts and, for auto-publish, chains publish) and advance its clock.
    Drafting inline would block the scheduler loop, so it's a job (like the LLM
    stays off the loop). No-ops entirely while the module is disabled."""
    if not (settings.gbp_api_enabled and settings.gbp_posts_enabled):
        return 0
    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    due = (
        supabase.table("gbp_post_schedules")
        .select("client_id, location_row_id, cadence, day_of_week, day_of_month, hour_local, "
                "topic_type, theme_notes, cta_type, cta_url, auto_publish, next_run_at")
        .eq("is_active", True).neq("cadence", "disabled")
        .lte("next_run_at", now.isoformat()).execute().data or []
    )
    enqueued = 0
    for sched in due:
        prev = None
        if sched.get("next_run_at"):
            try:
                prev = datetime.fromisoformat(sched["next_run_at"].replace("Z", "+00:00"))
            except ValueError:
                prev = None
        tz = gbp_timezone.resolve_client_timezone(sched["client_id"])
        next_run = compute_next_run_at(
            now, sched["cadence"], sched.get("day_of_week"),
            sched.get("day_of_month"), sched["hour_local"], prev=prev, tz=tz,
        )
        supabase.table("gbp_post_schedules").update({
            "last_run_at": now.isoformat(),
            "next_run_at": next_run.isoformat() if next_run else None,
        }).eq("client_id", sched["client_id"]).eq("location_row_id", sched["location_row_id"]).execute()
        try:
            enqueue_generate(sched["client_id"], {
                "location_row_id": sched["location_row_id"], "topic_type": sched["topic_type"],
                "theme": sched.get("theme_notes"), "cta_type": sched.get("cta_type"),
                "cta_url": sched.get("cta_url"), "auto_publish": bool(sched.get("auto_publish")),
                "schedule_id": None,
            }, user_id=None)  # type: ignore[arg-type]
            enqueued += 1
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning("gbp_posts.schedule_enqueue_failed",
                           extra={"client_id": sched["client_id"], "error": str(getattr(exc, "detail", exc))})
    if enqueued:
        logger.info("gbp_posts.schedules_enqueued", extra={"clients": enqueued})
    return enqueued


def enqueue_due_gbp_post_syncs() -> int:
    """Daily tick: enqueue a live-state sync per client that has an ok location.
    Catches async REJECTED verdicts + imports externally-created posts."""
    if not (settings.gbp_api_enabled and settings.gbp_posts_enabled):
        return 0
    supabase = get_supabase()
    client_ids = {
        r["client_id"] for r in (
            supabase.table("gbp_locations").select("client_id")
            .eq("access_status", "ok").execute().data or []
        )
    }
    count = 0
    for cid in client_ids:
        if _enqueue_sync(cid):
            count += 1
    return count

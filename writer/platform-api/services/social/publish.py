"""Social Media module — the publish path (PRD §9, GBP-Posts lifecycle template).

Platform-general: compose → (optional schedule) → freeze-gated, idempotent
publish job → status write, for Facebook (first live target), Instagram, X,
Pinterest. Supports text, images (single or carousel), ONE video (Facebook
video / Instagram Reel), per-platform passthrough options, media uploaded to the
suite's public bucket, and future-dated scheduling via a per-tick due sweep.

Accounts are connected MANUALLY in PostPeer for v1 (no connect flow) — a client's
accounts are read live from the provider, scoped to their ``social_profile_id``.

Pure helpers (``validate_post``, ``estimate_cost_usd``, ``build_media``) are
unit-tested.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from config import settings
from services.social import budget, get_adapter
from services.social.postpeer_adapter import x_credit_cost  # PostPeer credit model (fallback provider)

logger = logging.getLogger(__name__)

_PUBLISHABLE = {"scheduled", "failed", "rejected", "blocked_account"}
from services.social.media_store import get_media_store, media_key, resolve_media_type


def _assert_enabled() -> None:
    if not settings.social_enabled:
        raise HTTPException(status_code=503, detail="social_not_enabled")


# ── pure helpers (no network / DB — unit-tested) ─────────────────────────────

def build_media(
    image_urls: Optional[list[str]] = None, video_urls: Optional[list[str]] = None
) -> list[dict]:
    """Typed media list from separate image/video URL lists. Pure."""
    media: list[dict] = [{"type": "image", "url": u} for u in (image_urls or []) if u]
    media += [{"type": "video", "url": u} for u in (video_urls or []) if u]
    return media


def validate_post(
    platform: str,
    copy: str,
    media: Optional[list[dict]],
    spec: Optional[dict],
    fmt: str = "feed",
) -> dict:
    """Deterministic Platform-Spec check (PRD §6). {"hard": [...], "warnings": [...]}:
    a hard violation blocks approval/publish; a warning is advisory. ``fmt`` layers
    format-specific rules on top of the per-platform spec:

    - ``reel`` (Instagram/Facebook Reels are video-only) → require exactly ONE video
      and NO images.
    - ``story`` → require media (image or video); the caption is ignored by the
      platform (Stories carry no caption / link stickers), so a missing caption is
      never a violation, and a supplied caption is an advisory ``story_caption_ignored``.
    - ``carousel`` → require at least 2 media items (a one-item carousel is just a
      feed post); the per-spec ``max_images`` (≤10) still caps the count.
    """
    copy = copy or ""
    media = media or []
    fmt = (fmt or "feed").lower()
    images = [m for m in media if (m.get("type") or "image") == "image"]
    videos = [m for m in media if m.get("type") == "video"]
    hard: list[str] = []
    warnings: list[str] = []

    # A Story has no caption, so "no copy" is never an empty post for it (media is
    # required separately below); every other format needs copy or media.
    if not copy.strip() and not media and fmt != "story":
        hard.append("empty_post")

    # Format-specific media rules (platform-independent — needed for Facebook too,
    # whose spec has requires_image=false).
    if fmt == "reel":
        if images:
            hard.append(f"reel_no_images:{len(images)}")
        if len(videos) != 1:
            hard.append(f"reel_requires_one_video:{len(videos)}")
    elif fmt == "story":
        if not media:
            hard.append("story_requires_media")
        if copy.strip():
            warnings.append("story_caption_ignored")
    elif fmt == "carousel":
        if len(media) < 2:
            hard.append(f"carousel_needs_multiple:{len(media)}")

    if spec:
        char_limit = spec.get("char_limit")
        # A Story caption is dropped at publish, so don't block on its length.
        if char_limit and fmt != "story" and len(copy) > int(char_limit):
            hard.append(f"over_char_limit:{len(copy)}>{char_limit}")
        if spec.get("requires_image") and not media:
            hard.append("media_required")
        max_images = spec.get("max_images")
        if max_images and len(images) > int(max_images):
            hard.append(f"too_many_images:{len(images)}>{max_images}")
    if len(videos) > 1:
        hard.append(f"too_many_videos:{len(videos)}")
    # The X-link credit surcharge is a PostPeer-only pricing quirk; PostForMe is flat-priced.
    if (
        (platform or "").lower() in ("twitter", "x")
        and (settings.social_posting_provider or "").lower() == "postpeer"
        and x_credit_cost(platform, copy) >= 50
    ):
        warnings.append("x_link_post_50_credits")
    return {"hard": hard, "warnings": warnings}


def estimate_cost_usd(platform: str, copy: str, per_credit_usd: Optional[float] = None) -> float:
    """Estimated USD to publish one post, reserved against the fail-closed budget. Pure.
    PostForMe is flat per-post; PostPeer is credits × per-credit price (X links cost more)."""
    if (settings.social_posting_provider or "").lower() == "postforme":
        return round(float(settings.social_postforme_cost_per_post_usd), 4)
    price = per_credit_usd if per_credit_usd is not None else settings.social_credit_usd
    return round(x_credit_cost(platform, copy) * float(price), 4)


def _ensure_future_iso(scheduled_at: datetime, now: Optional[datetime] = None) -> str:
    """Return an ISO-8601 UTC string for a future time, else 422. Pure."""
    now = now or datetime.now(timezone.utc)
    dt = scheduled_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt <= now:
        raise HTTPException(status_code=422, detail="scheduled_in_past")
    return dt.astimezone(timezone.utc).isoformat()


# ── impure layer ─────────────────────────────────────────────────────────────

def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


def _client_profile_id(client_id: str) -> Optional[str]:
    rows = (
        _sb().table("clients").select("social_profile_id").eq("id", client_id).limit(1).execute()
    ).data or []
    return (rows[0].get("social_profile_id") if rows else None) or None


def _client_name(client_id: str) -> str:
    rows = (
        _sb().table("clients").select("name").eq("id", client_id).limit(1).execute()
    ).data or []
    return (rows[0].get("name") if rows else None) or "Client"


def _assert_account_allowed(client_id: str, account_id: str, *, require_live: bool = True) -> None:
    """Enforce client isolation: the target account must belong to THIS client's
    PostPeer profile (Social group). PostPeer has one account-wide key with no
    per-profile access control, so this membership check — not the picker's
    scoping (UX only) — is the actual boundary against publishing one client's
    content to another client's account.

    Two rungs:
    - The profile MUST be set (a client with no Social group can't publish at all).
      Cheap, DB-only, always enforced → 409 ``social_profile_not_set``.
    - The account must be in that profile's live integration list. When PostPeer
      is reachable, a non-member → 403. On a PostPeer transport/5xx/rate-limit
      error the behaviour depends on ``require_live``:
        * ``require_live=False`` (compose/schedule): swallow the error and proceed
          — a brief PostPeer outage must not block composing or scheduling a post.
          The publish job re-checks with ``require_live=True`` before it posts, so
          a wrong account still never reaches the platform.
        * ``require_live=True`` (the publish job, the authoritative gate): re-raise
          — we never publish to an account whose membership we couldn't confirm.
    """
    profile_id = _client_profile_id(client_id)
    if not profile_id:
        raise HTTPException(status_code=409, detail="social_profile_not_set")
    try:
        allowed = {
            i.account_id
            for i in get_adapter(client_id=client_id).list_integrations(profile_id=profile_id)
        }
    except HTTPException:
        if require_live:
            raise
        logger.warning(
            "social.membership_check_deferred",
            extra={"client_id": client_id, "account_id": account_id},
        )
        return
    if account_id not in allowed:
        raise HTTPException(status_code=403, detail="social_account_not_in_client_profile")


def ensure_profile_for_client(client_id: str, client_name: Optional[str] = None) -> str:
    """Return the client's PostPeer profile id, creating + storing one if absent.
    Idempotent — a client that already has a Social group keeps it.

    Concurrency/orphan hardening: two callers can race between the initial read and
    the create (e.g. a provisioning background task and a first compose). Both would
    call PostPeer's create_profile and one would win the clients UPDATE. We can't
    make create+store atomic across two systems, so we re-read the clients row
    immediately AFTER creating and, if a profile landed in the meantime, honour the
    stored one — never overwrite an existing mapping. The loser's PostPeer group is
    an empty, harmless orphan (no integrations); we log it for manual cleanup rather
    than expand the adapter contract with a delete only this edge case would use. A
    failure to persist is raised (the profile exists but isn't mapped) so the caller
    — a background task or a compose — surfaces it rather than silently returning an
    unmapped id."""
    _assert_enabled()
    existing = _client_profile_id(client_id)
    if existing:
        return existing
    name = (client_name or _client_name(client_id)).strip() or "Client"
    profile_id = get_adapter().create_profile(name=name, description=f"AR Tools client {client_id}")

    # Re-read after the create: if another caller stored a profile while we were
    # calling PostPeer, honour theirs (never clobber a mapping) and leave ours as a
    # logged orphan.
    raced = _client_profile_id(client_id)
    if raced:
        logger.warning(
            "social.profile_orphaned",
            extra={"client_id": client_id, "orphan_profile_id": profile_id, "kept": raced},
        )
        return raced

    try:
        _sb().table("clients").update(
            {"social_profile_id": profile_id, "updated_at": "now()"}
        ).eq("id", client_id).execute()
    except Exception as exc:  # noqa: BLE001 — a created-but-unmapped profile is an error
        logger.error(
            "social.profile_persist_failed",
            extra={"client_id": client_id, "profile_id": profile_id, "error": str(exc)},
        )
        raise HTTPException(status_code=502, detail="social_profile_failed") from exc
    logger.info("social.profile_provisioned", extra={"client_id": client_id, "profile_id": profile_id})
    return profile_id


def enqueue_profile_provision(client_id: str, client_name: Optional[str] = None) -> None:
    """Enqueue the client's PostPeer profile provisioning as an async job.

    Provisioning makes a synchronous PostPeer create_profile call; enqueuing keeps
    it off the client-create request path (every other provisioning step enqueues
    rather than blocking the HTTP response on an external call). Idempotent — the
    job re-checks and no-ops when a profile already exists, so a duplicate enqueue
    is harmless. Skipped when the module is off/unkeyed or a profile is already set.
    Best-effort — never raise into the caller's provisioning flow."""
    if not (settings.social_enabled and settings.postpeer_api_key):
        return
    try:
        if _client_profile_id(client_id):
            return
        _sb().table("async_jobs").insert(
            {
                "job_type": "social_profile_provision",
                "entity_id": client_id,
                "payload": {"client_id": client_id, "client_name": client_name},
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001 — enqueue is best-effort
        logger.warning(
            "social.profile_provision_enqueue_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )


def run_profile_provision_job(job: dict) -> None:
    """Worker entrypoint: provision the client's PostPeer profile. Idempotent."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    if not client_id:
        return
    ensure_profile_for_client(client_id, payload.get("client_name"))


def connect_url_for_client(
    client_id: str, platform: str, redirect_uri: Optional[str] = None
) -> str:
    """A per-client OAuth connect URL for one platform. For PostForMe the account lands in
    the client's own Project (the per-client key scopes it); for PostPeer it's scoped to the
    client's Social group. 409 if the client isn't connected yet (no key / no profile)."""
    _assert_enabled()
    profile_id = _client_profile_id(client_id)
    if not profile_id:
        raise HTTPException(status_code=409, detail="social_profile_not_set")
    # The adapter tags the new account with this as external_id. For PostForMe use the real
    # client id (a reconciliation reference), not the "postforme" connected-marker.
    scope = (
        client_id
        if (settings.social_posting_provider or "").lower() == "postforme"
        else profile_id
    )
    return get_adapter(client_id=client_id).connect_url(
        profile_id=scope, platform=(platform or "").lower(), redirect_uri=redirect_uri
    )


def _platform_spec(platform: str) -> Optional[dict]:
    rows = (
        _sb().table("social_platform_specs").select("*").eq("platform", (platform or "").lower())
        .limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def list_accounts(client_id: str) -> list[dict]:
    """The client's connected accounts, live from PostPeer, scoped to their Social
    group. Read-only (accounts are connected manually). Fail-closed: a client with
    no Social group mapped returns [] rather than PostPeer's whole account — with
    no per-profile access control on PostPeer's side, listing an unscoped set would
    leak other clients' accounts. The UI prompts to connect a Social group first."""
    _assert_enabled()
    profile_id = _client_profile_id(client_id)
    if not profile_id:
        return []
    integrations = get_adapter(client_id=client_id).list_integrations(profile_id=profile_id)
    return [
        {"account_id": i.account_id, "platform": i.platform, "handle": i.handle,
         "reconnect_required": i.reconnect_required}
        for i in integrations
    ]


def _validate_upload(data: bytes, content_type: str) -> tuple[str, str]:
    """Size/type-check an upload; images are also decode-verified. Returns
    (ext, media_type). Raises HTTPException on a bad upload."""
    if not data:
        raise HTTPException(status_code=422, detail="empty_file")
    if len(data) > int(settings.social_max_upload_mb * 1024 * 1024):
        raise HTTPException(status_code=413, detail="file_too_large")
    try:
        ext, media_type = resolve_media_type(content_type)
    except ValueError:
        raise HTTPException(status_code=422, detail="unsupported_media_type")
    if media_type == "image":
        try:
            import io

            from PIL import Image

            with Image.open(io.BytesIO(data)) as im:
                im.verify()
        except Exception:  # noqa: BLE001 — non-decodable upload is a bad image
            raise HTTPException(status_code=422, detail="invalid_image")
    return ext, media_type


def upload_media(data: bytes, content_type: str) -> dict:
    """Validate an uploaded image/video and store it via the media store (R2, else
    Supabase). Returns {"url", "type"}. Small-file / server path — big videos
    should use the presigned direct-upload endpoint instead."""
    _assert_enabled()
    ext, media_type = _validate_upload(data, content_type)
    ct = (content_type or "").lower().split(";")[0].strip()
    url = get_media_store().put_bytes(media_key(ext, "upload"), data, ct)
    return {"url": url, "type": media_type}


def presign_upload(content_type: str) -> dict:
    """A short-lived direct-upload URL for a big image/video: the browser PUTs the
    file straight to the store, keeping large bytes out of the API. Returns
    {"upload_url", "public_url", "headers", "type"}."""
    _assert_enabled()
    ct = (content_type or "").lower().split(";")[0].strip()
    try:
        ext, media_type = resolve_media_type(ct)
    except ValueError:
        raise HTTPException(status_code=422, detail="unsupported_media_type")
    signed = get_media_store().presigned_put_url(media_key(ext, "upload"), ct)
    return {**signed, "type": media_type}


def get_post(post_id: str) -> dict:
    rows = (_sb().table("social_posts").select("*").eq("id", post_id).limit(1).execute()).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="social_post_not_found")
    return rows[0]


def list_posts(client_id: str, limit: int = 100) -> list[dict]:
    return (
        _sb().table("social_posts").select("*").eq("client_id", client_id)
        .order("created_at", desc=True).limit(limit).execute()
    ).data or []


def create_post(
    client_id: str,
    platform: str,
    account_id: str,
    copy: str = "",
    image_urls: Optional[list[str]] = None,
    video_urls: Optional[list[str]] = None,
    platform_specific: Optional[dict] = None,
    fmt: str = "feed",
    scheduled_at: Optional[datetime] = None,
) -> dict:
    """Compose one platform-native post and publish it now, or schedule it for a
    future time. Validates against the Platform Spec (hard violation → 422) first."""
    _assert_enabled()
    # Compose-time gate: always enforce "profile is set" + a fast 403 when PostPeer
    # is reachable, but tolerate a PostPeer outage (require_live=False) so a blip
    # can't block composing/scheduling. run_publish_job re-checks authoritatively.
    _assert_account_allowed(client_id, account_id, require_live=False)
    platform = (platform or "").lower()
    media = build_media(image_urls, video_urls)
    verdict = validate_post(platform, copy, media, _platform_spec(platform), fmt=fmt)
    if verdict["hard"]:
        raise HTTPException(status_code=422, detail="social_spec_violation:" + verdict["hard"][0])

    scheduled_iso = _ensure_future_iso(scheduled_at) if scheduled_at else None

    draft = (
        _sb().table("social_drafts").insert({
            "client_id": client_id, "platform": platform, "format": fmt,
            "angle": "manual", "source_ref": {"type": "manual"},
            "copy": copy, "media": media,
            "image_urls": [m["url"] for m in media if m["type"] == "image"],
            "platform_metadata": platform_specific, "spec_verdict": verdict, "status": "approved",
        }).execute()
    ).data[0]

    post = (
        _sb().table("social_posts").insert({
            "draft_id": draft["id"], "client_id": client_id, "platform": platform,
            "account_id": account_id, "status": "scheduled", "scheduled_at": scheduled_iso,
        }).execute()
    ).data[0]

    # Publish now unless it's future-scheduled (the due sweep enqueues those).
    if scheduled_iso is None:
        _insert_publish_job(client_id, post["id"])
    return post


def _insert_publish_job(client_id: str, post_id: str) -> str:
    res = (
        _sb().table("async_jobs").insert({
            "job_type": "social_publish", "entity_id": client_id,
            "payload": {"client_id": client_id, "post_id": post_id},
        }).execute()
    )
    return res.data[0]["id"]


def _has_active_publish_job(client_id: str, post_id: str) -> bool:
    rows = (
        _sb().table("async_jobs").select("id, payload")
        .eq("job_type", "social_publish").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).execute().data or []
    )
    return any((r.get("payload") or {}).get("post_id") == post_id for r in rows)


def enqueue_due_social_posts() -> int:
    """Per-tick sweep: publish any post whose scheduled_at has come due. Skips
    frozen clients (publish paused until the freeze lifts) and posts with an
    active publish job. No-op until the module is enabled."""
    if not settings.social_enabled:
        return 0
    from services.freeze import is_frozen

    now = datetime.now(timezone.utc)
    due = (
        _sb().table("social_posts").select("id, client_id")
        .eq("status", "scheduled").not_.is_("scheduled_at", "null")
        .lte("scheduled_at", now.isoformat()).execute().data or []
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
            logger.warning("social.scheduled_enqueue_failed",
                           extra={"post_id": pid, "error": str(getattr(exc, "detail", exc))})
    if count:
        logger.info("social.scheduled_published", extra={"posts": count})
    return count


async def run_publish_job(job: dict) -> None:
    """Handler for job_type='social_publish'. Publishes ONE post to ONE account via
    the adapter, reserves budget first (fail-closed), reconciles status. Freeze
    gate is applied by the worker. Idempotent on requeue."""
    import asyncio

    from services import notifications  # lazy — keeps pure helpers importable without the DB layer

    payload = job.get("payload") or {}
    post_id = payload.get("post_id")
    client_id = payload.get("client_id")
    sb = _sb()

    def _settle_job(status: str, **fields) -> None:
        sb.table("async_jobs").update(
            {"status": status, "completed_at": "now()", **fields}
        ).eq("id", job["id"]).execute()

    def _fail(detail: str, post_status: str = "failed") -> None:
        sb.table("social_posts").update(
            {"status": post_status, "status_detail": str(detail)[:500], "updated_at": "now()"}
        ).eq("id", post_id).execute()
        _settle_job("failed", error=str(detail)[:500])
        notifications.emit(
            client_id, "social_post_failed", "Social post failed to publish",
            summary=str(detail)[:200], severity="warning", payload={"post_id": post_id},
        )

    try:
        post = get_post(post_id)
        if post.get("provider_post_id"):  # Guard 1 — already published
            _settle_job("complete", result={"post_id": post_id, "already_published": True})
            return
        if post.get("status") == "publishing":  # Guard 2 — interrupted; never double-post
            _fail("interrupted_verify_in_postpeer", post_status="failed")
            return

        draft = {}
        if post.get("draft_id"):
            drows = (sb.table("social_drafts").select("*").eq("id", post["draft_id"]).limit(1).execute()).data or []
            draft = drows[0] if drows else {}
        fmt = (draft.get("format") or "feed").lower()
        # Stories carry no caption — drop it here so it can never reach the platform,
        # regardless of how the draft was created (manual compose already sends empty
        # copy; a fan-out draft may carry copy that must not be published on a Story).
        copy = "" if fmt == "story" else (draft.get("copy") or "")
        media = draft.get("media") or [{"type": "image", "url": u} for u in (draft.get("image_urls") or [])]
        platform_specific = draft.get("platform_metadata") or None
        platform = post["platform"]
        account_id = post.get("account_id")
        if not account_id:
            _fail("no_account_id")
            return

        # Authoritative isolation gate at the actual side-effect (require_live=True):
        # the account must still belong to this client's profile now, catching a
        # profile that changed after compose or a compose-time check deferred by a
        # PostPeer outage. A non-member or an unconfirmable membership fails the
        # post rather than risk publishing to a wrong account.
        try:
            _assert_account_allowed(client_id, account_id, require_live=True)
        except HTTPException as exc:
            _fail(str(getattr(exc, "detail", "social_account_not_in_client_profile")))
            return

        est = estimate_cost_usd(platform, copy)
        cap = budget.ceiling_for_client(client_id)
        if not budget.reserve(client_id, est, cap=cap):
            _fail("budget_exceeded", post_status="failed")
            return

        sb.table("social_posts").update(
            {"status": "publishing", "updated_at": "now()"}
        ).eq("id", post_id).execute()

        result = await asyncio.to_thread(
            get_adapter(client_id=client_id).post,
            account_id, platform, copy, media or None, platform_specific, fmt,
        )
        if result.ok:
            sb.table("social_posts").update({
                "status": "published", "provider_post_id": result.provider_post_id,
                "post_url": result.post_url, "published_at": "now()",
                "status_detail": None, "updated_at": "now()",
            }).eq("id", post_id).execute()
            _settle_job("complete", result={"post_id": post_id, "url": result.post_url})
            logger.info("social.published", extra={"post_id": post_id, "platform": platform})
        else:
            sb.table("social_posts").update({
                "status": "rejected", "status_detail": (result.detail or "publish_failed")[:500],
                "updated_at": "now()",
            }).eq("id", post_id).execute()
            _settle_job("failed", error=(result.detail or "publish_failed")[:500])
            notifications.emit(
                client_id, "social_post_failed", "Social post rejected by the platform",
                summary=(result.detail or "publish_failed")[:200], severity="warning",
                payload={"post_id": post_id},
            )
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None) or str(exc)
        _fail(detail)
        logger.warning("social.publish_failed", extra={"post_id": post_id, "error": str(detail)})

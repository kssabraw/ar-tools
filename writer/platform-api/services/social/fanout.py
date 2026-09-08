"""Social Media module — the Creator's Angle fan-out (PRD §7).

Take ONE Source + ONE chosen Angle and fan it out across the target platforms:
generate platform-native copy (and, opt-in, a per-platform image) for each,
voice-enforced, and persist one **Draft** per platform under a shared
``angle_set_id``. A human reviews/edits the Drafts and publishes each (reusing the
publish lifecycle).

Runs as a background ``social_fanout`` job — multi-platform copy + image
generation is too slow for a request, and generating images is a paid,
budget-metered, freeze-gated action. The source + voice card are loaded ONCE and
reused across every platform.

Pure helpers (``resolve_platforms``, ``build_source_ref``, ``draft_status``,
``image_description_for_angle``) are unit-tested; the DB/LLM/image work is the
impure layer.
"""

from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException

from config import settings
from services.social import creator

logger = logging.getLogger(__name__)


def _assert_enabled() -> None:
    if not settings.social_enabled:
        raise HTTPException(status_code=503, detail="social_not_enabled")


def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


# ── pure helpers (unit-tested) ───────────────────────────────────────────────

def resolve_platforms(requested: list[str], available: list[str]) -> list[str]:
    """The distinct platforms to fan out to: those requested that the client has a
    connected account for, order-stable, deduped, lowercased. Pure."""
    avail = {(p or "").lower() for p in (available or [])}
    seen: set[str] = set()
    out: list[str] = []
    for p in (requested or []):
        pl = (p or "").lower().strip()
        if pl and pl in avail and pl not in seen:
            seen.add(pl)
            out.append(pl)
    return out


def build_source_ref(source_type: str, source_id: Optional[str], url: Optional[str]) -> dict:
    """The stored Source reference for a Draft (matches creator.load_source's
    shape), built without loading the source. Pure."""
    st = (source_type or "topic").lower()
    if st == "url":
        return {"type": "url", "url": (url or "").strip()}
    if st == "blog_run":
        return {"type": "blog_run", "run_id": (source_id or "").strip()}
    if st == "local_seo_page":
        return {"type": "local_seo_page", "page_id": (source_id or "").strip()}
    return {"type": "topic"}


def draft_status(has_media: bool, requires_image: bool, generation_ok: bool) -> str:
    """The Draft's status after generation. Pure:
    generation_failed → the copy call failed;
    needs_image → the platform needs an image and none was produced;
    ready → good to review/publish."""
    if not generation_ok:
        return "generation_failed"
    if requires_image and not has_media:
        return "needs_image"
    return "ready"


def image_description_for_angle(
    angle: Optional[str], angle_title: Optional[str], source_title: Optional[str]
) -> str:
    """A concise image-generation description derived from the angle/source. Pure."""
    for cand in (angle, angle_title, source_title):
        c = (cand or "").strip()
        if c:
            return c[:400]
    return "brand social media image"


# ── enqueue ──────────────────────────────────────────────────────────────────

def _client_accounts(client_id: str) -> list[dict]:
    from services.social import publish

    return publish.list_accounts(client_id)


def enqueue_fanout(client_id: str, req, user_id: Optional[str] = None) -> dict:
    """Create a Draft set (one 'generating' Draft per target platform) and enqueue
    the ``social_fanout`` job that fills them in. Validates the requested platforms
    against the client's connected accounts. Returns {angle_set_id, job_id, drafts}."""
    _assert_enabled()
    angle = (req.angle or "").strip()
    if not angle:
        raise HTTPException(status_code=422, detail="social_angle_required")

    available = [a["platform"] for a in _client_accounts(client_id)]
    platforms = resolve_platforms(req.platforms, available)
    if not platforms:
        raise HTTPException(status_code=422, detail="social_no_target_platforms")

    angle_set_id = str(uuid4())
    fmt = req.format or "feed"
    source_ref = build_source_ref(req.source_type, req.source_id, req.url)
    angle_title = (getattr(req, "angle_title", None) or angle)[:120]

    rows = [
        {
            "client_id": client_id, "angle_set_id": angle_set_id, "source_ref": source_ref,
            "angle": angle_title, "platform": p, "format": fmt, "status": "generating",
        }
        for p in platforms
    ]
    drafts = (_sb().table("social_drafts").insert(rows).execute()).data or []

    job = (
        _sb().table("async_jobs").insert({
            "job_type": "social_fanout", "entity_id": client_id,
            "payload": {
                "client_id": client_id, "angle_set_id": angle_set_id, "angle": angle,
                "angle_title": angle_title, "tone": getattr(req, "tone", None), "format": fmt,
                "include_image": bool(getattr(req, "include_image", False)),
                "include_hashtags": bool(getattr(req, "include_hashtags", True)),
                "source_type": req.source_type, "source_id": req.source_id, "url": req.url,
                "text": req.text, "user_id": user_id,
            },
        }).execute()
    ).data[0]
    return {"angle_set_id": angle_set_id, "job_id": job["id"], "drafts": drafts}


# ── the job ──────────────────────────────────────────────────────────────────

def _platform_spec(platform: str):
    from services.social import publish

    return publish._platform_spec(platform)


async def _maybe_generate_image(
    client_id: str, platform: str, fmt: str, description: str, user_id: Optional[str]
) -> Optional[str]:
    """Best-effort per-platform image for a fan-out draft. Returns a URL or None —
    a budget/gen failure is swallowed (the draft ships copy-only / needs_image)."""
    from services.social import image as social_image

    req = SimpleNamespace(platform=platform, format=fmt, description=description, aspect_ratio=None)
    try:
        out = await social_image.generate_image(client_id, req, user_id=user_id)
        return out.get("url")
    except HTTPException as exc:
        logger.info("social.fanout_image_skipped",
                    extra={"platform": platform, "detail": str(exc.detail)[:120]})
        return None
    except Exception as exc:  # noqa: BLE001 — image is best-effort
        logger.info("social.fanout_image_error", extra={"platform": platform, "error": str(exc)[:160]})
        return None


async def run_fanout_job(job: dict) -> None:
    """Handler for job_type='social_fanout'. Loads the source + voice card once,
    then for each pending Draft in the set generates platform copy (+ opt-in image)
    and marks it ready / needs_image / generation_failed. Best-effort per draft: one
    draft's failure never aborts the set. Settles its own job row."""
    from services import notifications

    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    angle_set_id = payload.get("angle_set_id")
    sb = _sb()

    def _settle(status: str, **fields) -> None:
        sb.table("async_jobs").update(
            {"status": status, "completed_at": "now()", **fields}
        ).eq("id", job["id"]).execute()

    try:
        source_title, source_text, _ref = await creator.load_source(
            client_id, payload.get("source_type") or "topic",
            source_id=payload.get("source_id"), url=payload.get("url"), text=payload.get("text"),
        )
        source_version = creator.source_version_of(source_text)
        client = creator._client_row(client_id)
        card, voice_block, client_context = await creator.resolve_voice_context(
            client, payload.get("user_id")
        )
    except HTTPException as exc:
        # Whole-set failure (bad/unreachable source): mark every pending draft failed.
        sb.table("social_drafts").update({"status": "generation_failed", "updated_at": "now()"}) \
            .eq("angle_set_id", angle_set_id).eq("status", "generating").execute()
        _settle("failed", error=str(exc.detail)[:500])
        return

    angle = payload.get("angle")
    angle_title = payload.get("angle_title")
    tone = payload.get("tone")
    fmt = payload.get("format") or "feed"
    include_image = bool(payload.get("include_image"))
    include_hashtags = bool(payload.get("include_hashtags", True))
    user_id = payload.get("user_id")

    pending = (
        sb.table("social_drafts").select("id, platform, format")
        .eq("angle_set_id", angle_set_id).eq("status", "generating").execute()
    ).data or []

    ready = failed = 0
    for draft in pending:
        platform = draft["platform"]
        spec = _platform_spec(platform)
        d_fmt = draft.get("format") or fmt
        update: dict = {"source_version": source_version, "updated_at": "now()"}
        try:
            copy, voice_warnings, spec_warnings = await creator.draft_platform_copy(
                platform=platform, spec=spec, fmt=d_fmt, source_title=source_title,
                source_text=source_text, angle=angle, tone=tone, include_hashtags=include_hashtags,
                card=card, voice_block=voice_block, client_context=client_context,
            )
        except Exception as exc:  # noqa: BLE001 — one draft failing doesn't abort the set
            logger.warning("social.fanout_draft_failed",
                           extra={"draft_id": draft["id"], "error": str(getattr(exc, 'detail', exc))[:200]})
            sb.table("social_drafts").update(
                {"status": "generation_failed", "source_version": source_version, "updated_at": "now()"}
            ).eq("id", draft["id"]).execute()
            failed += 1
            continue

        image_url: Optional[str] = None
        if include_image:
            image_url = await _maybe_generate_image(
                client_id, platform, d_fmt,
                image_description_for_angle(angle, angle_title, source_title), user_id,
            )
        media = [{"type": "image", "url": image_url}] if image_url else []
        requires_image = bool((spec or {}).get("requires_image"))
        status = draft_status(bool(media), requires_image, generation_ok=True)

        update.update({
            "copy": copy, "media": media,
            "image_urls": [image_url] if image_url else [],
            "voice_verdict": {"warnings": voice_warnings},
            "spec_verdict": {"warnings": spec_warnings},
            "status": status,
        })
        sb.table("social_drafts").update(update).eq("id", draft["id"]).execute()
        ready += 1

    _settle("complete", result={"angle_set_id": angle_set_id, "ready": ready, "failed": failed})
    if ready:
        notifications.emit(
            client_id, "social_fanout_ready", "Social drafts are ready to review",
            summary=f"{ready} platform draft(s) generated from your angle.",
            severity="info", payload={"angle_set_id": angle_set_id},
        )


# ── draft read / edit / publish ──────────────────────────────────────────────

def list_drafts(client_id: str, angle_set_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    q = (
        _sb().table("social_drafts").select("*").eq("client_id", client_id)
        .neq("status", "archived").order("created_at", desc=True).limit(limit)
    )
    if angle_set_id:
        q = q.eq("angle_set_id", angle_set_id)
    return q.execute().data or []


def get_draft(draft_id: str) -> dict:
    rows = (_sb().table("social_drafts").select("*").eq("id", draft_id).limit(1).execute()).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="social_draft_not_found")
    return rows[0]


def update_draft(
    draft_id: str,
    *,
    copy: Optional[str] = None,
    image_urls: Optional[list[str]] = None,
    platform_metadata: Optional[dict] = None,
) -> dict:
    """Human edit of a Draft before publish (copy / images / platform options).
    Recomputes status (needs_image ↔ ready) from the new media. Only provided
    fields change."""
    from services.social import publish

    draft = get_draft(draft_id)
    fields: dict = {"updated_at": "now()"}
    if copy is not None:
        fields["copy"] = copy
    if image_urls is not None:
        media = publish.build_media(image_urls, None)
        fields["image_urls"] = [u for u in image_urls if u]
        fields["media"] = media
    if platform_metadata is not None:
        fields["platform_metadata"] = platform_metadata

    # Recompute status when the draft is in a reviewable state (don't resurrect a
    # generating/failed/published row). Generation already succeeded, so this only
    # decides ready ↔ needs_image from the new media — never generation_failed.
    new_media = fields.get("media", draft.get("media") or [])
    if draft.get("status") in ("ready", "needs_image"):
        spec = publish._platform_spec(draft["platform"])
        requires_image = bool((spec or {}).get("requires_image"))
        fields["status"] = draft_status(bool(new_media), requires_image, generation_ok=True)

    row = (_sb().table("social_drafts").update(fields).eq("id", draft_id).execute()).data
    return row[0] if row else get_draft(draft_id)


def delete_draft(draft_id: str) -> dict:
    get_draft(draft_id)  # 404 if missing
    _sb().table("social_drafts").update({"status": "archived", "updated_at": "now()"}) \
        .eq("id", draft_id).execute()
    return {"ok": True}


def publish_existing_draft(
    draft_id: str, account_id: str, scheduled_at: Optional[datetime] = None
) -> dict:
    """Approve & publish a Draft to one connected account (reuses the publish
    lifecycle). Validates against the Platform Spec, creates the Post, enqueues the
    freeze-gated publish job (or leaves it for the due sweep when scheduled), and
    marks the Draft published."""
    _assert_enabled()
    from services.social import publish

    draft = get_draft(draft_id)
    if not account_id:
        raise HTTPException(status_code=422, detail="social_account_required")
    if draft.get("status") == "published":
        raise HTTPException(status_code=409, detail="social_draft_already_published")

    platform = draft["platform"]
    media = draft.get("media") or publish.build_media(draft.get("image_urls"), None)
    copy = draft.get("copy") or ""
    verdict = publish.validate_post(platform, copy, media, publish._platform_spec(platform))
    if verdict["hard"]:
        raise HTTPException(status_code=422, detail="social_spec_violation:" + verdict["hard"][0])

    scheduled_iso = publish._ensure_future_iso(scheduled_at) if scheduled_at else None
    post = (
        _sb().table("social_posts").insert({
            "draft_id": draft_id, "client_id": draft["client_id"], "platform": platform,
            "account_id": account_id, "status": "scheduled", "scheduled_at": scheduled_iso,
        }).execute()
    ).data[0]

    if scheduled_iso is None:
        publish._insert_publish_job(draft["client_id"], post["id"])
    _sb().table("social_drafts").update({"status": "published", "updated_at": "now()"}) \
        .eq("id", draft_id).execute()
    return post


def get_fanout_job(job_id: str) -> dict:
    rows = (
        _sb().table("async_jobs").select("id, status, result, error")
        .eq("id", job_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="social_job_not_found")
    return rows[0]

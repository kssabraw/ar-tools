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

# Platforms fan-out never targets: fan-out generates copy + IMAGES (no AI video in
# v1), and a YouTube post is video-only + Compose-only — so it's uploaded from the
# manual composer, never fanned out (mirrors the frontend FANOUT exclusion).
_FANOUT_EXCLUDED_PLATFORMS = frozenset({"youtube"})


def resolve_platforms(requested: list[str], available: list[str]) -> list[str]:
    """The distinct platforms to fan out to: those requested that the client has a
    connected account for, order-stable, deduped, lowercased, minus the platforms
    fan-out can't produce publishable drafts for (YouTube — video-only). Pure."""
    avail = {(p or "").lower() for p in (available or [])}
    seen: set[str] = set()
    out: list[str] = []
    for p in (requested or []):
        pl = (p or "").lower().strip()
        if pl and pl in avail and pl not in seen and pl not in _FANOUT_EXCLUDED_PLATFORMS:
            seen.add(pl)
            out.append(pl)
    return out


def build_source_ref(
    source_type: str, source_id: Optional[str], url: Optional[str], text: Optional[str] = None
) -> dict:
    """The stored Source reference for a Draft (matches creator.load_source's
    shape), built without loading the source. Pure. A topic ref carries its ``text`` when
    provided so the autonomy source cooldown can key on the topic (a topicless call is
    unchanged)."""
    st = (source_type or "topic").lower()
    if st == "url":
        return {"type": "url", "url": (url or "").strip()}
    if st == "blog_run":
        return {"type": "blog_run", "run_id": (source_id or "").strip()}
    if st == "local_seo_page":
        return {"type": "local_seo_page", "page_id": (source_id or "").strip()}
    ref = {"type": "topic"}
    if (text or "").strip():
        ref["text"] = text.strip()
    return ref


def draft_status(
    has_media: bool,
    requires_image: bool,
    generation_ok: bool,
    enough_media: bool = True,
    board_required_missing: bool = False,
) -> str:
    """The Draft's status after generation. Pure:
    generation_failed → the copy call failed;
    needs_image → the platform needs media and none/too-few was produced (a carousel
      passes enough_media=False until it has ≥2 slides);
    needs_board → a Pinterest draft has media but no board yet (fan-out can't pick a
      board; the user sets it in the Drafts tab before publishing). Ordered AFTER the
      media check, so a Pinterest draft still missing its image is needs_image first;
    ready → good to review/publish."""
    if not generation_ok:
        return "generation_failed"
    if requires_image and (not has_media or not enough_media):
        return "needs_image"
    if board_required_missing:
        return "needs_board"
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
    source_ref = build_source_ref(req.source_type, req.source_id, req.url, getattr(req, "text", None))
    angle_title = (getattr(req, "angle_title", None) or angle)[:120]

    rows = [
        {
            "client_id": client_id, "angle_set_id": angle_set_id, "source_ref": source_ref,
            "angle": angle_title, "platform": p, "format": fmt, "status": "generating",
        }
        for p in platforms
    ]
    drafts = (_sb().table("social_drafts").insert(rows).execute()).data or []

    try:
        job = (
            _sb().table("async_jobs").insert({
                "job_type": "social_fanout", "entity_id": client_id,
                "payload": {
                    "client_id": client_id, "angle_set_id": angle_set_id, "angle": angle,
                    "angle_title": angle_title, "tone": getattr(req, "tone", None), "format": fmt,
                    "include_image": bool(getattr(req, "include_image", False)),
                    "include_hashtags": bool(getattr(req, "include_hashtags", True)),
                    "slides": getattr(req, "slides", None),
                    "source_type": req.source_type, "source_id": req.source_id, "url": req.url,
                    "text": req.text, "user_id": user_id,
                    # P4 Social Manager (autonomy loop): stamp provenance so the drafts are
                    # counted for the weekly rate cap + badged, and auto-queue the ready ones
                    # (tier 2) so P3's drip can pick them up. Absent → manual behavior.
                    "produced_by": getattr(req, "produced_by", None),
                    "auto_queue": bool(getattr(req, "auto_queue", False)),
                },
            }).execute()
        ).data[0]
    except Exception:
        # The job that would fill these drafts didn't enqueue — don't leave orphan
        # 'generating' rows spinning forever. Best-effort cleanup, then re-raise.
        try:
            _sb().table("social_drafts").update({"status": "archived", "updated_at": "now()"}) \
                .eq("angle_set_id", angle_set_id).execute()
        except Exception:  # noqa: BLE001 — cleanup is best-effort
            logger.warning("social.fanout_orphan_cleanup_failed", extra={"angle_set_id": angle_set_id})
        raise
    return {"angle_set_id": angle_set_id, "job_id": job["id"], "drafts": drafts}


# ── the job ──────────────────────────────────────────────────────────────────

def _platform_spec(platform: str):
    from services.social import publish

    return publish._platform_spec(platform)


async def _maybe_generate_image(
    client_id: str, platform: str, fmt: str, description: str, user_id: Optional[str],
    *, client: dict, policy_template: Optional[str],
) -> Optional[str]:
    """Best-effort per-platform image for a fan-out draft. Returns a URL or None —
    a budget/gen failure is swallowed (the draft ships copy-only / needs_image).
    ``client``/``policy_template`` are the once-loaded values, passed so the image
    service doesn't re-read them per platform."""
    from services.social import image as social_image

    req = SimpleNamespace(platform=platform, format=fmt, description=description, aspect_ratio=None)
    try:
        out = await social_image.generate_image(
            client_id, req, user_id=user_id, client=client, policy_template=policy_template
        )
        return out.get("url")
    except HTTPException as exc:
        logger.info("social.fanout_image_skipped",
                    extra={"platform": platform, "detail": str(exc.detail)[:120]})
        return None
    except Exception as exc:  # noqa: BLE001 — image is best-effort
        logger.info("social.fanout_image_error", extra={"platform": platform, "error": str(exc)[:160]})
        return None


async def _generate_carousel_images(
    client_id: str, platform: str, descriptions: list[str], user_id: Optional[str],
    *, client: dict, policy_template: Optional[str],
) -> list[str]:
    """Generate one image per carousel slide description, all at the platform's single
    (carousel) aspect ratio so the slides share one shape. Each slide is a separate paid
    image — the cost multiplies per slide, reserved individually against the fail-closed
    budget inside ``generate_image``. Best-effort per slide: a slide that fails to
    generate (e.g. budget exhausted) is skipped, so a partial carousel still ships what
    it produced (and lands ``needs_image`` if it can't reach 2 slides)."""
    from services.social import image as social_image

    urls: list[str] = []
    for desc in descriptions:
        req = SimpleNamespace(platform=platform, format="carousel", description=desc, aspect_ratio=None)
        try:
            out = await social_image.generate_image(
                client_id, req, user_id=user_id, client=client, policy_template=policy_template
            )
        except HTTPException as exc:
            # Budget exhaustion (402) or a missing image config (503) won't clear on the
            # next slide, so stop reserving; a transient per-slide generation failure
            # (502, or an unexpected 4xx) is worth trying the remaining slides for.
            if getattr(exc, "status_code", 0) in (402, 503):
                logger.info("social.carousel_slides_stopped",
                            extra={"platform": platform, "detail": str(exc.detail)[:120]})
                break
            logger.info("social.carousel_slide_skipped",
                        extra={"platform": platform, "detail": str(exc.detail)[:120]})
            continue
        except Exception as exc:  # noqa: BLE001 — one slide is best-effort
            logger.info("social.carousel_slide_error", extra={"platform": platform, "error": str(exc)[:160]})
            continue
        if out.get("url"):
            urls.append(out["url"])
    return urls


async def run_fanout_job(job: dict) -> None:
    """Handler for job_type='social_fanout'. Loads the source + voice card once,
    then for each pending Draft in the set generates platform copy (+ opt-in image)
    and marks it ready / needs_image / generation_failed. Best-effort per draft: one
    draft's failure never aborts the set. Settles its own job row."""
    from services import notifications
    from services.freeze import is_frozen

    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    angle_set_id = payload.get("angle_set_id")
    sb = _sb()

    def _settle(status: str, **fields) -> None:
        sb.table("async_jobs").update(
            {"status": status, "completed_at": "now()", **fields}
        ).eq("id", job["id"]).execute()

    def _fail_pending(reason: str) -> None:
        """Mark every still-'generating' draft in the set failed so they don't spin
        forever, then settle the job failed."""
        sb.table("social_drafts").update({"status": "generation_failed", "updated_at": "now()"}) \
            .eq("angle_set_id", angle_set_id).eq("status", "generating").execute()
        _settle("failed", error=reason[:500])

    # Freeze is enforced here (not the blanket worker gate) so a client frozen
    # between enqueue and execution gets its pending drafts cleaned up instead of
    # orphaned, and no paid copy/image is generated. The enqueue route also gates.
    if client_id and is_frozen(client_id):
        _fail_pending("client_frozen")
        return

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
        _fail_pending(str(exc.detail))
        return

    angle = payload.get("angle")
    angle_title = payload.get("angle_title")
    tone = payload.get("tone")
    fmt = payload.get("format") or "feed"
    include_image = bool(payload.get("include_image"))
    include_hashtags = bool(payload.get("include_hashtags", True))
    user_id = payload.get("user_id")
    # P4 autonomy provenance + auto-queue (absent for a manual fan-out).
    produced_by = payload.get("produced_by")
    auto_queue = bool(payload.get("auto_queue"))
    # P4 QA gate — only relevant when auto-queuing (QA-at-generation guards the
    # UNREVIEWED auto-queue; a human-published draft is QA'd at publish time). Loaded
    # once. Off → today's behavior (auto-queue any ready draft).
    from services.social import qa as social_qa

    qa_gate = social_qa.qa_gate_enabled(client_id) if auto_queue else False
    # Resolve the compliance mode ONCE (the fan-out client row omits the column, so the
    # per-draft QA can't read it from `client`). Only needed when the gate is on.
    qa_mode = social_qa.resolve_compliance_mode(client_id) if qa_gate else "off"
    # Load the client's image-prompt template ONCE (reused for every platform's image).
    policy_template = None
    if include_image:
        from services.social import image as social_image

        policy_template = social_image._policy_template(client_id)
    # Load the client's copy-gen steering template ONCE (reused for every platform's copy).
    from services.social import policy as social_policy

    text_template = social_policy.text_prompt_template(client_id)

    pending = (
        sb.table("social_drafts").select("id, platform, format")
        .eq("angle_set_id", angle_set_id).eq("status", "generating").execute()
    ).data or []

    ready = failed = qa_blocked = 0
    for draft in pending:
        platform = draft["platform"]
        spec = _platform_spec(platform)
        d_fmt = (draft.get("format") or fmt or "feed").lower()
        update: dict = {"source_version": source_version, "updated_at": "now()"}
        # Stories have no caption — skip the (discarded) copy generation entirely and
        # keep the draft caption empty so the Drafts UI + publish never show/post one.
        if d_fmt == "story":
            copy, voice_warnings, spec_warnings = "", [], []  # type: str, list[str], list[str]
        else:
            try:
                copy, voice_warnings, spec_warnings = await creator.draft_platform_copy(
                    platform=platform, spec=spec, fmt=d_fmt, source_title=source_title,
                    source_text=source_text, angle=angle, tone=tone,
                    include_hashtags=include_hashtags,
                    card=card, voice_block=voice_block, client_context=client_context,
                    text_template=text_template,
                )
            except Exception as exc:  # noqa: BLE001 — one draft failing doesn't abort the set
                logger.warning("social.fanout_draft_failed",
                               extra={"draft_id": draft["id"],
                                      "error": str(getattr(exc, 'detail', exc))[:200]})
                sb.table("social_drafts").update(
                    {"status": "generation_failed", "source_version": source_version,
                     "updated_at": "now()"}
                ).eq("id", draft["id"]).execute()
                failed += 1
                continue

        image_urls: list[str] = []
        if d_fmt == "carousel":
            # A carousel is N slides, each its own paid Pro image (cost multiplies per
            # slide), all at the platform's single carousel aspect ratio.
            if include_image:
                slide_count = creator.resolve_slide_count(
                    payload.get("slides"),
                    settings.social_carousel_default_slides,
                    settings.social_carousel_max_slides,
                )
                descriptions = await creator.carousel_slide_descriptions(
                    source_title=source_title, source_text=source_text, angle=angle,
                    count=slide_count, client_context=client_context, voice_block=voice_block,
                )
                image_urls = await _generate_carousel_images(
                    client_id, platform, descriptions, user_id,
                    client=client, policy_template=policy_template,
                )
            media = [{"type": "image", "url": u} for u in image_urls]
            # A carousel always needs ≥2 slides regardless of the per-platform spec.
            status = draft_status(bool(media), True, generation_ok=True, enough_media=len(media) >= 2)
        else:
            image_url: Optional[str] = None
            if include_image:
                image_url = await _maybe_generate_image(
                    client_id, platform, d_fmt,
                    image_description_for_angle(angle, angle_title, source_title), user_id,
                    client=client, policy_template=policy_template,
                )
            image_urls = [image_url] if image_url else []
            media = [{"type": "image", "url": image_url}] if image_url else []
            requires_image = bool((spec or {}).get("requires_image"))
            # Fan-out can't pick a Pinterest board, so a Pinterest draft with its image
            # still needs a board set in the Drafts tab before it can publish.
            board_missing = (platform or "").lower() == "pinterest"
            status = draft_status(
                bool(media), requires_image, generation_ok=True,
                board_required_missing=board_missing,
            )

        # P4 autonomy: at tier 2 the loop auto-queues its OWN drafts (machine-approval)
        # so P3's drip can publish them — but ONLY a fully-ready draft (a needs_image /
        # needs_board draft is never silently queued). Publishing still needs the
        # platform's auto_fill + the global auto-publish switch (P3), so tier 2 alone
        # only reaches the queue. When the QA gate is on, a draft that fails ANY check is
        # held at 'ready' (a human decides) instead of auto-queued — never queue
        # unreviewed content that fails. The verdict rides on the draft either way.
        if auto_queue and status == "ready":
            if qa_gate:
                qa_verdict = social_qa.review_draft(
                    client_id=client_id, platform=platform, copy=copy, media=media,
                    fmt=d_fmt, card=card, compliance_mode=qa_mode,
                )
                update["qa_verdict"] = qa_verdict
                if social_qa.blocks_auto_queue(qa_verdict):
                    qa_blocked += 1          # status stays 'ready' — held for a human
                else:
                    status = "queued"
            else:
                status = "queued"
        update.update({
            "copy": copy, "media": media,
            "image_urls": image_urls,
            "voice_verdict": {"warnings": voice_warnings},
            "spec_verdict": {"warnings": spec_warnings},
            "status": status,
        })
        # Stamp autonomy provenance so the draft is counted for the weekly rate cap,
        # rotated by the source cooldown, and badged in the UI (merges, never clobbers).
        if produced_by:
            meta = dict(draft.get("platform_metadata") or {})
            meta["produced_by"] = produced_by
            update["platform_metadata"] = meta
        sb.table("social_drafts").update(update).eq("id", draft["id"]).execute()
        ready += 1

    _settle("complete", result={"angle_set_id": angle_set_id, "ready": ready,
                                "failed": failed, "qa_blocked": qa_blocked})
    if ready:
        notifications.emit(
            client_id, "social_fanout_ready", "Social drafts are ready to review",
            summary=f"{ready} platform draft(s) generated from your angle.",
            severity="info", payload={"angle_set_id": angle_set_id},
        )
    if qa_blocked:
        # QA held one or more auto-fill drafts back from the queue — a human decides.
        notifications.emit(
            client_id, "social_qa_failed", "Auto-fill drafts held by QA",
            summary=(f"{qa_blocked} auto-generated draft(s) failed the QA check and were "
                     "left for your review instead of queued."),
            severity="warning", payload={"angle_set_id": angle_set_id, "qa_blocked": qa_blocked},
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
    board_id: Optional[str] = None,
) -> dict:
    """Human edit of a Draft before publish (copy / images / platform options / a
    Pinterest board). Recomputes status (needs_image / needs_board ↔ ready) from the
    new media + board. Only provided fields change. ``board_id`` folds into
    platform_metadata's internal ``board_id`` key (setting a board on a Pinterest draft
    flips needs_board → ready)."""
    from services.social import publish

    draft = get_draft(draft_id)
    fields: dict = {"updated_at": "now()"}
    if copy is not None:
        fields["copy"] = copy
    if image_urls is not None:
        media = publish.build_media(image_urls, None)
        fields["image_urls"] = [u for u in image_urls if u]
        fields["media"] = media
    # Merge platform_metadata + the first-class board_id (board_id wins for its key).
    new_metadata = draft.get("platform_metadata")
    if platform_metadata is not None:
        new_metadata = platform_metadata
    if board_id is not None:
        merged = dict(new_metadata or {})
        bid = board_id.strip()
        if bid:
            merged["board_id"] = bid
        else:
            merged.pop("board_id", None)   # clearing the field
        new_metadata = merged
    if platform_metadata is not None or board_id is not None:
        fields["platform_metadata"] = new_metadata

    # Recompute status when the draft is in a reviewable state (don't resurrect a
    # generating/failed/published row). Generation already succeeded, so this only
    # decides ready ↔ needs_image/needs_board — never generation_failed. A ``queued``
    # draft is re-validated too: it STAYS queued while still valid, but an edit that
    # makes it invalid (image/board removed) drops it OUT of the drip queue rather than
    # leaving the sweep to fail-and-retry it forever.
    prev_status = draft.get("status")
    new_media = fields.get("media", draft.get("media") or [])
    if prev_status in ("ready", "needs_image", "needs_board", "queued"):
        d_fmt = (draft.get("format") or "feed").lower()
        if d_fmt == "carousel":
            # A carousel always needs ≥2 slides, regardless of the platform spec.
            new_status = draft_status(
                bool(new_media), True, generation_ok=True, enough_media=len(new_media) >= 2
            )
        else:
            spec = publish._platform_spec(draft["platform"])
            requires_image = bool((spec or {}).get("requires_image"))
            board_missing = (
                (draft.get("platform") or "").lower() == "pinterest"
                and not publish._pinterest_board_id(new_metadata if new_metadata is not None
                                                     else draft.get("platform_metadata"))
            )
            new_status = draft_status(
                bool(new_media), requires_image, generation_ok=True,
                board_required_missing=board_missing,
            )
        # An edit never silently dequeues a still-valid queued draft.
        if prev_status == "queued" and new_status == "ready":
            new_status = "queued"
        fields["status"] = new_status

    row = (_sb().table("social_drafts").update(fields).eq("id", draft_id).execute()).data
    return row[0] if row else get_draft(draft_id)


def delete_draft(draft_id: str) -> dict:
    get_draft(draft_id)  # 404 if missing
    _sb().table("social_drafts").update({"status": "archived", "updated_at": "now()"}) \
        .eq("id", draft_id).execute()
    return {"ok": True}


def publish_existing_draft(
    draft_id: str, account_id: str, scheduled_at: Optional[datetime] = None,
    *, force_qa: bool = False,
) -> dict:
    """Approve & publish a Draft to one connected account (reuses the publish
    lifecycle). Validates against the Platform Spec, creates the Post, enqueues the
    freeze-gated publish job (or leaves it for the due sweep when scheduled), and
    marks the Draft published.

    When the client's QA gate is on, a CRITICAL rubric fail (a guide-forbidden voice term
    or a banned regulated claim) blocks the publish (409 ``social_qa_violation``) unless
    ``force_qa`` — the 'Publish anyway' override. Non-critical misses (CTA / image) are
    advisory on this human path (platform/char/image-required are already hard-blocked by
    ``validate_post`` below)."""
    _assert_enabled()
    from services.social import publish

    draft = get_draft(draft_id)
    if not account_id:
        raise HTTPException(status_code=422, detail="social_account_required")
    if draft.get("status") == "published":
        raise HTTPException(status_code=409, detail="social_draft_already_published")
    # Client isolation at the write (see publish._assert_account_allowed): the
    # target account must belong to this draft's client's Social group. Compose-time
    # gate — tolerate a PostPeer outage (require_live=False); run_publish_job
    # re-checks authoritatively before it posts.
    publish._assert_account_allowed(
        str(draft["client_id"]), account_id, require_live=False
    )

    platform = draft["platform"]
    fmt = (draft.get("format") or "feed").lower()
    media = draft.get("media") or publish.build_media(draft.get("image_urls"), None)
    copy = draft.get("copy") or ""
    board_id = publish._pinterest_board_id(draft.get("platform_metadata"))
    verdict = publish.validate_post(
        platform, copy, media, publish._platform_spec(platform), fmt=fmt, board_id=board_id
    )
    if verdict["hard"]:
        raise HTTPException(status_code=422, detail="social_spec_violation:" + verdict["hard"][0])

    # P4 QA gate (opt-in): block a CRITICAL fail (forbidden voice term / banned claim)
    # unless force_qa. Advisory misses don't block a deliberate human publish. The verdict
    # is persisted on the draft either way (surfaced in the Drafts UI).
    if not force_qa:
        from services.social import qa as social_qa

        if social_qa.qa_gate_enabled(str(draft["client_id"])):
            qa_verdict = social_qa.review_draft(
                client_id=str(draft["client_id"]), platform=platform, copy=copy,
                media=media, fmt=fmt, board_id=board_id,
            )
            social_qa.persist_verdict(draft_id, qa_verdict)
            if social_qa.is_critical_fail(qa_verdict):
                reason = " | ".join(social_qa.critical_terms(qa_verdict))[:300]
                raise HTTPException(status_code=409, detail="social_qa_violation:" + reason)

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


def enqueue_draft(draft_id: str) -> dict:
    """Enroll a ready Draft in the cadence drip queue (status ``ready`` → ``queued``). A
    ``queued`` draft is 'approved and waiting for its next cadence slot' — the schedule
    sweep drips the oldest queued draft for a platform. Only a ``ready`` draft can be
    queued (idempotent if already queued). ``queued`` is free-text (no migration)."""
    _assert_enabled()
    draft = get_draft(draft_id)
    if draft.get("status") == "queued":
        return draft
    if draft.get("status") != "ready":
        raise HTTPException(status_code=409, detail="social_draft_not_queueable")
    row = (
        _sb().table("social_drafts").update({"status": "queued", "updated_at": "now()"})
        .eq("id", draft_id).execute()
    ).data
    return row[0] if row else get_draft(draft_id)


def dequeue_draft(draft_id: str) -> dict:
    """Remove a Draft from the cadence queue (status ``queued`` → ``ready``)."""
    _assert_enabled()
    draft = get_draft(draft_id)
    if draft.get("status") != "queued":
        raise HTTPException(status_code=409, detail="social_draft_not_queued")
    row = (
        _sb().table("social_drafts").update({"status": "ready", "updated_at": "now()"})
        .eq("id", draft_id).execute()
    ).data
    return row[0] if row else get_draft(draft_id)


def next_queued_draft(client_id: str, platform: str) -> Optional[dict]:
    """The oldest ``queued`` Draft for a (client, platform) — the next one a cadence drip
    would publish. None if the queue is empty."""
    rows = (
        _sb().table("social_drafts").select("*")
        .eq("client_id", client_id).eq("platform", (platform or "").lower())
        .eq("status", "queued").order("created_at", desc=False).limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def publish_drafts_batch(client_id: str, items: list) -> list[dict]:
    """Approve & publish/schedule multiple Drafts at once — the approval queue's batch
    action (PACE's 'approve 1,3'). Each item carries ``draft_id`` / ``account_id`` /
    optional ``scheduled_at``; each is published independently via
    ``publish_existing_draft`` so one item's failure never sinks the batch (partial
    success). Returns a per-item result list."""
    _assert_enabled()
    results: list[dict] = []
    for item in items or []:
        draft_id = str(getattr(item, "draft_id", ""))
        account_id = str(getattr(item, "account_id", "") or "")
        scheduled_at = getattr(item, "scheduled_at", None)
        try:
            draft = get_draft(draft_id)
            if str(draft.get("client_id")) != str(client_id):
                raise HTTPException(status_code=403, detail="social_draft_wrong_client")
            post = publish_existing_draft(draft_id, account_id, scheduled_at)
            results.append({"draft_id": draft_id, "ok": True, "post_id": post["id"], "error": None})
        except HTTPException as exc:
            results.append({"draft_id": draft_id, "ok": False, "post_id": None,
                            "error": str(getattr(exc, "detail", exc))})
        except Exception as exc:  # noqa: BLE001 — one item failing never sinks the batch
            logger.warning("social.batch_publish_item_failed",
                           extra={"draft_id": draft_id, "error": str(exc)[:200]})
            results.append({"draft_id": draft_id, "ok": False, "post_id": None,
                            "error": "internal_error"})
    return results


def get_fanout_job(job_id: str) -> dict:
    rows = (
        _sb().table("async_jobs").select("id, status, result, error")
        .eq("id", job_id).limit(1).execute()
    ).data or []
    if not rows:
        raise HTTPException(status_code=404, detail="social_job_not_found")
    return rows[0]

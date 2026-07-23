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
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import gbp_posts_api as api
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
# Publish (async job; freeze-gated)
# ───────────────────────────────────────────────────────────────────────────
def _insert_publish_job(client_id: str, post_id: str) -> str:
    """Insert a ``gbp_post_publish`` async job (no status/validation side effects).
    Shared by the interactive publish-now path and the due-scheduled sweep."""
    res = (
        get_supabase().table("async_jobs")
        .insert({"job_type": "gbp_post_publish", "entity_id": client_id,
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


def ensure_future_utc(when: datetime, now: datetime) -> str:
    """Normalize a scheduled time to a UTC ISO string, or raise if not future.
    Pure (unit-tested): naive datetimes are treated as UTC."""
    w = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    w = w.astimezone(timezone.utc)
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
    when_iso = ensure_future_utc(scheduled_at, datetime.now(timezone.utc))
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


async def run_publish_job(job: dict) -> None:
    """Handler for job_type='gbp_post_publish'. Builds the v4 body, creates the
    post on Google, persists the result, and schedules a state re-check."""
    payload = job.get("payload") or {}
    post_id = payload.get("post_id")
    client_id = payload.get("client_id")
    supabase = get_supabase()
    try:
        post = get_post(post_id)
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
    except Exception as exc:  # noqa: BLE001 — record failure for the poller + alert
        detail = getattr(exc, "detail", None) or str(exc)
        supabase.table("gbp_posts").update(
            {"status": "failed", "error": str(detail)[:500], "updated_at": "now()"}
        ).eq("id", post_id).execute()
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
        notifications.emit(
            client_id, "gbp_post_failed", "GBP post failed to publish",
            summary=str(detail)[:200], severity="warning", payload={"post_id": post_id},
        )
        logger.warning("gbp_posts.publish_failed", extra={"post_id": post_id, "error": str(detail)})


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


async def draft_summary(
    client: dict, topic_type: str, theme: Optional[str], source_url: Optional[str]
) -> str:
    """One bounded Claude call returning post body text. Raises on hard failure."""
    import anthropic  # lazy

    from services.report_llm import retry_transient

    ask = [f"Write a {topic_type} Google Business Profile post."]
    if theme:
        ask.append(f"Topic / angle: {theme}")
    if source_url:
        ask.append(f"Announce this page and point the call-to-action at it: {source_url}")
    user = build_client_context(client) + "\n\n" + "\n".join(ask)

    api_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=60)
    resp = await retry_transient(
        lambda: api_client.messages.create(
            model=settings.gbp_post_model,
            max_tokens=settings.gbp_post_max_tokens,
            system=_DRAFT_SYSTEM,
            messages=[{"role": "user", "content": user}],
        ),
        max_retries=2,
        log_tag="gbp_post_draft",
    )
    text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    return text[: settings.gbp_post_max_chars]


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


async def run_generate_job(job: dict) -> None:
    """Handler for job_type='gbp_post_generate'. Drafts copy, creates a draft
    post row, and (for auto-publish schedules, if not frozen) chains publish."""
    from services.freeze import is_frozen

    payload = job.get("payload") or {}
    client_id = payload["client_id"]
    supabase = get_supabase()
    try:
        client = _client(client_id)
        summary = await draft_summary(
            client, payload.get("topic_type") or "standard",
            payload.get("theme"), payload.get("source_url"),
        )
        if not summary:
            raise HTTPException(status_code=502, detail="empty_draft")
        row = {
            "client_id": client_id, "location_row_id": payload["location_row_id"],
            "schedule_id": payload.get("schedule_id"),
            "source": payload.get("source") or "ai",
            "topic_type": payload.get("topic_type") or "standard", "summary": summary,
            "cta_type": payload.get("cta_type"), "cta_url": payload.get("cta_url"),
            "status": "draft", "created_by": payload.get("user_id"),
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
                    supabase.table("gbp_posts").select("id, google_name, status")
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
                    if row.get("status") != lp["status"]:
                        supabase.table("gbp_posts").update({
                            "status": lp["status"], "google_state": lp.get("google_state"),
                            "search_url": lp.get("search_url"), "updated_at": "now()",
                        }).eq("id", row["id"]).execute()
                        reconciled += 1
                        if lp["status"] == "rejected":
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
def compute_next_run_at(
    now: datetime, cadence: str, day_of_week: Optional[int],
    day_of_month: Optional[int], hour_utc: int, prev: Optional[datetime] = None,
) -> Optional[datetime]:
    """Next fire time strictly after ``now`` (UTC). None when disabled. Pure.

    weekly/monthly recompute from ``now`` (robust to missed ticks). biweekly
    steps 14 days from ``prev`` (the prior next_run) to preserve its phase; with
    no ``prev`` it seeds on the next matching weekday like weekly.
    """
    if cadence == "disabled":
        return None
    if cadence in ("weekly", "biweekly"):
        dow = day_of_week if day_of_week is not None else 0
        if cadence == "biweekly" and prev is not None:
            candidate = prev
            while candidate <= now:
                candidate += timedelta(days=14)
            return candidate.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
        days_ahead = (dow - now.weekday()) % 7
        candidate = (now + timedelta(days=days_ahead)).replace(
            hour=hour_utc, minute=0, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate
    if cadence == "monthly":
        dom = day_of_month if day_of_month is not None else 1
        candidate = now.replace(day=dom, hour=hour_utc, minute=0, second=0, microsecond=0)
        if candidate <= now:
            year = now.year + (1 if now.month == 12 else 0)
            month = 1 if now.month == 12 else now.month + 1
            candidate = candidate.replace(year=year, month=month)
        return candidate
    raise HTTPException(status_code=400, detail="invalid_cadence")


def _default_schedule(location_row_id: Optional[str] = None) -> dict:
    return {
        "location_row_id": location_row_id, "cadence": "disabled", "day_of_week": None,
        "day_of_month": None, "hour_utc": 9, "topic_type": "standard", "theme_notes": None,
        "cta_type": None, "cta_url": None, "auto_publish": False, "is_active": False,
        "next_run_at": None, "last_run_at": None,
    }


def get_schedule(client_id: str) -> dict:
    res = (
        get_supabase().table("gbp_post_schedules")
        .select("location_row_id, cadence, day_of_week, day_of_month, hour_utc, topic_type, "
                "theme_notes, cta_type, cta_url, auto_publish, is_active, next_run_at, last_run_at")
        .eq("client_id", client_id).limit(1).execute().data
    )
    return res[0] if res else _default_schedule()


def upsert_schedule(client_id: str, req: dict, user_id: str) -> dict:
    _assert_enabled()
    cadence = req.get("cadence") or "disabled"
    if cadence not in _VALID_CADENCES:
        raise HTTPException(status_code=400, detail="invalid_cadence")
    location = _location(str(req["location_row_id"]), client_id)
    hour_utc = int(req.get("hour_utc", 9))
    day_of_week = req.get("day_of_week")
    day_of_month = req.get("day_of_month")
    if cadence in ("weekly", "biweekly") and day_of_week is None:
        day_of_week = 0
    if cadence == "monthly" and day_of_month is None:
        day_of_month = 1
    is_active = bool(req.get("is_active", True))
    now = datetime.now(timezone.utc)
    next_run = compute_next_run_at(now, cadence, day_of_week, day_of_month, hour_utc)
    next_run_iso = next_run.isoformat() if (next_run and is_active and cadence != "disabled") else None
    row = {
        "client_id": client_id, "location_row_id": location["id"], "cadence": cadence,
        "day_of_week": day_of_week, "day_of_month": day_of_month, "hour_utc": hour_utc,
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
        .select("client_id, location_row_id, cadence, day_of_week, day_of_month, hour_utc, "
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
        next_run = compute_next_run_at(
            now, sched["cadence"], sched.get("day_of_week"),
            sched.get("day_of_month"), sched["hour_utc"], prev=prev,
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

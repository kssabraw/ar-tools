"""Social Media module — the publish path (PRD §9, GBP-Posts lifecycle template).

Platform-general: the same compose → freeze-gated, idempotent publish job →
status write works for Facebook (the first live target), Instagram, X, Pinterest.
Accounts are connected MANUALLY in PostPeer for v1, so there is no connect flow
here — a client's connected accounts are read live from the provider, scoped to
the client's ``social_profile_id`` (the PostPeer "Social group"), and a post
targets one of their ``account_id``s.

The publish job clones ``gbp_posts_service.run_publish_job``: idempotent against a
requeue (a post that already has ``provider_post_id`` is done; a post left
``publishing`` by an interrupted worker is NOT re-posted, to avoid a real
double-publish), freeze-gated by the worker (``social_publish`` ∈
FREEZE_GATED_JOB_TYPES), and budget-reserved (fail-closed) before it spends.

Pure helpers (``validate_post``, ``estimate_cost_usd``) are unit-tested.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import HTTPException

from config import settings
from services.social import budget
from services.social.postpeer_adapter import get_adapter, x_credit_cost

logger = logging.getLogger(__name__)

# A post is publishable from these states (mirrors GBP _PUBLISHABLE).
_PUBLISHABLE = {"scheduled", "failed", "rejected", "blocked_account"}


def _assert_enabled() -> None:
    if not settings.social_enabled:
        raise HTTPException(status_code=503, detail="social_not_enabled")


# ── pure helpers (no network / DB — unit-tested) ─────────────────────────────

def validate_post(
    platform: str, copy: str, image_urls: Optional[list[str]], spec: Optional[dict]
) -> dict:
    """Deterministic Platform-Spec check (PRD §6). Returns
    {"hard": [...], "warnings": [...]}: a hard violation blocks approval/publish;
    a warning is advisory (e.g. the X link credit cost)."""
    copy = copy or ""
    images = image_urls or []
    hard: list[str] = []
    warnings: list[str] = []

    if not copy.strip() and not images:
        hard.append("empty_post")

    if spec:
        char_limit = spec.get("char_limit")
        if char_limit and len(copy) > int(char_limit):
            hard.append(f"over_char_limit:{len(copy)}>{char_limit}")
        if spec.get("requires_image") and not images:
            hard.append("image_required")
        max_images = spec.get("max_images")
        if max_images and len(images) > int(max_images):
            hard.append(f"too_many_images:{len(images)}>{max_images}")

    if (platform or "").lower() in ("twitter", "x") and x_credit_cost(platform, copy) >= 50:
        warnings.append("x_link_post_50_credits")

    return {"hard": hard, "warnings": warnings}


def estimate_cost_usd(platform: str, copy: str, per_credit_usd: Optional[float] = None) -> float:
    """Estimated USD to publish one post (credits × per-credit price). Pure."""
    price = per_credit_usd if per_credit_usd is not None else settings.social_credit_usd
    return round(x_credit_cost(platform, copy) * float(price), 4)


# ── impure layer ─────────────────────────────────────────────────────────────

def _sb():
    from db.supabase_client import get_supabase

    return get_supabase()


def _client_profile_id(client_id: str) -> Optional[str]:
    rows = (
        _sb().table("clients").select("social_profile_id").eq("id", client_id).limit(1).execute()
    ).data or []
    return (rows[0].get("social_profile_id") if rows else None) or None


def _platform_spec(platform: str) -> Optional[dict]:
    rows = (
        _sb().table("social_platform_specs").select("*").eq("platform", (platform or "").lower())
        .limit(1).execute()
    ).data or []
    return rows[0] if rows else None


def list_accounts(client_id: str) -> list[dict]:
    """The client's connected accounts, live from PostPeer, scoped to their
    Social group when one is set. Read-only (accounts are connected manually)."""
    _assert_enabled()
    profile_id = _client_profile_id(client_id)
    integrations = get_adapter().list_integrations(profile_id=profile_id)
    return [
        {
            "account_id": i.account_id,
            "platform": i.platform,
            "handle": i.handle,
            "reconnect_required": i.reconnect_required,
        }
        for i in integrations
    ]


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
    fmt: str = "feed",
) -> dict:
    """Compose one platform-native post and enqueue its publish. Validates against
    the Platform Spec (hard violation → 422) before anything is written."""
    _assert_enabled()
    platform = (platform or "").lower()
    image_urls = image_urls or []
    verdict = validate_post(platform, copy, image_urls, _platform_spec(platform))
    if verdict["hard"]:
        raise HTTPException(status_code=422, detail="social_spec_violation:" + verdict["hard"][0])

    draft = (
        _sb().table("social_drafts").insert({
            "client_id": client_id, "platform": platform, "format": fmt,
            "angle": "manual", "source_ref": {"type": "manual"},
            "copy": copy, "image_urls": image_urls,
            "spec_verdict": verdict, "status": "approved",
        }).execute()
    ).data[0]

    post = (
        _sb().table("social_posts").insert({
            "draft_id": draft["id"], "client_id": client_id, "platform": platform,
            "account_id": account_id, "status": "scheduled",
        }).execute()
    ).data[0]

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


async def run_publish_job(job: dict) -> None:
    """Handler for job_type='social_publish'. Publishes ONE post to ONE account via
    the adapter, reserves budget first (fail-closed), and reconciles status. The
    worker's freeze gate holds this for a frozen client. Idempotent on requeue."""
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
        # Guard 1 — already published; settle the duplicate without re-posting.
        if post.get("provider_post_id"):
            _settle_job("complete", result={"post_id": post_id, "already_published": True})
            return
        # Guard 2 — interrupted mid-publish. PostPeer gives no reliable way to
        # match an orphan, so do NOT repost (a real double-publish); flag for a
        # human to verify in PostPeer instead.
        if post.get("status") == "publishing":
            _fail("interrupted_verify_in_postpeer", post_status="failed")
            return

        draft = {}
        if post.get("draft_id"):
            drows = (sb.table("social_drafts").select("*").eq("id", post["draft_id"]).limit(1).execute()).data or []
            draft = drows[0] if drows else {}
        copy = draft.get("copy") or ""
        image_urls = draft.get("image_urls") or []
        platform = post["platform"]
        account_id = post.get("account_id")
        if not account_id:
            _fail("no_account_id")
            return

        # Budget: reserve the estimated cost before spending (fail-closed).
        est = estimate_cost_usd(platform, copy)
        cap = budget.ceiling_for_client(client_id)
        if not budget.reserve(client_id, est, cap=cap):
            _fail("budget_exceeded", post_status="failed")
            return

        sb.table("social_posts").update(
            {"status": "publishing", "updated_at": "now()"}
        ).eq("id", post_id).execute()

        result = await asyncio.to_thread(
            get_adapter().post, account_id, platform, copy, image_urls or None
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
    except Exception as exc:  # noqa: BLE001 — record failure for the poller
        detail = getattr(exc, "detail", None) or str(exc)
        _fail(detail)
        logger.warning("social.publish_failed", extra={"post_id": post_id, "error": str(detail)})

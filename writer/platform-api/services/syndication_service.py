"""Content Syndication — async job handlers + enqueue helpers.

Two job types drive the module:
  * syndication_scan — discover new site URLs for one client, record them as
    items, then enqueue one syndication_item job per new item (staggered so a
    big first scan runs at background priority and each item stays under the
    stale-job reaper window).
  * syndication_item — for one item: extract → unique rewrite → publish a public
    Google Doc + Sheet (each with a backlink), persisting the result.

Publishing is fully automatic (no review step) per the module's design decision.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from config import settings
from db.supabase_client import get_supabase
from services.google_docs import resolve_drive_folder
from services.syndication_discovery import scan_client
from services.syndication_publish import publish_item
from services.syndication_rewrite import extract_source_content, rewrite_unique

logger = logging.getLogger(__name__)


# ── config + lookups ─────────────────────────────────────────────────────────

def get_or_create_config(client_id: str) -> dict:
    """Return the client's syndication_config row, creating a default (disabled)
    row when none exists."""
    supabase = get_supabase()
    existing = (
        supabase.table("syndication_config").select("*").eq("client_id", client_id).execute()
    ).data or []
    if existing:
        return existing[0]
    row = {
        "client_id": client_id,
        "enabled": False,
        "interval_days": settings.syndication_default_interval_days,
        "share_mode": "public",
    }
    try:
        inserted = supabase.table("syndication_config").insert(row).execute()
        if inserted.data:
            return inserted.data[0]
    except Exception as exc:  # noqa: BLE001 — fall back to the in-memory default
        logger.warning("syndication_config_create_failed", extra={"client_id": client_id, "error": str(exc)})
    return row


def _get_client(client_id: str) -> dict | None:
    supabase = get_supabase()
    res = (
        supabase.table("clients")
        .select(
            "id, name, website_url, rank_tracking_location_code, "
            "google_drive_folder_id, drive_folders"
        )
        .eq("id", client_id)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


# ── enqueue ──────────────────────────────────────────────────────────────────

def _has_active_job(supabase, job_type: str, entity_id: str) -> bool:
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", job_type)
        .eq("entity_id", entity_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    return bool(existing.data)


def enqueue_scan(client_id: str) -> str | None:
    """Enqueue a syndication_scan job for a client (deduped). Returns the job id."""
    supabase = get_supabase()
    if _has_active_job(supabase, "syndication_scan", client_id):
        return None
    res = (
        supabase.table("async_jobs")
        .insert({"job_type": "syndication_scan", "entity_id": client_id, "payload": {"client_id": client_id}})
        .execute()
    )
    return res.data[0]["id"] if res.data else None


def _item_scheduled_at(index: int) -> str:
    """Staggered scheduled_at for the index-th item job (background priority)."""
    spacing = settings.syndication_item_job_spacing_seconds
    return (datetime.now(timezone.utc) + timedelta(seconds=index * spacing)).isoformat()


def enqueue_item_jobs(client_id: str) -> int:
    """Enqueue one syndication_item job per discovered, not-yet-queued item."""
    supabase = get_supabase()
    items = (
        supabase.table("syndication_items")
        .select("id")
        .eq("client_id", client_id)
        .eq("status", "discovered")
        .execute()
    ).data or []
    enqueued = 0
    rows = []
    for item in items:
        item_id = item["id"]
        if _has_active_job(supabase, "syndication_item", item_id):
            continue
        rows.append(
            {
                "job_type": "syndication_item",
                "entity_id": item_id,
                "payload": {"item_id": item_id, "client_id": client_id},
                "scheduled_at": _item_scheduled_at(enqueued),
            }
        )
        enqueued += 1
    if rows:
        supabase.table("async_jobs").insert(rows).execute()
    return enqueued


def retry_item(item_id: str) -> str | None:
    """Reset a failed item to 'discovered' and enqueue a fresh item job."""
    supabase = get_supabase()
    supabase.table("syndication_items").update(
        {"status": "discovered", "error": None, "updated_at": "now()"}
    ).eq("id", item_id).execute()
    if _has_active_job(supabase, "syndication_item", item_id):
        return None
    item = (
        supabase.table("syndication_items").select("client_id").eq("id", item_id).execute()
    ).data
    client_id = item[0]["client_id"] if item else None
    res = (
        supabase.table("async_jobs")
        .insert(
            {
                "job_type": "syndication_item",
                "entity_id": item_id,
                "payload": {"item_id": item_id, "client_id": client_id},
            }
        )
        .execute()
    )
    return res.data[0]["id"] if res.data else None


# ── job handlers ─────────────────────────────────────────────────────────────

async def run_syndication_scan_job(job: dict) -> None:
    """Handler for job_type='syndication_scan'. Discover new content, then
    enqueue an item job per new piece."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    try:
        client = _get_client(client_id)
        if not client:
            raise ValueError("client_not_found")
        config = get_or_create_config(client_id)
        result = await scan_client(client, config)
        queued = enqueue_item_jobs(client_id)
        result["queued"] = queued
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("syndication_scan_complete", extra={"client_id": client_id, **result})
    except Exception as exc:  # noqa: BLE001
        logger.warning("syndication_scan_job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


async def run_syndication_item_job(job: dict) -> None:
    """Handler for job_type='syndication_item'. Extract → rewrite → publish a
    public Doc + Sheet for one item."""
    payload = job.get("payload") or {}
    item_id = payload.get("item_id")
    job_id = job["id"]
    supabase = get_supabase()

    def _fail(error: str) -> None:
        supabase.table("syndication_items").update(
            {"status": "failed", "error": error[:500], "updated_at": "now()"}
        ).eq("id", item_id).execute()
        supabase.table("async_jobs").update(
            {"status": "failed", "error": error[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

    try:
        rows = (
            supabase.table("syndication_items").select("*").eq("id", item_id).execute()
        ).data or []
        if not rows:
            raise ValueError("item_not_found")
        item = rows[0]
        if item.get("status") == "published":
            # Idempotent: a requeued job for an already-published item is a no-op.
            supabase.table("async_jobs").update(
                {"status": "complete", "result": {"skipped": "already_published"}, "completed_at": "now()"}
            ).eq("id", job_id).execute()
            return

        client = _get_client(item["client_id"])
        if not client:
            raise ValueError("client_not_found")
        config = get_or_create_config(item["client_id"])
        share = config.get("share_mode") or "public"

        folder_id = resolve_drive_folder(client, item.get("content_type"))
        if not folder_id:
            raise ValueError("missing_google_drive_folder_id")

        supabase.table("syndication_items").update(
            {"status": "rewriting", "updated_at": "now()"}
        ).eq("id", item_id).execute()

        source_title, source_md = await extract_source_content(item["source_url"])
        new_title, new_md = await rewrite_unique(source_title, source_md)
        published = await publish_item(
            folder_id, new_title, new_md, item["source_url"], share=share
        )

        supabase.table("syndication_items").update(
            {
                "status": "published",
                "title": source_title or item.get("title"),
                "rewritten_title": new_title,
                "rewritten_markdown": new_md,
                "doc_id": published.get("doc_id"),
                "doc_url": published.get("doc_url"),
                "sheet_id": published.get("sheet_id"),
                "sheet_url": published.get("sheet_url"),
                "error": None,
                "published_at": "now()",
                "updated_at": "now()",
            }
        ).eq("id", item_id).execute()
        supabase.table("async_jobs").update(
            {"status": "complete", "result": published, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("syndication_item_published", extra={"item_id": item_id, "doc_url": published.get("doc_url")})
    except Exception as exc:  # noqa: BLE001
        logger.warning("syndication_item_failed", extra={"item_id": item_id, "error": str(exc)})
        try:
            _fail(str(exc))
        except Exception:
            logger.error("syndication_item_fail_persist_failed", extra={"item_id": item_id})

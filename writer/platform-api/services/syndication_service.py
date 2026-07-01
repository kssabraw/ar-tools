"""Content Syndication — async job handlers + enqueue helpers.

Manual select-and-publish model. Two job types drive the module:
  * syndication_scan — discover the client's site URLs and record any new ones as
    ``discovered`` candidates. Discovery only; it never publishes.
  * syndication_item — for one user-selected item: extract → unique rewrite →
    publish a public Google Doc and/or Sheet (per the client's publish_target),
    each with a backlink, persisting the result.

Nothing publishes on its own — the user ticks candidates and hits Publish, which
enqueues one syndication_item job per selection (`publish_items`).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from config import settings
from db.supabase_client import get_supabase
from services.google_docs import create_google_doc, create_google_sheet, resolve_drive_folder
from services.syndication_discovery import scan_client
from services.syndication_publish import build_doc_html, build_sheet_rows
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
        "publish_target": "both",
    }
    try:
        inserted = supabase.table("syndication_config").insert(row).execute()
        if inserted.data:
            return inserted.data[0]
    except Exception as exc:  # noqa: BLE001 — likely a concurrent insert (PK clash)
        logger.warning("syndication_config_create_failed", extra={"client_id": client_id, "error": str(exc)})
        # A concurrent caller may have created the row between our select and
        # insert; re-read so we return the real (possibly enabled) row, not the
        # disabled in-memory default.
        again = (
            supabase.table("syndication_config").select("*").eq("client_id", client_id).execute()
        ).data or []
        if again:
            return again[0]
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


def _active_item_entity_ids(supabase, client_id: str) -> set[str]:
    """The item ids that already have a pending/running syndication_item job
    (one query, not one-per-item)."""
    rows = (
        supabase.table("async_jobs")
        .select("entity_id")
        .eq("job_type", "syndication_item")
        .in_("status", ["pending", "running"])
        .execute()
    ).data or []
    return {r["entity_id"] for r in rows}


def _needs_publish(item: dict, want_doc: bool, want_sheet: bool) -> bool:
    """True when the item still lacks a wanted output. A 'published' item that is
    missing an output the current publish_target wants (e.g. target switched from
    doc → both) can be re-published to fill the gap; one that already has every
    wanted output is done."""
    if want_doc and not item.get("doc_id"):
        return True
    if want_sheet and not item.get("sheet_id"):
        return True
    return False


def publish_items(client_id: str, item_ids: list[str]) -> int:
    """Enqueue a syndication_item (rewrite + publish) job for each selected item.

    Manual action: the user ticks candidates and hits Publish. Only the client's
    own items are considered; an item with an active job is skipped (dedup), and
    an already-published item is skipped UNLESS it's missing an output the current
    publish_target wants. Jobs are lightly staggered. Returns the count enqueued."""
    if not item_ids:
        return 0
    supabase = get_supabase()
    config = get_or_create_config(client_id)
    target = config.get("publish_target") or "both"
    want_doc = target in ("doc", "both")
    want_sheet = target in ("sheet", "both")

    rows_data = (
        supabase.table("syndication_items")
        .select("id, status, doc_id, sheet_id")
        .eq("client_id", client_id)
        .in_("id", item_ids)
        .execute()
    ).data or []
    active = _active_item_entity_ids(supabase, client_id)

    jobs = []
    for item in rows_data:
        item_id = item["id"]
        if item_id in active:
            continue
        if item.get("status") == "published" and not _needs_publish(item, want_doc, want_sheet):
            continue
        jobs.append(
            {
                "job_type": "syndication_item",
                "entity_id": item_id,
                "payload": {"item_id": item_id, "client_id": client_id},
                "scheduled_at": _item_scheduled_at(len(jobs)),
            }
        )
    if jobs:
        supabase.table("async_jobs").insert(jobs).execute()
        logger.info("syndication_publish_selected", extra={"client_id": client_id, "queued": len(jobs)})
    return len(jobs)


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
    """Handler for job_type='syndication_scan'. Discover the site's pages and
    record any new ones as candidates. Discovery only — it never publishes."""
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
        # The scan only discovers candidates; publishing is a manual action, so
        # nothing is enqueued here.
        # Mark the scan done on success (not at enqueue time) so a failed scan
        # re-runs next cycle instead of being skipped by the interval gate.
        supabase.table("syndication_config").update(
            {"last_scan_date": datetime.now(timezone.utc).date().isoformat(), "updated_at": "now()"}
        ).eq("client_id", client_id).execute()
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

    def _patch(fields: dict) -> None:
        fields["updated_at"] = "now()"
        supabase.table("syndication_items").update(fields).eq("id", item_id).execute()

    try:
        rows = (
            supabase.table("syndication_items").select("*").eq("id", item_id).execute()
        ).data or []
        if not rows:
            raise ValueError("item_not_found")
        item = rows[0]
        source_url = item["source_url"]

        client = _get_client(item["client_id"])
        if not client:
            raise ValueError("client_not_found")
        config = get_or_create_config(item["client_id"])
        share = config.get("share_mode") or "public"
        target = config.get("publish_target") or "both"
        want_doc = target in ("doc", "both")
        want_sheet = target in ("sheet", "both")

        if item.get("status") == "published" and not _needs_publish(item, want_doc, want_sheet):
            # Idempotent: an already-published item with every wanted output is a
            # no-op (a requeue, or a re-select that changed nothing).
            supabase.table("async_jobs").update(
                {"status": "complete", "result": {"skipped": "already_published"}, "completed_at": "now()"}
            ).eq("id", job_id).execute()
            return

        folder_id = resolve_drive_folder(client, item.get("content_type"))
        if not folder_id:
            raise ValueError("missing_google_drive_folder_id")

        _patch({"status": "rewriting"})

        # Reuse a prior attempt's rewrite if present (a requeue after a partial
        # publish must not re-run the LLM, nor re-create an output that already
        # has an id — that would leak duplicate public Docs/Sheets).
        new_title = item.get("rewritten_title")
        new_md = item.get("rewritten_markdown")
        if not new_md:
            source_title, source_md = await extract_source_content(source_url)
            new_title, new_md = await rewrite_unique(source_title, source_md)
            _patch({
                "title": source_title or item.get("title"),
                "rewritten_title": new_title,
                "rewritten_markdown": new_md,
            })

        doc_url = item.get("doc_url")
        if want_doc and not item.get("doc_id"):
            doc = await create_google_doc(
                folder_id, new_title, build_doc_html(new_title, new_md, source_url),
                content_format="html", share=share,
            )
            doc_url = doc.get("doc_url")
            _patch({"doc_id": doc.get("doc_id"), "doc_url": doc_url})

        sheet_url = item.get("sheet_url")
        if want_sheet and not item.get("sheet_id"):
            sheet = await create_google_sheet(
                folder_id, new_title, build_sheet_rows(new_title, new_md, source_url), share=share,
            )
            sheet_url = sheet.get("sheet_url")
            _patch({"sheet_id": sheet.get("sheet_id"), "sheet_url": sheet_url})

        _patch({"status": "published", "error": None, "published_at": "now()"})
        result = {"doc_url": doc_url, "sheet_url": sheet_url}
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("syndication_item_published", extra={"item_id": item_id, "doc_url": doc_url})
    except Exception as exc:  # noqa: BLE001
        logger.warning("syndication_item_failed", extra={"item_id": item_id, "error": str(exc)})
        try:
            _fail(str(exc))
        except Exception:
            logger.error("syndication_item_fail_persist_failed", extra={"item_id": item_id})

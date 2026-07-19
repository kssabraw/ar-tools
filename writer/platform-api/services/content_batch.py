"""Content Scheduler — batch orchestration + the `content_batch_item` async job.

Bridges `content_schedule_store` (persistence/planning) to the suite's generators
and the shared `async_jobs` queue:

- `enqueue_items` releases a set of batch items NOW (create-now) — one staggered
  `content_batch_item` job per item, flipping each item scheduled -> queued.
- `enqueue_due_content_items` is the shared-scheduler tick hook: it releases any
  scheduled item that has come due (its batch still active).
- `run_content_batch_item_job` is the worker handler: it dispatches by
  content_type to the right generator (suite `runs` for blog/service/location,
  `local_seo_service.generate_page` for local SEO), records the produced artifact
  on the item, and settles the parent batch when its last item drains.

One job type covers all four content types so batch bookkeeping lives in one
place. Freeze Protocol: `content_batch_item` is freeze-gated in the worker, so a
frozen client's pending items fail fast with `client_frozen`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import content_schedule_store as store

logger = logging.getLogger(__name__)


def _spacing_seconds() -> int:
    # Reuse the Local SEO bulk spacing so batch jobs run at background priority
    # (staggered scheduled_at interleaves now-dated interactive jobs ahead of the
    # rest of a batch) without adding another knob.
    return getattr(settings, "local_seo_bulk_job_spacing_seconds", 180)


def _staggered_at(index: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=index * _spacing_seconds())).isoformat()


def _job_payload(batch: dict, item: dict) -> dict:
    """The `content_batch_item` job payload — everything the handler needs to
    generate + publish one page, self-contained so it survives a worker restart."""
    return {
        "batch_item_id": item["id"],
        "batch_id": batch["id"],
        "client_id": batch["client_id"],
        "content_type": batch["content_type"],
        "keyword": item["keyword"],
        "location": item.get("location"),
        "location_code": item.get("location_code"),
        "services": item.get("services") or [],
        "page_template_url": item.get("page_template_url"),
        "notes": item.get("notes"),
        "auto_publish": bool(batch.get("auto_publish")),
        "wp_publish": bool(batch.get("wp_publish")),
        "wp_status": batch.get("wp_status") or "draft",
        "user_id": batch.get("created_by"),
    }


def _enqueue_one(batch: dict, item: dict, index: int) -> Optional[str]:
    """Insert one `content_batch_item` job for a scheduled item and flip the item
    to queued. Conditional release (set_item_released) so a paused/cancelled/raced
    item is never double-enqueued — if the flip loses the race the job is left to
    be reaped as a no-op (the handler re-checks the item status). Returns job id."""
    supabase = get_supabase()
    res = supabase.table("async_jobs").insert({
        "job_type": "content_batch_item",
        "entity_id": batch["client_id"],
        "scheduled_at": _staggered_at(index),
        "payload": _job_payload(batch, item),
    }).execute()
    job_id = res.data[0]["id"]
    if not store.set_item_released(item["id"], job_id):
        # Lost the race (item paused/cancelled between read and release) — drop the
        # orphan job so the worker doesn't act on it.
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "item_not_releasable", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return None
    return job_id


def enqueue_items(batch: dict, items: list[dict]) -> int:
    """Release a set of just-created items immediately (create-now). Returns the
    number of jobs enqueued."""
    enqueued = 0
    for i, item in enumerate(items):
        if _enqueue_one(batch, item, i):
            enqueued += 1
    logger.info("content_batch.enqueued_now",
                extra={"batch_id": batch["id"], "enqueued": enqueued, "total": len(items)})
    return enqueued


def enqueue_due_content_items(limit: int = 200) -> int:
    """Shared-scheduler tick hook: release every scheduled item that has come due
    (its batch still active). Cheap due-query; no-op when nothing is due. Returns
    the number released this tick."""
    now = datetime.now(timezone.utc)
    due = store.due_items(now, limit=limit)
    if not due:
        return 0
    # Group by batch so each item's job carries the batch's cadence/publish opts.
    batches: dict[str, dict] = {}
    released = 0
    for i, item in enumerate(due):
        batch = batches.get(item["batch_id"]) or store.get_batch(item["batch_id"])
        if not batch:
            continue
        batches[item["batch_id"]] = batch
        if _enqueue_one(batch, item, i):
            released += 1
    if released:
        logger.info("content_batch.released_due", extra={"released": released, "due": len(due)})
    return released


async def _generate_run(payload: dict) -> Optional[str]:
    """Blog / service / location page: create a suite run + drive the orchestrator
    to completion. Returns the run id on success, None on failure."""
    from services.local_seo_service import _get_client
    from services.orchestrator import orchestrate_run
    from services.run_dispatch import create_run_and_snapshot

    client = _get_client(payload["client_id"])
    run_id = create_run_and_snapshot(
        client=client,
        keyword=payload["keyword"],
        content_type=payload["content_type"],
        location=payload.get("location"),
        location_code=payload.get("location_code"),
        services=payload.get("services") or [],
        writer_notes=(payload.get("notes") or "").strip() or None,
        created_by=payload.get("user_id"),
    )
    await orchestrate_run(run_id)
    status = (
        (get_supabase().table("runs").select("status").eq("id", run_id).single().execute()).data
        or {}
    ).get("status")
    return run_id if status == "complete" else None


async def _generate_local_seo(payload: dict) -> Optional[str]:
    """Local SEO page: the nlp-api generator (competitor analysis + Claude + 8-engine
    scoring). Returns the new page id on success, None on failure."""
    from services.local_seo_service import generate_page

    if not (payload.get("location") or "").strip():
        raise ValueError("local_seo_page item has no location")
    page = await generate_page(
        client_id=payload["client_id"],
        keyword=payload["keyword"],
        location=payload["location"],
        location_code=payload.get("location_code"),
        user_id=payload.get("user_id") or "",
        force_refresh=False,
        page_template_url=payload.get("page_template_url"),
        notes=(payload.get("notes") or "").strip() or None,
    )
    return (page or {}).get("id")


async def _generate_ecommerce(payload: dict) -> Optional[str]:
    """Ecommerce product page: the suite ecommerce writer (competitor analysis +
    Claude + 8-engine scoring). The CSV "Product" column is the head term. Returns
    the new page id on success, None on failure."""
    from services.ecommerce_service import generate_page

    page = await generate_page(
        client_id=payload["client_id"],
        keyword=payload["keyword"],
        page_type="product",
        source_url=None,
        product_input=None,
        user_id=payload.get("user_id") or "",
        notes=(payload.get("notes") or "").strip() or None,
    )
    return (page or {}).get("id")


async def run_content_batch_item_job(job: dict) -> None:
    """Worker handler for job_type='content_batch_item'. Generates one page via the
    content-type's generator, records the artifact on the batch item, settles the
    parent batch, then marks the async_jobs row. Freeze is enforced upstream in the
    worker; here a still-releasable item is generated exactly once."""
    payload = job.get("payload") or {}
    job_id = job["id"]
    item_id = payload.get("batch_item_id")
    batch_id = payload.get("batch_id")
    content_type = payload.get("content_type")
    supabase = get_supabase()

    # Idempotency: only act on an item that's actually queued (a reaped requeue of a
    # finished/cancelled item must be a no-op — never regenerate).
    item = store.get_item(item_id) if item_id else None
    if not item or item["status"] not in ("queued", "running"):
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"skipped": "item_not_queued"},
             "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    store.mark_item_running(item_id)
    try:
        if content_type == "local_seo_page":
            ref = await _generate_local_seo(payload)
            kind = "local_seo_page"
        elif content_type == "ecommerce":
            ref = await _generate_ecommerce(payload)
            kind = "ecommerce_page"
        elif content_type in ("blog_post", "service_page", "location_page"):
            ref = await _generate_run(payload)
            kind = "run"
        else:
            raise ValueError(f"unknown content_type {content_type!r}")

        if ref:
            store.finish_item(item_id, "complete", result_ref=ref, result_kind=kind)
            supabase.table("async_jobs").update(
                {"status": "complete", "result": {"result_ref": ref, "result_kind": kind},
                 "completed_at": "now()"}
            ).eq("id", job_id).execute()
            logger.info("content_batch.item_complete",
                        extra={"job_id": job_id, "item_id": item_id,
                               "content_type": content_type, "result_ref": ref})
        else:
            store.finish_item(item_id, "failed", error="content generation failed")
            supabase.table("async_jobs").update(
                {"status": "failed", "error": "content generation failed",
                 "completed_at": "now()"}
            ).eq("id", job_id).execute()
    except Exception as exc:  # noqa: BLE001 — one bad item must not stop the worker
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("content_batch.item_failed",
                       extra={"job_id": job_id, "item_id": item_id, "error": str(detail)})
        store.finish_item(item_id, "failed", error=str(detail))
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
    finally:
        if batch_id:
            try:
                store.complete_if_drained(batch_id)
            except Exception as exc:  # noqa: BLE001 — settling is best-effort
                logger.warning("content_batch.drain_check_failed",
                               extra={"batch_id": batch_id, "error": str(exc)})

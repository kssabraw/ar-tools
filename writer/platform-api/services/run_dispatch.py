"""Shared run creation — insert the run row + freeze the client_context snapshot.

Both the `POST /runs` router and Fanout's service_page job need to create a run
with an identical client-context snapshot (brand voice / ICP resolution +
format detection). Factoring it here keeps a single source of truth so the two
call sites can't drift.
"""

from __future__ import annotations

import logging
from typing import Optional

from db.supabase_client import get_supabase
from services import brand_voice_service, icp_service
from services.file_parser import detect_format

logger = logging.getLogger(__name__)

# A run is "still owns the work" (adopt it instead of creating a duplicate) unless
# it reached a terminal FAILED/CANCELLED state — a transient-retry attempt
# deliberately supersedes a failed run with a fresh one.
_ADOPTABLE_STATUSES_EXCLUDED = {"failed", "cancelled"}


def find_run_by_source_ref(source_ref: str) -> Optional[dict]:
    """The latest run created for a work-item key, or None. Pure read."""
    res = (
        get_supabase()
        .table("runs")
        .select("id, status")
        .eq("source_ref", source_ref)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def create_run_and_snapshot(
    *,
    client: dict,
    keyword: str,
    content_type: str = "blog_post",
    service: Optional[str] = None,
    location: Optional[str] = None,
    location_code: Optional[int] = None,
    services: Optional[list[str]] = None,
    intent_override: Optional[str] = None,
    sie_outlier_mode: str = "safe",
    sie_force_refresh: bool = False,
    brief_force_refresh: bool = False,
    reoptimize_source_url: Optional[str] = None,
    reoptimize_source_html: Optional[str] = None,
    writer_notes: Optional[str] = None,
    created_by: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> str:
    """Insert a `runs` row + its frozen `client_context_snapshots` row.

    Returns the new run id. Does NOT enforce the API concurrency cap or
    dispatch orchestration — callers own pacing + dispatch (the router uses
    BackgroundTasks; Fanout drives `orchestrate_run` synchronously).

    `source_ref` (optional) makes creation IDEMPOTENT per work-item: an
    externally-driven caller (a content-batch item, a fanout scheduled run) that
    re-enters after a redeploy/reap passes the same key, and any run for that key
    still in progress (or already complete) is returned instead of a duplicate
    being created. Only a terminal failed/cancelled run is superseded (a
    transient-retry attempt). Interactive callers omit it (always create).
    """
    supabase = get_supabase()
    client_id = str(client["id"])

    if source_ref:
        existing = find_run_by_source_ref(source_ref)
        if existing and existing.get("status") not in _ADOPTABLE_STATUSES_EXCLUDED:
            # Adopt the in-progress/complete run — its snapshot already exists.
            logger.info(
                "run_dispatch.adopted_existing_run",
                extra={"run_id": existing["id"], "source_ref": source_ref,
                       "status": existing.get("status")},
            )
            return existing["id"]

    run_result = supabase.table("runs").insert(
        {
            "client_id": client_id,
            "keyword": keyword,
            "intent_override": intent_override,
            "sie_outlier_mode": sie_outlier_mode,
            "sie_force_refresh": sie_force_refresh,
            "brief_force_refresh": brief_force_refresh,
            "content_type": content_type,
            "service": service or (keyword if content_type == "service_page" else None),
            "location": location,
            "location_code": location_code,
            "services": services or [],
            "reoptimize_source_url": reoptimize_source_url,
            "reoptimize_source_html": reoptimize_source_html,
            "writer_notes": writer_notes,
            "status": "queued",
            "created_by": created_by,
            "source_ref": source_ref,
        }
    ).execute()
    run_id = run_result.data[0]["id"]

    # Freeze the client context at run-creation time. brand_text/icp_text come
    # from the converged brand_voice / detected_icp (Option A), falling back to
    # the legacy free-text columns when those are unset.
    brand_text = brand_voice_service.resolve_brand_guide_text(client)
    icp_text = icp_service.resolve_icp_text(client)
    website_analysis = client.get("website_analysis")
    website_unavailable = (
        website_analysis is None or client.get("website_analysis_status") != "complete"
    )

    supabase.table("client_context_snapshots").insert(
        {
            "run_id": run_id,
            "client_id": client_id,
            "brand_guide_text": brand_text,
            "brand_guide_format": detect_format(brand_text, "text/plain"),
            "icp_text": icp_text,
            "icp_format": detect_format(icp_text, "text/plain"),
            "website_analysis": website_analysis,
            "website_analysis_unavailable": website_unavailable,
            # Reference page structures the writing modules mirror, frozen at
            # run-creation time alongside the rest of the client context.
            "page_structures": client.get("page_structures") or {},
        }
    ).execute()

    # The snapshot is frozen here, so a run created before a client's brand guide
    # is written produces an article with NO voice and NO ICP — and used to do so
    # silently (the Writer degrades to schema 1.9-degraded and completes happily).
    # That is how an article can fail a brand-voice audit it never had the guide
    # for. Say so, once per client, rather than discovering it in review.
    if not brand_text.strip() and not icp_text.strip():
        logger.warning(
            "run.no_brand_context",
            extra={"run_id": run_id, "client_id": client_id},
        )
        from services import notifications

        notifications.emit(
            client_id,
            kind="content_no_brand_context",
            title="Content generated without a brand voice or ICP",
            summary=(
                "This client has no brand voice guide and no ICP on file, so the "
                "article is being written without them. Add them on the client's "
                "Setup page — content created before they exist cannot follow them, "
                "and will not match a later brand-voice review."
            ),
            severity="warning",
            payload={"run_id": run_id},
            # One per client: the gap is a client-level fact, not a per-run event,
            # so a bulk batch must not fire a notification per article.
            dedupe_key=f"content_no_brand_context:{client_id}",
        )

    return run_id

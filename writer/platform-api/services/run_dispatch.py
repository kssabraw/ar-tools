"""Shared run creation — insert the run row + freeze the client_context snapshot.

Both the `POST /runs` router and Fanout's service_page job need to create a run
with an identical client-context snapshot (brand voice / ICP resolution +
format detection). Factoring it here keeps a single source of truth so the two
call sites can't drift.
"""

from __future__ import annotations

from typing import Optional

from db.supabase_client import get_supabase
from services import brand_voice_service, icp_service
from services.file_parser import detect_format


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
    writer_notes: Optional[str] = None,
    created_by: Optional[str] = None,
) -> str:
    """Insert a `runs` row + its frozen `client_context_snapshots` row.

    Returns the new run id. Does NOT enforce the API concurrency cap or
    dispatch orchestration — callers own pacing + dispatch (the router uses
    BackgroundTasks; Fanout drives `orchestrate_run` synchronously).
    """
    supabase = get_supabase()
    client_id = str(client["id"])

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
            "writer_notes": writer_notes,
            "status": "queued",
            "created_by": created_by,
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

    return run_id

"""Clients CRUD router."""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth, require_staff
from models.clients import (
    ClientCreateRequest,
    ClientDetail,
    ClientListItem,
    ClientUpdateRequest,
    PageStructureUrls,
)
from services import brand_voice_service, github_infer, icp_service, rank_location
from services.file_parser import detect_format
from services.gbp_service import get_business_details, resolve_business, search_businesses
from services.page_structure_scraper import PAGE_TYPES

logger = logging.getLogger(__name__)

router = APIRouter(tags=["clients"])


def _to_client_detail(row: dict) -> ClientDetail:
    """Build a ClientDetail, replacing the secret WP app password with a boolean
    so it never leaves the backend."""
    safe = dict(row)
    safe["wordpress_app_password_set"] = bool(safe.pop("wordpress_app_password", None))
    return ClientDetail(**safe)


def _enqueue_website_scrape(client_id: str, website_url: str) -> None:
    supabase = get_supabase()
    supabase.table("async_jobs").insert(
        {
            "job_type": "website_scrape",
            "entity_id": client_id,
            "payload": {"website_url": website_url, "client_id": client_id},
        }
    ).execute()


def _enqueue_auto_brand_voice_icp(client: dict, user_id: str) -> None:
    """Auto-generate a new client's brand voice + ICP as background jobs (best-
    effort). Skipped when disabled, or when there's nothing to analyze (no
    website and no GBP). The scans never override user-authored structured
    assets — a freeform brand guide / ICP typed at creation is preserved and
    merely enriched. See `brand_voice_service.run_brand_voice_scan_job` /
    `icp_service.run_icp_scan_job`."""
    if not settings.auto_generate_brand_voice_icp:
        return
    if not (client.get("website_url") or client.get("gbp")):
        logger.info(
            "client_auto_assets_skipped_no_source", extra={"client_id": client["id"]}
        )
        return
    supabase = get_supabase()
    rows = [
        {
            "job_type": job_type,
            "entity_id": client["id"],
            "payload": {"client_id": client["id"], "user_id": user_id},
        }
        for job_type in ("brand_voice_scan", "icp_scan")
    ]
    supabase.table("async_jobs").insert(rows).execute()
    logger.info("client_auto_assets_enqueued", extra={"client_id": client["id"]})


def _enqueue_page_structure_scrape(client_id: str, page_type: str, url: str) -> None:
    supabase = get_supabase()
    supabase.table("async_jobs").insert(
        {
            "job_type": "page_structure_scrape",
            "entity_id": client_id,
            "payload": {"client_id": client_id, "page_type": page_type, "url": url},
        }
    ).execute()


def _sync_page_structures(
    existing: dict, urls: Optional[PageStructureUrls]
) -> tuple[dict, list[tuple[str, str]]]:
    """Diff submitted reference URLs against the stored structures.

    Returns (merged_structures, to_enqueue) where to_enqueue is the list of
    (page_type, url) whose page must be (re)scraped. Behavior per page type:
      - new/changed URL  → mark pending + clear stale analysis + enqueue scrape
      - unchanged URL    → keep the stored entry (don't re-scrape)
      - cleared (empty)  → drop the entry entirely
    A None `urls` (field omitted) leaves the structures untouched.
    """
    merged = dict(existing or {})
    to_enqueue: list[tuple[str, str]] = []
    if urls is None:
        return merged, to_enqueue

    submitted = urls.model_dump()
    for page_type in PAGE_TYPES:
        new_url = (submitted.get(page_type) or "").strip()
        current = merged.get(page_type) or {}
        current_url = (current.get("url") or "").strip()
        if not new_url:
            merged.pop(page_type, None)
            continue
        if new_url == current_url and current.get("status") == "complete":
            continue  # unchanged + already analyzed — leave as-is
        merged[page_type] = {
            "url": new_url,
            "status": "pending",
            "error": None,
            "analysis": None,
            "analyzed_at": None,
        }
        to_enqueue.append((page_type, new_url))
    return merged, to_enqueue


def _resolve_file_fields(
    supabase,
    source_type: str,
    text: str,
    file_id: Optional[UUID],
    user_id: str,
) -> tuple[str, Optional[str], Optional[str]]:
    """Return (resolved_text, file_path, original_filename) for brand_guide or icp."""
    if source_type == "text":
        return text or "", None, None

    if not file_id:
        raise HTTPException(
            status_code=422,
            detail="validation_error: file_id is required when source_type=file",
        )
    # File was already uploaded and parsed; text is passed by the client
    # (the upload response returned parsed_text which the frontend stored in form state)
    return text or "", f"files/{user_id}/{file_id}", None


@router.get("/clients", response_model=list[ClientListItem])
async def list_clients(
    archived: bool = Query(False),
    auth: dict = Depends(require_auth),
) -> list[ClientListItem]:
    supabase = get_supabase()
    result = (
        supabase.table("clients")
        .select("id, name, website_url, website_analysis_status, archived, created_at, logo_url")
        .eq("archived", archived)
        .order("name")
        .execute()
    )
    return [ClientListItem(**row) for row in (result.data or [])]


@router.get("/clients/gbp/search")
async def gbp_search(
    q: str = Query(...),
    auth: dict = Depends(require_auth),
) -> dict:
    suggestions = await search_businesses(q)
    return {"suggestions": suggestions}


@router.get("/clients/gbp/details")
async def gbp_details(
    place_id: str = Query(...),
    auth: dict = Depends(require_auth),
) -> dict:
    return await get_business_details(place_id)


@router.get("/clients/gbp/resolve")
async def gbp_resolve(
    input: str = Query(..., min_length=1),
    auth: dict = Depends(require_auth),
) -> dict:
    """Resolve a pasted GBP URL, share link, place_id, CID, or free-text
    query into a full profile."""
    return await resolve_business(input)


@router.get("/clients/{client_id}", response_model=ClientDetail)
async def get_client(
    client_id: UUID,
    auth: dict = Depends(require_auth),
) -> ClientDetail:
    supabase = get_supabase()
    result = (
        supabase.table("clients")
        .select("*")
        .eq("id", str(client_id))
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    return _to_client_detail(result.data)


@router.post("/clients", response_model=ClientDetail, status_code=201)
async def create_client(
    body: ClientCreateRequest,
    auth: dict = Depends(require_staff),
) -> ClientDetail:
    supabase = get_supabase()

    # Check for duplicate name
    existing = (
        supabase.table("clients")
        .select("id")
        .eq("name", body.name)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="client_name_taken")

    brand_text, brand_file_path, brand_filename = _resolve_file_fields(
        supabase,
        body.brand_guide_source_type,
        body.brand_guide_text,
        body.brand_guide_file_id,
        auth["user_id"],
    )
    icp_text, icp_file_path, icp_filename = _resolve_file_fields(
        supabase,
        body.icp_source_type,
        body.icp_text,
        body.icp_file_id,
        auth["user_id"],
    )

    row = {
        "name": body.name,
        "website_url": body.website_url,
        "brand_guide_source_type": body.brand_guide_source_type,
        "brand_guide_text": brand_text,
        "brand_guide_file_path": brand_file_path,
        "icp_source_type": body.icp_source_type,
        "icp_text": icp_text,
        "icp_file_path": icp_file_path,
        "website_analysis_status": "pending",
        "google_drive_folder_id": body.google_drive_folder_id,
        "github_repo": body.github_repo,
        "github_branch": body.github_branch,
        "github_content_path": body.github_content_path,
        "wordpress_site_url": body.wordpress_site_url,
        "wordpress_username": body.wordpress_username,
        "wordpress_app_password": body.wordpress_app_password or None,
        "logo_url": body.logo_url,
        "gsc_property": body.gsc_property,
        "business_location": body.business_location,
        "created_by": auth["user_id"],
    }
    if body.gbp_place_id is not None:
        row["gbp_place_id"] = body.gbp_place_id
    if body.gbp is not None:
        row["gbp"] = body.gbp.model_dump()
    if body.target_cities is not None:
        row["target_cities"] = body.target_cities
    if body.drive_folders is not None:
        row["drive_folders"] = body.drive_folders
    if body.github_content_paths is not None:
        row["github_content_paths"] = body.github_content_paths
    # Recipe Engine budget inputs (§1–§2).
    if body.retainer_monthly is not None:
        row["retainer_monthly"] = body.retainer_monthly
    if body.is_sab is not None:
        row["is_sab"] = body.is_sab
    if body.client_type is not None:
        row["client_type"] = body.client_type
    if body.strategist_weekday is not None:
        row["strategist_weekday"] = body.strategist_weekday
    # Reference page structures: seed the pending entries so the row reflects the
    # configured URLs immediately; the scrape jobs are enqueued after insert.
    page_structures, ps_to_enqueue = _sync_page_structures({}, body.page_structure_urls)
    if page_structures:
        row["page_structures"] = page_structures
    # Converge the legacy free-text brand guide into the canonical brand_voice
    # (Option A) so a brand-new client's guide is usable by both consumers.
    brand_voice = brand_voice_service.merge_raw_text(None, brand_text)
    if brand_voice is not None:
        row["brand_voice"] = brand_voice
    detected_icp = icp_service.merge_raw_text(None, icp_text)
    if detected_icp is not None:
        row["detected_icp"] = detected_icp
    result = supabase.table("clients").insert(row).execute()
    client = result.data[0]

    if body.website_url:
        _enqueue_website_scrape(client["id"], body.website_url)
    # Discover the existing-site URL/slug conventions when a repo is configured
    # (SOP "site always wins" — populates github_inferred_patterns).
    if body.github_repo:
        github_infer.enqueue_github_infer(client["id"])
    for page_type, url in ps_to_enqueue:
        _enqueue_page_structure_scrape(client["id"], page_type, url)
    # Auto-generate the brand voice + ICP so they exist without a manual scan.
    _enqueue_auto_brand_voice_icp(client, auth["user_id"])
    # Auto-track the client's own domain for backlink monitoring (best-effort;
    # the daily scheduler pass also backfills, so a failure here self-heals).
    try:
        from services import backlink_explorer

        backlink_explorer.ensure_client_domain_tracked(client["id"], client.get("website_url"))
    except Exception as exc:
        logger.warning("client_backlink_autotrack_failed", extra={"client_id": client["id"], "error": str(exc)})
    # Auto-derive the rank-tracking location from the GBP (best-effort, async).
    if body.gbp is not None:
        rank_location.enqueue_location_derive(client["id"])
    # Auto-provision the client's deliverables sheet (Drive copy of the master
    # template — PRD §5.5). Self-gated + best-effort; no-ops until the module
    # flag + template/folder ids are configured.
    try:
        from services import deliverables_sheet

        deliverables_sheet.enqueue_provision(client["id"])
    except Exception as exc:
        logger.warning("client_deliverables_provision_failed", extra={"client_id": client["id"], "error": str(exc)})
    logger.info("client_created", extra={"client_id": client["id"], "user_id": auth["user_id"]})

    return _to_client_detail(client)


@router.patch("/clients/{client_id}", response_model=ClientDetail)
async def update_client(
    client_id: UUID,
    body: ClientUpdateRequest,
    auth: dict = Depends(require_staff),
) -> ClientDetail:
    supabase = get_supabase()

    existing_result = (
        supabase.table("clients").select("*").eq("id", str(client_id)).single().execute()
    )
    if not existing_result.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    existing = existing_result.data

    updates: dict = {"updated_at": "now()"}
    website_changed = False

    if body.name is not None:
        # Check duplicate name (excluding self)
        dup = (
            supabase.table("clients")
            .select("id")
            .eq("name", body.name)
            .neq("id", str(client_id))
            .execute()
        )
        if dup.data:
            raise HTTPException(status_code=409, detail="client_name_taken")
        updates["name"] = body.name

    if body.website_url is not None and body.website_url != existing.get("website_url"):
        updates["website_url"] = body.website_url
        updates["website_analysis_status"] = "pending"
        updates["website_analysis"] = None
        updates["website_analysis_error"] = None
        website_changed = True

    if body.brand_guide_source_type is not None:
        updates["brand_guide_source_type"] = body.brand_guide_source_type
    if body.brand_guide_text is not None:
        updates["brand_guide_text"] = body.brand_guide_text
        # Keep the canonical brand_voice in sync only when the guide actually
        # changed, so unrelated client edits don't flip an app voice to 'user'.
        if body.brand_guide_text != existing.get("brand_guide_text"):
            updates["brand_voice"] = brand_voice_service.merge_raw_text(
                existing.get("brand_voice"), body.brand_guide_text
            )
    if body.icp_source_type is not None:
        updates["icp_source_type"] = body.icp_source_type
    if body.icp_text is not None:
        updates["icp_text"] = body.icp_text
        # Keep the canonical detected_icp in sync only when the write-up changed.
        if body.icp_text != existing.get("icp_text"):
            updates["detected_icp"] = icp_service.merge_raw_text(
                existing.get("detected_icp"), body.icp_text
            )
    if body.google_drive_folder_id is not None:
        updates["google_drive_folder_id"] = body.google_drive_folder_id
    if body.drive_folders is not None:
        updates["drive_folders"] = body.drive_folders
    if body.github_repo is not None:
        updates["github_repo"] = body.github_repo
    if body.github_branch is not None:
        updates["github_branch"] = body.github_branch
    if body.github_content_path is not None:
        updates["github_content_path"] = body.github_content_path
    if body.github_content_paths is not None:
        updates["github_content_paths"] = body.github_content_paths
    if body.wordpress_site_url is not None:
        updates["wordpress_site_url"] = body.wordpress_site_url or None
    if body.wordpress_username is not None:
        updates["wordpress_username"] = body.wordpress_username or None
    # app_password: omitted (None) leaves the stored secret untouched; an empty
    # string clears it; a value replaces it.
    if body.wordpress_app_password is not None:
        updates["wordpress_app_password"] = body.wordpress_app_password or None
    if body.logo_url is not None:
        updates["logo_url"] = body.logo_url
    if body.gsc_property is not None:
        updates["gsc_property"] = body.gsc_property
    if body.business_location is not None:
        updates["business_location"] = body.business_location
    # Recipe Engine budget inputs (§1–§2).
    if body.retainer_monthly is not None:
        updates["retainer_monthly"] = body.retainer_monthly
    if body.is_sab is not None:
        updates["is_sab"] = body.is_sab
    if body.client_type is not None:
        updates["client_type"] = body.client_type
    # Explicit-set semantics: an explicit null clears the per-client review day
    # back to the global default (a plain `is not None` guard couldn't do that).
    if "strategist_weekday" in body.model_fields_set:
        updates["strategist_weekday"] = body.strategist_weekday
    if body.gbp_place_id is not None:
        updates["gbp_place_id"] = body.gbp_place_id
    if body.gbp is not None:
        updates["gbp"] = body.gbp.model_dump()
    if body.target_cities is not None:
        updates["target_cities"] = body.target_cities

    # Reference page structures: diff submitted URLs vs stored, enqueue changed.
    ps_to_enqueue: list[tuple[str, str]] = []
    if body.page_structure_urls is not None:
        merged_ps, ps_to_enqueue = _sync_page_structures(
            existing.get("page_structures") or {}, body.page_structure_urls
        )
        updates["page_structures"] = merged_ps

    result = supabase.table("clients").update(updates).eq("id", str(client_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="client_not_found")

    if website_changed:
        _enqueue_website_scrape(str(client_id), body.website_url)
    # Re-discover site conventions when the repo changes, or when the website
    # changes and a repo is already configured (sitemap-derived conventions).
    repo_changed = body.github_repo is not None and updates.get("github_repo") != existing.get("github_repo")
    if repo_changed or (website_changed and (updates.get("github_repo") or existing.get("github_repo"))):
        github_infer.enqueue_github_infer(str(client_id))
    for page_type, url in ps_to_enqueue:
        _enqueue_page_structure_scrape(str(client_id), page_type, url)
    # Re-derive the rank-tracking location only when the GBP actually changed
    # (the job still skips manually-set clients and only re-pulls on a change).
    if body.gbp is not None and updates.get("gbp") != existing.get("gbp"):
        rank_location.enqueue_location_derive(str(client_id))

    logger.info("client_updated", extra={"client_id": str(client_id), "user_id": auth["user_id"]})
    return _to_client_detail(result.data[0])


@router.post("/clients/{client_id}/archive", response_model=dict)
async def archive_client(
    client_id: UUID,
    auth: dict = Depends(require_staff),
) -> dict:
    supabase = get_supabase()
    result = (
        supabase.table("clients")
        .update({"archived": True, "updated_at": "now()"})
        .eq("id", str(client_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    logger.info("client_archived", extra={"client_id": str(client_id), "user_id": auth["user_id"]})
    return {"id": str(client_id), "archived": True}


@router.post("/clients/{client_id}/reanalyze", response_model=dict, status_code=202)
async def reanalyze_client(
    client_id: UUID,
    auth: dict = Depends(require_staff),
) -> dict:
    supabase = get_supabase()
    result = (
        supabase.table("clients")
        .select("website_url")
        .eq("id", str(client_id))
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="client_not_found")

    supabase.table("clients").update(
        {"website_analysis_status": "pending", "website_analysis_error": None}
    ).eq("id", str(client_id)).execute()

    job_result = supabase.table("async_jobs").insert(
        {
            "job_type": "website_scrape",
            "entity_id": str(client_id),
            "payload": {
                "website_url": result.data["website_url"],
                "client_id": str(client_id),
            },
        }
    ).execute()

    job_id = (job_result.data or [{}])[0].get("id", "")
    return {"job_id": job_id}


@router.post("/clients/{client_id}/infer-github-patterns", response_model=dict, status_code=202)
async def infer_github_patterns(
    client_id: UUID,
    auth: dict = Depends(require_staff),
) -> dict:
    """Re-discover the client's existing-site URL/slug conventions (repo Git tree
    + sitemap → github_inferred_patterns). Requires a configured GitHub repo or a
    website to infer from."""
    supabase = get_supabase()
    result = (
        supabase.table("clients")
        .select("github_repo, website_url")
        .eq("id", str(client_id))
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    if not (result.data.get("github_repo") or result.data.get("website_url")):
        raise HTTPException(status_code=422, detail="no_repo_or_website_to_infer")

    github_infer.enqueue_github_infer(str(client_id))
    return {"enqueued": True}


@router.post("/clients/{client_id}/page-structures/reanalyze", response_model=dict, status_code=202)
async def reanalyze_page_structures(
    client_id: UUID,
    page_type: Optional[str] = Query(None),
    auth: dict = Depends(require_staff),
) -> dict:
    """Re-scrape + re-analyze the client's stored reference page structure(s).

    Unlike create/update — which only (re)scrape a URL when it *changes* — this
    forces a fresh analysis of the already-stored URL(s), e.g. after the client's
    page itself was redesigned. Pass `page_type` to refresh one reference page;
    omit it to refresh all stored ones. Resets each target to `pending` and
    enqueues a `page_structure_scrape` job.
    """
    if page_type is not None and page_type not in PAGE_TYPES:
        raise HTTPException(status_code=422, detail="invalid_page_type")

    supabase = get_supabase()
    result = (
        supabase.table("clients")
        .select("page_structures")
        .eq("id", str(client_id))
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="client_not_found")

    structures = result.data.get("page_structures") or {}
    targets = [page_type] if page_type else list(PAGE_TYPES)
    reanalyzed: list[str] = []
    for pt in targets:
        url = ((structures.get(pt) or {}).get("url") or "").strip()
        if not url:
            continue
        structures[pt] = {
            "url": url,
            "status": "pending",
            "error": None,
            "analysis": None,
            "analyzed_at": None,
        }
        reanalyzed.append(pt)

    if not reanalyzed:
        raise HTTPException(status_code=422, detail="no_reference_urls_to_reanalyze")

    supabase.table("clients").update(
        {"page_structures": structures, "updated_at": "now()"}
    ).eq("id", str(client_id)).execute()

    for pt in reanalyzed:
        _enqueue_page_structure_scrape(str(client_id), pt, structures[pt]["url"])

    logger.info(
        "client_page_structures_reanalyze",
        extra={"client_id": str(client_id), "user_id": auth["user_id"], "page_types": reanalyzed},
    )
    return {"reanalyzed": reanalyzed}

"""Clients CRUD router."""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from db.supabase_client import get_supabase
from middleware.auth import require_admin, require_auth
from models.clients import ClientCreateRequest, ClientDetail, ClientListItem, ClientUpdateRequest
from services.file_parser import detect_format

logger = logging.getLogger(__name__)

router = APIRouter(tags=["clients"])


def _enqueue_website_scrape(client_id: str, website_url: str) -> None:
    supabase = get_supabase()
    supabase.table("async_jobs").insert(
        {
            "job_type": "website_scrape",
            "entity_id": client_id,
            "payload": {"website_url": website_url, "client_id": client_id},
        }
    ).execute()


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
        .select("id, name, website_url, website_analysis_status, archived, created_at")
        .eq("archived", archived)
        .order("name")
        .execute()
    )
    return [ClientListItem(**row) for row in (result.data or [])]


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
    return ClientDetail(**result.data)


@router.post("/clients", response_model=ClientDetail, status_code=201)
async def create_client(
    body: ClientCreateRequest,
    auth: dict = Depends(require_admin),
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
        "created_by": auth["user_id"],
    }
    result = supabase.table("clients").insert(row).execute()
    client = result.data[0]

    _enqueue_website_scrape(client["id"], body.website_url)
    logger.info("client_created", extra={"client_id": client["id"], "user_id": auth["user_id"]})

    return ClientDetail(**client)


@router.patch("/clients/{client_id}", response_model=ClientDetail)
async def update_client(
    client_id: UUID,
    body: ClientUpdateRequest,
    auth: dict = Depends(require_admin),
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
    if body.icp_source_type is not None:
        updates["icp_source_type"] = body.icp_source_type
    if body.icp_text is not None:
        updates["icp_text"] = body.icp_text
    if body.google_drive_folder_id is not None:
        updates["google_drive_folder_id"] = body.google_drive_folder_id

    result = supabase.table("clients").update(updates).eq("id", str(client_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="client_not_found")

    if website_changed:
        _enqueue_website_scrape(str(client_id), body.website_url)

    logger.info("client_updated", extra={"client_id": str(client_id), "user_id": auth["user_id"]})
    return ClientDetail(**result.data[0])


@router.post("/clients/{client_id}/archive", response_model=dict)
async def archive_client(
    client_id: UUID,
    auth: dict = Depends(require_admin),
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
    auth: dict = Depends(require_admin),
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

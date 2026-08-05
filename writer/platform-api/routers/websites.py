"""Website Builder — REST surface.

Ships dark behind `website_builder_enabled`: while the flag is off every route
returns 503 so a half-built module can never create a repo by accident.

Creating a site is deliberately two calls — POST to record the intent, then
POST .../provision to act on it. Provisioning mints a real GitHub repo and a
real Cloudflare project, and those are not things a stray form submission
should do as a side effect of typing a name.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth, require_staff
from services import website_provision
from services.freeze import assert_not_frozen

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websites"])

_SITE_TYPES = {"local_business", "informational"}


def _enabled() -> None:
    if not settings.website_builder_enabled:
        raise HTTPException(status_code=503, detail="website_builder_not_enabled")


class WebsiteCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    site_type: str
    slug: Optional[str] = None
    config: dict = Field(default_factory=dict)


class WebsiteUpdateRequest(BaseModel):
    name: Optional[str] = None
    custom_domain: Optional[str] = None
    config: Optional[dict] = None


@router.get("/clients/{client_id}/websites")
async def list_websites(client_id: str, auth: dict = Depends(require_auth)) -> dict:
    _enabled()
    rows = (
        get_supabase()
        .table("websites")
        .select("*")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .execute()
    ).data or []
    return {"websites": rows}


@router.post("/clients/{client_id}/websites")
async def create_website(
    client_id: str,
    body: WebsiteCreateRequest,
    auth: dict = Depends(require_staff),
) -> dict:
    _enabled()
    if body.site_type not in _SITE_TYPES:
        raise HTTPException(status_code=400, detail="invalid_site_type")
    # A site is content output, so it joins the freeze gate like every other
    # generator (plan §8).
    assert_not_frozen(client_id)

    slug = website_provision.slugify(body.slug or body.name)
    try:
        row = (
            get_supabase()
            .table("websites")
            .insert(
                {
                    "client_id": client_id,
                    "name": body.name,
                    "slug": slug,
                    "site_type": body.site_type,
                    "config": body.config or {},
                }
            )
            .execute()
        ).data
    except Exception as exc:
        # The (client_id, slug) unique index is the guard against a double
        # submit quietly creating two repos for the same site.
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="website_slug_exists") from exc
        logger.error("websites.create_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error") from exc
    return {"website": row[0] if row else None}


@router.get("/websites/{website_id}")
async def get_website(website_id: str, auth: dict = Depends(require_auth)) -> dict:
    _enabled()
    rows = (
        get_supabase().table("websites").select("*").eq("id", website_id).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="website_not_found")
    pages = (
        get_supabase()
        .table("website_pages")
        .select("*")
        .eq("website_id", website_id)
        .order("route")
        .execute()
    ).data or []
    deploys = (
        get_supabase()
        .table("website_deploys")
        .select("*")
        .eq("website_id", website_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    ).data or []
    return {"website": rows[0], "pages": pages, "deploys": deploys}


@router.patch("/websites/{website_id}")
async def update_website(
    website_id: str, body: WebsiteUpdateRequest, auth: dict = Depends(require_staff)
) -> dict:
    _enabled()
    patch = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not patch:
        return {"updated": False}
    rows = (
        get_supabase().table("websites").update(patch).eq("id", website_id).execute()
    ).data
    return {"website": rows[0] if rows else None}


@router.post("/websites/{website_id}/provision")
async def provision_website(website_id: str, auth: dict = Depends(require_staff)) -> dict:
    """Enqueue provisioning. Safe to call again after a failure — the job is a
    resumable step machine, so a retry picks up where it stopped rather than
    re-creating the repo."""
    _enabled()
    rows = (
        get_supabase()
        .table("websites")
        .select("id, client_id, status")
        .eq("id", website_id)
        .limit(1)
        .execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="website_not_found")
    assert_not_frozen(rows[0]["client_id"])

    existing = (
        get_supabase()
        .table("async_jobs")
        .select("id")
        .eq("job_type", "website_provision")
        .eq("entity_id", website_id)
        .in_("status", ["pending", "running"])
        .execute()
    ).data or []
    if existing:
        return {"queued": False, "reason": "already_queued", "job_id": existing[0]["id"]}

    job = (
        get_supabase()
        .table("async_jobs")
        .insert(
            {
                "job_type": "website_provision",
                "entity_id": website_id,
                "payload": {"website_id": website_id},
            }
        )
        .execute()
    ).data
    return {"queued": True, "job_id": job[0]["id"] if job else None}


@router.get("/websites/{website_id}/deploys")
async def list_deploys(website_id: str, auth: dict = Depends(require_auth)) -> dict:
    _enabled()
    rows = (
        get_supabase()
        .table("website_deploys")
        .select("*")
        .eq("website_id", website_id)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    ).data or []
    return {"deploys": rows}

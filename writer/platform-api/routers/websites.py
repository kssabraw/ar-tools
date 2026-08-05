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
from services import (
    website_deploy,
    website_generate,
    website_plan_store,
    website_provision,
    website_publish,
)
from services.freeze import assert_not_frozen

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websites"])

_SITE_TYPES = {"local_business", "informational", "lead_gen"}


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


class PlanBuildRequest(BaseModel):
    """The catalog a plan is built from.

    Held on the site until the client-level Business Facts store (PRD §4.10)
    exists; the shape is the one that store will feed. Nothing here is derived
    from GBP categories — a category is a taxonomy label and a service is a
    billable job, and wiring one into the other silently produces the wrong page
    inventory.
    """

    catalog: list[dict] = Field(default_factory=list)
    cities: list[dict] = Field(default_factory=list)


class PlanApproveRequest(BaseModel):
    # A property-vs-client cell overlap is admin-overridable and nothing else
    # is; the blocking planning errors (reserved slugs, duplicate paths) are
    # fixed by editing the catalog, not by waving them through.
    override_conflicts: bool = False


class PageSelectionRequest(BaseModel):
    """Explicit selection, never 'everything'.

    Both generation and publishing cost something — money for the first, a live
    change for the second — so the count is visible before dispatch by
    construction rather than by a UI convention.
    """

    page_ids: list[str] = Field(default_factory=list)


class PublishRequest(PageSelectionRequest):
    # Forces past an overridable gate only. A facts-consistency failure is not
    # overridable at any role.
    force: bool = False


def _load_site(website_id: str) -> dict:
    rows = (
        get_supabase().table("websites").select("*").eq("id", website_id).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="website_not_found")
    return rows[0]


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


# --------------------------------------------------------------------------
# Site plan
# --------------------------------------------------------------------------


@router.get("/websites/{website_id}/plan")
async def get_plan(website_id: str, auth: dict = Depends(require_auth)) -> dict:
    """The stored plan rows plus a freshly recomputed set of issues.

    The issues are re-derived rather than read from a cache written at build
    time, so the plan tab and the approval gate can never disagree about whether
    the plan is blocked.
    """
    _enabled()
    website = _load_site(website_id)
    plan = website_plan_store.recompute(website)
    return {
        "pages": website_plan_store.stored(website_id),
        "plan": plan,
        "approved": website_plan_store.is_approved(website),
        "approval": (website.get("config") or {}).get("plan") or {},
        "conflicts": [
            {"kind": i.kind, "blocking": i.blocking, "detail": i.detail}
            for i in website_plan_store.conflict_issues(website)
        ],
    }


@router.post("/websites/{website_id}/plan")
async def build_plan(
    website_id: str, body: PlanBuildRequest, auth: dict = Depends(require_staff)
) -> dict:
    """Build (or rebuild) the site plan and persist it as reviewable rows."""
    _enabled()
    website = _load_site(website_id)
    assert_not_frozen(website["client_id"])
    result = website_plan_store.build(
        website, catalog=body.catalog, cities=body.cities
    )
    return {"plan": result, "pages": website_plan_store.stored(website_id)}


@router.post("/websites/{website_id}/plan/approve")
async def approve_plan(
    website_id: str, body: PlanApproveRequest, auth: dict = Depends(require_staff)
) -> dict:
    """Approve the plan. Refused while any blocking issue stands.

    Blocking issues are planning errors the reference says to surface rather
    than silently resolve — a reserved-slug collision or two entries claiming
    one path. A published slug is immutable, so the cost of approving a wrong
    URL is a permanent redirect rather than an edit.
    """
    _enabled()
    website = _load_site(website_id)
    blockers = website_plan_store.approval_blockers(website)

    conflicts = [b for b in blockers if b["kind"] == "portfolio_conflict"]
    if conflicts and body.override_conflicts:
        if auth.get("role") != "admin":
            raise HTTPException(status_code=403, detail="requires_admin")
        blockers = [b for b in blockers if b["kind"] != "portfolio_conflict"]

    if blockers:
        raise HTTPException(
            status_code=409,
            detail={"error": "plan_blocked", "issues": blockers},
        )

    approval = website_plan_store.approve(website, actor=auth.get("user_id") or "")
    return {"approved": True, "approval": approval}


# --------------------------------------------------------------------------
# Generate and publish
# --------------------------------------------------------------------------


@router.post("/websites/{website_id}/generate")
async def generate_pages(
    website_id: str, body: PageSelectionRequest, auth: dict = Depends(require_auth)
) -> dict:
    """Enqueue body-copy generation for the selected planned pages.

    VAs may generate — that is their work, and it is idempotent. What they may
    not do is publish (PRD §2): publish here means the public internet, not a
    reviewable Doc.
    """
    _enabled()
    website = _load_site(website_id)
    assert_not_frozen(website["client_id"])

    if not website_plan_store.is_approved(website):
        raise HTTPException(status_code=409, detail="plan_not_approved")

    client = (
        get_supabase()
        .table("clients")
        .select("*")
        .eq("id", website["client_id"])
        .limit(1)
        .execute()
    ).data
    if not client:
        raise HTTPException(status_code=404, detail="client_not_found")
    if not website_generate.has_brand_context(client[0]):
        # Upstream of the -degraded run rather than downstream of it: the same
        # rule §5.4 applies at publish, moved to where it prevents the spend.
        raise HTTPException(status_code=409, detail="content_no_brand_context")

    page_ids = website_plan_store.coerce_ids(
        website_plan_store.stored(website_id), body.page_ids
    )
    if not page_ids:
        raise HTTPException(status_code=400, detail="no_pages_selected")

    job_ids = website_generate.enqueue_generation(
        website_id=website_id,
        client_id=website["client_id"],
        page_ids=page_ids,
        user_id=auth.get("user_id") or "",
    )
    return {"queued": len(job_ids), "job_ids": job_ids}


@router.post("/websites/{website_id}/publish")
async def publish_pages(
    website_id: str, body: PublishRequest, auth: dict = Depends(require_staff)
) -> dict:
    """Enqueue a commit for each selected page. staff+ only."""
    _enabled()
    website = _load_site(website_id)
    assert_not_frozen(website["client_id"])
    if not website.get("github_repo"):
        raise HTTPException(status_code=409, detail="website_not_provisioned")
    if not website_plan_store.is_approved(website):
        raise HTTPException(status_code=409, detail="plan_not_approved")

    page_ids = website_plan_store.coerce_ids(
        website_plan_store.stored(website_id), body.page_ids
    )
    if not page_ids:
        raise HTTPException(status_code=400, detail="no_pages_selected")

    job_ids = website_publish.enqueue_publish(
        website_id=website_id,
        client_id=website["client_id"],
        page_ids=page_ids,
        user_id=auth.get("user_id") or "",
        force=body.force,
    )
    return {"queued": len(job_ids), "job_ids": job_ids}


@router.post("/websites/{website_id}/pages/{page_id}/retry")
async def retry_page(
    website_id: str, page_id: str, auth: dict = Depends(require_auth)
) -> dict:
    """Re-run a publish that failed. Open to VAs — retrying is idempotent.

    Only a *failed* row is retryable: a page held by a quality gate sits at
    draft and needs the gate cleared, not another attempt, and a draft page
    reaching publish through this route would be a way around the staff bar.
    """
    _enabled()
    website = _load_site(website_id)
    assert_not_frozen(website["client_id"])
    rows = (
        get_supabase()
        .table("website_pages")
        .select("id, status, website_id")
        .eq("id", page_id)
        .limit(1)
        .execute()
    ).data
    if not rows or rows[0]["website_id"] != website_id:
        raise HTTPException(status_code=404, detail="website_page_not_found")
    if rows[0]["status"] != "failed":
        raise HTTPException(status_code=409, detail="page_not_failed")

    job_ids = website_publish.enqueue_publish(
        website_id=website_id,
        client_id=website["client_id"],
        page_ids=[page_id],
        user_id=auth.get("user_id") or "",
    )
    return {"queued": len(job_ids), "job_ids": job_ids}


# --------------------------------------------------------------------------
# Deploys
# --------------------------------------------------------------------------


@router.post("/websites/{website_id}/deploys/recheck")
async def recheck_deploys(website_id: str, auth: dict = Depends(require_auth)) -> dict:
    """The 'Re-check now' action behind an unknown deploy status.

    A deploy whose run we lost sight of is reported as unknown rather than
    failed (PRD §6.3), because the site is very likely serving fine — this is
    how somebody asks again.
    """
    _enabled()
    _load_site(website_id)
    job_id = website_deploy.enqueue_deploy_poll(website_id)
    return {"queued": bool(job_id), "job_id": job_id}


@router.post("/websites/{website_id}/jobs/status")
async def jobs_status(
    website_id: str, body: dict, auth: dict = Depends(require_auth)
) -> dict:
    """Batch poll for a generate/publish run, so the UI can be left mid-batch."""
    _enabled()
    job_ids = [j for j in (body.get("job_ids") or []) if j][:200]
    if not job_ids:
        return {"jobs": []}
    rows = (
        get_supabase()
        .table("async_jobs")
        .select("id, status, error, result, entity_id")
        .in_("id", job_ids)
        .execute()
    ).data or []
    return {
        "jobs": [
            {k: r.get(k) for k in ("id", "status", "error", "result")}
            for r in rows
            if r.get("entity_id") == website_id
        ]
    }

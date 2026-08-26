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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth, require_staff
from services import (
    website_content_plan,
    website_deploy,
    website_generate,
    website_plan_store,
    website_provision,
    website_publish,
    website_settings,
    website_theme,
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
    # Scale gates are "blocking until acknowledged" (PRD §4.3, §8.D): a matrix
    # over 200 pages or an index over the ratified 25-link budget is a judgement
    # about size, so it needs a named human decision rather than a wall. Names
    # the issue kinds being signed off — 'matrix_signoff', 'link_budget'.
    acknowledge: list[str] = Field(default_factory=list)
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


class FactsUpdateRequest(BaseModel):
    """A partial edit of a site's business facts.

    Every group is optional and only sent groups are applied (the router uses
    `exclude_unset`), so the tab can save one section without disturbing the
    rest. Within `business`, a present-but-empty field clears it back to GBP.
    """

    business: Optional[dict] = None
    tagline: Optional[str] = None
    description: Optional[str] = None
    forms: Optional[dict] = None
    analytics: Optional[dict] = None


class ThemeSelectRequest(BaseModel):
    theme_id: str
    # An unapproved theme can still be applied deliberately — that is how you
    # look at one on a real site before signing it off — but never by default.
    force: bool = False


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


@router.get("/websites/status")
async def website_builder_status(auth: dict = Depends(require_auth)) -> dict:
    """Whether the module is switched on.

    Deliberately NOT behind `_enabled()`: the frontend has to be able to ask
    while the answer is "no" so it can hide the workspace card and 404 the
    route. Same pattern as /pace/status and /qa/status — a dead card that 503s
    on click is worse than no card.
    """
    return {"enabled": bool(settings.website_builder_enabled)}


@router.get("/websites")
async def list_all_websites(
    include_deleted: bool = False, auth: dict = Depends(require_staff)
) -> dict:
    """The fleet: every site across every client (PRD §6.1).

    This exists because the module's unit of management is the fleet, not the
    client — "what's live", "what failed to deploy last night", "how many
    shipped this month" are unanswerable from inside one client's workspace,
    and §7's throughput metrics are read straight off this screen.

    Deliberately read-only. The index links into each site's workspace card,
    which is where work happens; the only actions here are on the Trash.
    """
    _enabled()
    supabase = get_supabase()
    query = supabase.table("websites").select("*").order("created_at", desc=True)
    query = (
        query.not_.is_("deleted_at", "null") if include_deleted
        else query.is_("deleted_at", "null")
    )
    sites = query.limit(200).execute().data or []

    names: dict[str, str] = {}
    kinds: dict[str, str] = {}
    latest: dict[str, dict] = {}
    if sites:
        client_rows = (
            supabase.table("clients")
            .select("id, name, kind")
            .in_("id", list({s["client_id"] for s in sites}))
            .execute()
        ).data or []
        names = {c["id"]: c.get("name") or "" for c in client_rows}
        kinds = {c["id"]: c.get("kind") or "client" for c in client_rows}

        # One read for every site's newest deploy rather than N queries: the
        # fleet view is a dashboard, and it should stay one round trip.
        deploys = (
            supabase.table("website_deploys")
            .select("website_id, status, created_at, url")
            .in_("website_id", [s["id"] for s in sites])
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        ).data or []
        for row in deploys:
            latest.setdefault(row["website_id"], row)

    return {
        "websites": [
            {
                **site,
                "client_name": names.get(site["client_id"], ""),
                "client_kind": kinds.get(site["client_id"], "client"),
                "last_deploy": latest.get(site["id"]),
            }
            for site in sites
        ]
    }


@router.delete("/websites/{website_id}")
async def delete_website(website_id: str, auth: dict = Depends(require_staff)) -> dict:
    """Soft-delete: removes the site from the module's lists and nothing else.

    PRD §3.2 — the repo, the Worker, the domain and the live site are untouched.
    That follows from the module's first principle: the repo IS the site, so
    deleting our *record* must not destroy the artifact somebody was handed.
    Purging the external resources is a separate, admin-only act and is not
    built.
    """
    _enabled()
    rows = (
        get_supabase()
        .table("websites")
        .update({"deleted_at": "now()", "updated_at": "now()"})
        .eq("id", website_id)
        .execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="website_not_found")
    logger.info("websites.soft_deleted", extra={"website_id": website_id})
    return {"deleted": True}


@router.post("/websites/{website_id}/restore")
async def restore_website(website_id: str, auth: dict = Depends(require_staff)) -> dict:
    """Clear the soft-delete flag. Nothing is re-provisioned — nothing was undone."""
    _enabled()
    rows = (
        get_supabase()
        .table("websites")
        .update({"deleted_at": None, "updated_at": "now()"})
        .eq("id", website_id)
        .execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="website_not_found")
    return {"restored": True}


@router.get("/clients/{client_id}/websites")
async def list_websites(client_id: str, auth: dict = Depends(require_auth)) -> dict:
    _enabled()
    rows = (
        get_supabase()
        .table("websites")
        .select("*")
        .eq("client_id", client_id)
        .is_("deleted_at", "null")
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


@router.get("/websites/{website_id}/facts")
async def get_website_facts(website_id: str, auth: dict = Depends(require_auth)) -> dict:
    """The site's business facts as it would actually use them (GBP-filled),
    each labelled `user`/`gbp`/unset so the editor shows what came from where."""
    _enabled()
    try:
        # get_facts loads the site itself and raises SettingsError when it is
        # gone, so a separate existence check would only duplicate the read.
        return website_settings.get_facts(website_id)
    except website_settings.SettingsError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/websites/{website_id}/facts")
async def update_website_facts(
    website_id: str, body: FactsUpdateRequest, auth: dict = Depends(require_staff)
) -> dict:
    """Save edited business facts. On a provisioned site this re-commits
    site.config.json and records a `config` deploy so the live site updates;
    on an unprovisioned one the facts wait for the provision commit.

    Not freeze-gated: correcting a phone number is not content output, and a
    frozen client may well need its NAP fixed. Staff-gated like every write."""
    _enabled()
    # Only send fields the caller actually set, so an omitted group is left
    # untouched rather than cleared.
    edits = body.model_dump(exclude_unset=True)
    if not edits:
        return {"updated": False}
    try:
        # save_facts loads the site itself (and 404s via SettingsError), so there
        # is no pre-load here — and it returns the post-save view, so there is no
        # re-read after either.
        result = await website_settings.save_facts(website_id, edits)
    except website_settings.SettingsError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info(
        "websites.facts_updated",
        extra={"website_id": website_id, "committed": result.get("committed"),
               "client_id": (result.get("website") or {}).get("client_id")},
    )
    return {
        "updated": True,
        "committed": result.get("committed", False),
        "deploy_id": result.get("deploy_id"),
        "facts": result.get("facts"),
    }


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


class ContentPlanRequest(BaseModel):
    """An informational site's cluster inventory (pillars -> posts).

    Site-owned: stored on `config.content_plan`, editable, and durable across a
    re-research. The shape is what `website_plan.content_plan_pillars` parses.
    """

    content_plan: dict = Field(default_factory=dict)


class ContentPlanSeedRequest(BaseModel):
    # A seed refuses to clobber an edited plan unless `replace` is set — the
    # strategist plan is the seed, not a live dependency, so re-seeding is a
    # deliberate act.
    replace: bool = False


def _rebuild_after_content_plan(website_id: str) -> dict:
    """Rebuild the plan rows after the content plan changed, and return them."""
    website = _load_site(website_id)
    config = website.get("config") or {}
    result = website_plan_store.build(
        website, catalog=config.get("catalog") or [], cities=config.get("cities") or []
    )
    return {"plan": result, "pages": website_plan_store.stored(website_id)}


@router.put("/websites/{website_id}/content-plan")
async def set_content_plan(
    website_id: str, body: ContentPlanRequest, auth: dict = Depends(require_staff)
) -> dict:
    """Set an informational site's content plan, then rebuild the plan rows.

    The content plan is the site's own inventory; a geo site has none, so this is
    refused for a non-informational site rather than storing a plan nothing reads.
    """
    _enabled()
    website = _load_site(website_id)
    assert_not_frozen(website["client_id"])
    if (website.get("site_type") or "") != "informational":
        raise HTTPException(status_code=409, detail="content_plan_only_for_informational_sites")

    config = dict(website.get("config") or {})
    config["content_plan"] = body.content_plan or {}
    get_supabase().table("websites").update(
        {"config": config, "updated_at": "now()"}
    ).eq("id", website_id).execute()

    return {
        "summary": website_content_plan.plan_summary(config["content_plan"]),
        **_rebuild_after_content_plan(website_id),
    }


@router.post("/websites/{website_id}/content-plan/seed")
async def seed_content_plan(
    website_id: str, body: ContentPlanSeedRequest, auth: dict = Depends(require_staff)
) -> dict:
    """Seed the content plan from the client's latest topic-strategist plan.

    A one-shot import: after it, the plan is the site's own data. Rebuilds the
    plan rows so the seeded pages are immediately reviewable.
    """
    _enabled()
    website = _load_site(website_id)
    assert_not_frozen(website["client_id"])
    try:
        seeded = website_content_plan.import_from_strategist(website, replace=body.replace)
    except website_content_plan.SeedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"seeded": seeded, **_rebuild_after_content_plan(website_id)}


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

    Two kinds of blocker, and they clear differently. **Planning errors** — a
    reserved-slug collision, two entries claiming one path — are wrong rather
    than large, and are fixed by editing the catalog; a published slug is
    immutable, so approving a wrong URL costs a permanent redirect rather than
    an edit. **Scale gates** are judgements about size and clear with a named
    sign-off in `acknowledge`.
    """
    _enabled()
    website = _load_site(website_id)
    blockers = website_plan_store.approval_blockers(
        website, acknowledged=body.acknowledge
    )

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

    approval = website_plan_store.approve(
        website, actor=auth.get("user_id") or "", acknowledged=body.acknowledge
    )
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


# --------------------------------------------------------------------------
# Themes
# --------------------------------------------------------------------------
#
# Themes are fleet-level, not per-client: the same uploaded design is often the
# starting point for several sites, and re-uploading it per client would produce
# several themes that drift apart under separate compiles.


@router.get("/website-themes")
async def list_themes(auth: dict = Depends(require_auth)) -> dict:
    _enabled()
    rows = (
        get_supabase()
        .table("website_themes")
        .select("*")
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    ).data or []
    return {"themes": rows}


@router.get("/website-themes/{theme_id}")
async def get_theme(theme_id: str, auth: dict = Depends(require_auth)) -> dict:
    """The theme plus the CSS it compiled to.

    The CSS is returned in full because reviewing a theme means reading the
    values — a preview image would show what one design looks like, not what the
    site will inherit.
    """
    _enabled()
    rows = (
        get_supabase().table("website_themes").select("*").eq("id", theme_id).limit(1).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="theme_not_found")

    css = ""
    if rows[0].get("status") == "ready":
        try:
            css = website_theme.load_built(theme_id, ["tokens.css"])["tokens.css"].decode(
                "utf-8", errors="replace"
            )
        except Exception as exc:  # noqa: BLE001 — a missing artefact is not a 500
            logger.warning(
                "websites.theme_css_unreadable",
                extra={"theme_id": theme_id, "error": str(exc)[:200]},
            )
    return {"theme": rows[0], "tokens_css": css}


@router.post("/website-themes")
async def upload_theme(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    auth: dict = Depends(require_staff),
) -> dict:
    """Upload a Claude Design export and start compiling it.

    Accepts the `.dc.html` on its own or the whole export zip. The compile runs
    as a job because it makes an LLM call and downloads fonts; the row appears
    immediately as `compiling` so the upload is visibly not lost.
    """
    _enabled()
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty_upload")
    if len(data) > settings.website_theme_max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="upload_too_large")

    supabase = get_supabase()
    row = (
        supabase.table("website_themes")
        .insert(
            {
                "name": (name or file.filename or "Untitled design").strip()[:120],
                "source_kind": "upload",
                "status": "compiling",
                "theme_source": "design_import",
            }
        )
        .execute()
    ).data
    if not row:
        raise HTTPException(status_code=500, detail="internal_error")
    theme = row[0]

    source_ref = f"{theme['id']}/source/{website_theme.safe_upload_name(file.filename)}"
    try:
        supabase.storage.from_(settings.website_theme_bucket).upload(
            source_ref, data, {"content-type": "application/octet-stream", "upsert": "true"}
        )
    except Exception as exc:
        # Leaving the row at 'compiling' with nothing to compile would look like
        # a hung job forever.
        supabase.table("website_themes").update(
            {"status": "failed", "error": "upload_storage_failed"}
        ).eq("id", theme["id"]).execute()
        logger.error("websites.theme_upload_failed", extra={"error": str(exc)[:300]})
        raise HTTPException(status_code=500, detail="upload_storage_failed") from exc

    supabase.table("website_themes").update({"source_ref": source_ref}).eq(
        "id", theme["id"]
    ).execute()
    job = (
        supabase.table("async_jobs")
        .insert(
            {
                "job_type": "website_theme_compile",
                "entity_id": theme["id"],
                "payload": {"theme_id": theme["id"]},
            }
        )
        .execute()
    ).data
    return {"theme_id": theme["id"], "job_id": job[0]["id"] if job else None}


@router.post("/website-themes/{theme_id}/recompile")
async def recompile_theme(theme_id: str, auth: dict = Depends(require_staff)) -> dict:
    """Re-run the compile on the design already uploaded.

    The role assignment is a judgement call made by a model, so 'that accent is
    the wrong colour' has to be answerable without asking for the file again.
    """
    _enabled()
    rows = (
        get_supabase()
        .table("website_themes")
        .select("id, source_ref")
        .eq("id", theme_id)
        .limit(1)
        .execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="theme_not_found")
    if not rows[0].get("source_ref"):
        raise HTTPException(status_code=400, detail="theme_has_no_source")

    get_supabase().table("website_themes").update(
        {"status": "compiling", "error": None}
    ).eq("id", theme_id).execute()
    job = (
        get_supabase()
        .table("async_jobs")
        .insert(
            {
                "job_type": "website_theme_compile",
                "entity_id": theme_id,
                "payload": {"theme_id": theme_id},
            }
        )
        .execute()
    ).data
    return {"queued": True, "job_id": job[0]["id"] if job else None}


@router.post("/website-themes/{theme_id}/approve")
async def approve_theme(theme_id: str, auth: dict = Depends(require_staff)) -> dict:
    """Sign a compiled theme off for use (PRD §4.14).

    A theme is selectable only once someone has looked at it — the compile can
    succeed and still be wrong, because 'which measured colour is the accent' is
    a judgement.
    """
    _enabled()
    rows = (
        get_supabase()
        .table("website_themes")
        .select("id, status")
        .eq("id", theme_id)
        .limit(1)
        .execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="theme_not_found")
    if rows[0].get("status") != "ready":
        raise HTTPException(status_code=409, detail="theme_not_ready")
    updated = (
        get_supabase()
        .table("website_themes")
        .update({"approved_at": "now()", "updated_at": "now()"})
        .eq("id", theme_id)
        .execute()
    ).data
    return {"theme": updated[0] if updated else None}


@router.post("/websites/{website_id}/theme")
async def set_site_theme(
    website_id: str, body: ThemeSelectRequest, auth: dict = Depends(require_staff)
) -> dict:
    """Point a site at a theme, and commit it if the repo already exists.

    Committing here rather than enqueueing: it is one commit, and the caller is
    the person who will look at the site to see whether the swap did what they
    wanted.
    """
    _enabled()
    site = _load_site(website_id)
    assert_not_frozen(site["client_id"])

    rows = (
        get_supabase()
        .table("website_themes")
        .select("*")
        .eq("id", body.theme_id)
        .limit(1)
        .execute()
    ).data
    if not rows:
        raise HTTPException(status_code=404, detail="theme_not_found")
    theme = rows[0]
    if theme.get("status") != "ready":
        raise HTTPException(status_code=409, detail="theme_not_ready")
    if not theme.get("approved_at") and not body.force:
        raise HTTPException(status_code=409, detail="theme_not_approved")

    get_supabase().table("websites").update(
        {"theme_id": theme["id"], "updated_at": "now()"}
    ).eq("id", website_id).execute()

    try:
        sha = await website_theme.apply_theme_to_site(site, theme)
    except Exception as exc:  # noqa: BLE001
        # The selection stands — provisioning will carry the theme in on its
        # next commit — but the caller must know the live site did not change.
        logger.error(
            "websites.theme_apply_failed",
            extra={"website_id": website_id, "error": str(exc)[:300]},
        )
        raise HTTPException(status_code=502, detail="theme_commit_failed") from exc

    return {"theme_id": theme["id"], "committed": bool(sha), "commit_sha": sha}


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

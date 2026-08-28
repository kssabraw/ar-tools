"""Website Builder — persisting a site plan as reviewable rows.

`website_plan` computes the inventory; this module is the impure half that
stores it, reads it back, and decides whether it may be approved.

Three rules it enforces that are easy to get wrong:

1. **A rebuild never touches a published page.** Re-running the planner after
   editing the catalog is expected and cheap; silently deleting or re-pointing a
   row whose file is already live is not. Published routes that leave the plan
   are reported, not removed — a live slug's retirement is a redirect
   (reference §1.2), which is a publish-path action nobody has built yet.
2. **A rebuild never clobbers generated content.** The plan owns route, type,
   trigger, tier and generation inputs; the generator owns `content_source` and
   `source_id`. Rebuilding must not orphan a page somebody already paid to
   write.
3. **Approval is refused while the plan is blocked.** Every blocking issue is a
   planning error the reference says to surface rather than silently resolve,
   and a wrong URL outlives the mistake that made it.

Where the catalog comes from: the request body, persisted onto
`websites.config`. The client-level Business Facts store (PRD §4.10) is a later
slice; this is the shape it will feed, held on the site until then rather than
inventing a client-level schema ahead of the intake that owns it.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from db.supabase_client import get_supabase
from services import website_plan
from services.website_plan import (
    CityEntry,
    PillarEntry,
    PlanIssue,
    ServiceEntry,
    SitePlan,
)

logger = logging.getLogger(__name__)

# Fields the planner owns on an existing row. Everything else — content_source,
# source_id, status, commit_sha — belongs to generation and publishing.
_PLANNER_FIELDS = ("page_type", "title", "trigger", "tier", "plan")

# The trigger stamped on a hand-added page. A rebuild must never prune one just
# because it isn't in the deterministic inventory (that is the whole point of
# adding it), so `build()` keeps `trigger="manual"` rows the way it keeps
# published ones.
MANUAL_TRIGGER = "manual"


class ManualPageError(Exception):
    """A manual "add a page" request the store refused, with the HTTP status the
    router should return (400 for bad input, 409 for a route that already exists).
    """

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def parse_catalog(raw: Iterable[dict]) -> list[ServiceEntry]:
    """Service catalog entries from stored/posted config.

    Slugs are derived when absent but honoured when given: a slug is editable
    before first publish and immutable after (PRD §4.10), so the caller's value
    always wins over a re-derivation.
    """
    out: list[ServiceEntry] = []
    for item in raw or []:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        out.append(
            ServiceEntry(
                name=name,
                slug=website_plan.slugify(item.get("slug") or name),
                teaser=(item.get("teaser") or "").strip(),
                order=int(item.get("order") or 100),
                include_in_matrix=bool(item.get("include_in_matrix", True)),
                parent_slug=(
                    website_plan.slugify(item["parent_slug"])
                    if item.get("parent_slug")
                    else None
                ),
                variations=_parse_variations(item),
            )
        )
    return out


def _parse_variations(item: dict) -> tuple:
    """Service variations from config, accepting both the current shape and the
    pre-generalization one.

    * `variations: [{label, kind}]` — the current shape; `kind` defaults to
      "type" and an unknown kind is coerced to "type".
    * `variations: ["Oak Tree Removal", …]` — bare strings read as type modifiers.
    * `brands: ["Carrier", …]` — the pre-generalization field, read as brand
      modifiers ONLY when the current `variations` field is absent, so an
      existing site's stored catalog keeps working until its next save migrates
      it forward. Once `variations` is present it is authoritative and legacy
      `brands` are ignored — the frontend's `normalizeService` drops `brands`
      the moment it writes `variations`, so honouring both here would let the two
      double up; this mirrors that "variations wins" rule.
    """
    out: list = []
    seen: set = set()

    def add(label: str, kind: str) -> None:
        label = (label or "").strip()
        if not label:
            return
        key = (label.lower(), kind)
        if key in seen:
            return
        seen.add(key)
        out.append(website_plan.ServiceVariation(label=label, kind=kind))

    if item.get("variations") is not None:
        for v in item["variations"]:
            if isinstance(v, str):
                add(v, "type")
            elif isinstance(v, dict):
                kind = v.get("kind")
                add(v.get("label") or "", kind if kind in website_plan.VARIATION_KINDS else "type")
    else:
        for legacy in item.get("brands") or []:
            if isinstance(legacy, str):
                add(legacy, "brand")
    return tuple(out)


def parse_cities(raw: Iterable[dict]) -> list[CityEntry]:
    """City entries with their Maps-entity-passed neighborhoods."""
    out: list[CityEntry] = []
    for item in raw or []:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        hoods = []
        for hood in item.get("neighborhoods") or []:
            if isinstance(hood, str):
                hood_name, hood_slug = hood.strip(), website_plan.slugify(hood)
            else:
                hood_name = (hood.get("name") or "").strip()
                hood_slug = website_plan.slugify(hood.get("slug") or hood_name)
            if hood_name:
                hoods.append((hood_name, hood_slug))
        out.append(
            CityEntry(
                name=name,
                slug=website_plan.slugify(item.get("slug") or name),
                neighborhoods=tuple(hoods),
            )
        )
    return out


def head_terms(
    config: dict, catalog: list[ServiceEntry], cities: list[CityEntry]
) -> tuple[Optional[str], Optional[str]]:
    """The primary service and city a location page's geo term is built from.

    A top-level location page targets the geo head term — "plumber anaheim", not
    a specific service — so it needs one service name that stands for the
    business. Explicit config wins; otherwise the first catalog entry in nav
    order, which is what the nav itself leads with.
    """
    business = (config or {}).get("business") or {}
    top = sorted([s for s in catalog if not s.parent_slug], key=lambda s: (s.order, s.slug))
    primary_service = (business.get("primaryService") or "").strip() or (
        top[0].name if top else None
    )
    primary_city = (business.get("city") or "").strip() or (
        cities[0].name if cities else None
    )
    return primary_service or None, primary_city or None


def posts_by_path(pillars: list[PillarEntry]) -> dict:
    """Every planned post keyed by its /blog/{slug}/ route."""
    return {
        website_plan._path("blog", p.slug): p
        for pillar in pillars
        for p in pillar.posts
    }


def pillars_by_path(pillars: list[PillarEntry]) -> dict:
    """Every pillar keyed by its /{topic-slug}/ route."""
    return {website_plan._path(pillar.slug): pillar for pillar in pillars}


def plan_rows(
    website_id: str,
    plan: SitePlan,
    *,
    catalog: list[ServiceEntry],
    cities: list[CityEntry],
    pillars: Optional[list[PillarEntry]] = None,
    primary_service: Optional[str],
    primary_city: Optional[str],
) -> list[dict]:
    """One row per planned page, ready to insert or merge."""
    services_by_slug = {s.slug: s for s in catalog}
    cities_by_slug = {c.slug: c for c in cities}
    pillar_list = pillars or []
    posts_map = posts_by_path(pillar_list)
    pillars_map = pillars_by_path(pillar_list)
    rows = []
    for page in plan.pages:
        payload = website_plan.plan_payload(
            page,
            services=services_by_slug,
            cities=cities_by_slug,
            posts=posts_map,
            pillars=pillars_map,
            primary_service=primary_service,
            primary_city=primary_city,
        )
        rows.append(
            {
                "website_id": website_id,
                "route": page.path,
                "page_type": page.page_type,
                "title": page.title,
                "trigger": page.trigger,
                "tier": page.tier,
                "plan": payload,
                "content_source": "static" if payload.get("engine") == "template" else "composed",
                "status": "draft",
            }
        )
    return rows


def merge_row(existing: dict, planned: dict) -> dict:
    """The patch a rebuild applies to a row that already exists.

    Only the planner's own fields move. `content_source` is included **only**
    when the row has never been generated, because flipping a written page back
    to 'composed' would orphan the `local_seo_pages` record that holds its text.
    """
    patch = {k: planned[k] for k in _PLANNER_FIELDS if k in planned}
    if not existing.get("source_id"):
        patch["content_source"] = planned["content_source"]
    return {k: v for k, v in patch.items() if existing.get(k) != v}


def build(website: dict, *, catalog: list[dict], cities: list[dict]) -> dict:
    """Build the plan, persist it as rows, and return it for review."""
    supabase = get_supabase()
    website_id = website["id"]
    config = dict(website.get("config") or {})

    services = parse_catalog(catalog)
    city_entries = parse_cities(cities)
    # The content plan is site-owned (config.content_plan). An informational site
    # is planned from it; a geo site has none, so this is empty and inert there.
    pillars = website_plan.content_plan_pillars(config.get("content_plan"))
    primary_service, primary_city = head_terms(config, services, city_entries)

    plan = website_plan.build_plan(
        site_type=website.get("site_type") or "local_business",
        catalog=services,
        cities=city_entries,
        content_plan=config.get("content_plan"),
    )
    rows = plan_rows(
        website_id,
        plan,
        catalog=services,
        cities=city_entries,
        pillars=pillars,
        primary_service=primary_service,
        primary_city=primary_city,
    )

    existing = (
        supabase.table("website_pages")
        .select("*")
        .eq("website_id", website_id)
        .is_("superseded_at", "null")
        .execute()
    ).data or []
    by_route = {r["route"]: r for r in existing}
    planned_routes = {r["route"] for r in rows}

    inserts = []
    for row in rows:
        prior = by_route.get(row["route"])
        if prior is None:
            inserts.append(row)
            continue
        patch = merge_row(prior, row)
        if patch:
            patch["updated_at"] = "now()"
            supabase.table("website_pages").update(patch).eq("id", prior["id"]).execute()
    if inserts:
        supabase.table("website_pages").insert(inserts).execute()

    # A route that left the plan: drop it if nothing was ever committed for it,
    # keep it (and say so) if it is live — retiring a published slug is a 301,
    # not a delete. A hand-added `manual` page is never in the deterministic plan
    # to begin with, so it always reads as an orphan here; it is kept regardless
    # of publish state, or "add a page" would be undone by the next rebuild.
    orphans = [r for r in existing if r["route"] not in planned_routes]
    removable = [
        r["id"]
        for r in orphans
        if r.get("status") != "published" and r.get("trigger") != MANUAL_TRIGGER
    ]
    if removable:
        supabase.table("website_pages").delete().in_("id", removable).execute()
    orphaned_published = [r["route"] for r in orphans if r.get("status") == "published"]

    # Store the inputs so a rebuild is repeatable and the plan tab can show what
    # it was built from.
    config["catalog"] = catalog
    config["cities"] = cities
    supabase.table("websites").update({"config": config, "updated_at": "now()"}).eq(
        "id", website_id
    ).execute()

    logger.info(
        "website_plan.built",
        extra={"website_id": website_id, "pages": len(rows), "blocked": plan.blocked},
    )
    return {
        **serialize(plan),
        "orphaned_published": orphaned_published,
        "primary_service": primary_service,
        "primary_city": primary_city,
    }


def add_manual_page(
    website: dict,
    *,
    page_type: str,
    service: Optional[str] = None,
    city: Optional[str] = None,
    subservice: Optional[str] = None,
    title: Optional[str] = None,
    keyword: Optional[str] = None,
    location: Optional[str] = None,
    post_format: Optional[str] = None,
    angle: Optional[str] = None,
    target_keywords: Optional[list[str]] = None,
) -> dict:
    """Insert one hand-added page as a `trigger="manual"` draft row.

    The single upstream gap the rest of the pipeline doesn't have: everything
    downstream (generate, gate, publish, deploy, retry, drip) is already keyed on
    a `website_pages.id`, but only `build()` ever created a row — from the whole
    deterministic catalog. This mints exactly one, reusing the planner's own
    derivation so the page behaves like any other, then leaves it to the existing
    generate-by-id / publish-by-id flow.

    Refuses a reserved-slug collision (a planning error, not a size call — the URL
    is immutable once published) and a route an active row already claims (which
    the partial unique index would reject anyway, but with a clearer code).
    """
    supabase = get_supabase()
    website_id = website["id"]
    config = website.get("config") or {}
    services = parse_catalog(config.get("catalog") or [])
    city_entries = parse_cities(config.get("cities") or [])
    primary_service, primary_city = head_terms(config, services, city_entries)

    try:
        page, payload = website_plan.build_manual_page(
            page_type=page_type,
            service=service,
            city=city,
            subservice=subservice,
            title=title,
            keyword=keyword,
            location=location,
            post_format=post_format,
            angle=angle,
            target_keywords=target_keywords,
            catalog=services,
            cities=city_entries,
            primary_service=primary_service,
            primary_city=primary_city,
        )
    except ValueError as exc:
        raise ManualPageError(str(exc), 400) from exc

    if any(i.kind == "reserved_slug" for i in website_plan.check_paths([page])):
        raise ManualPageError("reserved_slug", 400)

    if page.path in {r["route"] for r in stored(website_id)}:
        raise ManualPageError("page_route_exists", 409)

    row = {
        "website_id": website_id,
        "route": page.path,
        "page_type": page.page_type,
        "title": page.title,
        "trigger": page.trigger,
        "tier": page.tier,
        "plan": payload,
        "content_source": "static" if payload.get("engine") == "template" else "composed",
        "status": "draft",
    }
    inserted = (supabase.table("website_pages").insert(row).execute()).data or [row]
    logger.info(
        "website_plan.manual_page_added",
        extra={"website_id": website_id, "route": page.path, "page_type": page.page_type},
    )
    return inserted[0]


def serialize(plan: SitePlan) -> dict:
    return {
        "pages": [
            {
                "path": p.path,
                "page_type": p.page_type,
                "title": p.title,
                "trigger": p.trigger,
                "tier": p.tier,
                "is_core": p.is_core,
                "is_core_conditional": p.is_core_conditional,
            }
            for p in plan.pages
        ],
        "issues": [
            {
                "kind": i.kind,
                "blocking": i.blocking,
                "detail": i.detail,
                # The plan tab needs this to know whether to offer a sign-off
                # button or send the user back to edit the catalog.
                "acknowledgeable": i.acknowledgeable,
            }
            for i in plan.issues
        ],
        "matrix_count": plan.matrix_count,
        "links_per_index": plan.links_per_index,
        "blocked": plan.blocked,
    }


def stored(website_id: str) -> list[dict]:
    return (
        get_supabase()
        .table("website_pages")
        .select("*")
        .eq("website_id", website_id)
        .is_("superseded_at", "null")
        .order("tier")
        .order("route")
        .execute()
    ).data or []


def recompute(website: dict) -> dict:
    """Re-derive the plan's issues from the stored catalog, without writing.

    The plan tab and the approval gate must agree, so both read the same
    computation rather than a verdict cached at build time — an edited catalog
    would otherwise approve against a stale set of issues.
    """
    config = website.get("config") or {}
    services = parse_catalog(config.get("catalog") or [])
    city_entries = parse_cities(config.get("cities") or [])
    plan = website_plan.build_plan(
        site_type=website.get("site_type") or "local_business",
        catalog=services,
        cities=city_entries,
        content_plan=config.get("content_plan"),
    )
    return serialize(plan)


def conflict_issues(website: dict) -> list[PlanIssue]:
    """Portfolio conflicts for a lead-gen property (PRD §4.12.4).

    Only owned properties are checked: client sites never overlapped by
    construction, each having its own footprint. A property competing with a
    *client* for the same service × city cells is a relationship failure on the
    agency's own infrastructure, so it blocks; property vs property warns.
    """
    if (website.get("site_type") or "") != "lead_gen":
        return []

    supabase = get_supabase()
    own = [r["route"] for r in stored(website["id"])]

    others = (
        supabase.table("websites")
        .select("id, name, client_id")
        .neq("id", website["id"])
        .is_("deleted_at", "null")
        .execute()
    ).data or []
    if not others:
        return []

    client_kinds = {
        c["id"]: c.get("kind") or "client"
        for c in (
            supabase.table("clients")
            .select("id, kind")
            .in_("id", [o["client_id"] for o in others])
            .execute()
        ).data
        or []
    }
    routes = (
        supabase.table("website_pages")
        .select("website_id, route")
        .in_("website_id", [o["id"] for o in others])
        .eq("page_type", "local_landing")
        .execute()
    ).data or []
    by_site: dict[str, list[str]] = {}
    for row in routes:
        by_site.setdefault(row["website_id"], []).append(row["route"])

    return website_plan.portfolio_conflicts(
        own,
        [
            {
                "name": o.get("name"),
                "kind": client_kinds.get(o["client_id"], "client"),
                "routes": by_site.get(o["id"]) or [],
            }
            for o in others
        ],
    )


def approval_blockers(
    website: dict, *, acknowledged: Optional[list[str]] = None
) -> list[dict]:
    """Everything standing between this plan and approval.

    `acknowledged` names issue kinds a human has signed off. Only an
    `acknowledgeable` issue can be cleared that way — a scale gate is a
    judgement about size, so it needs a decision; a reserved-slug collision is
    simply wrong, and acknowledging it would ship a URL nobody can change later.
    """
    acked = set(acknowledged or [])
    plan = recompute(website)
    issues = [i for i in plan["issues"] if i["blocking"]]
    issues += [
        {
            "kind": i.kind,
            "blocking": i.blocking,
            "detail": i.detail,
            "acknowledgeable": i.acknowledgeable,
        }
        for i in conflict_issues(website)
        if i.blocking
    ]
    return [i for i in issues if not (i.get("acknowledgeable") and i["kind"] in acked)]


def approve(
    website: dict, *, actor: str, acknowledged: Optional[list[str]] = None
) -> dict:
    """Stamp the plan approved. Queues nothing — approval is a human's verdict."""
    config = dict(website.get("config") or {})
    plan_meta = dict(config.get("plan") or {})
    plan_meta["approved_at"] = _now_iso()
    plan_meta["approved_by"] = actor
    # What was signed off, by whom. A sign-off nobody can find afterwards is
    # indistinguishable from a gate that never fired.
    plan_meta["acknowledged"] = sorted(set(acknowledged or []))
    config["plan"] = plan_meta
    get_supabase().table("websites").update(
        {"config": config, "updated_at": "now()"}
    ).eq("id", website["id"]).execute()
    logger.info("website_plan.approved", extra={"website_id": website["id"], "actor": actor})
    return plan_meta


def is_approved(website: dict) -> bool:
    return bool(((website.get("config") or {}).get("plan") or {}).get("approved_at"))


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def coerce_ids(pages: list[dict], page_ids: Optional[list[str]]) -> list[str]:
    """Validate a caller's page selection against the site's own rows.

    An explicit selection is required for anything that costs money, so this
    never falls back to "everything" — an empty or unmatched selection returns
    empty and the caller reports it.
    """
    valid = {p["id"] for p in pages}
    return [pid for pid in (page_ids or []) if pid in valid]

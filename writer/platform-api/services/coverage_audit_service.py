"""Coverage Audit — the impure runner + report store (Phase 1: Tier 1).

Phase 0 built the pure core (`services/coverage_audit.py`): site classification,
the AXES-ONLY coverage grid, the gap diff, and the demand-floored ranking. This
module is the I/O half that wires the core to reality for **Tier 1
(city × main-service)**:

  1. **Service axis** — auto-derived (team-editable): the service-shaped pages the
     client's site already has (`coverage_audit.derive_site_services`) + the GBP
     categories as a SEED that a planner LLM expands into real service phrases
     (GBP categories are business-type labels — "Roofing contractor" — never read
     as the service axis directly, plan §0.2). Best-effort: no LLM → the
     site-derived axis alone.
  2. **Location axis** — the seed city + `target_cities.resolve_target_cities`
     (GBP service area + manual list + site place-names + nearby). Without
     `GOOGLE_MAPS_API_KEY` that returns only the seed city, so the report carries a
     VISIBLE degraded note (plan §5) — never a silent empty axis.
  3. **The tier job** — scan the site (`discover_site_urls`) → classify → build both
     axes → `build_coverage_grid` + `diff_coverage` → demand-rank via
     `keyword_market` (RESERVED through `reserve_coverage_audit_calls` BEFORE any
     paid call) → persist a `coverage_audits` run (jsonb). ONE job per tier (plan
     §8 Major #3), every paid step idempotent/cached so a reaper requeue never
     re-bills.

The Matrix seed (`seed_matrix_from_audit`) passes AXES ONLY to
`local_seo_matrix_store.create_matrix`; the Matrix's own `mark_coverage` owns
per-cell present/absent (plan §8 Major #1). The audit never writes a cell verdict.

Best-effort throughout: a dead source degrades that slice with a visible note and
never aborts the audit.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import coverage_audit as core
from services import (
    census_cdp,
    icp_service,
    keyword_market,
    local_seo_silo,
    site_page_index,
    target_cities,
)
from services.dataforseo_rank import location_code_for

logger = logging.getLogger(__name__)

TIER_MIN = 1
TIER_MAX = 4
# Phase 1: Tier 1 (city × main-service). Phase 2: Tier 2 (city × subservice).
# Phase 3: Tier 3 (CDP × main-service — the census CDP location axis).
# Phase 4: Tier 4 (CDP × subservice — the CDP location axis crossed with the
# subservice axis; the largest cross-product, where the demand floor earns its keep).
SUPPORTED_TIERS = (1, 2, 3, 4)

_AUDIT_COLS = (
    "id, client_id, status, tier, service_axis, location_axis, gaps, provenance, "
    "error, sitemap_url, created_at"
)


# ── daily paid-call meter (mirror domain_intel / keyword_research) ─────────────
class BudgetExceeded(Exception):
    """Raised when today's Coverage-Audit paid-call budget is exhausted."""


def _today() -> str:
    return date.today().isoformat()


def budget_remaining() -> int:
    """Paid DataForSEO calls left in today's budget (a large number when the guard
    is disabled)."""
    cap = settings.coverage_audit_daily_call_budget
    if cap <= 0:
        return 10**9
    try:
        rows = (
            get_supabase()
            .table("coverage_audit_usage")
            .select("calls")
            .eq("day", _today())
            .limit(1)
            .execute()
            .data
        )
    except Exception:  # noqa: BLE001 — accounting read never blocks a preflight
        return cap
    used = rows[0]["calls"] if rows else 0
    return max(0, cap - used)


def reserve_budget(n: int) -> None:
    """Reserve ``n`` paid calls against today's budget, or raise ``BudgetExceeded``.
    Atomic via the ``reserve_coverage_audit_calls`` RPC (single check-and-increment).
    An RPC failure is fail-open (accounting never blocks work) — mirrors
    ``domain_intel.reserve_budget``. ``n`` ≤ 0 reserves nothing."""
    if n <= 0:
        return
    cap = settings.coverage_audit_daily_call_budget
    if cap <= 0:
        return
    try:
        res = get_supabase().rpc(
            "reserve_coverage_audit_calls", {"p_day": _today(), "p_n": n, "p_cap": cap}
        ).execute()
        fit = res.data
    except Exception as exc:  # noqa: BLE001
        logger.warning("coverage_audit.budget_accounting_failed", extra={"error": str(exc)})
        return
    if fit is False:
        raise BudgetExceeded(f"coverage_audit_budget_exceeded: cap {cap} reached today")


# ── small helpers ──────────────────────────────────────────────────────────────
def _website(client: dict) -> str:
    gbp = client.get("gbp") or {}
    return (gbp.get("website") or client.get("website_url") or "").strip()


def _seed_location(client: dict) -> str:
    """The client's seed area string for `resolve_target_cities` + the matrix
    location. Prefers `business_location`; degrades to "" (→ location axis is
    seed-less and the report says so)."""
    return (client.get("business_location") or "").strip()


def _gbp_categories(client: dict) -> list[str]:
    """The client's GBP categories (primary + additional) — the SEED the planner
    expands into service phrases. Never the service axis itself (plan §0.2)."""
    gbp = client.get("gbp") or {}
    cats: list[str] = []
    seen: set[str] = set()
    for raw in [gbp.get("gbp_category")] + list(gbp.get("gbp_categories") or []):
        name = (raw or "").strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            cats.append(name)
    return cats


def _in_tool_index(client_id: str) -> dict:
    """A content-word-set token index over the client's in-tool Local SEO pages
    (active only), so a page generated in-tool but not yet on the live site still
    reads as `present` in the report (plan §3.1). Location index is left empty —
    in-tool pages carry a canonical `location` ("Melbourne,Victoria,Australia"),
    not a bare hub slug, and the primary-service city-page match already covers an
    in-tool city page. Best-effort: any read failure → empty index."""
    token_index: dict[frozenset, str] = {}
    try:
        rows = (
            get_supabase()
            .table("local_seo_pages")
            .select("id, keyword, published_url")
            .eq("client_id", client_id)
            .is_("deleted_at", "null")
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001 — in-tool coverage is a bonus signal
        logger.warning("coverage_audit.in_tool_read_failed", extra={"client_id": client_id, "error": str(exc)})
        return {"token_index": {}, "location_index": {}}
    for row in rows:
        key = site_page_index.content_tokens(row.get("keyword") or "")
        if key and key not in token_index:
            token_index[key] = row.get("published_url") or f"in_tool:{row.get('id')}"
    return {"token_index": token_index, "location_index": {}}


# ── service-axis planner (GBP-category expansion, best-effort LLM) ─────────────
_SERVICE_AXIS_SYSTEM = (
    "You are a local SEO strategist. Given a local business's observed service "
    "pages and its Google Business Profile categories, list its distinct MAIN "
    "SERVICES as short, commercial, CITY-AGNOSTIC service phrases a customer would "
    "search — e.g. 'Roof Restoration', 'Gutter Cleaning', 'Emergency Plumbing'. "
    "GBP categories are business-TYPE labels ('Roofing Contractor', 'Plumber') — "
    "translate them into the actual services offered; never return a category "
    "verbatim as a service. Merge duplicates and synonyms. Exclude non-service "
    "pages (about, contact, blog), place names, and brand names. Prefer the "
    "business's real observed services; add an obvious missing core service only "
    "when the categories clearly imply it. Return 3–15 services, most important "
    "first."
)

_SERVICE_AXIS_SCHEMA = {
    "type": "object",
    "properties": {
        "services": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Distinct main services as short city-agnostic commercial phrases.",
        }
    },
    "required": ["services"],
}


def _plan_service_axis(site_services: list[str], gbp_cats: list[str], business_name: str) -> tuple[list[str], Optional[str]]:
    """One best-effort Sonnet call: clean + expand the site-derived services with
    the GBP-category seed into a tidy main-service list. Returns
    ``(services, note)``; a ``note`` is set when the planner was unavailable/failed
    (the caller then falls back to the site-derived services). Blocking — call via
    a thread."""
    if not (site_services or gbp_cats):
        return [], None
    llm = local_seo_silo._service_llm()
    if not llm:
        return [], "Service-axis planner skipped — content model not configured; used the site's own service pages."
    user = (
        f"Business: {business_name or '(unknown)'}\n"
        f"Observed service pages: {', '.join(site_services) if site_services else '(none found)'}\n"
        f"GBP categories: {', '.join(gbp_cats) if gbp_cats else '(none)'}"
    )
    try:
        data = llm.call_tool(
            system=_SERVICE_AXIS_SYSTEM,
            user=user,
            tool_name="main_services",
            tool_description="The business's distinct main services as short city-agnostic commercial phrases.",
            input_schema=_SERVICE_AXIS_SCHEMA,
            purpose="coverage_audit/service_axis",
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001 — planner is best-effort
        logger.warning("coverage_audit.service_axis_planner_failed", extra={"error": str(exc)})
        return [], "Service-axis planner failed — used the site's own service pages."
    out: list[str] = []
    seen: set[str] = set()
    for raw in data.get("services") or []:
        label = (raw or "").strip()
        key = label.lower()
        if label and key not in seen:
            seen.add(key)
            out.append(label)
    return out, None


def _derive_service_axis(client: dict, classified: dict, place_vocab: list[str]) -> tuple[list[dict], dict]:
    """Resolve the auto-derived Tier-1 service axis + its provenance. Merges the
    planner's expansion (authoritative order) with any site-observed service not
    already covered, so nothing real is dropped if the planner misses it. Each
    entry is tagged with its source(s) for the review screen. Best-effort."""
    site_services = core.derive_site_services(classified, place_vocab)
    gbp_cats = _gbp_categories(client)
    planned, note = _plan_service_axis(site_services, gbp_cats, client.get("name") or "")

    site_set = {s.lower() for s in site_services}
    gbp_set = {c.lower() for c in gbp_cats}
    planned_set = {p.lower() for p in planned}

    # Planner order first, then any observed site service the planner didn't emit.
    ordered: list[str] = list(planned)
    seen = set(planned_set)
    for s in site_services:
        if s.lower() not in seen:
            seen.add(s.lower())
            ordered.append(s)
    # Last resort: no site pages and no planner → offer the raw GBP categories so
    # the team has something to edit rather than an empty axis.
    fallback_used = False
    if not ordered and gbp_cats:
        ordered = list(gbp_cats)
        fallback_used = True

    axis: list[dict] = []
    for label in ordered:
        low = label.lower()
        sources = []
        if low in planned_set:
            sources.append("planner")
        if low in site_set:
            sources.append("site")
        if low in gbp_set:
            sources.append("gbp")
        axis.append({"label": label, "sources": sources or ["derived"]})

    notes: list[str] = []
    if note:
        notes.append(note)
    if fallback_used:
        notes.append("No service pages found and the planner was unavailable — showing raw GBP categories; edit these into real services.")
    if not axis:
        notes.append("No services could be derived — add them manually to run the audit.")
    provenance = {
        "site_services": site_services,
        "gbp_categories": gbp_cats,
        "planner_used": bool(planned),
        "notes": notes,
        "confirmed": False,
    }
    return axis, provenance


# ── subservice axis (Tier 2 — expand each main service, city-agnostic) ─────────
_SUBSERVICE_PLANNER_UNAVAILABLE = (
    "Subservice planner unavailable — showing the main services instead "
    "(Tier 2 degraded to main-service coverage). Retry once the content model is configured."
)


async def _derive_subservice_axis(
    client: dict, main_axis: list[dict], representative_city: str
) -> tuple[list[dict], dict]:
    """Expand each confirmed main service into its subservice variations and derive
    a CITY-AGNOSTIC subservice axis (Tier 2).

    Runs the Local SEO planner `local_seo_silo._generate_service_pages(service,
    representative_city, llm, icp_block)` once per main service — it emits per-city
    pages — then strips the representative city via the reused
    `local_seo_matrix.service_labels_from_pages` (plan §0.2 / §6) and merges across
    services with the pure `core.merge_subservice_axis`. Best-effort: no LLM / every
    call failing → an empty axis (the caller falls back to the main-service axis
    with a visible note — never aborts). The representative city is the seed city
    (same string the planner composes with and the strip removes). Returns
    ``(axis, provenance)``."""
    from services import local_seo_matrix  # local import: pulls the heavy silo chain lazily

    main_services = [
        str((e or {}).get("label") or "").strip()
        for e in (main_axis or [])
        if str((e or {}).get("label") or "").strip()
    ]
    prov: dict = {
        "kind": "subservice",
        "main_services": main_services,
        "representative_city": representative_city,
        "planned_services": [],
        "failed_services": [],
        "empty_services": [],  # planner returned, but no composable subservice came out
        "notes": [],
        "confirmed": False,
    }
    if not main_services:
        prov["notes"].append("No main services to expand into subservices.")
        return [], prov

    llm = local_seo_silo._service_llm()
    if not llm:
        prov["notes"].append("Subservice planner skipped — content model not configured.")
        return [], prov

    # ICP grounds the planner's buying-situation reasoning; best-effort (a client
    # with no ICP on file → the planner infers the ideal customer itself).
    icp_block = ""
    try:
        icp_block = icp_service.resolve_icp_text(client) or ""
    except Exception as exc:  # noqa: BLE001 — ICP grounding is non-critical
        logger.warning("coverage_audit.icp_fetch_failed", extra={"error": str(exc)})

    # One planner call per main service. These are best-effort Anthropic calls — NOT
    # metered through `coverage_audit_usage` and NOT cached, so unlike the demand
    # batch a reaper requeue of this tier re-runs them (cheap: one call per service,
    # far under the 30-min reaper window; only the DataForSEO demand step is the
    # metered/idempotent one the reserve-before-spend guard protects).
    per_service_labels: list[dict] = []
    for service in main_services:
        try:
            per_silo = await asyncio.to_thread(
                local_seo_silo._generate_service_pages, service, representative_city, llm, icp_block
            )
        except Exception as exc:  # noqa: BLE001 — one service failing must not sink the axis
            logger.warning(
                "coverage_audit.subservice_gen_failed",
                extra={"service": service, "error": str(exc)},
            )
            prov["failed_services"].append(service)
            continue
        labels = local_seo_matrix.service_labels_from_pages(per_silo, representative_city)
        if labels:
            per_service_labels.append({"service": service, "labels": labels})
            prov["planned_services"].append(service)
        else:
            # Planner succeeded but produced nothing composable (e.g. every page
            # keyword was blank / stripped away) — record it so the review screen can
            # explain the omission rather than the service silently vanishing.
            prov["empty_services"].append(service)

    axis = core.merge_subservice_axis(per_service_labels)
    if not axis:
        prov["notes"].append("Subservice expansion produced no subservices.")
    if prov["failed_services"]:
        prov["notes"].append(
            f"Could not expand {len(prov['failed_services'])} service(s) into subservices."
        )
    if prov["empty_services"]:
        prov["notes"].append(
            f"{len(prov['empty_services'])} service(s) yielded no distinct subservices."
        )
    return axis, prov


# ── location axis (seed city + resolve_target_cities) ──────────────────────────
async def _resolve_location_axis(
    client: dict, seed_location: str, location_code: Optional[int]
) -> tuple[list[dict], dict]:
    """Seed city + `resolve_target_cities`. Returns ``(axis, provenance)``. Surfaces
    the geocoding-unavailable degrade VISIBLY (plan §5) rather than a silent
    seed-only axis."""
    notes: list[str] = []
    axis: list[dict] = []
    seen: set[str] = set()

    seed_city = local_seo_silo._parse_area(seed_location)[0] if seed_location else ""
    if seed_city:
        axis.append({"name": seed_city, "source": "seed"})
        seen.add(seed_city.lower())
    else:
        notes.append("No business location set — set the client's business location to build a location axis.")

    if not settings.google_maps_api_key:
        notes.append("Geocoding unavailable — limited to the seed city. Set GOOGLE_MAPS_API_KEY to discover the full service-area city list.")
    elif seed_city:
        try:
            cities, city_notes = await target_cities.resolve_target_cities(
                client, seed_location, location_code, get_supabase()
            )
            notes.extend(city_notes)
            for c in cities:
                name = (c.get("name") or "").strip()
                if name and name.lower() not in seen:
                    seen.add(name.lower())
                    axis.append({"name": name, "source": c.get("source") or "discovered"})
        except Exception as exc:  # noqa: BLE001 — city discovery is best-effort
            logger.warning("coverage_audit.location_axis_failed", extra={"error": str(exc)})
            notes.append("City discovery failed — limited to the seed city.")

    return axis, {"notes": notes, "seed_city": seed_city}


# ── demand ranking (reserve BEFORE any paid call, cache-idempotent) ────────────
def _collect_keywords(diff: dict) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for section in ("missing_services", "missing_locations", "missing_cells"):
        for gap in diff.get(section) or []:
            kw = (gap.get("keyword") or "").strip()
            if kw and kw.lower() not in seen:
                seen.add(kw.lower())
                out.append(kw)
    return out


async def _fetch_demand(keywords: list[str], location_code: Optional[int]) -> tuple[dict, bool, list[str]]:
    """Cached-first market data for the gap keywords, refreshing only stale/missing
    rows and RESERVING the paid budget before spending. Returns
    ``(market, available, notes)``. Idempotent — a reaper requeue finds the cache
    warm, so `stale` is empty and nothing is re-billed (plan §8 Major #3)."""
    notes: list[str] = []
    if not keywords or location_code is None:
        if location_code is None:
            notes.append("No rank-tracking location — demand data unavailable.")
        return {}, False, notes

    supabase = get_supabase()
    eligible = [k for k in keywords if keyword_market.market_eligible(k)]
    if not eligible:
        return {}, False, notes

    cached = keyword_market.fetch_cached_market(supabase, eligible, location_code)
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.keyword_market_refresh_days)
    stale = keyword_market.stale_keywords(eligible, cached, cutoff)
    if stale:
        try:
            reserve_budget(math.ceil(len(stale) / 1000))
            await keyword_market.refresh_keywords(supabase, stale, location_code)
        except BudgetExceeded:
            notes.append("Demand budget exhausted for today — ranked on cached demand only.")
        except Exception as exc:  # noqa: BLE001 — demand fetch is best-effort
            logger.warning("coverage_audit.demand_fetch_failed", extra={"error": str(exc)})
            notes.append("Demand lookup failed — ranked on cached demand only.")

    market = keyword_market.fetch_cached_market(supabase, eligible, location_code)
    return market, bool(market), notes


# ── the tier run ───────────────────────────────────────────────────────────────
async def run_coverage_audit_tier(
    audit_id: str,
    client_id: str,
    tier: int,
    service_axis_override: Optional[list] = None,
    sitemap_url: Optional[str] = None,
) -> dict:
    """Run one tier of the audit and persist it onto the `coverage_audits` row
    ``audit_id``. Idempotent by audit_id: a reaper requeue re-runs into the same
    row with the caches warm.

    Tier 1 = city × main-service; Tier 2 = city × subservice; Tier 3 = CDP ×
    main-service; Tier 4 = CDP × subservice. Two orthogonal axes:
      * LOCATION axis — cities (`resolve_target_cities`) for tiers 1/2, or the
        authoritative Census CDP list for the service area
        (`census_cdp.resolve_cdp_axis`) for tiers 3/4.
      * SERVICE axis — main services for tiers 1/3, or their city-agnostic
        subservice expansion for tiers 2/4.
    The location-hub ("missing locations") rows are KEPT for main-service tiers
    (1/3 — a location hub IS a main-service concept: does a city/CDP have a
    "<primary main service> <location>" landing page) and DROPPED for subservice
    tiers (2/4 — a location-hub gap is a Tier-1/3 question measured against the
    MAIN service axis; re-reporting it in a subservice audit would double-count and
    rank against a keyword absent from this tier's axis). The grid / diff /
    demand-rank / matrix-seed path is otherwise identical across every tier."""
    if tier not in SUPPORTED_TIERS:
        raise ValueError(f"unsupported_tier: {tier}")
    supabase = get_supabase()
    client = local_seo_silo._get_client(client_id)
    notes: list[str] = []

    seed_location = _seed_location(client)
    location_code = location_code_for(client)

    # 1) Location axis first — its names are the place vocabulary the classifier
    #    uses to split service vs place tokens.
    #    Tiers 3/4 swap cities → the census CDP list, but STILL use the city names as
    #    the classifier's place vocabulary (a Tier-3/4 service page is still
    #    "/service-city/" or "/subservice-city/", so cities — not CDPs — strip its
    #    place tokens); the CDP names are added to the vocabulary too. All
    #    census/geocode — no paid calls.
    if tier in (3, 4):
        location_axis, loc_prov, city_vocab = await census_cdp.resolve_cdp_axis(
            client, seed_location, location_code, supabase
        )
        place_vocab = list(city_vocab) + core._axis_names(location_axis)
    else:
        location_axis, loc_prov = await _resolve_location_axis(client, seed_location, location_code)
        place_vocab = [row["name"] for row in location_axis]
    notes.extend(loc_prov.get("notes") or [])

    # 2) Scan the site (free sitemap first; the paid site: fallback is reserved).
    #    An operator-supplied sitemap_url (optional) is crawled verbatim — for a site
    #    whose sitemap is at a non-standard path or to point straight at a large
    #    site's index. The audit's own (higher) sitemap caps apply because a missed
    #    page reads as a false gap; a cap-truncated scan surfaces a visible note.
    website = _website(client)
    scan_caps = {
        "max_urls": settings.coverage_sitemap_max_urls,
        "max_files": settings.coverage_sitemap_max_files,
    }
    urls: list[str] = []
    source = "none"
    if not website and not sitemap_url:
        notes.append("No website configured — cannot scan the site; every axis reads as a gap.")
    else:
        urls, source = await site_page_index.discover_site_urls(
            website, location_code or 0, use_paid_fallback=False, sitemap_url=sitemap_url, **scan_caps
        )
        # Only spend on the paid site: fallback when a website domain exists to query
        # (a sitemap-only, website-less run can't use it). The retry is paid_only, so
        # it doesn't re-crawl the sitemap the free pass already tried.
        if not urls and website:
            try:
                reserve_budget(1)
            except BudgetExceeded:
                notes.append("No sitemap and the demand budget is exhausted — site scan limited; results may over-report gaps.")
            else:
                urls, source = await site_page_index.discover_site_urls(
                    website, location_code or 0, paid_only=True
                )
        if source == "sitemap_truncated":
            notes.append(
                f"Site scan hit a scan cap ({settings.coverage_sitemap_max_urls:,} pages / "
                f"{settings.coverage_sitemap_max_files} sitemaps) — some pages weren't scanned, so gaps may be "
                "over-reported. Point the audit at a more specific sitemap URL to narrow the scan."
            )
        if not urls:
            notes.append("No pages discovered on the site — results may over-report gaps.")

    # 3) Classify + derive/confirm the service axis (tier-specific).
    #    An edited axis (override) is used verbatim for any tier — for Tiers 2/4 the
    #    supplied list is the confirmed SUBSERVICE axis. A fresh Tier-1 or Tier-3 run
    #    derives main services (Tier 3 differs only in its LOCATION axis); a fresh
    #    Tier-2 or Tier-4 run derives main services, then expands each into a
    #    city-agnostic subservice axis (Tier 4 differs from Tier 2 only in its LOCATION
    #    axis), degrading to the main services if the planner is unavailable — never
    #    aborting.
    classified = core.classify_site_pages(urls, place_vocab)
    seed_city = loc_prov.get("seed_city") or ""
    if service_axis_override is not None:
        service_axis = [
            {"label": (s.get("label") if isinstance(s, dict) else s) or "", "sources": ["confirmed"]}
            for s in service_axis_override
            if (s.get("label") if isinstance(s, dict) else s)
        ]
        svc_prov: dict = {
            "confirmed": True,
            "kind": "subservice" if tier in (2, 4) else "main_service",
            "notes": ["Service axis edited and confirmed by the team."],
        }
    elif tier in (1, 3):
        # `_derive_service_axis` runs the planner LLM (`_plan_service_axis` →
        # `llm.call_tool`), a blocking multi-second call — offload it so it never
        # stalls the shared event loop the API + every job lane run on (the same
        # reason `_derive_subservice_axis` threads `_generate_service_pages`).
        service_axis, svc_prov = await asyncio.to_thread(
            _derive_service_axis, client, classified, place_vocab
        )
    else:  # tiers 2/4 — expand main services into a city-agnostic subservice axis
        main_axis, main_prov = await asyncio.to_thread(
            _derive_service_axis, client, classified, place_vocab
        )
        sub_axis, sub_prov = await _derive_subservice_axis(client, main_axis, seed_city)
        combined_notes = list(main_prov.get("notes") or []) + list(sub_prov.get("notes") or [])
        if sub_axis:
            service_axis = sub_axis
            svc_prov = {
                "confirmed": False,
                "kind": "subservice",
                "notes": combined_notes,
                "main_service_axis": main_prov,
                "main_services": sub_prov.get("main_services", []),
                "planned_services": sub_prov.get("planned_services", []),
                "failed_services": sub_prov.get("failed_services", []),
                "empty_services": sub_prov.get("empty_services", []),
                "representative_city": seed_city,
            }
        else:
            # Degrade cleanly to the main-service axis (never abort). The report is
            # still useful — it shows main-service coverage — and the team can retry.
            service_axis = main_axis
            svc_prov = {
                "confirmed": False,
                "kind": "main_service_fallback",
                "notes": combined_notes + [_SUBSERVICE_PLANNER_UNAVAILABLE],
                "main_service_axis": main_prov,
                "main_services": sub_prov.get("main_services", []),
            }
    notes.extend(svc_prov.get("notes") or [])

    # 4) Build the AXES-ONLY report grid + diff.
    #    The location-hub keyword uses the primary MAIN service for the main-service
    #    tiers (1/3); the subservice tiers (2/4) drop location rows entirely (below),
    #    so they need no primary and pass None.
    site_index = {
        "token_index": site_page_index.build_page_token_index(urls),
        "location_index": site_page_index.build_location_slug_index(urls),
    }
    in_tool_index = _in_tool_index(client_id)
    # Tiers 1 and 3 carry location-hub rows keyed on the primary MAIN service
    # ("<primary service> <location>"); Tiers 2/4 drop them (below) and pass None.
    primary_service = (
        str(service_axis[0]["label"]) if (tier in (1, 3) and service_axis) else None
    )
    grid = core.build_coverage_grid(
        service_axis, location_axis, site_index, in_tool_index, primary_service=primary_service
    )
    diff = core.diff_coverage(grid)
    if tier in (2, 4):
        # Location-hub rows are a main-service concern (does a city/CDP have a
        # main-service landing page), measured against the MAIN service axis — so a
        # subservice audit (Tier 2 = city, Tier 4 = CDP) drops them (re-reporting
        # would double-count the Tier-1/3 audit and rank against a keyword absent from
        # this tier's axis). Dropping them also keeps the demand fetch from spending on
        # hub keywords this tier won't show. Tiers 1/3 KEEP them (a location hub IS a
        # main-service concept). Decision recorded in provenance.
        diff["missing_locations"] = []

    # 5) Demand — reserve before spend, cache-idempotent.
    market, demand_available, demand_notes = await _fetch_demand(_collect_keywords(diff), location_code)
    notes.extend(demand_notes)

    # Services + locations are few and high-value → ranked unfloored. Cells get the
    # demand FLOOR (plan §8 Major #4) — but only when demand data is actually
    # available; with no demand at all, flooring would hide every gap, so show them.
    cell_floor = settings.coverage_cell_volume_min if demand_available else 0
    if not demand_available:
        notes.append("Demand data unavailable — cells are shown unranked and the demand floor is disabled.")
    ranked_services = core.rank_gaps(diff["missing_services"], market, min_volume=0)
    ranked_locations = core.rank_gaps(diff["missing_locations"], market, min_volume=0)
    ranked_cells = core.rank_gaps(diff["missing_cells"], market, min_volume=cell_floor)

    gaps = {
        "missing_services": ranked_services,
        "missing_locations": ranked_locations,
        "missing_cells": ranked_cells,
        "counts": {
            **grid["counts"],
            "cells_shown": len(ranked_cells),
            "cells_below_floor": grid["counts"]["cells_absent"] - len(ranked_cells),
            "cell_floor": cell_floor,
        },
    }

    # De-duplicate notes (order-preserving) for a clean report banner.
    degraded_notes: list[str] = []
    for n in notes:
        if n and n not in degraded_notes:
            degraded_notes.append(n)

    provenance = {
        "service_axis": svc_prov,
        "location_axis": loc_prov,
        "scan": {"url_count": len(urls), "source": source, "website": website, "sitemap_url": sitemap_url or None},
        "demand": {"available": demand_available, "location_code": location_code},
        # Subservice tiers (2/4) show subservice + subservice×location cell gaps only;
        # the location-hub ("missing locations") rows are a main-service concern (plan
        # §7 / handoff open item, resolved in Phase 2 for Tier 2 and mirrored for Tier
        # 4 in Phase 4). Tiers 1 and 3 keep them (a location hub IS a main-service
        # concept). The frontend keys the location stat + table off this.
        "location_rows_shown": tier in (1, 3),
        "degraded_notes": degraded_notes,
    }

    row = {
        "status": "complete",
        "tier": tier,
        "service_axis": service_axis,
        "location_axis": location_axis,
        "gaps": gaps,
        "provenance": provenance,
        "error": None,
    }
    supabase.table("coverage_audits").update(row).eq("id", audit_id).eq("client_id", client_id).execute()
    logger.info(
        "coverage_audit.tier_complete",
        extra={
            "audit_id": audit_id, "client_id": client_id, "tier": tier,
            "services": len(service_axis), "locations": len(location_axis),
            "cells_shown": len(ranked_cells),
        },
    )
    return {"audit_id": audit_id, "status": "complete"}


# ── async job handler ──────────────────────────────────────────────────────────
async def run_coverage_audit_job(job: dict) -> None:
    """async_jobs handler for job_type='coverage_audit'. One job per tier."""
    payload = job.get("payload") or {}
    job_id = job["id"]
    audit_id = str(payload.get("audit_id") or "")
    client_id = str(payload.get("client_id") or job.get("entity_id") or "")
    tier = int(payload.get("tier") or 1)
    supabase = get_supabase()
    try:
        if not audit_id or not client_id:
            raise ValueError("coverage_audit_missing_ids")
        result = await run_coverage_audit_tier(
            audit_id, client_id, tier,
            service_axis_override=payload.get("service_axis"),
            sitemap_url=payload.get("sitemap_url"),
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job_id).execute()
    except BudgetExceeded:
        _fail_audit(audit_id, client_id, "budget_exceeded")
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "budget_exceeded", "completed_at": "now()"}
        ).eq("id", job_id).execute()
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None) or str(exc)
        logger.warning("coverage_audit.job_failed", extra={"job_id": job_id, "error": str(detail)})
        _fail_audit(audit_id, client_id, str(detail)[:500])
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(detail)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def _fail_audit(audit_id: Optional[str], client_id: Optional[str], error: str) -> None:
    if not audit_id:
        return
    try:
        get_supabase().table("coverage_audits").update(
            {"status": "failed", "error": error}
        ).eq("id", audit_id).eq("client_id", client_id).execute()
    except Exception:  # noqa: BLE001 — the job row already carries the failure
        pass


# ── enqueue / read (for the router) ────────────────────────────────────────────
def enqueue_coverage_audit(
    client_id: str,
    tier: int,
    user_id: Optional[str],
    service_axis: Optional[list] = None,
    sitemap_url: Optional[str] = None,
) -> tuple[str, str]:
    """Create a `coverage_audits` run row (status pending) and enqueue its tier job.
    Returns ``(audit_id, job_id)``. An edited service axis (``service_axis``
    supplied) starts a fresh run — the prior run stays as history. ``sitemap_url``
    (optional) is an explicit sitemap/sitemap-index URL to crawl verbatim; it is
    stored on the run so an edit-axis re-run reuses it."""
    if tier not in SUPPORTED_TIERS:
        raise HTTPException(status_code=400, detail="coverage_audit_tier_unsupported")
    clean_sitemap = (sitemap_url or "").strip() or None
    supabase = get_supabase()
    # Dedup a fresh auto-run: if an audit for this (client, tier) is already
    # pending/running with no edited axis, reuse it instead of stacking a second
    # paid run (a double-click, a client retry, or a second tab). An edited re-run
    # (`service_axis` supplied) always starts fresh — the team asked for a new axis.
    if service_axis is None:
        inflight = (
            supabase.table("async_jobs")
            .select("id, payload")
            .eq("job_type", "coverage_audit")
            .eq("entity_id", client_id)
            .in_("status", ["pending", "running"])
            .execute()
            .data
            or []
        )
        for row in inflight:
            p = row.get("payload") or {}
            if int(p.get("tier") or 0) == tier and p.get("service_axis") is None and p.get("audit_id"):
                return p["audit_id"], row["id"]
    audit = (
        supabase.table("coverage_audits")
        .insert({"client_id": client_id, "status": "pending", "tier": tier, "sitemap_url": clean_sitemap})
        .execute()
    ).data[0]
    audit_id = audit["id"]
    job = (
        supabase.table("async_jobs")
        .insert(
            {
                "job_type": "coverage_audit",
                "entity_id": client_id,
                "payload": {
                    "client_id": client_id,
                    "audit_id": audit_id,
                    "tier": tier,
                    "service_axis": service_axis,
                    "sitemap_url": clean_sitemap,
                    "user_id": user_id,
                },
            }
        )
        .execute()
    ).data[0]
    return audit_id, job["id"]


def get_audit(client_id: str, audit_id: str) -> Optional[dict]:
    rows = (
        get_supabase()
        .table("coverage_audits")
        .select(_AUDIT_COLS)
        .eq("id", audit_id)
        .eq("client_id", client_id)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def list_audits(client_id: str, tier: Optional[int] = None, limit: int = 25) -> list[dict]:
    q = (
        get_supabase()
        .table("coverage_audits")
        .select("id, status, tier, created_at, error")
        .eq("client_id", client_id)
    )
    if tier is not None:
        q = q.eq("tier", tier)
    return q.order("created_at", desc=True).limit(limit).execute().data or []


def latest_audit(client_id: str, tier: int) -> Optional[dict]:
    rows = (
        get_supabase()
        .table("coverage_audits")
        .select(_AUDIT_COLS)
        .eq("client_id", client_id)
        .eq("tier", tier)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


# ── seed a Matrix from a completed audit (AXES ONLY — plan §0.5 / §8 Major #1) ──
async def seed_matrix_from_audit(client_id: str, audit_id: str, user_id: str) -> dict:
    """Create a Service×Location Matrix seeded with the audit tier's FULL axes
    (every service × every location). AXES ONLY: `create_matrix` builds the cells
    and marks their coverage itself — the audit never writes a cell verdict."""
    from services import local_seo_matrix_store

    audit = get_audit(client_id, audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="coverage_audit_not_found")
    if audit.get("status") != "complete":
        raise HTTPException(status_code=409, detail="coverage_audit_not_complete")

    client = local_seo_silo._get_client(client_id)
    service_axis = audit.get("service_axis") or []
    location_axis = audit.get("location_axis") or []
    if not core._axis_names(service_axis) or not core._axis_names(location_axis):
        raise HTTPException(status_code=400, detail="coverage_audit_axes_empty")

    tier = audit.get("tier") or 1
    name = f"Coverage Audit T{tier} — {client.get('name') or 'client'}"
    body = core.build_matrix_seed_body(
        name=name,
        location=_seed_location(client) or (audit.get("provenance") or {}).get("location_axis", {}).get("seed_city") or "",
        location_code=location_code_for(client),
        service_axis=service_axis,
        location_axis=location_axis,
    )
    matrix = await local_seo_matrix_store.create_matrix(client_id, body, user_id)
    logger.info(
        "coverage_audit.matrix_seeded",
        extra={"client_id": client_id, "audit_id": audit_id, "matrix_id": matrix.get("id")},
    )
    return matrix

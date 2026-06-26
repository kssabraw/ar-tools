"""Local SEO silo planner (#2) — service-variation + neighborhood page targets.

Behind the "Plan Silo" tab. Given a **service + city** it produces two kinds of
candidate local page targets:

  1. **Service silos** — a single LLM call (Sonnet — `_generate_service_pages`,
     `local_seo_service_model`) expands the input service into the distinct
     service-variation landing pages a local business should have, grouped into
     silos. The model plans from the **ideal customer's** perspective: it's handed
     the client's rendered ICP (+ differentiators) via
     `icp_service.resolve_icp_text` when one is on file, and infers the realistic
     ideal customer for the service/city itself when it isn't — then enumerates the
     customer's distinct buying situations and maps each to a commercial landing
     page. The variation kinds are *examples it picks from*, not a fixed taxonomy:
     availability/urgency (24 hour, after hours, same day — only for breakdown /
     time-pressure services, never planned work like roof restoration),
     audience/property (commercial, residential, strata — only the audiences a
     trade actually splits by), trade-specific job/problem types generated from the
     service itself (roof restoration → leak repair, tile replacement, storm
     damage…; an emergency plumber → burst pipe, blocked drain, hot water…), and
     customer trigger/situation silos (insurance claim, storm damage, pre-sale…).
     Every page must stay commercial/transactional (no informational/blog topics).
     Sonnet rather than Haiku: the customer reasoning + silo-relevance judgement and
     trade-specific modifiers need stronger world knowledge — Haiku stamped generic
     urgency/audience buckets onto non-urgency services and anchored on the
     prompt's plumber example. The service's own qualifier is
     preserved — an "emergency plumber" stays an *emergency* service, never
     broadening to a bare "plumber" — and no suburb names appear here (that's the
     Neighborhoods silo's job). The model returns only each variation's *modifier*
     and the keyword is composed deterministically as
     `"<modifier> <service> <city>"`, so the full service phrase is always present
     (e.g. `"after hours emergency plumber Sydney"`, never `"after hours plumber
     Sydney"`). Each page also carries a few same-intent supporting keywords.

  2. **Neighborhoods silo** — geocoding-verified. It proposes the city's
     sub-areas (Haiku — in whatever local term fits the country: neighborhoods,
     suburbs, districts), then geocodes the city + each candidate and keeps only
     those whose centre falls inside the city's geocoded footprint
     (`place_is_within_city`). Country-agnostic — it works for a US neighborhood
     nested in the city's locality and an AU/UK suburb that is its own locality
     alike, because it verifies geography, not name nesting — and drops adjacent
     towns, oversized regions, and centroid-fallback bogus names.

Both steps are best-effort and gated on the Anthropic (+ Google Maps for
neighborhoods) keys; without them the rest of the plan is unaffected (a degraded
note explains why). It runs as an `async_jobs` job (job_type='local_seo_silo');
the route enqueues + polls. (The earlier Topic-Fanout keyword-expansion pipeline
was dropped here — it broadened too far and surfaced generic-service + suburb
noise the service silos kept having to filter out.)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import HTTPException

from config import settings
from db.supabase_client import get_supabase
from services import site_page_index, target_cities

logger = logging.getLogger(__name__)

# Neighborhood discovery. The seed service is paired with each verified
# neighborhood ("<service> <neighborhood>") as a page target under this silo.
_NEIGHBORHOOD_SILO = "Neighborhoods"
# Google place types too big to be a within-city sub-area. A candidate that
# geocodes to one of these (e.g. an LLM proposed a county/state) is rejected even
# if its centre happens to fall inside the city box. Everything smaller —
# locality (AU/UK suburb), sublocality, neighborhood, postal_town, etc. — is
# allowed and gated geographically instead (see `place_is_within_city`).
_TOO_BIG_TYPES = frozenset({
    "administrative_area_level_1", "administrative_area_level_2",
    "administrative_area_level_3", "country", "continent",
})


def _get_client(client_id: str) -> dict:
    supabase = get_supabase()
    res = supabase.table("clients").select("*").eq("id", client_id).single().execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="client_not_found")
    return res.data


async def start_silo_plan(
    client_id: str,
    keyword: str,
    location: str,
    location_code: Optional[int],
    user_id: str,
) -> str:
    """Validate the area, then enqueue a `local_seo_silo` job. Returns the job id.

    One plan in flight per client — a pending/running job is reused rather than
    stacking another expensive pipeline run."""
    from services import locations_service

    client = _get_client(client_id)
    canonical_location, resolved_code = await locations_service.resolve_location(
        client, location, location_code
    )

    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "local_seo_silo")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]

    res = (
        supabase.table("async_jobs")
        .insert(
            {
                "job_type": "local_seo_silo",
                "entity_id": client_id,
                "payload": {
                    "client_id": client_id,
                    "keyword": keyword.strip(),
                    "location": canonical_location,
                    "location_code": resolved_code,
                    "user_id": user_id,
                },
            }
        )
        .execute()
    )
    return res.data[0]["id"]


def get_silo_plan(job_id: str, client_id: str) -> dict:
    """Read a plan job's row. Returns {status, items, degraded_notes, error}.

    Scoped to the client (the job's `entity_id`) so a job id can't be polled
    across clients."""
    supabase = get_supabase()
    res = (
        supabase.table("async_jobs")
        .select("status, result, error, entity_id")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    if not res.data or res.data[0].get("entity_id") != client_id:
        raise HTTPException(status_code=404, detail="silo_plan_not_found")
    row = res.data[0]
    result = row.get("result") or {}
    return {
        "status": row["status"],
        "items": result.get("items", []),
        "degraded_notes": result.get("degraded_notes", []),
        "error": row.get("error"),
    }


# ── worker handler ───────────────────────────────────────────────────────────

async def run_silo_plan_job(job: dict) -> None:
    """async_jobs handler for job_type='local_seo_silo'.

    The Fanout pipeline is blocking (synchronous DataForSEO + LLM + clustering),
    so it runs in a worker thread to keep platform-api's event loop responsive."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    keyword = (payload.get("keyword") or "").strip()
    location = (payload.get("location") or "").strip()
    location_code = payload.get("location_code")
    job_id = job["id"]
    supabase = get_supabase()

    logger.info(
        "local_seo_silo.started",
        extra={"job_id": job_id, "client_id": client_id, "keyword": keyword},
    )
    try:
        if not keyword:
            raise ValueError("keyword_required")

        # Ground the silo planning in the client's ideal customer. Best-effort: a
        # missing/failed ICP fetch just means the model infers the customer instead.
        icp_block = ""
        try:
            from services import icp_service

            icp_block = icp_service.resolve_icp_text(_get_client(client_id))
        except Exception as exc:  # noqa: BLE001 — ICP grounding is non-critical
            logger.warning("local_seo_silo.icp_fetch_failed", extra={"client_id": client_id, "error": str(exc)})

        plan = await asyncio.to_thread(_run_pipeline, keyword, location, location_code, icp_block)
        # Append a geocoding-verified "Neighborhoods" silo (within-city only). It's
        # an additive best-effort step, so a defensive failure here must never sink
        # an otherwise-good plan — belt-and-suspenders around its own internal
        # guards.
        try:
            neigh_entry, neigh_notes = await _discover_neighborhood_silo(
                keyword, location, plan["per_silo"], supabase
            )
        except Exception as exc:  # noqa: BLE001 — neighborhoods are non-critical
            logger.warning(
                "local_seo_silo.neighborhoods_unexpected_error",
                extra={"job_id": job_id, "client_id": client_id, "error": str(exc)},
            )
            neigh_entry, neigh_notes = None, ["Neighborhood pages skipped — unexpected error."]
        if neigh_entry:
            plan["per_silo"].append(neigh_entry)
        plan["degraded_notes"] = [*plan.get("degraded_notes", []), *neigh_notes]

        # Expand beyond the seed city to the other cities the business targets —
        # its GBP service area, a manual list, place-names on its own site, and
        # cities within ~10 miles (Overpass). Each becomes its own silo: a
        # "<service> <city>" page plus that city's verified neighborhoods. Threads
        # the running keyword set so a place shared across cities isn't planned
        # twice. Best-effort — its own guards keep a failure from sinking the plan.
        try:
            existing_keys = {
                p["keyword"].strip().lower()
                for g in plan["per_silo"] for p in g.get("pages", [])
            }
            client = _get_client(client_id)
            cities, city_notes = await target_cities.resolve_target_cities(
                client, location, location_code, supabase
            )
            city_silos, sub_notes = await _build_target_city_silos(
                keyword, cities, existing_keys, supabase
            )
            plan["per_silo"].extend(city_silos)
            plan["degraded_notes"].extend([*city_notes, *sub_notes])
        except Exception as exc:  # noqa: BLE001 — extra cities are non-critical
            logger.warning(
                "local_seo_silo.target_cities_failed",
                extra={"job_id": job_id, "client_id": client_id, "error": str(exc)},
            )
            plan["degraded_notes"].append("Additional target cities skipped — discovery error.")

        # Check the client's live site for generic location pages (e.g.
        # /inner-west/) so areas that already have one are flagged `on_site`
        # rather than offered for creation. Best-effort — its own guards keep a
        # failure from sinking the plan.
        site_index, site_note = await _build_site_location_index(client_id, location_code)
        if site_note:
            plan["degraded_notes"].append(site_note)
        items = _to_items(plan["per_silo"], client_id, site_index)

        supabase.table("async_jobs").update(
            {
                "status": "complete",
                "result": {"items": items, "degraded_notes": plan.get("degraded_notes", [])},
                "completed_at": "now()",
            }
        ).eq("id", job_id).execute()
        logger.info(
            "local_seo_silo.complete",
            extra={"job_id": job_id, "client_id": client_id, "items": len(items)},
        )
    except Exception as exc:
        logger.warning(
            "local_seo_silo.failed",
            extra={"job_id": job_id, "client_id": client_id, "error": str(exc)},
        )
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


def _run_pipeline(
    keyword: str, location: str, location_code: Optional[int] = None, icp_block: str = "",
) -> dict:
    """Blocking: generate the service-variation page topics for "<service> <city>"
    with one LLM call (Sonnet — no keyword-expansion tool), planned from the ideal
    customer's perspective (`icp_block` = the client's rendered ICP, or "" to let the
    model infer it). Returns
    {"per_silo": [{"silo": name, "pages": [{keyword, supporting_keywords}, ...]}],
    "degraded_notes": [...]}; the Neighborhoods silo is appended by the job handler.

    `location_code` is accepted for signature compatibility but unused — the planner
    no longer drives DataForSEO (the city is parsed from `location`)."""
    city = _parse_area(location)[0] or location.strip()
    llm = _service_llm()
    if not llm:
        return {"per_silo": [], "degraded_notes": ["Service pages skipped — content model not configured."]}
    try:
        per_silo = _generate_service_pages(keyword, city, llm, icp_block)
    except Exception as exc:  # noqa: BLE001 — surface as a degraded note, not a crash
        logger.warning("local_seo_silo.service_gen_failed", extra={"error": str(exc)})
        return {"per_silo": [], "degraded_notes": ["Service pages unavailable — could not generate."]}
    notes = [] if per_silo else ["No service-variation pages were generated."]
    return {"per_silo": per_silo, "degraded_notes": notes}


# ── service-variation generation (LLM — replaces the keyword-expansion tool) ───

_SERVICE_SYSTEM = (
    "You are a local SEO strategist who plans landing pages by thinking as the "
    "business's IDEAL CUSTOMER. Given a SERVICE, a CITY, and (optionally) that "
    "client's customer profile, produce the set of distinct service-variation landing "
    "pages the business should have, grouped into silos.\n"
    "HOW TO THINK:\n"
    "1. Establish the ideal customer. If a CUSTOMER PROFILE is given below, treat it "
    "as authoritative. If none is given, infer the realistic ideal customer(s) for "
    "this service in this city yourself before planning.\n"
    "2. As that customer, enumerate the DISTINCT buying situations that would make "
    "them search for this service and expect a DIFFERENT page -- their reasons, "
    "triggers, property types, and problems. Group these into silos by the kind of "
    "distinction.\n"
    "3. Turn each into a commercial landing page. Use ONLY the distinction kinds this "
    "customer genuinely has -- the kinds below are EXAMPLES, not a required set; omit "
    "any that don't fit and add others the customer clearly needs:\n"
    "   - urgency / timing (24 hour, after hours, same day, emergency): ONLY when the "
    "customer buys under time pressure or when something has broken -- NOT for "
    "planned / project work like roof restoration, renovations, or installations "
    "(nobody searches 'after hours roof restoration');\n"
    "   - audience / property (commercial, residential, strata, industrial): only the "
    "segments this customer base actually splits into, none if it doesn't;\n"
    "   - job / problem type: the specific variations of the work this customer needs "
    "(e.g. roof restoration -> leak repair, tile replacement, storm damage; emergency "
    "plumber -> burst pipe, blocked drain, hot water) -- from your own knowledge of "
    "the trade, NOT copied from these examples;\n"
    "   - trigger / situation the customer is in (e.g. insurance claim, storm damage, "
    "pre-sale, new purchase) when it drives a distinct search.\n"
    "KEEP EVERY PAGE COMMERCIAL: each must be a transactional service page someone "
    "would search to HIRE a provider -- NEVER informational or blog topics (no 'how "
    "much does X cost', 'X vs Y', 'is X worth it', 'guide', 'tips').\n"
    "OUTPUT RULES: for each page return ONLY the MODIFIER -- the few words that "
    "distinguish the variation -- NOT the full phrase; the service and city are "
    "attached automatically as '<modifier> <service> <city>' (so modifier 'storm "
    "damage' for service 'roof restoration' in 'Melbourne' becomes 'storm damage roof "
    "restoration Melbourne'). The modifier is JUST the variation words -- NEVER repeat "
    "the service words (e.g. 'plumber', 'emergency'), the city, or any suburb / "
    "neighbourhood name (suburbs are handled separately). Include ONE base page with "
    "an empty modifier (\"\") for the service itself. Each page's supporting_keywords "
    "are 0-3 full search phrases for the SAME page that DO include the full service "
    "(close phrasings / plurals / word-order variants). Quality over quantity -- only "
    "real, distinct, commercial page topics this customer would actually search."
)

_SERVICE_SCHEMA = {
    "type": "object",
    "properties": {
        "silos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "pages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "modifier": {
                                    "type": "string",
                                    "description": "Variation words ONLY (e.g. 'after hours', 'burst pipe', 'commercial'); empty for the base service page.",
                                },
                                "supporting_keywords": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["modifier", "supporting_keywords"],
                        },
                    },
                },
                "required": ["name", "pages"],
            },
        }
    },
    "required": ["silos"],
}


def _service_llm():
    """Construct the service-generation LLM client (Sonnet — `local_seo_service_model`),
    or None when the Anthropic key is absent."""
    if not settings.anthropic_api_key:
        return None
    try:
        from fanout.llm.anthropic_client import AnthropicLLM

        return AnthropicLLM(
            api_key=settings.anthropic_api_key,
            model=settings.local_seo_service_model,
            max_tokens=2048,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("local_seo_silo.service_client_failed", extra={"error": str(exc)})
        return None


def _compose_service_keyword(modifier: str, service: str, city: str) -> str:
    """Splice a service-silo page keyword as "<modifier> <service> <city>", always
    keeping the FULL service phrase. The model returns only the variation modifier
    (e.g. "after hours", "burst pipe", "commercial"); composing the service in
    deterministically means the qualifier can never be dropped (Haiku kept dropping
    it when asked to emit whole phrases — "after hours plumber" instead of "after
    hours emergency plumber"). Any service- OR city-word the model echoed into the
    modifier is stripped so a redundant qualifier or a leaked city/suburb doesn't
    duplicate (e.g. modifier "emergency"/"hot water emergency" for service
    "emergency plumber", or modifier "plumber sydney" which must not yield
    "sydney emergency plumber Sydney"); an empty modifier yields the base
    "<service> <city>" page."""
    service = (service or "").strip()
    city = (city or "").strip()
    drop_words = {w.lower() for w in service.split()} | {w.lower() for w in city.split()}
    mod_words = [w for w in (modifier or "").split() if w.lower() not in drop_words]
    modifier = " ".join(mod_words).strip()
    head = f"{modifier} {service}".strip() if modifier else service
    return f"{head} {city}".strip()


def _generate_service_pages(service: str, city: str, llm, icp_block: str = "") -> list[dict]:
    """Sonnet tool-use: the service-variation landing pages for "<service> <city>",
    grouped into silos, planned from the IDEAL CUSTOMER's perspective. `icp_block`
    is the client's rendered ICP (+ differentiators) when available; absent it, the
    model infers the ideal customer for the service/city itself. The model returns
    only each page's MODIFIER (the variation words); the full keyword is composed
    deterministically as "<modifier> <service> <city>" so the service qualifier is
    always present. Returns [{"silo": name, "pages": [{keyword, supporting_keywords}]}],
    deduped across silos by composed keyword (first silo wins). The LLM is injected so
    this is unit-testable without the network."""
    user = f"Service: {service}\nCity: {city}"
    if icp_block.strip():
        user += (
            "\n\nCUSTOMER PROFILE (the client's ideal customer — plan the silos as this "
            f"person, around their situations and needs):\n{icp_block.strip()}"
        )
    else:
        user += (
            "\n\nNo customer profile is on file — infer the realistic ideal customer for "
            "this service in this city, then plan the silos around that customer."
        )
    try:
        data = llm.call_tool(
            system=_SERVICE_SYSTEM,
            user=user,
            tool_name="service_pages",
            tool_description="Service-variation landing pages for the service in the city, grouped into silos.",
            input_schema=_SERVICE_SCHEMA,
            purpose="local_seo_silo/service_pages",
            temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"service_gen_failed: {exc}") from exc

    service_words = {w.lower() for w in service.split()}
    per_silo: list[dict] = []
    seen: set[str] = set()  # dedupe composed page keywords across all silos (first wins)
    for silo in data.get("silos") or []:
        name = (silo.get("name") or "").strip()
        if not name:
            continue
        pages: list[dict] = []
        for page in silo.get("pages") or []:
            kw = _compose_service_keyword(page.get("modifier") or "", service, city)
            key = kw.lower()
            if not kw or key in seen:
                continue
            seen.add(key)
            supporting: list[str] = []
            sup_seen: set[str] = {key}
            for s in page.get("supporting_keywords") or []:
                sk = (s or "").strip()
                if not sk or sk.lower() in sup_seen:
                    continue
                # Keep only chips that carry the full service (every service word
                # present, any order) so a supporting variant can't quietly drop the
                # qualifier the way the page keyword used to.
                if not service_words.issubset({w.lower() for w in sk.split()}):
                    continue
                sup_seen.add(sk.lower())
                supporting.append(sk)
            pages.append({"keyword": kw, "supporting_keywords": supporting})
        if pages:
            per_silo.append({"silo": name, "pages": pages})

    # Safety net: guarantee the base "<service> <city>" page exists even if the
    # model omitted the empty-modifier page.
    base_kw = _compose_service_keyword("", service, city)
    if base_kw and base_kw.lower() not in seen and per_silo:
        per_silo[0]["pages"].insert(0, {"keyword": base_kw, "supporting_keywords": []})
    return per_silo


# ── neighborhood discovery (geocoding-verified, within-city) ──────────────────

_NEIGHBORHOOD_SYSTEM = (
    "You are a local SEO expert with strong worldwide geographic knowledge. Given "
    "a place (with its state/region and country), list the real, recognized "
    "sub-areas WITHIN it that locals name — use whatever term is correct for that "
    "country: neighborhoods or districts (US), suburbs (Australia / NZ), "
    "areas/wards/boroughs (UK), barrios, quartiers, etc. Include only sub-areas "
    "inside that place's own city/metropolitan area; never separate towns or "
    "cities, counties/LGAs, regions, states, postcodes, or landmarks. If it has "
    "few recognized sub-areas, return fewer — quality over quantity. Return the "
    "local names only, with no city/country suffix."
)

_NEIGHBORHOOD_SCHEMA = {
    "type": "object",
    "properties": {
        "neighborhoods": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Local sub-area names (neighborhoods / suburbs / districts) within the place.",
        }
    },
    "required": ["neighborhoods"],
}


def _parse_area(location: str) -> tuple[str, str, str]:
    """Split a DataForSEO canonical area into (city, state, country). The US
    canonical is "City,State,Country" (3 segments); a 2-segment area is
    "City,Country" (e.g. "London,United Kingdom"), so the second segment is the
    country — not a state. Degrades gracefully for a bare city."""
    parts = [p.strip() for p in (location or "").split(",") if p.strip()]
    city = parts[0] if parts else ""
    if len(parts) >= 3:
        state, country = parts[1], parts[-1]
    elif len(parts) == 2:
        state, country = "", parts[1]
    else:
        state, country = "", ""
    return city, state, country


def place_is_within_city(candidate: dict, city_geo: dict) -> bool:
    """True when a forward-geocoded candidate is a real sub-area geographically
    INSIDE the target city — country-agnostic. Works for a US neighborhood
    (nested in the city's locality) and an AU/UK suburb (its own locality) alike,
    because it checks geography, not name nesting:

      1. it resolved to a place that isn't the city itself / a centroid fallback
         (distinct place_id), and
      2. it isn't a region bigger than a town (no county/state/country type), and
      3. its centre falls inside the city's geocoded footprint (bounds, padded),
         or — when the city has no footprint — within a radius of the city centre.

    Pure; unit-tested."""
    import services.maps_geocode as mg

    if not candidate or not candidate.get("matched"):
        return False
    if not city_geo or not city_geo.get("matched"):
        return False
    cpid, citypid = candidate.get("place_id"), city_geo.get("place_id")
    if cpid and citypid and cpid == citypid:
        return False  # snapped to the city itself — a bogus / centroid-fallback name
    types = {str(t).lower() for t in (candidate.get("result_types") or [])}
    if types & _TOO_BIG_TYPES:
        return False  # a county / state / country, not a sub-area
    lat, lng = candidate.get("lat"), candidate.get("lng")
    if lat is None or lng is None:
        return False
    bounds = city_geo.get("bounds")
    if bounds:
        return mg.point_in_bounds(lat, lng, bounds, pad=settings.local_seo_city_bounds_pad)
    clat, clng = city_geo.get("lat"), city_geo.get("lng")
    if clat is None or clng is None:
        return False
    return mg.haversine_km(lat, lng, clat, clng) <= settings.local_seo_neighborhood_radius_km


def _propose_neighborhoods(city: str, state: str, country: str, max_n: int) -> list[str]:
    """Haiku tool-use: candidate sub-areas within the place, in whatever local term
    fits the country (neighborhood / suburb / district). Geocoding verifies them
    downstream, so a rough list is fine. Blocking — call via a thread."""
    from fanout.llm.anthropic_client import AnthropicError, AnthropicLLM

    llm = AnthropicLLM(
        api_key=settings.anthropic_api_key,
        model=settings.local_seo_neighborhood_model,
        max_tokens=1024,
    )
    where = ", ".join(p for p in (city, state, country) if p)
    try:
        data = llm.call_tool(
            system=_NEIGHBORHOOD_SYSTEM,
            user=(
                f"Place: {where}. List up to {max_n} distinct sub-areas (neighborhoods, "
                "suburbs, or districts — whatever locals call them) located inside this "
                "place's own city/metro area."
            ),
            tool_name="list_neighborhoods",
            tool_description="Return local sub-areas located within the given place.",
            input_schema=_NEIGHBORHOOD_SCHEMA,
            purpose="local_seo_silo/neighborhoods",
            temperature=0.0,
        )
    except AnthropicError as exc:
        raise ValueError(f"neighborhood_llm_failed: {exc}") from exc

    seen: set[str] = set()
    names: list[str] = []
    for raw in data.get("neighborhoods") or []:
        name = (raw or "").strip()
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names[:max_n]


def _query_area(*parts: str) -> str:
    return ", ".join(p for p in parts if p)


async def _neighborhoods_for_city(
    keyword: str, city: str, state: str, country: str, city_geo: dict,
    existing: set[str], supabase,
) -> tuple[list[dict], list[str]]:
    """Core sub-area discovery for ONE already-geocoded city: propose its sub-areas,
    keep those that geocode-verify inside `city_geo`'s footprint, and return
    "<service> <sub-area>" page dicts (each carrying its bare `location_name`),
    skipping any keyword already in `existing`. Pure best-effort; reused for the
    seed city and every additional target city."""
    try:
        names = await asyncio.to_thread(
            _propose_neighborhoods, city, state, country, settings.local_seo_max_neighborhoods
        )
    except Exception as exc:
        logger.warning("local_seo_silo.neighborhoods_propose_failed", extra={"city": city, "error": str(exc)})
        return [], [f"Sub-areas for {city} skipped — could not list them."]
    if not names:
        return [], []

    from services import maps_geocode

    queries = {name: _query_area(name, city, state, country) for name in names}
    try:
        geo = await maps_geocode.forward_geocode_places(list(queries.values()), supabase=supabase)
    except Exception as exc:
        logger.warning("local_seo_silo.neighborhoods_geocode_failed", extra={"city": city, "error": str(exc)})
        return [], [f"Sub-areas for {city} skipped — geocoding lookup failed."]

    pages: list[dict] = []
    for name in names:
        if not place_is_within_city(geo.get(queries[name]) or {}, city_geo):
            continue
        page_kw = f"{keyword} {name}".strip()
        key = page_kw.lower()
        if key not in existing:
            existing.add(key)
            # `location_name` (the bare sub-area) lets the existing-page check match
            # a generic location page on the client's site (e.g. /inner-west/) by
            # place, independent of the service prefix in the keyword.
            pages.append({"keyword": page_kw, "supporting_keywords": [], "location_name": name})
    return pages, []


async def _discover_neighborhood_silo(
    keyword: str, location: str, per_silo: list[dict], supabase,
) -> tuple[Optional[dict], list[str]]:
    """Seed-city "Neighborhoods" silo: geocode the seed city for its footprint, then
    run `_neighborhoods_for_city`. Country-agnostic and best-effort — any failure or
    missing prerequisite yields no silo + a degraded note, never an aborted plan."""
    city, state, country = _parse_area(location)
    if not city:
        return None, ["Neighborhood pages skipped — no city in the area."]
    if not settings.anthropic_api_key:
        return None, ["Neighborhood pages skipped — content model not configured."]
    if not settings.google_maps_api_key:
        return None, [
            "Neighborhood pages skipped — geocoding not configured, so sub-areas "
            "can't be verified as within the city."
        ]

    from services import maps_geocode

    city_query = _query_area(city, state, country)
    try:
        geo = await maps_geocode.forward_geocode_places([city_query], supabase=supabase)
    except Exception as exc:
        logger.warning("local_seo_silo.neighborhoods_geocode_failed", extra={"error": str(exc)})
        return None, ["Neighborhood pages skipped — geocoding lookup failed."]

    city_geo = geo.get(city_query) or {}
    if not city_geo.get("matched") or (not city_geo.get("bounds") and city_geo.get("lat") is None):
        return None, ["Neighborhood pages skipped — couldn't resolve the city to verify sub-areas."]

    existing = {p["keyword"].strip().lower() for g in per_silo for p in g.get("pages", [])}
    pages, notes = await _neighborhoods_for_city(
        keyword, city, state, country, city_geo, existing, supabase
    )
    if not pages:
        return None, notes or ["No sub-areas could be verified within the city."]
    return {"silo": _NEIGHBORHOOD_SILO, "pages": pages}, notes


async def _build_target_city_silos(
    keyword: str, additional_cities: list[dict], existing: set[str], supabase,
) -> tuple[list[dict], list[str]]:
    """One silo per additional target city: a "<service> <city>" location page plus
    that city's geocode-verified neighborhoods (full sub-division). `existing` is
    threaded across cities so a place shared between them isn't planned twice.
    Best-effort per city — a city that fails sub-division still contributes its own
    location page."""
    silos: list[dict] = []
    notes: list[str] = []
    for city in additional_cities:
        name = city["name"]
        # The city itself as a location page (carries location_name for the
        # live-site existing-page check, like a neighborhood does).
        city_pages: list[dict] = []
        city_kw = f"{keyword} {name}".strip()
        if city_kw.lower() not in existing:
            existing.add(city_kw.lower())
            city_pages.append({"keyword": city_kw, "supporting_keywords": [], "location_name": name})

        city_geo = {
            "matched": True,
            "place_id": city.get("place_id"),
            "lat": city.get("lat"),
            "lng": city.get("lng"),
            "bounds": city.get("bounds"),
        }
        if settings.anthropic_api_key and (city_geo["bounds"] or city_geo["lat"] is not None):
            sub_pages, sub_notes = await _neighborhoods_for_city(
                keyword, name, city.get("state", ""), city.get("country", ""),
                city_geo, existing, supabase,
            )
            city_pages.extend(sub_pages)
            notes.extend(sub_notes)
        if city_pages:
            silos.append({"silo": name, "pages": city_pages})
    return silos, notes


def _to_items(
    per_silo: list[dict], client_id: str, site_index: Optional[dict[str, str]] = None,
) -> list[dict]:
    """Flatten silos → page targets, marking each:

      - ``found``   — a page already generated in the tool (`local_seo_pages`,
                      matched on keyword); ``url`` is its published doc, and
      - ``on_site`` — a generic location page for this place already exists on the
                      client's live site (`site_index`, matched on the page's bare
                      `location_name`); ``url`` is the live page, else
      - ``missing`` — nothing yet; offer it for creation.

    `found` wins over `on_site` (a page we built and track is the more actionable
    record). Only location targets carry a `location_name`, so the live-site check
    applies to area/location pages — not service-variation pages."""
    supabase = get_supabase()
    site_index = site_index or {}
    existing: dict[str, dict] = {}
    try:
        rows = (
            supabase.table("local_seo_pages")
            .select("keyword, published_doc_url")
            .eq("client_id", client_id)
            .execute()
            .data
            or []
        )
        for r in rows:
            kw = (r.get("keyword") or "").strip().lower()
            if kw:
                existing.setdefault(kw, r)
    except Exception as exc:
        logger.warning(
            "local_seo_silo.existing_lookup_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )

    items: list[dict] = []
    for group in per_silo:
        silo = group["silo"]
        for page in group["pages"]:
            kw = page["keyword"]
            match = existing.get(kw.strip().lower())
            if match:
                status, url = "found", match.get("published_doc_url")
            else:
                site_url = (
                    site_page_index.match_site_location_page(
                        page.get("location_name") or "", site_index
                    )
                    if page.get("location_name")
                    else None
                )
                status, url = ("on_site", site_url) if site_url else ("missing", None)
            items.append(
                {
                    "keyword": kw,
                    "group": silo,
                    "status": status,
                    "url": url,
                    "supporting_keywords": page.get("supporting_keywords", []),
                }
            )
    return items


async def _build_site_location_index(
    client_id: str, location_code: Optional[int],
) -> tuple[dict[str, str], Optional[str]]:
    """Discover the client's existing location pages from their live site. Returns
    ``(slug→url index, degraded_note)`` — the note is set only when the check is
    skipped or had to fall back, never on a clean sitemap read. Best-effort: any
    failure yields an empty index + an explanatory note, never an aborted plan."""
    try:
        client = _get_client(client_id)
    except HTTPException:
        return {}, None
    website = (client.get("gbp") or {}).get("website") or client.get("website_url") or ""
    if not website.strip():
        return {}, (
            "Existing-page check skipped — no website on file, so every area shows "
            "as missing. Add the client's website to detect location pages already "
            "on the site."
        )

    code = location_code
    if not code:
        try:
            from services.dataforseo_rank import location_code_for

            code = location_code_for(client)
        except Exception:  # noqa: BLE001 — only needed for the DataForSEO fallback
            code = settings.dataforseo_default_location_code

    try:
        urls, source = await site_page_index.discover_site_urls(website, code)
    except Exception as exc:  # noqa: BLE001 — discovery is non-critical
        logger.warning(
            "local_seo_silo.site_discovery_failed",
            extra={"client_id": client_id, "error": str(exc)},
        )
        return {}, "Existing-page check skipped — couldn't read the client's site."

    if source == "none":
        return {}, (
            "Existing-page check skipped — couldn't read the site's sitemap or "
            "find it in Google's index, so existing location pages may be missed."
        )
    note = None
    if source == "google_index":
        note = (
            "No sitemap found — checked Google's index for existing location pages "
            "instead (may be less complete)."
        )
    return site_page_index.build_location_slug_index(urls), note

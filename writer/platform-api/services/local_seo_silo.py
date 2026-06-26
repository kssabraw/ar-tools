"""Local SEO silo planner (#2) — service-variation + neighborhood page targets.

Behind the "Plan Silo" tab. Given a **service + city** it produces two kinds of
candidate local page targets:

  1. **Service silos** — a single Haiku call (`_generate_service_pages`) expands
     the input service into the distinct service-variation landing pages a local
     business should have, grouped into silos by the kind of variation:
     availability/urgency (24 hour, after hours, weekend), audience/property
     (commercial, residential, strata), and trade-specific job/problem types
     (burst pipe, blocked drain, hot water…). The service's own qualifier is
     preserved — an "emergency plumber" stays an *emergency* service, never
     broadening to a bare "plumber" — and no suburb names appear here (that's the
     Neighborhoods silo's job). Each page is `"<variation> <city>"` plus a few
     same-intent supporting keywords.

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
    # DataForSEO Labs (keyword expansion + competitor mining) only accepts a
    # COUNTRY-level location code; the city code drives degraded task errors. Pin
    # the country once at enqueue time so the worker uses it for the Labs calls
    # (the city stays in the seed/SERP).
    country_code = await locations_service.resolve_country_code(client)

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
                    "country_location_code": country_code,
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
    country_location_code = payload.get("country_location_code")
    job_id = job["id"]
    supabase = get_supabase()

    logger.info(
        "local_seo_silo.started",
        extra={"job_id": job_id, "client_id": client_id, "keyword": keyword},
    )
    try:
        if not keyword:
            raise ValueError("keyword_required")

        plan = await asyncio.to_thread(
            _run_pipeline, keyword, location, location_code, country_location_code
        )
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
        items = _to_items(plan["per_silo"], client_id)

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
    keyword: str, location: str, location_code: Optional[int] = None,
    country_location_code: Optional[int] = None,
) -> dict:
    """Blocking: generate the service-variation page topics for "<service> <city>"
    with one Haiku call (no keyword-expansion tool). Returns
    {"per_silo": [{"silo": name, "pages": [{keyword, supporting_keywords}, ...]}],
    "degraded_notes": [...]}; the Neighborhoods silo is appended by the job handler.

    `location_code` / `country_location_code` are accepted for signature
    compatibility but unused — the planner no longer drives DataForSEO."""
    city = _parse_area(location)[0] or location.strip()
    llm = _service_llm()
    if not llm:
        return {"per_silo": [], "degraded_notes": ["Service pages skipped — content model not configured."]}
    try:
        per_silo = _generate_service_pages(keyword, city, llm)
    except Exception as exc:  # noqa: BLE001 — surface as a degraded note, not a crash
        logger.warning("local_seo_silo.service_gen_failed", extra={"error": str(exc)})
        return {"per_silo": [], "degraded_notes": ["Service pages unavailable — could not generate."]}
    return {"per_silo": per_silo, "degraded_notes": []}


# ── service-variation generation (LLM — replaces the keyword-expansion tool) ───

_SERVICE_SYSTEM = (
    "You are a local SEO strategist. Given a SERVICE and a CITY, produce the set of "
    "distinct service-variation landing pages a local business offering that service "
    "should have, grouped into silos by the kind of variation. Apply only modifiers "
    "that genuinely fit THIS service:\n"
    "  - Availability / urgency: 24 hour, after hours, weekend, same day, emergency "
    "(when not already in the service);\n"
    "  - Audience / property: commercial, residential, strata, industrial;\n"
    "  - Job / problem type for the trade: e.g. for an emergency plumber -- burst "
    "pipe, blocked drain, hot water, gas leak, leaking tap; for a roofer -- leak "
    "repair, storm damage, re-roofing, gutter.\n"
    "ALWAYS keep the service's own qualifier -- an 'emergency plumber' stays an "
    "EMERGENCY service; never broaden to a bare 'plumber'. Do NOT add suburb / "
    "neighbourhood names (handled separately) -- the only location is the CITY. Each "
    "page's keyword is the natural search phrase '<variation> <city>'. Include the "
    "base service ('<service> <city>') as one page. Give each page 0-3 "
    "supporting_keywords that are close phrasings / plurals / word-order variants of "
    "the same intent. Quality over quantity -- only real, distinct page topics."
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
                                "keyword": {"type": "string"},
                                "supporting_keywords": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["keyword", "supporting_keywords"],
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
    """Construct the Haiku service-generation client, or None when the Anthropic
    key is absent."""
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


def _generate_service_pages(service: str, city: str, llm) -> list[dict]:
    """Haiku tool-use: the service-variation landing pages for "<service> <city>",
    grouped into silos. Returns [{"silo": name, "pages": [{keyword,
    supporting_keywords}]}], deduped across silos by keyword (first silo wins).
    The LLM is injected so this is unit-testable without the network."""
    try:
        data = llm.call_tool(
            system=_SERVICE_SYSTEM,
            user=f"Service: {service}\nCity: {city}",
            tool_name="service_pages",
            tool_description="Service-variation landing pages for the service in the city, grouped into silos.",
            input_schema=_SERVICE_SCHEMA,
            purpose="local_seo_silo/service_pages",
            temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"service_gen_failed: {exc}") from exc

    per_silo: list[dict] = []
    seen: set[str] = set()  # dedupe page keywords across all silos (first wins)
    for silo in data.get("silos") or []:
        name = (silo.get("name") or "").strip()
        if not name:
            continue
        pages: list[dict] = []
        for page in silo.get("pages") or []:
            kw = (page.get("keyword") or "").strip()
            key = kw.lower()
            if not kw or key in seen:
                continue
            seen.add(key)
            supporting: list[str] = []
            sup_seen: set[str] = {key}
            for s in page.get("supporting_keywords") or []:
                sk = (s or "").strip()
                if sk and sk.lower() not in sup_seen:
                    sup_seen.add(sk.lower())
                    supporting.append(sk)
            pages.append({"keyword": kw, "supporting_keywords": supporting})
        if pages:
            per_silo.append({"silo": name, "pages": pages})
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


async def _discover_neighborhood_silo(
    keyword: str, location: str, per_silo: list[dict], supabase,
) -> tuple[Optional[dict], list[str]]:
    """Propose sub-areas of the target city, geocode-verify each falls inside the
    city's footprint, and return a "Neighborhoods" silo of "<service> <sub-area>"
    page targets (deduped against the silos already planned). Country-agnostic and
    best-effort: any failure or missing prerequisite yields no silo + a degraded
    note, never an aborted plan."""
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

    try:
        names = await asyncio.to_thread(
            _propose_neighborhoods, city, state, country, settings.local_seo_max_neighborhoods
        )
    except Exception as exc:
        logger.warning("local_seo_silo.neighborhoods_propose_failed", extra={"error": str(exc)})
        return None, ["Neighborhood pages skipped — could not list sub-areas."]
    if not names:
        return None, []

    from services import maps_geocode

    def _query(*parts: str) -> str:
        return ", ".join(p for p in parts if p)

    # Geocode the city itself (for its footprint) alongside the candidates, in one
    # cached batch.
    city_query = _query(city, state, country)
    queries = {name: _query(name, city, state, country) for name in names}
    try:
        geo = await maps_geocode.forward_geocode_places(
            [city_query, *queries.values()], supabase=supabase
        )
    except Exception as exc:
        logger.warning("local_seo_silo.neighborhoods_geocode_failed", extra={"error": str(exc)})
        return None, ["Neighborhood pages skipped — geocoding lookup failed."]

    city_geo = geo.get(city_query) or {}
    if not city_geo.get("matched") or (not city_geo.get("bounds") and city_geo.get("lat") is None):
        return None, ["Neighborhood pages skipped — couldn't resolve the city to verify sub-areas."]

    # Keywords already planned in other silos — don't re-surface a sub-area page
    # the Fanout expansion already produced.
    existing = {p["keyword"].strip().lower() for g in per_silo for p in g.get("pages", [])}
    pages: list[dict] = []
    seen: set[str] = set()
    for name in names:
        if not place_is_within_city(geo.get(queries[name]) or {}, city_geo):
            continue
        page_kw = f"{keyword} {name}".strip()
        key = page_kw.lower()
        if key not in existing and key not in seen:
            seen.add(key)
            pages.append({"keyword": page_kw, "supporting_keywords": []})

    if not pages:
        return None, ["No sub-areas could be verified within the city."]
    return {"silo": _NEIGHBORHOOD_SILO, "pages": pages}, []


def _to_items(per_silo: list[dict], client_id: str) -> list[dict]:
    """Flatten silos → page targets, marking each found/missing against the
    client's already-generated `local_seo_pages` (matched on keyword)."""
    supabase = get_supabase()
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
            items.append(
                {
                    "keyword": kw,
                    "group": silo,
                    "status": "found" if match else "missing",
                    "url": (match or {}).get("published_doc_url"),
                    "supporting_keywords": page.get("supporting_keywords", []),
                }
            )
    return items

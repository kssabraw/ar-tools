"""Target-city discovery for the Local SEO silo planner.

The planner is seeded with one **service + city**, but a local business usually
serves several cities. This resolves the *full set of cities to plan for* from
four sources, then geocodes + filters them so only real, nearby localities
survive:

  1. **seed** — the city the user entered (always the primary; returned separately
     by the caller, so it's excluded from the *additional* list here).
  2. **gbp** — Google Business Profile "service area" places we capture at fetch
     time (`clients.gbp.service_area_places`).
  3. **manual** — cities the team typed on the client (`clients.target_cities`).
  4. **website** — place-name slugs from the client's own site (reusing the
     sitemap index built for the existing-page check), de-hyphenated to names.
  5. **nearby** — cities/towns within a radius of the seed city, enumerated from
     OpenStreetMap via Overpass (Google has no list-within-radius endpoint).

Authoritative sources (gbp/manual) are kept regardless of distance — the business
explicitly serves there. Discovered sources (website/nearby) must geocode to a
city-level locality and sit within a distance bound, to keep noise out. Every
candidate is forward-geocoded (cached) for its centre/bounds so neighborhood
sub-division can run per city. Best-effort throughout: a dead source contributes
nothing and adds a degraded note, never an aborted plan.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import settings
from services import maps_geocode, overpass, site_page_index

logger = logging.getLogger(__name__)

# Google place types too coarse to be a target *city* (county/state/country).
_TOO_BIG_TYPES = frozenset({
    "administrative_area_level_1", "administrative_area_level_2",
    "administrative_area_level_3", "country", "continent",
})
# City-level result types we accept for *discovered* candidates (website/nearby).
_CITY_LEVEL_TYPES = frozenset({"locality", "postal_town"})


def _parse_area(location: str) -> tuple[str, str, str]:
    """(city, state, country) from a DataForSEO canonical area — mirrors
    local_seo_silo._parse_area (duplicated to avoid a circular import)."""
    parts = [p.strip() for p in (location or "").split(",") if p.strip()]
    city = parts[0] if parts else ""
    if len(parts) >= 3:
        state, country = parts[1], parts[-1]
    elif len(parts) == 2:
        state, country = "", parts[1]
    else:
        state, country = "", ""
    return city, state, country


def _slug_to_name(slug: str) -> str:
    """A site path slug back to a candidate place name: 'inner-west' → 'Inner West'."""
    return " ".join(w for w in slug.replace("_", "-").split("-") if w).title()


def website_candidate_names(urls: list[str]) -> list[str]:
    """Distinct candidate place names from a site's URL path slugs. Heuristic — the
    geocode filter downstream discards anything that isn't a real city."""
    seen: set[str] = set()
    names: list[str] = []
    for url in urls:
        for slug in site_page_index.url_path_slugs(url):
            name = _slug_to_name(slug)
            key = name.lower()
            if name and key not in seen:
                seen.add(key)
                names.append(name)
    return names


def _query(*parts: str) -> str:
    return ", ".join(p for p in parts if p)


async def resolve_target_cities(
    client: dict, seed_location: str, location_code: Optional[int], supabase,
) -> tuple[list[dict], list[str]]:
    """Return ``(additional_cities, degraded_notes)``. Each city is
    ``{name, lat, lng, bounds, place_id, state, country, source}`` and excludes the
    seed city. Caps at `local_seo_max_target_cities`."""
    notes: list[str] = []
    seed_city, seed_state, seed_country = _parse_area(seed_location)
    if not seed_city:
        return [], notes
    if not settings.google_maps_api_key:
        return [], ["Extra target cities skipped — geocoding not configured."]

    # 1) Candidate names from the authoritative + website sources, with provenance.
    sources: dict[str, str] = {}  # normalized name → source (first source wins)
    _names: dict[str, str] = {}   # normalized name → display name

    def _add(name: str, source: str) -> None:
        nm = (name or "").strip()
        key = nm.lower()
        if nm and key != seed_city.lower() and key not in sources:
            sources[key] = source
            _names[key] = nm

    gbp = client.get("gbp") or {}
    for nm in gbp.get("service_area_places") or []:
        _add(nm, "gbp")
    for nm in client.get("target_cities") or []:
        _add(nm, "manual")

    website = (gbp.get("website") or client.get("website_url") or "").strip()
    if website:
        try:
            urls, _src = await site_page_index.discover_site_urls(website, location_code or 0)
            for nm in website_candidate_names(urls):
                _add(nm, "website")
        except Exception as exc:  # noqa: BLE001 — website source is non-critical
            logger.warning("target_cities.website_failed", extra={"error": str(exc)})

    # 2) Geocode the seed (for its centre) plus the candidates gathered so far.
    seed_query = _query(seed_city, seed_state, seed_country)
    cand_queries = {key: _query(_names[key], seed_state, seed_country) for key in sources}
    try:
        geo = await maps_geocode.forward_geocode_places(
            [seed_query, *cand_queries.values()], supabase=supabase
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("target_cities.geocode_failed", extra={"error": str(exc)})
        return [], ["Extra target cities skipped — geocoding lookup failed."]

    seed_geo = geo.get(seed_query) or {}
    seed_lat, seed_lng = seed_geo.get("lat"), seed_geo.get("lng")
    seed_pid = seed_geo.get("place_id")

    # 3) Nearby cities within the radius (Overpass), then geocode their names too.
    if seed_lat is not None and seed_lng is not None:
        try:
            nearby = await overpass.nearby_cities(
                seed_lat, seed_lng, settings.local_seo_nearby_city_radius_km
            )
        except Exception as exc:  # noqa: BLE001 — Overpass is best-effort
            logger.warning("target_cities.overpass_failed", extra={"error": str(exc)})
            nearby = []
            notes.append("Nearby-city lookup unavailable — used the named sources only.")
        new_nearby = {}
        for c in nearby:
            key = (c.get("name") or "").strip().lower()
            if key and key != seed_city.lower() and key not in sources:
                sources[key] = "nearby"
                _names[key] = c["name"]
                new_nearby[key] = _query(c["name"], seed_state, seed_country)
        if new_nearby:
            try:
                geo.update(
                    await maps_geocode.forward_geocode_places(list(new_nearby.values()), supabase=supabase)
                )
                cand_queries.update(new_nearby)
            except Exception as exc:  # noqa: BLE001
                logger.warning("target_cities.nearby_geocode_failed", extra={"error": str(exc)})
    elif not seed_geo.get("matched"):
        notes.append("Couldn't resolve the seed city — nearby cities were not searched.")

    # 4) Keep real, distinct localities; bound discovered sources by distance.
    radius = settings.local_seo_nearby_city_radius_km
    website_max_km = radius * settings.local_seo_website_city_radius_mult
    kept: list[dict] = []
    seen_pids: set[str] = set()
    for key, source in sources.items():
        cg = geo.get(cand_queries[key]) or {}
        if not cg.get("matched"):
            continue
        pid = cg.get("place_id")
        if pid and (pid == seed_pid or pid in seen_pids):
            continue
        types = {str(t).lower() for t in (cg.get("result_types") or [])}
        if types & _TOO_BIG_TYPES:
            continue
        lat, lng = cg.get("lat"), cg.get("lng")
        dist = (
            maps_geocode.haversine_km(seed_lat, seed_lng, lat, lng)
            if None not in (seed_lat, seed_lng, lat, lng)
            else None
        )
        if source in ("website", "nearby"):
            if not (types & _CITY_LEVEL_TYPES):
                continue
            limit = radius if source == "nearby" else website_max_km
            if dist is None or dist > limit:
                continue
        if pid:
            seen_pids.add(pid)
        kept.append({
            "name": _names[key],
            "lat": lat,
            "lng": lng,
            "bounds": cg.get("bounds"),
            "place_id": pid,
            "state": cg.get("admin_area") or seed_state,
            "country": cg.get("country") or seed_country,
            "source": source,
            "_dist": dist if dist is not None else 1e9,
        })

    # 5) Order by intent (authoritative first, then by proximity) and cap.
    _rank = {"gbp": 0, "manual": 0, "website": 1, "nearby": 2}
    kept.sort(key=lambda c: (_rank.get(c["source"], 9), c["_dist"]))
    cap = settings.local_seo_max_target_cities
    if len(kept) > cap:
        notes.append(f"Target cities capped at {cap} (found {len(kept)}).")
        kept = kept[:cap]
    for c in kept:
        c.pop("_dist", None)
    return kept, notes

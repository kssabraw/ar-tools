"""Coverage Audit Tier 3 — Census-Designated-Place (CDP) enumeration (worker-only).

Tier 3 is *CDP × main-service*: the ONLY delta from Tier 1 is the **location
axis** — the authoritative Census CDP list for the client's service area, instead
of `target_cities.resolve_target_cities`' cities. The service axis stays the main
services (the runner reuses the Tier-1 path).

This is a **new census integration** (plan §3.2 / §8 Major #2), not a reuse of
`census_demand.py`: that module queries the TIGERweb *block-group* layer; nothing
enumerates CDPs. Here we query a **different** ArcGIS-REST layer (the Census
Designated Places layer, same `tigerweb.geo.census.gov` host) — sharing only the
host + access pattern. **census.gov is egress-blocked from the sandbox** (as with
`census_demand.py` / `leadoff_geocode.py`), so the live TIGERweb query is built +
tested on the deployed worker only. The pure decision helpers around it
(`pick_cdp_layer`, `parse_cdp_features`, `footprint_bbox`, `point_in_bbox`,
`build_footprint_geos`, `county_scope`, `assemble_cdp_axis`, `is_stale`) are
sandbox-unit-tested; the network call itself is isolated + mocked.

The three steps (plan §3.2):

  (a) **service area → county FIPS.** Forward-geocode the seed city + the resolved
      target cities (`resolve_target_cities`, cache-served) → their centres →
      reverse-geocode each centre to its county via the free census
      `geographies/coordinates` endpoint (reuse `leadoff_counties._county_for_coord`,
      the same census.gov family). The **states** those counties belong to are the
      TIGERweb enumeration unit; the counties record the scope.

      **CDP county scope (owner decision, plan §7): the counties the resolved
      service-area cities sit in** (city-anchored), and a CDP is kept ONLY if it
      geocode-verifies inside the service-area footprint (step c). Counties merely
      scope which states we enumerate + are recorded in provenance; the footprint
      containment gate is what actually decides membership. This bounds the census
      pulls to the counties the client demonstrably operates in — never a broad
      radius-edge probe — while the containment gate keeps far CDPs out.

  (b) **TIGERweb CDP-layer query.** Per state (the cacheable unit — a state's CDP
      set is static, so it's cached in `census_cdp_cache` keyed by state FIPS and
      SHARED across every client in that state), enumerate the Census Designated
      Places with their centroids. Pre-filter to the service-area footprint bbox
      (pure, free) so only CDPs near the client survive to verification.

  (c) **verify containment against the footprint.** Each surviving CDP's
      AUTHORITATIVE Census centroid (from step b) is checked against the footprint
      cities with `maps_geocode.place_is_within_city` — kept only when it falls
      inside a resolved footprint city. We do NOT forward-geocode the CDP name: the
      centroid is exact, and geocoding "<CDP>, <seed_state>" would mislocate a CDP in
      a DIFFERENT state of a multi-state footprint (e.g. Kansas City straddles
      MO/KS) and re-introduce Google name ambiguity — so the centroid check is both
      more correct and free.

**No paid DataForSEO calls** happen in CDP resolution — it's all keyless census +
one cached Google forward-geocode for the seed/footprint cities (the CDPs
themselves are verified by centroid, no per-CDP geocode) — so the
`coverage_audit_usage` meter is untouched by the location axis. Best-effort
throughout: no key / dead source / no counties
resolved → the CDP tier degrades with a visible note, never aborts (mirrors the
`resolve_target_cities` geocoding-unavailable pattern). Idempotent — a reaper
requeue finds every cache warm and re-bills nothing.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from config import settings

logger = logging.getLogger(__name__)

# TIGERweb ArcGIS REST — same host + service as census_demand.py's block-group
# fetch, but a DIFFERENT layer (Census Designated Places, resolved by name).
_TIGERWEB_SERVICE = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/"
    "TIGERweb/tigerWMS_Current/MapServer"
)
_RETRY_WAITS = [8, 30]
_PAGE_SIZE = 2000  # ArcGIS page size for the per-state CDP enumeration
_MAX_PAGES = 20    # safety cap on pagination (a state has at most ~1.5k CDPs)
_KM_PER_DEGREE_LAT = 111.0

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; AR-Tools-CoverageAudit/1.0; "
                   "+https://amazingrankings.com)"),
    "Accept": "application/json",
}


# ── pure helpers (unit-tested — no I/O) ────────────────────────────────────────
def _coerce_coord(raw: Any) -> Optional[float]:
    """TIGERweb CENTLAT/CENTLON strings ('+41.87…') → float, or None."""
    try:
        return float(str(raw).lstrip("+"))
    except (TypeError, ValueError):
        return None


def pick_cdp_layer(layers: list[dict[str, Any]]) -> Optional[int]:
    """The TIGERweb layer id for the **Census Designated Places** polygon layer,
    from the service metadata (robust to layer-id drift across TIGER vintages).

    Mirrors `census_demand.pick_bg_layer`: prefer the exact "census designated
    place(s)" name and exclude label + tribal layers (tigerWMS_Current also carries
    "…Labels" annotation layers and an "American Indian … Places" family). Pure."""
    for layer in layers:
        name = str(layer.get("name") or "").lower()
        if "census designated place" in name and "label" not in name:
            return layer.get("id")
    for layer in layers:
        name = str(layer.get("name") or "").lower()
        if (
            "designated place" in name
            and "label" not in name
            and "tribal" not in name
            and "american indian" not in name
        ):
            return layer.get("id")
    return None


def parse_cdp_features(resp_json: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Parse a TIGERweb CDP-layer query into ``([{name, geoid, lat, lng}], exceeded)``.

    ``exceeded`` is the ArcGIS ``exceededTransferLimit`` flag, so the caller can
    page. A feature with no name or no centroid is dropped (can't place/verify it).
    Pure."""
    feats: list[dict[str, Any]] = []
    for feat in resp_json.get("features") or []:
        attrs = feat.get("attributes") or {}
        name = str(attrs.get("NAME") or attrs.get("BASENAME") or "").strip()
        geoid = str(attrs.get("GEOID") or "").strip()
        lat = _coerce_coord(attrs.get("CENTLAT") or attrs.get("INTPTLAT"))
        lng = _coerce_coord(attrs.get("CENTLON") or attrs.get("INTPTLON"))
        if name and lat is not None and lng is not None:
            feats.append({"name": name, "geoid": geoid, "lat": lat, "lng": lng})
    return feats, bool(resp_json.get("exceededTransferLimit"))


def footprint_bbox(
    centers: list[tuple[Optional[float], Optional[float]]], pad_km: float
) -> Optional[tuple[float, float, float, float]]:
    """(lat_min, lat_max, lng_min, lng_max) enclosing every footprint city centre,
    padded by ``pad_km`` on each side (longitude scaled by cos(lat)). The cheap,
    free pre-filter that trims a state's CDPs to the client's area before the
    geocode-verify. Returns None when no centre has coordinates. Pure."""
    pts = [(la, ln) for la, ln in centers if la is not None and ln is not None]
    if not pts:
        return None
    lats = [p[0] for p in pts]
    lngs = [p[1] for p in pts]
    mid = sum(lats) / len(lats)
    dlat = pad_km / _KM_PER_DEGREE_LAT
    cos_lat = max(math.cos(math.radians(mid)), 1e-6)
    dlng = pad_km / (_KM_PER_DEGREE_LAT * cos_lat)
    return (min(lats) - dlat, max(lats) + dlat, min(lngs) - dlng, max(lngs) + dlng)


def point_in_bbox(
    lat: Optional[float], lng: Optional[float],
    bbox: Optional[tuple[float, float, float, float]],
) -> bool:
    """Is a CDP centroid inside the padded footprint bbox? Pure."""
    if bbox is None or lat is None or lng is None:
        return False
    la_min, la_max, ln_min, ln_max = bbox
    return la_min <= lat <= la_max and ln_min <= lng <= ln_max


def build_footprint_geos(
    seed_geo: Optional[dict], target_cities: Optional[list[dict]]
) -> list[dict]:
    """The list of footprint city geos `place_is_within_city` verifies a CDP
    against — the seed city (a forward-geocode result, used as-is) plus each
    resolved target city, synthesised into the ``{matched, place_id, lat, lng,
    bounds}`` shape `place_is_within_city` reads (`resolve_target_cities` strips
    `matched`). A city with no coordinates is skipped (can't bound it). Pure."""
    out: list[dict] = []
    if seed_geo and seed_geo.get("matched") and seed_geo.get("lat") is not None:
        out.append(seed_geo)
    for c in target_cities or []:
        lat, lng = c.get("lat"), c.get("lng")
        if lat is None or lng is None:
            continue
        out.append({
            "matched": True,
            "place_id": c.get("place_id"),
            "lat": lat,
            "lng": lng,
            "bounds": c.get("bounds"),
            "result_types": [],
        })
    return out


def resolve_seed_place(
    seed_geo: Optional[dict],
    parsed_city: str,
    parsed_state: str,
    parsed_country: str,
) -> tuple[str, str, str]:
    """The clean ``(city, state, country)`` for the service area, preferring the
    seed forward-geocode's OWN address components over the comma-split of the raw
    ``business_location``.

    ``local_seo_silo._parse_area`` assumes DataForSEO's canonical
    ``"City,State,Country"`` and takes segment[0] as the city — but a client's
    ``business_location`` is often a full street address
    (``"2890 Marina Mile Blvd, 108 W State Rd 84 Suite, Fort Lauderdale, FL 33312"``),
    so it mis-reads the street as the city and the suite/zip as the state/country.
    The seed geocode resolves the address to its real ``locality`` (Fort
    Lauderdale) / ``administrative_area_level_1`` (Florida) / ``country`` (United
    States), which is what the CDP footprint + verify queries need. Falls back to
    each parsed value when the geocode lacks that component (a bare-city location
    is unchanged). Pure; unit-tested."""
    geo = seed_geo or {}
    city = (geo.get("city") or "").strip() or parsed_city
    state = (geo.get("admin_area") or "").strip() or parsed_state
    country = (geo.get("country") or "").strip() or parsed_country
    return city, state, country


def county_scope(
    county_results: Optional[list[tuple[str, str]]]
) -> tuple[list[str], list[str]]:
    """From the reverse-geocode ``(county_name, county_fips)`` results, the deduped
    sorted ``(county_fips, state_fips)`` lists. A 5-digit county FIPS's first two
    digits are its state FIPS — the TIGERweb enumeration unit. Pure."""
    counties: set[str] = set()
    states: set[str] = set()
    for res in county_results or []:
        if not res:
            continue
        fips = str(res[1] or "").strip()
        if len(fips) == 5 and fips.isdigit():
            counties.add(fips)
            states.add(fips[:2])
    return sorted(counties), sorted(states)


def assemble_cdp_axis(names: Optional[list[str]], cap: int = 0) -> list[dict]:
    """The verified CDP names → the location-axis shape (``{name, source}``, matching
    `resolve_target_cities`' rows so it flows through `build_coverage_grid` /
    `build_matrix_seed_body` byte-identically). Deduped case-insensitively, ordered
    by name, capped at ``cap`` (0 = uncapped). Pure."""
    seen: set[str] = set()
    out: list[dict] = []
    for raw in names or []:
        nm = (raw or "").strip()
        key = nm.lower()
        if nm and key not in seen:
            seen.add(key)
            out.append({"name": nm, "source": "census_cdp"})
    out.sort(key=lambda x: x["name"].lower())
    if cap and len(out) > cap:
        out = out[:cap]
    return out


def is_stale(pulled_at: Any, refresh_days: int) -> bool:
    """Pure staleness check for a cached row's pulled_at (0/negative days → never
    stale). Unparseable → stale (re-pull)."""
    if refresh_days <= 0:
        return False
    try:
        ts = datetime.fromisoformat(str(pulled_at))
    except (TypeError, ValueError):
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts < datetime.now(timezone.utc) - timedelta(days=refresh_days)


def _area_query(*parts: str) -> str:
    return ", ".join(p for p in parts if p)


# ── per-state CDP cache (census_cdp_cache) ─────────────────────────────────────
def state_cdps_cached(state_fips: str, refresh_days: int) -> Optional[list[dict]]:
    """The cached CDP list for a state, or None when absent/stale (→ the caller
    re-enumerates from TIGERweb). Best-effort: any read failure → None."""
    from db.supabase_client import get_supabase

    try:
        rows = (
            get_supabase()
            .table("census_cdp_cache")
            .select("cdps, pulled_at")
            .eq("state_fips", state_fips)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001 — cache is best-effort
        logger.warning("census_cdp.cache_read_failed", extra={"state": state_fips, "error": str(exc)})
        return None
    if not rows:
        return None
    if is_stale(rows[0].get("pulled_at"), refresh_days):
        return None
    cdps = rows[0].get("cdps")
    return cdps if isinstance(cdps, list) else []


def _write_state_cdps(supabase, state_fips: str, cdps: list[dict]) -> None:
    try:
        supabase.table("census_cdp_cache").upsert(
            {
                "state_fips": state_fips,
                "cdps": cdps,
                "pulled_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="state_fips",
        ).execute()
    except Exception as exc:  # noqa: BLE001 — cache write never blocks the tier
        logger.warning("census_cdp.cache_write_failed", extra={"state": state_fips, "error": str(exc)})


# ── TIGERweb network (worker-only — census.gov egress-blocked from the sandbox) ─
async def _get_json(client, url: str, params: dict) -> Any:
    """GET with the browser-ish headers + transient-retry the census hosts need
    (mirrors census_demand._get_json). Returns parsed JSON, or None on a
    hard/parse failure. Imports httpx lazily so the pure helpers stay importable."""
    import httpx

    for attempt in range(len(_RETRY_WAITS) + 1):
        try:
            resp = await client.get(url, params=params, headers=_HEADERS, timeout=120.0)
            if resp.status_code in (429, 500, 502, 503, 504):
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException) as exc:
            transient = not (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code not in (429, 500, 502, 503, 504)
            )
            if transient and attempt < len(_RETRY_WAITS):
                import asyncio
                await asyncio.sleep(_RETRY_WAITS[attempt])
                continue
            logger.warning("census_cdp.get_failed", extra={"url": url, "error": str(exc)[:200]})
            return None
        except ValueError:
            return None
    return None


async def _resolve_cdp_layer(client) -> Optional[int]:
    """The TIGERweb Census-Designated-Places layer id, from the service metadata."""
    meta = await _get_json(client, _TIGERWEB_SERVICE, {"f": "json"})
    if not isinstance(meta, dict):
        return None
    return pick_cdp_layer(meta.get("layers") or [])


async def _fetch_state_cdps(client, state_fips: str, layer_id: int) -> list[dict]:
    """Every CDP in a state from TIGERweb (paginated). ``where=STATE='SS'`` is a
    deterministic, cacheable enumeration; outFields keep the name + centroid so the
    footprint pre-filter needs no geometry."""
    url = f"{_TIGERWEB_SERVICE}/{layer_id}/query"
    out: list[dict] = []
    offset = 0
    for _ in range(_MAX_PAGES):
        params = {
            "where": f"STATE='{state_fips}'",
            "outFields": "NAME,BASENAME,GEOID,CENTLAT,CENTLON,INTPTLAT,INTPTLON",
            "returnGeometry": "false",
            "orderByFields": "GEOID",
            "resultOffset": offset,
            "resultRecordCount": _PAGE_SIZE,
            "f": "json",
        }
        data = await _get_json(client, url, params)
        if not isinstance(data, dict):
            break
        feats, exceeded = parse_cdp_features(data)
        out.extend(feats)
        # Advance by the number of rows the SERVER returned, not the parsed count:
        # a page can drop rows (no name/centroid), and stepping resultOffset by the
        # smaller parsed count would re-request the dropped tail on the next page
        # (deduped downstream, but wasted calls). `raw_count` also gates the loop, so
        # a page of all-unparseable rows still makes progress rather than breaking early.
        raw_count = len(data.get("features") or [])
        if not exceeded or not raw_count:
            break
        offset += raw_count
    return out


# ── the CDP location axis (orchestration) ──────────────────────────────────────
async def resolve_cdp_axis(
    client: dict, seed_location: str, location_code: Optional[int], supabase,
    center: Optional[tuple[float, float]] = None,
    radius_km: Optional[float] = None,
) -> tuple[list[dict], dict, list[str]]:
    """Resolve the Tier-3 CDP location axis for a client's service area.

    Returns ``(cdp_axis, provenance, city_names)``:
      * ``cdp_axis`` — the verified CDP location axis (``[{name, source}]``);
      * ``provenance`` — how it was derived (counties/states/candidate+verified
        counts + degraded notes) for the report banner;
      * ``city_names`` — the resolved footprint city names (seed + targets), which
        the runner uses as the classifier's **place vocabulary** so the MAIN-service
        axis is derived correctly even when the CDP axis degrades (a Tier-3 service
        page is still ``/service-city/``, so cities — not CDPs — strip its place
        tokens). CDP names are added to the vocabulary by the runner too.

    Best-effort: no seed / no maps key / no counties / dead census → an empty axis
    with a visible note (never raises)."""
    from services import local_seo_silo

    seed_city, seed_state, seed_country = local_seo_silo._parse_area(seed_location)
    city_names: list[str] = [seed_city] if seed_city else []
    prov: dict = {
        "kind": "cdp",
        "seed_city": seed_city,
        "counties": [],
        "county_names": [],
        "states": [],
        "candidates": 0,
        "verified": 0,
        "footprint_cities": list(city_names),
        "notes": [],
    }
    if not seed_city:
        prov["notes"].append("No business location — the CDP tier can't resolve a service area.")
        return [], prov, city_names
    if not settings.google_maps_api_key:
        prov["notes"].append(
            "Geocoding unavailable — the CDP tier needs GOOGLE_MAPS_API_KEY to resolve and verify CDPs."
        )
        return [], prov, city_names

    from services import maps_geocode, target_cities

    # 1) Footprint: forward-geocode the seed location (cache-served) + resolve the
    #    target cities (one resolve_target_cities call — same as Tier 1/2).
    #    Geocode the RAW business_location (the most complete string), not the
    #    comma-split — `_parse_area` mis-reads a street address, and the raw string
    #    resolves to the real city regardless.
    seed_query = (seed_location or "").strip() or _area_query(seed_city, seed_state, seed_country)
    try:
        geo = await maps_geocode.forward_geocode_places([seed_query], supabase=supabase)
    except Exception as exc:  # noqa: BLE001
        logger.warning("census_cdp.seed_geocode_failed", extra={"error": str(exc)})
        prov["notes"].append("CDP tier skipped — couldn't geocode the seed city.")
        return [], prov, city_names
    seed_geo = geo.get(seed_query) or {}
    if not seed_geo.get("matched") or seed_geo.get("lat") is None:
        prov["notes"].append("CDP tier skipped — couldn't resolve the seed city to verify CDPs.")
        return [], prov, city_names

    # Adopt the geocode's OWN locality/admin/country over the (possibly
    # street-address) comma-split, so the seed city, footprint containment, the
    # classifier place vocab, the CDP verify queries, and the Tier-4 representative
    # city all use the real city (e.g. "Fort Lauderdale", not "2890 Marina Mile Blvd").
    seed_city, seed_state, seed_country = resolve_seed_place(
        seed_geo, seed_city, seed_state, seed_country
    )
    prov["seed_city"] = seed_city
    city_names = [seed_city] if seed_city else []

    # Prefer a CITY-level geo (with real city bounds) for containment: the raw seed
    # geocode of a street address has a rooftop-sized box that no CDP falls inside.
    # Re-geocode the clean city; fall back to the raw seed geo if that misses.
    seed_footprint_geo = seed_geo
    city_query = _area_query(seed_city, seed_state, seed_country)
    if city_query and city_query.strip().lower() != seed_query.strip().lower():
        try:
            city_geo_map = await maps_geocode.forward_geocode_places([city_query], supabase=supabase)
        except Exception as exc:  # noqa: BLE001 — best-effort; the raw seed geo still works
            logger.warning("census_cdp.city_geocode_failed", extra={"error": str(exc)})
            city_geo_map = {}
        city_geo = city_geo_map.get(city_query) or {}
        if city_geo.get("matched") and city_geo.get("bounds") and city_geo.get("lat") is not None:
            seed_footprint_geo = city_geo

    try:
        cities, city_notes = await target_cities.resolve_target_cities(
            client, seed_location, location_code, supabase
        )
    except Exception as exc:  # noqa: BLE001 — city discovery is best-effort
        logger.warning("census_cdp.target_cities_failed", extra={"error": str(exc)})
        cities, city_notes = [], []
    prov["notes"].extend(city_notes)
    for c in cities:
        nm = (c.get("name") or "").strip()
        if nm and nm.lower() != seed_city.lower():
            city_names.append(nm)
    prov["footprint_cities"] = list(dict.fromkeys(city_names))

    footprint_geos = build_footprint_geos(seed_footprint_geo, cities)
    centers = [(g.get("lat"), g.get("lng")) for g in footprint_geos]
    bbox = footprint_bbox(centers, settings.local_seo_neighborhood_radius_km)
    if not bbox:
        prov["notes"].append("CDP tier skipped — no geocoded footprint to search within.")
        return [], prov, city_names

    # 2) Resolve the footprint counties → states (Scope B), then enumerate CDPs per
    #    state (cached), pre-filtered to the footprint bbox. All census.gov —
    #    no paid DataForSEO calls, so nothing is metered.
    import httpx

    from services import leadoff_counties

    candidates: list[dict] = []
    try:
        async with httpx.AsyncClient(follow_redirects=True) as hc:
            county_results: list[tuple[str, str]] = []
            for lat, lng in centers:
                if lat is None or lng is None:
                    continue
                try:
                    res = await leadoff_counties._county_for_coord(hc, lat, lng)
                except Exception:  # noqa: BLE001 — one bad centre never sinks the run
                    res = None
                if res:
                    county_results.append(res)
            counties, states = county_scope(county_results)
            prov["counties"] = counties
            prov["states"] = states
            prov["county_names"] = sorted({r[0] for r in county_results if r and r[0]})
            if not states:
                prov["notes"].append(
                    "Couldn't resolve the service-area counties from census — CDP tier skipped."
                )
                return [], prov, city_names

            layer_id: Optional[int] = None
            for st in states:
                st_cdps = state_cdps_cached(st, settings.coverage_cdp_cache_days)
                if st_cdps is None:
                    if layer_id is None:
                        layer_id = await _resolve_cdp_layer(hc)
                    if layer_id is None:
                        prov["notes"].append("Census CDP layer unavailable — CDP tier degraded.")
                        continue
                    st_cdps = await _fetch_state_cdps(hc, st, layer_id)
                    # NEVER cache an empty enumeration: every US state has CDPs, so
                    # [] means a transient TIGERweb failure, not truth. Caching it
                    # fresh would serve zero CDPs for coverage_cdp_cache_days (365) to
                    # EVERY client in the state until the row goes stale. Mirrors
                    # census_demand.py's `if rows:` upsert guard.
                    if st_cdps:
                        _write_state_cdps(supabase, st, st_cdps)
                    else:
                        prov["notes"].append(
                            f"Census returned no CDPs for state {st} (likely a transient "
                            "TIGERweb failure) — not cached; a retry will re-fetch."
                        )
                for cdp in st_cdps:
                    lat, lng = cdp.get("lat"), cdp.get("lng")
                    name = (cdp.get("name") or "").strip()
                    # Keep every in-bbox CDP (no dedup here): a same-named CDP can
                    # exist in two footprint states, and only one may be inside the
                    # footprint — containment decides per-centroid, name-dedup is at
                    # the end.
                    if name and point_in_bbox(lat, lng, bbox):
                        candidates.append({"name": name, "lat": lat, "lng": lng})
    except Exception as exc:  # noqa: BLE001 — census/TIGERweb is best-effort
        logger.warning("census_cdp.enumeration_failed", extra={"error": str(exc)})
        prov["notes"].append("CDP enumeration failed — tier degraded.")
        return [], prov, city_names

    prov["candidates"] = len(candidates)
    if not candidates:
        prov["notes"].append("No CDPs found within the service-area footprint.")
        return [], prov, city_names

    # 3) Verify containment using each CDP's AUTHORITATIVE Census centroid against
    #    the footprint (reuse place_is_within_city). We deliberately do NOT
    #    forward-geocode the CDP name here: geocoding "<CDP>, <seed_state>" mislocates
    #    a CDP that sits in a DIFFERENT state of a multi-state footprint (e.g. Kansas
    #    City straddles MO/KS — a KS CDP queried as "…, Missouri" resolves wrong or
    #    not at all and gets dropped), and it re-introduces Google name ambiguity for
    #    common CDP names. The TIGERweb centroid is exact, so a synthetic locality
    #    candidate built from it feeds the same bounds/radius check with no extra
    #    paid geocode and no state-string coupling. Name-dedup is applied here (via
    #    `seen`) so a CDP kept in two states counts once.
    verified: list[str] = []
    seen: set[str] = set()
    beyond_radius = 0
    for cand in candidates:
        key = cand["name"].lower()
        if key in seen:
            continue
        # Radius hard bound (owner ruling 2026-09-14): when a business center +
        # radius are supplied, a CDP whose authoritative Census centroid is beyond
        # the radius is excluded — the audit is scoped to "within N miles of the
        # business", not the whole city footprint. Additive to the containment check.
        if center is not None and radius_km is not None:
            dist = maps_geocode.haversine_km(center[0], center[1], cand["lat"], cand["lng"])
            if dist > radius_km:
                beyond_radius += 1
                continue
        synthetic = {
            "matched": True,
            "place_id": None,
            "result_types": ["locality"],
            "lat": cand["lat"],
            "lng": cand["lng"],
        }
        if any(maps_geocode.place_is_within_city(synthetic, fc) for fc in footprint_geos):
            seen.add(key)
            verified.append(cand["name"])
    if beyond_radius:
        prov["beyond_radius"] = beyond_radius

    axis = assemble_cdp_axis(verified, settings.coverage_cdp_max)
    prov["verified"] = len(verified)  # distinct CDPs passing containment (pre-cap)
    prov["axis_size"] = len(axis)     # what the tier actually uses (post-cap)
    if not axis:
        prov["notes"].append("No CDPs verified within the service-area footprint.")
    elif settings.coverage_cdp_max and len(verified) > settings.coverage_cdp_max:
        prov["notes"].append(
            f"CDPs capped at {settings.coverage_cdp_max} (found {len(verified)} within the footprint)."
        )
    return axis, prov, city_names

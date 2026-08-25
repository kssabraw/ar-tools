"""LeadOff GBP Placement Advisor — Census demand surface fetch + cache (plan §6).

The free, $0 demand side of the placement advisor: US Census ACS 5-year data at
**block-group** resolution (households B25001, population B01003, median income
B19013, year-built buckets B25034) joined to **TIGERweb block-group centroids**,
cached in the app-owned `census_block_demand` table (~annual freshness — ACS
updates yearly). Filled per-market on the first advisor run by the async
`leadoff_placement` job; the placement zones are then computed ON READ from this
cache (like forecasting — no result table), by services/leadoff_placement.py.

Same census.gov infra family as the three integrations already live on the
deployed worker (income backfill = api.census.gov; geocode + county backfill =
geocoding.geo.census.gov), so the ACS + geographies/coordinates hosts are
proven. TIGERweb (tigerweb.geo.census.gov) is the one host these precedents
haven't exercised — the job REPORTS centroid coverage + a sample on every run so
the first live run confirms it (plan Phase 0a is validated via the worker, since
the sandbox egress proxy blocks census.gov).

Best-effort throughout: a county that fails to fetch is logged and skipped, never
aborting the market; a market whose counties won't fetch degrades to
`{available:false}` at the router, never a crash.

httpx / config / db are imported lazily inside the impure functions so the pure
parse/coerce/bbox helpers stay importable (and unit-testable) without deps.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_ACS_BASE = "https://api.census.gov/data"
# TIGERweb ArcGIS REST — block-group internal-point (centroid) lookup by county.
# The layer id for "Census Block Groups" varies by service vintage, so we
# resolve it by name from the service metadata rather than hardcoding it.
_TIGERWEB_SERVICE = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/"
    "TIGERweb/tigerWMS_Current/MapServer")
_RETRY_WAITS = [8, 30]
_STATE_PAUSE = 0.4
# ACS 5-year variables: households (housing units), population, median household
# income, and the 11 B25034 year-structure-built buckets (001 total, 002 2020+,
# … 011 1939-or-earlier) for the housing-age demand weight.
_ACS_VARS = ["B25001_001E", "B01003_001E", "B19013_001E"] + [
    f"B25034_{i:03d}E" for i in range(1, 12)]

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; AR-Tools-LeadOff/1.0; "
                   "+https://amazingrankings.com)"),
    "Accept": "application/json",
}

# Degrees per mile (equirectangular) — matches maps_grid's constant.
_MILES_PER_DEGREE_LAT = 69.0


# ── Pure helpers (unit-tested) ────────────────────────────────────────────────

def coerce_int(raw: Any) -> Optional[int]:
    """ACS integer → int, or None for the no-data/jam sentinels (negative
    values like -666666666, empty, nulls)."""
    try:
        v = int(float(raw))
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def parse_acs_blockgroups(matrix: list[list[Any]]) -> list[dict[str, Any]]:
    """Parse the ACS JSON matrix (row 0 = header) into block-group demand dicts
    keyed by the 12-digit GEOID. Rows with no usable household count are dropped
    (a block group with no housing is not a demand candidate). The geometry
    columns (state/county/tract/block group) assemble the GEOID."""
    if not matrix or len(matrix) < 2:
        return []
    header = [h.lower() for h in matrix[0]]
    idx = {h: i for i, h in enumerate(header)}
    try:
        i_state = idx["state"]
        i_county = idx["county"]
        i_tract = idx["tract"]
        i_bg = idx["block group"]
        i_hh = idx["b25001_001e"]
    except KeyError:
        return []
    i_pop = idx.get("b01003_001e")
    i_inc = idx.get("b19013_001e")

    out: list[dict[str, Any]] = []
    for row in matrix[1:]:
        households = coerce_int(row[i_hh])
        if not households:
            continue
        geoid = (f"{row[i_state]}{row[i_county]}"
                 f"{row[i_tract]}{row[i_bg]}")
        housing_age = {v.upper(): coerce_int(row[idx[v.lower()]])
                       for v in _ACS_VARS if v.startswith("B25034_")
                       and v.lower() in idx
                       and coerce_int(row[idx[v.lower()]]) is not None}
        out.append({
            "geoid": geoid,
            "county_fips": f"{row[i_state]}{row[i_county]}",
            "households": households,
            "population": (coerce_int(row[i_pop]) if i_pop is not None else None) or 0,
            "median_income": coerce_int(row[i_inc]) if i_inc is not None else None,
            "housing_age": housing_age,
        })
    return out


def parse_tigerweb_centroids(resp_json: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """{geoid: (lat, lng)} from a TIGERweb block-group query. The internal-point
    fields are CENTLAT/CENTLON (strings with a leading '+'), GEOID the key."""
    out: dict[str, tuple[float, float]] = {}
    for feat in (resp_json.get("features") or []):
        attrs = feat.get("attributes") or {}
        geoid = str(attrs.get("GEOID") or "").strip()
        lat = _coerce_coord(attrs.get("CENTLAT") or attrs.get("INTPTLAT"))
        lng = _coerce_coord(attrs.get("CENTLON") or attrs.get("INTPTLON"))
        if geoid and lat is not None and lng is not None:
            out[geoid] = (lat, lng)
    return out


def _coerce_coord(raw: Any) -> Optional[float]:
    try:
        return float(str(raw).lstrip("+"))
    except (TypeError, ValueError):
        return None


def bbox_for(center_lat: float, center_lng: float,
             radius_miles: float) -> tuple[float, float, float, float]:
    """(lat_min, lat_max, lng_min, lng_max) box enclosing the analysis radius,
    for the on-read block-group query. Longitude degrees are scaled by cos(lat)."""
    import math
    dlat = radius_miles / _MILES_PER_DEGREE_LAT
    cos_lat = max(math.cos(math.radians(center_lat)), 1e-6)
    dlng = radius_miles / (_MILES_PER_DEGREE_LAT * cos_lat)
    return (center_lat - dlat, center_lat + dlat,
            center_lng - dlng, center_lng + dlng)


def merge_demand_rows(acs: list[dict[str, Any]],
                      centroids: dict[str, tuple[float, float]],
                      now: str) -> list[dict[str, Any]]:
    """Join ACS demand rows to their TIGERweb centroids → the cache rows. A block
    group with no centroid is dropped (can't place it on the map). Pure."""
    rows = []
    for bg in acs:
        ll = centroids.get(bg["geoid"])
        if not ll:
            continue
        rows.append({
            "geoid": bg["geoid"],
            "county_fips": bg["county_fips"],
            "lat": ll[0], "lng": ll[1],
            "households": bg["households"],
            "population": bg["population"],
            "median_income": bg["median_income"],
            "housing_age": bg["housing_age"],
            "pulled_at": now,
        })
    return rows


# ── County discovery (edge points → the counties the radius overlaps) ─────────

async def discover_counties(client, center_lat: float, center_lng: float,
                            radius_miles: float,
                            primary_fips: Optional[str]) -> set[str]:
    """The set of 5-digit county FIPS the analysis radius overlaps: the city's
    own county (from city_counties, $0) plus any distinct county the 8 octant
    edge points at the radius resolve to via the free geographies/coordinates
    endpoint (the same host+parser the county backfill uses). Best-effort — a
    failed edge point is skipped."""
    from services.leadoff_counties import _county_for_coord
    from services.maps_octants import _SECTOR_BEARING, dest_point

    fips: set[str] = set()
    if primary_fips:
        fips.add(primary_fips)
    dist_m = radius_miles * 1609.344
    for bearing in _SECTOR_BEARING.values():
        dp = dest_point(center_lat, center_lng, bearing, dist_m)
        try:
            res = await _county_for_coord(client, dp["lat"], dp["lng"])
        except Exception:
            res = None
        if res:
            fips.add(res[1])
    return fips


# ── Census ACS + TIGERweb fetch ───────────────────────────────────────────────

async def _get_json(client, url: str, params: dict) -> Any:
    """GET with the browser-ish headers + transient-retry the census hosts need.
    Returns parsed JSON, or None on a hard/parse failure."""
    import httpx
    for attempt in range(len(_RETRY_WAITS) + 1):
        try:
            resp = await client.get(url, params=params, headers=_HEADERS,
                                    timeout=120.0)
            if resp.status_code in (429, 500, 502, 503, 504):
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.TransportError,
                httpx.TimeoutException) as exc:
            transient = not (isinstance(exc, httpx.HTTPStatusError)
                             and exc.response.status_code not in
                             (429, 500, 502, 503, 504))
            if transient and attempt < len(_RETRY_WAITS):
                await asyncio.sleep(_RETRY_WAITS[attempt])
                continue
            logger.warning("census_demand.get_failed",
                           extra={"url": url, "error": str(exc)[:200]})
            return None
        except ValueError:
            return None
    return None


async def _fetch_acs_county(client, state: str, county: str) -> list[dict[str, Any]]:
    from config import settings
    params = {
        "get": "NAME," + ",".join(_ACS_VARS),
        "for": "block group:*",
        "in": f"state:{state} county:{county}",
    }
    if settings.census_api_key:
        params["key"] = settings.census_api_key
    url = f"{_ACS_BASE}/{settings.leadoff_income_acs_year}/acs/acs5"
    data = await _get_json(client, url, params)
    return parse_acs_blockgroups(data) if isinstance(data, list) else []


async def _resolve_bg_layer(client) -> Optional[int]:
    """Find the TIGERweb layer id whose name is the block-group layer, from the
    service metadata (robust to layer-id drift across TIGER vintages)."""
    meta = await _get_json(client, _TIGERWEB_SERVICE, {"f": "json"})
    if not isinstance(meta, dict):
        return None
    for layer in (meta.get("layers") or []):
        name = str(layer.get("name") or "").lower()
        if "block group" in name:
            return layer.get("id")
    return None


async def _fetch_centroids_county(client, state: str, county: str,
                                  layer_id: int) -> dict[str, tuple[float, float]]:
    """Block-group centroids for a county from TIGERweb. Queries by GEOID prefix
    (state+county) with outFields=* — robust to STATE/COUNTY/CENTLAT field-name
    differences across TIGER vintages; parse_tigerweb_centroids reads CENTLAT/
    CENTLON or the INTPTLAT/INTPTLON internal point."""
    url = f"{_TIGERWEB_SERVICE}/{layer_id}/query"
    params = {
        "where": f"GEOID LIKE '{state}{county}%'",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    data = await _get_json(client, url, params)
    return parse_tigerweb_centroids(data) if isinstance(data, dict) else {}


async def _tigerweb_diag(client, state: str, county: str,
                         layer_id: Optional[int]) -> dict[str, Any]:
    """One-shot diagnostic when centroids come back empty: the resolved layer
    list + a raw one-row county query (response keys / feature count / any error
    / the first feature's attribute names) so a failed TIGERweb pull is
    debuggable from the job row without hitting the endpoint by hand."""
    out: dict[str, Any] = {}
    meta = await _get_json(client, _TIGERWEB_SERVICE, {"f": "json"})
    if isinstance(meta, dict):
        out["layers"] = [{"id": lyr.get("id"), "name": lyr.get("name")}
                         for lyr in (meta.get("layers") or [])][:40]
    if layer_id is not None:
        data = await _get_json(client, f"{_TIGERWEB_SERVICE}/{layer_id}/query", {
            "where": f"GEOID LIKE '{state}{county}%'", "outFields": "*",
            "returnGeometry": "false", "resultRecordCount": 1, "f": "json"})
        if isinstance(data, dict):
            feats = data.get("features") or []
            out["query_keys"] = list(data.keys())
            out["feature_count"] = len(feats)
            if "error" in data:
                out["error"] = str(data.get("error"))[:400]
            if feats:
                out["first_attrs"] = list((feats[0].get("attributes") or {}).keys())
        else:
            out["query_raw_type"] = str(type(data))
    return out


# ── Cache access ──────────────────────────────────────────────────────────────

def county_cached(county_fips: str) -> bool:
    """True when the demand cache already holds this county's block groups."""
    from db.supabase_client import get_supabase
    return bool((get_supabase().table("census_block_demand").select("geoid")
                 .eq("county_fips", county_fips).limit(1).execute().data or []))


def blockgroups_in_bbox(lat_min: float, lat_max: float,
                        lng_min: float, lng_max: float) -> list[dict[str, Any]]:
    """Cached block groups whose centroid falls in the bounding box (the on-read
    demand surface for a market). Paginated for a dense metro."""
    from db.supabase_client import get_supabase
    supabase = get_supabase()
    out: list[dict[str, Any]] = []
    page = 0
    while True:
        chunk = (supabase.table("census_block_demand")
                 .select("geoid, lat, lng, households, population, "
                         "median_income, housing_age")
                 .gte("lat", lat_min).lte("lat", lat_max)
                 .gte("lng", lng_min).lte("lng", lng_max)
                 .range(page * 1000, page * 1000 + 999).execute().data or [])
        out.extend(chunk)
        if len(chunk) < 1000:
            return out
        page += 1


def _upsert_demand(supabase, rows: list[dict[str, Any]]) -> None:
    for i in range(0, len(rows), 500):
        supabase.table("census_block_demand").upsert(rows[i:i + 500]).execute()


def primary_county_fips(city_id: int) -> Optional[str]:
    """The city's own county FIPS from the backfilled city_counties map."""
    from db.supabase_client import get_supabase
    rows = (get_supabase().table("city_counties").select("county_fips")
            .eq("city_id", city_id).limit(1).execute().data or [])
    return rows[0].get("county_fips") if rows else None


def city_center(city_id: int) -> Optional[tuple[float, float]]:
    from services.leadoff_db import get_leadoff_client
    rows = (get_leadoff_client().table("cities")
            .select("latitude, longitude").eq("city_id", city_id)
            .limit(1).execute().data or [])
    if not rows or rows[0].get("latitude") is None:
        return None
    return float(rows[0]["latitude"]), float(rows[0]["longitude"])


def enqueue_placement(city_id: int, category_id: str,
                      user_id: Optional[str] = None) -> Optional[str]:
    """Enqueue a leadoff_placement job to fill the market's counties, unless one
    is already pending/running for this market. Returns the job id to poll."""
    from db.supabase_client import get_supabase
    supabase = get_supabase()
    # async_jobs.entity_id is a UUID column, so the market key lives in the
    # payload (which run_placement_job reads) — dedupe an in-flight job for this
    # market via the payload's city_id, and stamp a real UUID entity_id.
    existing = (supabase.table("async_jobs").select("id")
                .eq("job_type", "leadoff_placement")
                .eq("payload->>city_id", str(city_id))
                .in_("status", ["pending", "running"]).limit(1)
                .execute().data or [])
    if existing:
        return existing[0]["id"]
    payload: dict[str, Any] = {"city_id": city_id, "category_id": category_id}
    if user_id:
        payload["user_id"] = user_id
    row = (supabase.table("async_jobs").insert({
        "job_type": "leadoff_placement", "entity_id": str(uuid.uuid4()),
        "payload": payload, "max_attempts": 3}).execute().data or [])
    return row[0]["id"] if row else None


# ── Job ───────────────────────────────────────────────────────────────────────

async def run_placement_job(job: dict) -> None:
    """Fill census_block_demand for every county the market's radius overlaps.
    Zones are computed on read afterwards; this job only populates the cache.
    Reports coverage + a centroid sample so the first live run validates the
    ACS + TIGERweb pull (plan Phase 0a via the worker)."""
    import httpx

    from config import settings
    from db.supabase_client import get_supabase
    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    city_id = payload.get("city_id")
    try:
        center = city_center(int(city_id)) if city_id else None
        if center is None:
            raise RuntimeError("city has no coordinates")
        radius = settings.placement_analysis_radius_miles
        primary = primary_county_fips(int(city_id))
        now = datetime.now(timezone.utc).isoformat()

        per_county: dict[str, dict[str, Any]] = {}
        centroid_sample: list[dict[str, Any]] = []
        tigerweb_diag: Optional[dict[str, Any]] = None
        async with httpx.AsyncClient(follow_redirects=True) as client:
            counties = await discover_counties(client, center[0], center[1],
                                               radius, primary)
            layer_id = await _resolve_bg_layer(client)
            for fips in sorted(counties):
                if county_cached(fips):
                    per_county[fips] = {"cached": True}
                    continue
                state, county = fips[:2], fips[2:]
                acs = await _fetch_acs_county(client, state, county)
                centroids = ({} if layer_id is None else
                             await _fetch_centroids_county(
                                 client, state, county, layer_id))
                rows = merge_demand_rows(acs, centroids, now)
                if rows:
                    _upsert_demand(supabase, rows)
                    if not centroid_sample:
                        centroid_sample = [
                            {"geoid": r["geoid"], "lat": r["lat"],
                             "lng": r["lng"], "households": r["households"]}
                            for r in rows[:5]]
                per_county[fips] = {"acs": len(acs), "centroids": len(centroids),
                                    "written": len(rows)}
                await asyncio.sleep(_STATE_PAUSE)

            # If TIGERweb yielded no centroids despite ACS data, capture the raw
            # response shape (layers + one-row query) so the failure is
            # debuggable from the job row (runs while the client is still open).
            if (sum(v.get("written", 0) for v in per_county.values()) == 0
                    and any(v.get("acs", 0) for v in per_county.values())):
                probe = primary or (sorted(counties)[0] if counties else None)
                if probe:
                    tigerweb_diag = await _tigerweb_diag(
                        client, probe[:2], probe[2:], layer_id)

        total_written = sum(v.get("written", 0) for v in per_county.values())
        result = {
            "city_id": city_id, "primary_county": primary,
            "analysis_radius_miles": radius,
            "counties": per_county,
            "tigerweb_layer_id": layer_id,
            "block_groups_written": total_written,
            "centroid_sample": centroid_sample,
            "tigerweb_diag": tigerweb_diag,
            "acs_year": settings.leadoff_income_acs_year,
            "note": ("Demand surface cached; placement zones are computed on "
                     "read. If centroids=0 for every county, TIGERweb "
                     "(tigerweb.geo.census.gov) is unreachable from the worker "
                     "— zones will report available:false until that host is "
                     "allowed."),
        }
        supabase.table("async_jobs").update({
            "status": "complete", "result": result, "completed_at": "now()",
        }).eq("id", job_id).execute()
        logger.info("census_demand.complete",
                    extra={"city_id": city_id, "written": total_written})
    except Exception as exc:
        logger.error("census_demand.failed",
                     extra={"job_id": job_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


# ── Market read (impure orchestration — pins + cache + pure core + naming) ────

def _pins_for(city_id: int, category_id: str) -> list[dict[str, Any]]:
    """This market's live competitor GBP pins in the placement pressure shape
    (lat/lng/review_count + display fields), coords-only."""
    from services.leadoff_gbp_pins import read_gbp_pins
    out = []
    for p in read_gbp_pins(city_id, category_id):
        if p.get("lat") is None or p.get("lng") is None:
            continue
        out.append({
            "lat": float(p["lat"]), "lng": float(p["lng"]),
            "review_count": int(p.get("review_count") or 0),
            "name": p.get("business_name"), "rating": p.get("rating"),
            "rank": p.get("rank_position"), "place_id": p.get("place_id"),
        })
    return out


async def _name_and_filter_zones(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best-effort reverse-geocode each zone to its nearest locality and DROP
    zones that name to nothing (water / unpopulated land) — the same land-use
    filter proximity uses. Only filters when naming actually ran (API key
    present); with no key everything reads None and we must not drop everything,
    so those pass through unnamed. Prepends 'near <locality>' to the narrative."""
    from config import settings
    if not zones or not settings.google_maps_api_key:
        return zones
    try:
        from db.supabase_client import get_supabase
        from services.maps_geocode import reverse_geocode_points
        named = await reverse_geocode_points(zones, supabase=get_supabase())
    except Exception:
        logger.warning("census_demand.zone_naming_failed", exc_info=True)
        return zones
    kept = []
    for zone, loc in zip(zones, named):
        locality = loc.get("city") or loc.get("admin_area")
        if locality:
            zone["locality"] = locality
            zone["narrative"] = f"Near {locality}. " + zone.get("narrative", "")
            kept.append(zone)
        # else: unnamed → likely unpopulated, drop from the suggestions
    return kept


async def market_placement(city_id: int, category_id: str) -> dict[str, Any]:
    """The GBP placement read for one market. Degrades explicitly, never raises:
      * no city coords            → available:false, city_has_no_coordinates
      * no live competitor pins   → available:false, no_gbp_pins (+ map-refresh nudge)
      * demand cache not filled   → available:false, census_not_cached (+ job_id to poll)
      * < min_blockgroups         → available:false, too_few_blockgroups (declines)
      * < min_pins (but > 0)      → available:true, thin_field, zones:[] (surface only)
      * otherwise                 → available:true, ranked zones + map layer
    """
    from config import settings
    from services import leadoff_placement as core

    center = city_center(city_id)
    if center is None:
        return {"available": False, "reason": "city_has_no_coordinates"}

    pins = _pins_for(city_id, category_id)
    if not pins:
        return {"available": False, "reason": "no_gbp_pins",
                "hint": ("Plot the live competitor GBPs first (Refresh map, "
                         "~$0.004) — the advisor needs the real field.")}

    radius = settings.placement_analysis_radius_miles
    bbox = bbox_for(center[0], center[1], radius)
    surface_rows = blockgroups_in_bbox(*bbox)
    if not surface_rows:
        job_id = enqueue_placement(city_id, category_id)
        return {"available": False, "reason": "census_not_cached",
                "job_id": job_id,
                "hint": "Building the demand surface from Census data — poll the job."}

    if len(surface_rows) < settings.placement_min_blockgroups:
        return {"available": False, "reason": "too_few_blockgroups",
                "block_groups": len(surface_rows),
                "hint": ("Too few Census block groups here for a meaningful "
                         "sub-city placement question (a small/rural town).")}

    surface = core.build_demand_surface(
        surface_rows,
        income_weight=settings.placement_income_weight,
        housing_age_weight=settings.placement_housing_age_weight)

    map_pins = [{"lat": round(p["lat"], 6), "lng": round(p["lng"], 6),
                 "name": p["name"], "reviews": p["review_count"],
                 "rating": p["rating"], "rank": p["rank"],
                 "place_id": p["place_id"]} for p in pins]
    base = {
        "available": True, "source": "placement",
        "center": {"lat": round(center[0], 6), "lng": round(center[1], 6)},
        "radius_miles": radius, "pins": map_pins,
        "block_groups": len(surface),
    }

    if len(pins) < settings.placement_min_pins:
        base.update({
            "thin_field": True, "zones": [],
            "note": (f"Only {len(pins)} competitor pins captured — below the "
                     f"{settings.placement_min_pins}-pin floor, so zones aren't "
                     f"ranked against the field (same discipline as proximity). "
                     f"Refresh the map or scout to strengthen the read."),
        })
        return base

    built = core.build_zones(
        center[0], center[1], surface, pins,
        radius_miles=radius,
        demand_decay_miles=settings.placement_demand_decay_miles,
        pressure_decay_miles=settings.placement_pressure_decay_miles,
        zone_count=settings.placement_zone_count,
        min_separation_miles=settings.placement_min_separation_miles)
    built["zones"] = await _name_and_filter_zones(built["zones"])
    # add compact maps deep-links for each surviving zone
    for z in built["zones"]:
        z["maps_url"] = f"https://www.google.com/maps?q={z['lat']},{z['lng']}"
    base.update({
        "thin_field": False,
        "zones": built["zones"],
        "catchment_miles": built["catchment_miles"],
        "note": built["note"],
    })
    return base


async def score_market_point(city_id: int, category_id: str,
                             lat: float, lng: float) -> dict[str, Any]:
    """Score an arbitrary point (dropped pin / pasted address) against the
    market's zones — the "Both" half (plan §5.2). Rebuilds the market grid so
    the point uses the SAME market-relative scale, then returns its score,
    percentile, nearest competitor, and distance to the best zone. Degrades with
    the same reasons as market_placement (needs pins + a filled demand cache)."""
    from config import settings
    from services import leadoff_placement as core

    center = city_center(city_id)
    if center is None:
        return {"available": False, "reason": "city_has_no_coordinates"}
    pins = _pins_for(city_id, category_id)
    if not pins:
        return {"available": False, "reason": "no_gbp_pins"}
    radius = settings.placement_analysis_radius_miles
    surface_rows = blockgroups_in_bbox(*bbox_for(center[0], center[1], radius))
    if not surface_rows:
        job_id = enqueue_placement(city_id, category_id)
        return {"available": False, "reason": "census_not_cached", "job_id": job_id}

    surface = core.build_demand_surface(
        surface_rows,
        income_weight=settings.placement_income_weight,
        housing_age_weight=settings.placement_housing_age_weight)
    built = core.build_zones(
        center[0], center[1], surface, pins,
        radius_miles=radius,
        demand_decay_miles=settings.placement_demand_decay_miles,
        pressure_decay_miles=settings.placement_pressure_decay_miles,
        zone_count=settings.placement_zone_count,
        min_separation_miles=settings.placement_min_separation_miles)
    point = core.score_point(lat, lng, surface, pins, built["grid"])

    best = built["zones"][0] if built["zones"] else None
    if best:
        point["best_zone_score"] = best["score"]
        point["best_zone_miles"] = round(
            core.haversine_miles(lat, lng, best["lat"], best["lng"]), 1)
        point["best_zone_locality"] = best.get("locality")
    return {"available": True, "point": point,
            "center": {"lat": round(center[0], 6), "lng": round(center[1], 6)}}


def cache_freshness_days() -> int:
    from config import settings
    return settings.leadoff_income_refresh_days


def is_stale(pulled_at: Any, refresh_days: int) -> bool:
    """Pure staleness check for a cached row's pulled_at (annual ACS refresh)."""
    try:
        ts = datetime.fromisoformat(str(pulled_at))
    except (TypeError, ValueError):
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts < datetime.now(timezone.utc) - timedelta(days=refresh_days)

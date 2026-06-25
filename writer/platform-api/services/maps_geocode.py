"""Weak-zone reverse geocoding for the Maps geo-grid ranker (Module #5).

Turns the geo-grid's weakest pins into real place names so the team can answer
"where exactly are we weak, and which towns are there?" and target local SEO work
there. Two layers, matching the user's ask:

  - every hyper-local octant pin (the priority GBP-page targets) is labelled with
    its nearest city; and
  - all the weak grid cells (not ranked, or ranked worse than a threshold) are
    aggregated into the unique nearby localities they fall in — a ranked list of
    "weak coverage areas" with pin counts, directions, and worst/avg rank.

Reverse geocoding uses the Google Geocoding web service. Results are cached
cross-client by rounded lat/lng (`maps_geocode_cache`) so regenerating a report
or scanning overlapping grids never re-bills the same coordinate. Absent an API
key the rest of the report is unaffected — it just carries no place names.

The pure helpers (weak-cell extraction, address parsing, aggregation) do no I/O
and are unit-tested directly; only `reverse_geocode_points` / `build_weak_locations`
touch the network and the cache.
"""

from __future__ import annotations

import asyncio
import logging
import math
from statistics import mean
from typing import Optional

import httpx

from config import settings
from services import maps_analytics
from services.maps_grid import _MILES_PER_DEGREE_LAT

logger = logging.getLogger(__name__)

_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
_TIMEOUT = 30.0
_GEOCODE_CONCURRENCY = 8
# Rounding for the cache key (4 dp ≈ 11 m) — fine enough that two distinct grid
# pins never collide, coarse enough that a re-scan of the same grid is a cache hit.
_KEY_DP = 4
# Address-component types we treat as a "city", most-specific first.
_CITY_TYPES = (
    "locality", "postal_town", "administrative_area_level_3",
    "sublocality", "neighborhood",
)


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def _cell_latlng(ri: int, ci: int, n: int, center_lat: float, center_lng: float) -> tuple[float, float]:
    """Lat/lng of rank_grid cell [ri][ci] (row 0 = NORTH, 1-mile spacing).

    Mirrors the frontend `cellLatLng` and `maps_analytics` orientation exactly
    (north = center - row), NOT `maps_grid.generate_grid_points` (whose row 0 is
    the south edge — the opposite convention from the stored rank grid).
    """
    c = (n - 1) / 2
    north = c - ri
    east = ci - c
    cos_lat = math.cos(math.radians(center_lat))
    deg_lat_per_mile = 1.0 / _MILES_PER_DEGREE_LAT
    deg_lng_per_mile = 1.0 / (_MILES_PER_DEGREE_LAT * max(cos_lat, 1e-6))
    return center_lat + north * deg_lat_per_mile, center_lng + east * deg_lng_per_mile


def extract_weak_cells(
    rank_grid: list[list], center_lat: Optional[float], center_lng: Optional[float],
    threshold: int, azimuth_offset_deg: float = 0.0,
) -> list[dict]:
    """In-circle pins that rank worse than `threshold` (or not at all), each with
    its real lat/lng + ring + compass octant. Excludes the business's own pin."""
    n = max((len(r) for r in (rank_grid or [])), default=0)
    if n == 0 or center_lat is None or center_lng is None:
        return []
    center = (n - 1) / 2
    radius_sq = (n / 2) ** 2
    out: list[dict] = []
    for ri, row in enumerate(rank_grid or []):
        for ci, cell in enumerate(row or []):
            if (ri - center) ** 2 + (ci - center) ** 2 > radius_sq:
                continue  # outside the inscribed circle — not shown/counted
            rank = float(cell) if isinstance(cell, (int, float)) and not isinstance(cell, bool) else None
            if rank is not None and rank <= threshold:
                continue  # ranks well enough here — not a weak spot
            north = center - ri
            east = ci - center
            if north == 0 and east == 0:
                continue  # the business's own location — not a target zone
            lat, lng = _cell_latlng(ri, ci, n, center_lat, center_lng)
            out.append({
                "row": ri, "col": ci,
                "lat": round(lat, 6), "lng": round(lng, 6),
                "rank": rank,
                "ring": max(1, round(math.hypot(north, east))),
                "octant": maps_analytics._octant_for(north, east, azimuth_offset_deg),
            })
    return out


def _weakness_sort_key(cell: dict) -> tuple:
    """Weakest-first ordering: unranked pins, then worst rank, then outer rings —
    so capping keeps the most important weak cells."""
    ranked = cell.get("rank") is not None
    return (ranked, -(cell["rank"] if ranked else 999), -(cell.get("ring") or 0))


def parse_geocode_results(results: Optional[list]) -> dict:
    """Pull {city, admin_area, formatted, place_id} from Google reverse-geocode
    results. Components are scanned across all results (same point) so a city is
    found even when results[0] is a bare street address."""
    comps: list[dict] = []
    for r in results or []:
        comps.extend(r.get("address_components") or [])

    def _find(*types: str) -> Optional[str]:
        for t in types:
            for c in comps:
                if t in (c.get("types") or []):
                    return c.get("long_name")
        return None

    first = (results or [{}])[0] if results else {}
    return {
        "city": _find(*_CITY_TYPES),
        "admin_area": _find("administrative_area_level_1"),
        "formatted": first.get("formatted_address"),
        "place_id": first.get("place_id"),
    }


def aggregate_weak_areas(geocoded_cells: list[dict], top_n: int = 12) -> list[dict]:
    """Group geocoded weak cells into unique localities, ranked weakest/biggest
    first. Each area carries its pin count, the octants it spans, worst/avg rank,
    and a representative lat/lng (the single weakest pin — the most actionable
    point to drop a map link on)."""
    groups: dict[str, dict] = {}
    for cell in geocoded_cells:
        key = cell.get("city") or cell.get("formatted") or f"{cell['lat']:.3f},{cell['lng']:.3f}"
        g = groups.setdefault(key, {"city": cell.get("city"), "admin_area": cell.get("admin_area"), "cells": []})
        g["cells"].append(cell)

    areas: list[dict] = []
    for g in groups.values():
        cells = g["cells"]
        ranks = [c["rank"] for c in cells if c["rank"] is not None]
        not_ranked = sum(1 for c in cells if c["rank"] is None)
        # Representative = the single weakest pin (an unranked one if present,
        # otherwise the worst rank).
        rep = max(cells, key=lambda c: (c["rank"] is None, c["rank"] if c["rank"] is not None else 0))
        octants = sorted({c["octant"] for c in cells if c.get("octant")})
        areas.append({
            "city": g["city"],
            "admin_area": g["admin_area"],
            "pins": len(cells),
            "not_ranked": not_ranked,
            "octants": octants,
            "worst_rank": None if not_ranked else (max(ranks) if ranks else None),
            "avg_rank": round(mean(ranks), 1) if ranks else None,
            "lat": rep["lat"],
            "lng": rep["lng"],
        })
    # Biggest dead-zones first: most weak pins, then most unranked pins.
    areas.sort(key=lambda a: (-a["pins"], -a["not_ranked"]))
    return areas[:top_n]


# ----------------------------------------------------------------------------
# Reverse geocoding (Google) + cross-client cache
# ----------------------------------------------------------------------------
def _key(lat: float, lng: float) -> tuple[float, float]:
    return (round(lat, _KEY_DP), round(lng, _KEY_DP))


def _load_cache(supabase, keys: list[tuple[float, float]]) -> dict[tuple[float, float], dict]:
    """Cached locations for these rounded keys (over-fetches by lat/lng IN, then
    filters to the exact pairs — the working set per report is small)."""
    if not supabase or not keys:
        return {}
    lats = sorted({k[0] for k in keys})
    lngs = sorted({k[1] for k in keys})
    try:
        rows = (
            supabase.table("maps_geocode_cache")
            .select("lat_key, lng_key, city, admin_area, formatted, place_id")
            .in_("lat_key", lats).in_("lng_key", lngs).execute()
        ).data or []
    except Exception as exc:  # cache is best-effort — never sink geocoding
        logger.warning("maps_geocode_cache_read_failed", extra={"error": str(exc)})
        return {}
    wanted = set(keys)
    out: dict[tuple[float, float], dict] = {}
    for r in rows:
        k = (round(float(r["lat_key"]), _KEY_DP), round(float(r["lng_key"]), _KEY_DP))
        if k in wanted:
            out[k] = {f: r.get(f) for f in ("city", "admin_area", "formatted", "place_id")}
    return out


def _write_cache(supabase, fresh: dict[tuple[float, float], dict]) -> None:
    if not supabase or not fresh:
        return
    rows = [{"lat_key": k[0], "lng_key": k[1], **loc} for k, loc in fresh.items()]
    try:
        supabase.table("maps_geocode_cache").upsert(rows, on_conflict="lat_key,lng_key").execute()
    except Exception as exc:
        logger.warning("maps_geocode_cache_write_failed", extra={"error": str(exc)})


async def _geocode_one(client: httpx.AsyncClient, lat: float, lng: float, api_key: str) -> Optional[dict]:
    """One reverse-geocode call. Returns parsed location on a definitive answer
    (OK / ZERO_RESULTS — both cacheable), or None on a transient error (not
    cached, so it retries next time)."""
    try:
        resp = await client.get(_GEOCODE_URL, params={"latlng": f"{lat},{lng}", "key": api_key})
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        logger.warning("maps_geocode_request_failed", extra={"lat": lat, "lng": lng, "error": str(exc)})
        return None
    status = body.get("status")
    if status == "OK":
        return parse_geocode_results(body.get("results"))
    if status == "ZERO_RESULTS":
        return parse_geocode_results(None)  # definitive "nothing here" — cache the blank
    logger.warning("maps_geocode_status", extra={"status": status, "error": body.get("error_message")})
    return None


async def reverse_geocode_points(
    points: list[dict], *, api_key: Optional[str] = None, supabase=None,
) -> list[dict]:
    """Enrich each point (carrying lat/lng) with {city, admin_area, formatted,
    place_id}. Dedups by rounded key, serves hits from `maps_geocode_cache`, calls
    Google for misses (bounded concurrency), and writes the misses back. With no
    API key the points pass through unenriched."""
    api_key = settings.google_maps_api_key if api_key is None else api_key
    if not points or not api_key:
        return [dict(p) for p in points]

    keyed = [(_key(p["lat"], p["lng"]), p) for p in points]
    cache = _load_cache(supabase, [k for k, _ in keyed])
    misses = sorted({k for k, _ in keyed if k not in cache})

    if misses:
        sem = asyncio.Semaphore(_GEOCODE_CONCURRENCY)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async def _run(k: tuple[float, float]):
                async with sem:
                    return k, await _geocode_one(client, k[0], k[1], api_key)
            results = await asyncio.gather(*(_run(k) for k in misses))
        fresh = {k: loc for k, loc in results if loc is not None}
        cache.update(fresh)
        _write_cache(supabase, fresh)

    blank = {"city": None, "admin_area": None, "formatted": None, "place_id": None}
    return [{**p, **(cache.get(k) or blank)} for k, p in keyed]


# ----------------------------------------------------------------------------
# Orchestration — the full per-keyword weak-locations payload.
# ----------------------------------------------------------------------------
async def build_weak_locations(
    rank_grid: Optional[list], center_lat: Optional[float], center_lng: Optional[float],
    octant_points: Optional[list[dict]] = None, *,
    threshold: Optional[int] = None, max_cells: Optional[int] = None,
    azimuth_offset_deg: float = 0.0, api_key: Optional[str] = None, supabase=None,
) -> dict:
    """The `report_weak_locations` payload for one keyword: octant pins labelled
    with their nearest city, plus weak grid cells aggregated into nearby
    localities. Geocoding is best-effort — a missing key/quota yields the same
    shape minus place names (`geocoded=False`)."""
    threshold = settings.maps_weak_rank_threshold if threshold is None else threshold
    max_cells = settings.maps_geocode_max_cells if max_cells is None else max_cells
    api_key = settings.google_maps_api_key if api_key is None else api_key
    octant_points = octant_points or []

    weak_cells = extract_weak_cells(rank_grid, center_lat, center_lng, threshold, azimuth_offset_deg)
    weak_cells.sort(key=_weakness_sort_key)
    capped = len(weak_cells) > max_cells
    kept = weak_cells[:max_cells]

    base = {
        "geocoded": bool(api_key),
        "capped": capped,
        "weak_threshold": threshold,
        "weak_cell_count": len(weak_cells),
    }
    if not api_key:
        # No geocoding: surface the octant pins (no city) so the UI degrades to
        # raw coordinates rather than hiding them.
        return {**base, "octant_pins": [dict(p) for p in octant_points], "weak_areas": []}

    combined = await reverse_geocode_points(
        [dict(c) for c in kept] + [dict(p) for p in octant_points],
        api_key=api_key, supabase=supabase,
    )
    enriched_cells = combined[:len(kept)]
    enriched_octants = combined[len(kept):]
    return {
        **base,
        "octant_pins": enriched_octants,
        "weak_areas": aggregate_weak_areas(enriched_cells),
    }

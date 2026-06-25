"""Weak-zone reverse geocoding for the Maps geo-grid ranker (Module #5).

Turns the geo-grid's weakest pins into real place names so the team can answer
"where exactly are we weak, and which towns are there?" and target local SEO work
there. Two layers, matching the user's ask:

  - every hyper-local octant pin (the priority GBP-page targets) is labelled with
    its nearest city; and
  - all the "opportunity" grid cells (not ranked, or ranked outside the pack) are
    scored for targeting priority (severity × proximity × beatability × cohesion,
    the last down-weighting weak pins isolated among strong neighbors) and
    aggregated into the unique nearby localities they fall in — a 0-100,
    target-first list of "weak coverage areas" with tier, pin counts, directions,
    and worst/avg rank.

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


# Tier labels by rank band, most→least severe (drives the badge + cap ordering).
_TIER_ORDER = {"critical": 3, "weak": 2, "watch": 1}


def _tier(rank: Optional[float], weak_threshold: int) -> str:
    """Critical = unranked dead zone; Weak = ranked but >= the weak boundary;
    Watch = the low-priority band just outside the pack (floor < rank < weak)."""
    if rank is None:
        return "critical"
    return "weak" if rank >= weak_threshold else "watch"


def _severity(rank: Optional[float], floor: int, unranked_eff: int) -> float:
    """0-1 weakness, anchored at the pack edge (`floor`) and topping out at
    `unranked_eff`. Rank just past the pack ≈ 0 (barely weak), unranked = 1.0."""
    eff = unranked_eff if rank is None else rank
    span = max(1e-9, unranked_eff - floor)
    return max(0.0, min(1.0, (eff - floor) / span))


def _proximity(ring: int, max_ring: int) -> float:
    """0-1 closeness weight: innermost ring = 1.0, outer edge → ~1/max_ring.
    Closer pins matter more (own your backyard; more realistically rankable)."""
    if max_ring <= 0:
        return 1.0
    return max(0.0, (max_ring - ring + 1) / max_ring)


def _to_float(v) -> Optional[float]:
    """Coerce a review count to float, or None if it isn't a usable number.
    Accepts ints/floats and numeric strings (e.g. "77"); rejects bools, None,
    and non-numeric junk — so a malformed `gbp_review_count` degrades to neutral
    rather than raising."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _beatability(comp_reviews, client_reviews, bmin: float, bmax: float) -> float:
    """Multiplier in [bmin, bmax]: > 1 where the strongest competitor outranking
    us has FEWER reviews than the client (easy to overtake), < 1 where an
    entrenched, review-rich competitor holds the spot. Neutral (1.0) when either
    review count is missing or non-numeric."""
    comp, client = _to_float(comp_reviews), _to_float(client_reviews)
    if comp is None or client is None:
        return 1.0
    ratio = (client + 1.0) / (comp + 1.0)
    return max(bmin, min(bmax, 1.0 + 0.4 * math.log10(ratio)))


def _cell_rank(rank_grid: list[list], ri: int, ci: int) -> Optional[float]:
    """Parsed rank at [ri][ci], or None (unranked / non-numeric / out of bounds)."""
    if ri < 0 or ri >= len(rank_grid):
        return None
    row = rank_grid[ri] or []
    if ci < 0 or ci >= len(row):
        return None
    cell = row[ci]
    return float(cell) if isinstance(cell, (int, float)) and not isinstance(cell, bool) else None


def _cohesion_factor(
    rank_grid: list[list], ri: int, ci: int, center: float, radius_sq: float,
    floor: int, unranked_eff: int, c_floor: float,
) -> float:
    """How weak a pin's 8 immediate (in-circle) neighbors are, scaled to
    [c_floor, 1.0]. A weak pin ringed by strong (in-pack) pins → near c_floor
    (likely noise — down-weighted); a pin inside a real weak patch → near 1.0.
    Pins with no in-circle neighbors are treated as fully isolated (c_floor)."""
    sevs: list[float] = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = ri + dr, ci + dc
            if (nr - center) ** 2 + (nc - center) ** 2 > radius_sq:
                continue  # neighbor outside the scanned circle — doesn't count
            if nr < 0 or nr >= len(rank_grid) or nc < 0 or nc >= len(rank_grid[nr] or []):
                continue
            sevs.append(_severity(_cell_rank(rank_grid, nr, nc), floor, unranked_eff))
    cohesion = (sum(sevs) / len(sevs)) if sevs else 0.0
    return c_floor + (1.0 - c_floor) * cohesion


def _strongest_competitor_reviews(
    competitors_above: Optional[dict], ri: int, ci: int,
) -> Optional[float]:
    """Reviews of the most review-rich competitor ranking above the client at
    grid cell [ri][ci] (the toughest one to displace). None when unknown."""
    if not competitors_above:
        return None
    grid = competitors_above.get("grid") or []
    directory = competitors_above.get("directory") or {}
    if ri >= len(grid):
        return None
    row = grid[ri] or []
    if ci >= len(row) or not row[ci]:
        return None
    revs: list[float] = []
    for entry in row[ci]:
        pid = entry[0] if isinstance(entry, (list, tuple)) and entry else None
        rv = (directory.get(pid) or {}).get("reviews") if pid else None
        if isinstance(rv, (int, float)) and not isinstance(rv, bool):
            revs.append(float(rv))
    return max(revs) if revs else None


def extract_weak_cells(
    rank_grid: list[list], center_lat: Optional[float], center_lng: Optional[float],
    floor: int, *, weak_threshold: Optional[int] = None,
    unranked_effective_rank: Optional[int] = None,
    competitors_above: Optional[dict] = None, client_reviews: Optional[float] = None,
    beatability_bounds: Optional[tuple[float, float]] = None,
    cohesion_floor: Optional[float] = None,
    azimuth_offset_deg: float = 0.0,
) -> list[dict]:
    """In-circle "opportunity" pins (unranked or ranked worse than `floor`), each
    scored for targeting priority. Excludes the business's own pin and pins in the
    pack (rank <= floor). Every cell carries its real lat/lng, ring, octant, tier,
    and an `opportunity` score (severity × proximity × beatability × cohesion —
    the last down-weights weak pins isolated among strong neighbors)."""
    weak_threshold = settings.maps_weak_rank_threshold if weak_threshold is None else weak_threshold
    unranked_eff = settings.maps_unranked_effective_rank if unranked_effective_rank is None else unranked_effective_rank
    bmin, bmax = beatability_bounds or (settings.maps_beatability_min, settings.maps_beatability_max)
    c_floor = settings.maps_cohesion_floor if cohesion_floor is None else cohesion_floor
    n = max((len(r) for r in (rank_grid or [])), default=0)
    if n == 0 or center_lat is None or center_lng is None:
        return []
    center = (n - 1) / 2
    radius_sq = (n / 2) ** 2
    max_ring = max(1, (n - 1) // 2)
    out: list[dict] = []
    for ri, row in enumerate(rank_grid or []):
        for ci, cell in enumerate(row or []):
            if (ri - center) ** 2 + (ci - center) ** 2 > radius_sq:
                continue  # outside the inscribed circle — not shown/counted
            rank = float(cell) if isinstance(cell, (int, float)) and not isinstance(cell, bool) else None
            if rank is not None and rank <= floor:
                continue  # in the local pack here — not an opportunity
            north = center - ri
            east = ci - center
            if north == 0 and east == 0:
                continue  # the business's own location — not a target zone
            lat, lng = _cell_latlng(ri, ci, n, center_lat, center_lng)
            ring = max(1, round(math.hypot(north, east)))
            sev = _severity(rank, floor, unranked_eff)
            prox = _proximity(ring, max_ring)
            beat = _beatability(
                _strongest_competitor_reviews(competitors_above, ri, ci),
                client_reviews, bmin, bmax,
            )
            cohesion = _cohesion_factor(rank_grid, ri, ci, center, radius_sq, floor, unranked_eff, c_floor)
            out.append({
                "row": ri, "col": ci,
                "lat": round(lat, 6), "lng": round(lng, 6),
                "rank": rank,
                "ring": ring,
                "octant": maps_analytics._octant_for(north, east, azimuth_offset_deg),
                "tier": _tier(rank, weak_threshold),
                "severity": round(sev, 4),
                "proximity": round(prox, 4),
                "beatability": round(beat, 4),
                "cohesion": round(cohesion, 4),
                "opportunity": round(sev * prox * beat * cohesion, 6),
            })
    return out


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


def aggregate_weak_areas(geocoded_cells: list[dict], top_n: Optional[int] = None) -> list[dict]:
    """Group geocoded opportunity cells into unique localities, ranked by targeting
    priority (highest first). Each area carries a 0-100 `priority` (normalized
    per keyword), a `tier` (the most severe pin in it), its pin count, the octants
    it spans, worst/avg rank, and a representative lat/lng (the highest-priority
    pin — the most actionable point to drop a map link on). `top_n=None` = all."""
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
        # Representative = the highest-priority pin (most actionable point).
        rep = max(cells, key=lambda c: c.get("opportunity", 0))
        octants = sorted({c["octant"] for c in cells if c.get("octant")})
        tier = max((c.get("tier") for c in cells), key=lambda t: _TIER_ORDER.get(t, 0))
        areas.append({
            "city": g["city"],
            "admin_area": g["admin_area"],
            "pins": len(cells),
            "not_ranked": not_ranked,
            "octants": octants,
            "worst_rank": None if not_ranked else (max(ranks) if ranks else None),
            "avg_rank": round(mean(ranks), 1) if ranks else None,
            "tier": tier,
            "score_raw": round(sum(c.get("opportunity", 0) for c in cells), 6),
            "lat": rep["lat"],
            "lng": rep["lng"],
        })
    # Normalize to a 0-100 priority within this keyword (worst area = 100), then
    # rank highest-priority first — the team's work order.
    max_raw = max((a["score_raw"] for a in areas), default=0.0) or 1.0
    for a in areas:
        a["priority"] = round(100 * a["score_raw"] / max_raw)
    areas.sort(key=lambda a: -a["score_raw"])
    return areas if top_n is None else areas[:top_n]


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
# Forward geocoding (Google) + cross-client cache — place-name verification.
# ----------------------------------------------------------------------------
def parse_forward_result(results: Optional[list]) -> dict:
    """Pull {matched, city, admin_area, formatted, place_id, result_types, lat,
    lng} from a Google *forward*-geocode response. Unlike `parse_geocode_results`
    (reverse) this keeps the top result's `types` and geometry so the caller can
    verify a candidate is neighborhood-specific (not a fallback to the city
    centroid) and inside the expected city."""
    blank = {
        "matched": False, "city": None, "admin_area": None, "formatted": None,
        "place_id": None, "result_types": [], "lat": None, "lng": None,
    }
    if not results:
        return blank
    first = results[0] or {}
    comps: list[dict] = first.get("address_components") or []

    def _find(*types: str) -> Optional[str]:
        for t in types:
            for c in comps:
                if t in (c.get("types") or []):
                    return c.get("long_name")
        return None

    loc = ((first.get("geometry") or {}).get("location")) or {}
    return {
        "matched": True,
        "city": _find(*_CITY_TYPES),
        "admin_area": _find("administrative_area_level_1"),
        "formatted": first.get("formatted_address"),
        "place_id": first.get("place_id"),
        "result_types": list(first.get("types") or []),
        "lat": loc.get("lat"),
        "lng": loc.get("lng"),
    }


def _norm_query(query: str) -> str:
    """Cache key: lower-cased, whitespace-collapsed query string."""
    return " ".join((query or "").lower().split())


_FWD_FIELDS = ("matched", "city", "admin_area", "formatted", "place_id", "result_types", "lat", "lng")


def _load_forward_cache(supabase, norms: list[str]) -> dict[str, dict]:
    if not supabase or not norms:
        return {}
    try:
        rows = (
            supabase.table("geocode_forward_cache")
            .select("query_norm, matched, city, admin_area, formatted, place_id, result_types, lat, lng")
            .in_("query_norm", sorted(set(norms))).execute()
        ).data or []
    except Exception as exc:  # cache is best-effort — never sink geocoding
        logger.warning("geocode_forward_cache_read_failed", extra={"error": str(exc)})
        return {}
    out: dict[str, dict] = {}
    for r in rows:
        out[r["query_norm"]] = {f: (r.get(f) if f != "result_types" else (r.get(f) or [])) for f in _FWD_FIELDS}
    return out


def _write_forward_cache(supabase, fresh: dict[str, dict]) -> None:
    if not supabase or not fresh:
        return
    rows = [{"query_norm": norm, **{f: loc.get(f) for f in _FWD_FIELDS}} for norm, loc in fresh.items()]
    try:
        supabase.table("geocode_forward_cache").upsert(rows, on_conflict="query_norm").execute()
    except Exception as exc:
        logger.warning("geocode_forward_cache_write_failed", extra={"error": str(exc)})


async def _forward_geocode_one(client: httpx.AsyncClient, query: str, api_key: str) -> Optional[dict]:
    """One forward-geocode call. Returns the parsed result on a definitive answer
    (OK / ZERO_RESULTS — both cacheable), or None on a transient error (not
    cached, so it retries next time)."""
    try:
        resp = await client.get(_GEOCODE_URL, params={"address": query, "key": api_key})
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        logger.warning("geocode_forward_request_failed", extra={"query": query, "error": str(exc)})
        return None
    status = body.get("status")
    if status == "OK":
        return parse_forward_result(body.get("results"))
    if status == "ZERO_RESULTS":
        return parse_forward_result(None)  # definitive "no such place" — cache the miss
    logger.warning("geocode_forward_status", extra={"status": status, "error": body.get("error_message")})
    return None


async def forward_geocode_places(
    queries: list[str], *, api_key: Optional[str] = None, supabase=None,
) -> dict[str, dict]:
    """Forward-geocode each query string, returning {original_query: parsed} where
    parsed carries {matched, city, admin_area, result_types, lat, lng, ...}. Dedups
    by normalized key, serves hits from `geocode_forward_cache`, calls Google for
    misses (bounded concurrency), and writes them back (negatives included). With
    no API key, every query maps to an unmatched blank so the caller degrades to
    skipping verification rather than trusting an unverified name."""
    api_key = settings.google_maps_api_key if api_key is None else api_key
    blank = {f: ([] if f == "result_types" else (False if f == "matched" else None)) for f in _FWD_FIELDS}
    if not queries or not api_key:
        return {q: dict(blank) for q in queries}

    keyed = [(q, _norm_query(q)) for q in queries]
    cache = _load_forward_cache(supabase, [n for _, n in keyed])
    misses = sorted({n for _, n in keyed if n not in cache})

    if misses:
        sem = asyncio.Semaphore(_GEOCODE_CONCURRENCY)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            async def _run(norm: str):
                async with sem:
                    return norm, await _forward_geocode_one(client, norm, api_key)
            results = await asyncio.gather(*(_run(n) for n in misses))
        fresh = {n: loc for n, loc in results if loc is not None}
        cache.update(fresh)
        _write_forward_cache(supabase, fresh)

    return {q: dict(cache.get(n) or blank) for q, n in keyed}


# ----------------------------------------------------------------------------
# Orchestration — the full per-keyword weak-locations payload.
# ----------------------------------------------------------------------------
async def build_weak_locations(
    rank_grid: Optional[list], center_lat: Optional[float], center_lng: Optional[float],
    octant_points: Optional[list[dict]] = None, *,
    floor: Optional[int] = None, weak_threshold: Optional[int] = None,
    max_cells: Optional[int] = None, competitors_above: Optional[dict] = None,
    client_reviews: Optional[float] = None,
    azimuth_offset_deg: float = 0.0, api_key: Optional[str] = None, supabase=None,
) -> dict:
    """The `report_weak_locations` payload for one keyword: octant pins labelled
    with their nearest city, plus opportunity grid cells scored for priority and
    aggregated into nearby localities (a 0-100, target-first ranking). Geocoding
    is best-effort — a missing key/quota yields the same shape minus place names
    (`geocoded=False`)."""
    floor = settings.maps_strong_rank_threshold if floor is None else floor
    weak_threshold = settings.maps_weak_rank_threshold if weak_threshold is None else weak_threshold
    max_cells = settings.maps_geocode_max_cells if max_cells is None else max_cells
    api_key = settings.google_maps_api_key if api_key is None else api_key
    octant_points = octant_points or []

    weak_cells = extract_weak_cells(
        rank_grid, center_lat, center_lng, floor, weak_threshold=weak_threshold,
        competitors_above=competitors_above, client_reviews=client_reviews,
        azimuth_offset_deg=azimuth_offset_deg,
    )
    # Highest-priority first, so a cap only ever drops the lowest "Watch" cells.
    weak_cells.sort(key=lambda c: -c.get("opportunity", 0))
    capped = len(weak_cells) > max_cells
    kept = weak_cells[:max_cells]

    base = {
        "geocoded": bool(api_key),
        "capped": capped,
        "opportunity_floor": floor,
        "weak_threshold": weak_threshold,
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

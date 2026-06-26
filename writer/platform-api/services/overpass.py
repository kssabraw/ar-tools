"""Nearby-city enumeration via the Overpass API (OpenStreetMap).

Google's geo APIs resolve a place you name but can't *enumerate* the cities/towns
around a point — there's no "list places within a radius" endpoint. Overpass can:
it queries OSM for ``place=city|town`` nodes within a radius of a centre. Free and
keyless (public endpoints, ODbL — attribution to OpenStreetMap contributors).

Used by the silo planner's target-city discovery to find the other cities a local
business may serve within a radius of its primary city. Best-effort: a failed or
slow public endpoint yields an empty list (the rest of the plan is unaffected),
with a mirror tried before giving up. Pure query-build / parse helpers are
unit-tested; the network call is a thin wrapper.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0
KM_PER_MILE = 1.609344


# ── pure helpers (no I/O) — unit-tested ──────────────────────────────────────

def build_nearby_cities_query(
    lat: float, lng: float, radius_m: int, place_types: tuple[str, ...] = ("city", "town"),
) -> str:
    """Overpass QL for ``place=<type>`` nodes within `radius_m` metres of a point.

    Nodes only (place labels are overwhelmingly nodes) so ``out;`` carries lat/lon
    for each result without needing geometry resolution."""
    type_re = "|".join(place_types)
    return (
        f"[out:json][timeout:25];"
        f'node["place"~"^({type_re})$"](around:{radius_m},{lat},{lng});'
        f"out;"
    )


def parse_overpass_elements(body: dict) -> list[dict]:
    """Extract ``{name, lat, lng, place}`` from an Overpass JSON response. Prefers a
    localized English name (``name:en``) then ``name``; skips nameless elements and
    de-dupes by lower-cased name (first wins)."""
    out: list[dict] = []
    seen: set[str] = set()
    for el in (body or {}).get("elements") or []:
        tags = el.get("tags") or {}
        name = (tags.get("name:en") or tags.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        lat, lng = el.get("lat"), el.get("lon")
        if lat is None or lng is None:
            continue
        seen.add(key)
        out.append({"name": name, "lat": lat, "lng": lng, "place": tags.get("place")})
    return out


# ── network (best-effort) ────────────────────────────────────────────────────

async def nearby_cities(lat: float, lng: float, radius_km: float) -> list[dict]:
    """Cities/towns within `radius_km` of (lat, lng), via Overpass. Returns
    ``[{name, lat, lng, place}]`` (possibly empty). Never raises — tries the
    configured endpoint then a mirror, and returns [] if both fail."""
    if lat is None or lng is None:
        return []
    place_types = tuple(t.strip() for t in settings.local_seo_overpass_place_types.split(",") if t.strip())
    query = build_nearby_cities_query(lat, lng, int(radius_km * 1000), place_types or ("city", "town"))
    endpoints = [settings.local_seo_overpass_url, settings.local_seo_overpass_mirror_url]

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": "ar-tools-overpass/1.0"}) as client:
        for endpoint in endpoints:
            if not endpoint:
                continue
            try:
                resp = await client.post(endpoint, data={"data": query})
                resp.raise_for_status()
                return parse_overpass_elements(resp.json())
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(
                    "overpass.request_failed", extra={"endpoint": endpoint, "error": str(exc)},
                )
                continue
    return []

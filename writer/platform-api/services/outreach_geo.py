"""Any-city geo resolution for the outreach scan form.

A scan targets a *submarket* — a city sub-area with a fixed 81-point grid. The pre-seeded markets
ship their submarkets from a definition file, which is why the scan form's picker is a fixed
dropdown. This module lets an operator instead type ANY city and get its real sub-areas as scan
targets, so the form becomes "City + Business type" (owner request 2026-08-08).

THE ENUMERATION, and why it is two sources:

    Google resolves a place you *name*, but has no endpoint that *lists* a city's neighbourhoods.
    So sub-areas come from OpenStreetMap (Overpass: ``place=suburb|neighbourhood|...`` nodes within
    the city), and each candidate is then VERIFIED against Google geocoding and kept only if it
    resolves to a real place geographically inside the city. Every sub-area shown is therefore
    Google-recognised; the *list* just can't be sourced from Google, because Google won't produce
    one. This is the exact pipeline the Local SEO neighbourhood silo already rides
    (`local_seo_silo._neighborhoods_for_city`); the primitives are reused, not reinvented.

This module is READ-ONLY: it resolves and lists. Creating the market/submarket/keyword rows and
running discovery + the scan is the execution layer, built separately — so nothing here spends the
~$0.81 scan or the discovery pull, and a bad enumeration can only show a wrong list, never bill.

Best-effort throughout: no Google key, an unreadable Overpass, or a city that doesn't geocode all
degrade to a clear empty result with a note, never a 500.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from config import settings
from services import maps_geocode
from services.maps_geocode import place_is_within_city
from services.outreach import OutreachError

logger = logging.getLogger(__name__)


# --- pure helpers (no I/O) — unit-tested ------------------------------------------------------


def _norm(text: Optional[str]) -> str:
    return " ".join((text or "").lower().split())


def city_region(city_geo: dict) -> str:
    """The ", <admin area>, <country>" suffix that disambiguates a sub-area query — without it
    "Highland Park, Los Angeles" can geocode to the wrong state entirely (the same I-032 hazard the
    outreach seeder guards). Empty parts are dropped."""
    return ", ".join(p for p in (city_geo.get("admin_area"), city_geo.get("country")) if p)


def city_display_name(city_geo: dict) -> str:
    """A human label for the resolved city. Prefers Google's own formatted address, then the
    city + region components, then whatever matched."""
    if city_geo.get("formatted"):
        return str(city_geo["formatted"])
    parts = [city_geo.get("city"), city_region(city_geo)]
    joined = ", ".join(p for p in parts if p)
    return joined or "Unknown city"


def subarea_query(name: str, city_geo: dict) -> str:
    """The geocode query for one candidate sub-area: "<sub-area>, <city>, <region>"."""
    city = city_geo.get("city") or ""
    return ", ".join(p for p in (name, city, city_region(city_geo)) if p)


def dedupe_by_name(items: list[dict]) -> list[dict]:
    """Case-insensitive de-dup on ``name``, first occurrence wins (Overpass can surface the same
    place from several nodes)."""
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        key = _norm(item.get("name"))
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def prefilter_in_bounds(candidates: list[dict], city_geo: dict, pad: float) -> list[dict]:
    """Drop OSM candidates whose OWN coordinates fall outside the city's box, BEFORE paying to
    geocode them. Overpass searches a radius (a circle), so it spills past a non-circular city;
    this trims the obvious spill for free. When the city has no box, keep everything — the radius
    already bounded it and Google verification is the real gate."""
    bounds = city_geo.get("bounds")
    if not bounds:
        return list(candidates)
    kept: list[dict] = []
    for c in candidates:
        lat, lng = c.get("lat"), c.get("lng")
        if lat is None or lng is None:
            continue
        if maps_geocode.point_in_bounds(float(lat), float(lng), bounds, pad=pad):
            kept.append(c)
    return kept


def verified_subareas(
    candidates: list[dict], geo_map: dict[str, dict], city_geo: dict
) -> list[dict]:
    """Keep only candidates Google verifies as a real place inside the city, returning
    ``[{name, lat, lng, place_id}]`` with the AUTHORITATIVE geocoded centre + place_id (not the
    OSM node's). ``geo_map`` is {subarea_query: forward-geocode result}. Verification is
    `place_is_within_city` — the same country-agnostic geographic test the Local SEO silo uses, so
    a US neighbourhood nested in the locality and an AU/UK suburb that is its own locality both
    pass, and a county/state/centroid-fallback is rejected. Order is preserved; de-duped by the
    resolved place_id so two candidate names snapping to one place collapse."""
    out: list[dict] = []
    seen_place: set[str] = set()
    for c in candidates:
        name = c.get("name")
        geo = geo_map.get(subarea_query(name, city_geo)) or {}
        if not place_is_within_city(geo, city_geo):
            continue
        pid = geo.get("place_id")
        if pid and pid in seen_place:
            continue
        if pid:
            seen_place.add(pid)
        out.append(
            {
                "name": name,
                "lat": geo.get("lat"),
                "lng": geo.get("lng"),
                "place_id": pid,
            }
        )
    return out


def _place_types() -> tuple[str, ...]:
    return tuple(t.strip() for t in settings.outreach_subarea_place_types.split(",") if t.strip())


# --- async orchestration (the I/O) ------------------------------------------------------------


async def resolve_city(query: str, *, supabase=None) -> dict:
    """Forward-geocode a typed city string to a resolved place. Raises `OutreachError`
    ('city_query_required' / 'city_not_found') on empty or unmatched input — the caller's degraded
    path is to show the error, not an empty list that reads as "this city has no sub-areas"."""
    query = (query or "").strip()
    if not query:
        raise OutreachError("city_query_required")
    geo_map = await maps_geocode.forward_geocode_places([query], supabase=supabase)
    city_geo = geo_map.get(query) or {}
    if not city_geo.get("matched"):
        # No key, or Google didn't recognise it — indistinguishable to the caller and handled the
        # same way: we cannot enumerate what we cannot place.
        raise OutreachError("city_not_found")
    return city_geo


async def enumerate_subareas(query: str, *, supabase=None) -> dict:
    """Resolve a city, then return its Google-verified sub-areas as scan targets.

    Returns ``{city: {...}, subareas: [{name, lat, lng, place_id}], note: str|None}``. The pipeline:
    OSM-enumerate (Overpass) → cheap in-bounds prefilter → cap → Google-verify each → cap. Every
    stage degrades to a noted empty list rather than raising, EXCEPT an unresolvable city (that is
    the caller's to surface)."""
    from services import overpass  # local import: keeps the module importable without httpx at load

    city_geo = await resolve_city(query, supabase=supabase)
    lat, lng = city_geo.get("lat"), city_geo.get("lng")
    city_out = {
        "name": city_display_name(city_geo),
        "city": city_geo.get("city"),
        "region": city_region(city_geo),
        "lat": lat,
        "lng": lng,
        "place_id": city_geo.get("place_id"),
    }

    place_types = _place_types()
    try:
        raw = await overpass.places_near(
            float(lat), float(lng), settings.outreach_subarea_radius_km, place_types
        )
    except Exception as exc:  # noqa: BLE001 — enumeration is best-effort; a dead endpoint is a note
        logger.warning("outreach_geo.overpass_failed", extra={"city": query, "error": str(exc)})
        return {"city": city_out, "subareas": [], "note": "Could not reach the sub-area source."}

    if not raw:
        return {"city": city_out, "subareas": [], "note": "No sub-areas found for this city."}

    candidates = prefilter_in_bounds(
        dedupe_by_name(raw), city_geo, settings.outreach_subarea_bounds_pad
    )[: settings.outreach_subarea_max_candidates]

    queries = [subarea_query(c["name"], city_geo) for c in candidates]
    try:
        geo_map = await maps_geocode.forward_geocode_places(queries, supabase=supabase)
    except Exception as exc:  # noqa: BLE001
        logger.warning("outreach_geo.verify_failed", extra={"city": query, "error": str(exc)})
        return {"city": city_out, "subareas": [], "note": "Could not verify sub-areas."}

    verified = verified_subareas(candidates, geo_map, city_geo)[: settings.outreach_subarea_max_results]
    note = None if verified else "No sub-areas passed verification for this city."
    return {"city": city_out, "subareas": verified, "note": note}

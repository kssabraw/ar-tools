"""Pure-helper tests for the any-city geo layer (services/outreach_geo).

Only the pure helpers are exercised here — name/query building, de-dup, the cheap in-bounds
prefilter, and the Google-verification filter. The async orchestration (`resolve_city`,
`enumerate_subareas`) is thin I/O over these and over already-tested primitives
(`maps_geocode.forward_geocode_places`, `overpass.places_near`, `place_is_within_city`), so it is
left to live verification rather than mocked end to end.
"""

from __future__ import annotations

from services import outreach_geo as og


# A resolved city with a real bounding box (LA-ish, rounded).
CITY = {
    "matched": True,
    "city": "Los Angeles",
    "admin_area": "California",
    "country": "United States",
    "formatted": "Los Angeles, CA, USA",
    "place_id": "CITY",
    "result_types": ["locality", "political"],
    "lat": 34.05,
    "lng": -118.24,
    "bounds": {"sw_lat": 33.70, "ne_lat": 34.34, "sw_lng": -118.67, "ne_lng": -118.15},
}


def _sub_geo(place_id, lat, lng, types=("neighborhood",)):
    return {
        "matched": True,
        "place_id": place_id,
        "result_types": list(types),
        "lat": lat,
        "lng": lng,
        "bounds": None,
    }


# --- name / query building --------------------------------------------------------------------


def test_city_region_and_display():
    assert og.city_region(CITY) == "California, United States"
    assert og.city_display_name(CITY) == "Los Angeles, CA, USA"


def test_city_display_falls_back_without_formatted():
    geo = {**CITY, "formatted": None}
    assert og.city_display_name(geo) == "Los Angeles, California, United States"


def test_subarea_query_disambiguates_with_region():
    # The region suffix is what stops "Highland Park, Los Angeles" resolving to the wrong state.
    assert og.subarea_query("Highland Park", CITY) == (
        "Highland Park, Los Angeles, California, United States"
    )


# --- de-dup -----------------------------------------------------------------------------------


def test_dedupe_by_name_is_case_insensitive_first_wins():
    items = [
        {"name": "Echo Park", "lat": 1},
        {"name": "echo park", "lat": 2},
        {"name": "Silver Lake", "lat": 3},
        {"name": "", "lat": 4},
    ]
    out = og.dedupe_by_name(items)
    assert [i["name"] for i in out] == ["Echo Park", "Silver Lake"]
    assert out[0]["lat"] == 1  # first occurrence kept


# --- cheap in-bounds prefilter ----------------------------------------------------------------


def test_prefilter_keeps_in_bounds_drops_outside():
    cands = [
        {"name": "Echo Park", "lat": 34.08, "lng": -118.26},   # inside
        {"name": "Faraway", "lat": 40.71, "lng": -74.00},      # NYC — outside
        {"name": "NoCoords", "lat": None, "lng": None},        # unusable
    ]
    kept = og.prefilter_in_bounds(cands, CITY, pad=0.15)
    assert [c["name"] for c in kept] == ["Echo Park"]


def test_prefilter_keeps_all_when_city_has_no_bounds():
    geo = {**CITY, "bounds": None}
    cands = [{"name": "A", "lat": 34.0, "lng": -118.2}, {"name": "B", "lat": 40.0, "lng": -74.0}]
    # No box to trim against — the radius already bounded the search and Google verify is the gate.
    assert og.prefilter_in_bounds(cands, geo, pad=0.15) == cands


# --- Google-verification filter ---------------------------------------------------------------


def test_verified_keeps_inside_city_uses_geocoded_center():
    cands = [{"name": "Echo Park"}]
    geo_map = {og.subarea_query("Echo Park", CITY): _sub_geo("SUB1", 34.08, -118.26)}
    out = og.verified_subareas(cands, geo_map, CITY)
    assert out == [{"name": "Echo Park", "lat": 34.08, "lng": -118.26, "place_id": "SUB1"}]


def test_verified_drops_unmatched_and_outside_and_too_big():
    cands = [
        {"name": "Good"},        # inside -> kept
        {"name": "Unmatched"},   # not matched -> dropped
        {"name": "Faraway"},     # outside the box -> dropped
        {"name": "County"},      # admin_area_level_2 -> too big, dropped
        {"name": "IsCity"},      # snapped to the city's own place_id -> dropped
    ]
    geo_map = {
        og.subarea_query("Good", CITY): _sub_geo("G", 34.10, -118.30),
        og.subarea_query("Unmatched", CITY): {"matched": False},
        og.subarea_query("Faraway", CITY): _sub_geo("F", 40.71, -74.00),
        og.subarea_query("County", CITY): _sub_geo(
            "C", 34.10, -118.30, types=("administrative_area_level_2",)
        ),
        og.subarea_query("IsCity", CITY): _sub_geo("CITY", 34.05, -118.24),
    }
    out = og.verified_subareas(cands, geo_map, CITY)
    assert [o["name"] for o in out] == ["Good"]


def test_verified_dedupes_on_resolved_place_id():
    # Two candidate names that snap to the same Google place collapse to one.
    cands = [{"name": "Echo Park"}, {"name": "Echo Pk"}]
    geo_map = {
        og.subarea_query("Echo Park", CITY): _sub_geo("SAME", 34.08, -118.26),
        og.subarea_query("Echo Pk", CITY): _sub_geo("SAME", 34.08, -118.26),
    }
    out = og.verified_subareas(cands, geo_map, CITY)
    assert len(out) == 1 and out[0]["name"] == "Echo Park"

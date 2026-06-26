"""Unit tests for the Local SEO silo planner's country-agnostic neighborhood
discovery (Module #2).

Verification is geographic, not name-nesting: a proposed sub-area is kept only if
it geocodes to a place INSIDE the target city's footprint. That works worldwide —
a US neighborhood (nested in the city's locality) and an AU/UK suburb (its own
locality) are both accepted when their centre is inside the city box, while
adjacent towns, oversized regions, and centroid-fallback bogus names are dropped.

Pure logic + the discovery orchestration with the LLM proposal and the Google
forward-geocode call mocked — no network, no Anthropic.
"""

import asyncio

from config import settings
from services import local_seo_silo as silo
from services import maps_geocode as mg

# Real-ish city footprints (north-east / south-west corners).
ANAHEIM = {"ne_lat": 33.86, "ne_lng": -117.68, "sw_lat": 33.79, "sw_lng": -117.95}
SYDNEY = {"ne_lat": -33.578, "ne_lng": 151.343, "sw_lat": -34.118, "sw_lng": 150.520}


# ── parse_forward_result (maps_geocode) ───────────────────────────────────────
def test_parse_forward_result_extracts_city_country_types_bounds():
    results = [
        {
            "address_components": [
                {"long_name": "Anaheim Hills", "types": ["neighborhood", "political"]},
                {"long_name": "Anaheim", "types": ["locality", "political"]},
                {"long_name": "California", "types": ["administrative_area_level_1"]},
                {"long_name": "United States", "types": ["country", "political"]},
            ],
            "formatted_address": "Anaheim Hills, Anaheim, CA, USA",
            "geometry": {
                "location": {"lat": 33.85, "lng": -117.74},
                "bounds": {"northeast": {"lat": 33.86, "lng": -117.72},
                           "southwest": {"lat": 33.83, "lng": -117.76}},
            },
            "place_id": "abc",
            "types": ["neighborhood", "political"],
        }
    ]
    parsed = mg.parse_forward_result(results)
    assert parsed["matched"] is True
    assert parsed["city"] == "Anaheim"          # locality wins (forward city = locality/postal_town only)
    assert parsed["admin_area"] == "California"
    assert parsed["country"] == "United States"
    assert parsed["result_types"] == ["neighborhood", "political"]
    assert parsed["lat"] == 33.85 and parsed["lng"] == -117.74
    assert parsed["bounds"] == {"ne_lat": 33.86, "ne_lng": -117.72, "sw_lat": 33.83, "sw_lng": -117.76}


def test_parse_forward_result_falls_back_to_viewport_when_no_bounds():
    results = [{
        "geometry": {
            "location": {"lat": 1.0, "lng": 2.0},
            "viewport": {"northeast": {"lat": 1.5, "lng": 2.5},
                         "southwest": {"lat": 0.5, "lng": 1.5}},
        },
        "types": ["locality"],
    }]
    parsed = mg.parse_forward_result(results)
    assert parsed["bounds"] == {"ne_lat": 1.5, "ne_lng": 2.5, "sw_lat": 0.5, "sw_lng": 1.5}


def test_parse_forward_result_blank_on_no_results():
    parsed = mg.parse_forward_result(None)
    assert parsed["matched"] is False
    assert parsed["city"] is None and parsed["result_types"] == [] and parsed["bounds"] is None


def test_parse_forward_result_city_is_locality_only_not_neighborhood():
    # No `locality` component → city is None (never the place's own name).
    results = [{
        "address_components": [
            {"long_name": "Downtown", "types": ["neighborhood", "political"]},
            {"long_name": "California", "types": ["administrative_area_level_1"]},
        ],
        "types": ["neighborhood", "political"],
        "geometry": {"location": {"lat": 1.0, "lng": 2.0}},
    }]
    assert mg.parse_forward_result(results)["city"] is None


# ── point_in_bounds / haversine_km (pure geometry) ────────────────────────────
def test_point_in_bounds_inside_and_outside():
    assert mg.point_in_bounds(33.85, -117.74, ANAHEIM) is True
    # Garden Grove centre sits just south of Anaheim's box → outside.
    assert mg.point_in_bounds(33.7739, -117.9414, ANAHEIM) is False


def test_point_in_bounds_handles_southern_hemisphere():
    # Bondi inside Greater Sydney; Newcastle (120 km north) outside.
    assert mg.point_in_bounds(-33.8915, 151.2767, SYDNEY) is True
    assert mg.point_in_bounds(-32.9283, 151.7817, SYDNEY) is False


def test_point_in_bounds_pad_expands_box():
    pt_lat, pt_lng = 33.788, -117.80  # ~0.002° below the box
    assert mg.point_in_bounds(pt_lat, pt_lng, ANAHEIM, pad=0.0) is False
    assert mg.point_in_bounds(pt_lat, pt_lng, ANAHEIM, pad=0.1) is True


def test_point_in_bounds_none_bounds():
    assert mg.point_in_bounds(1.0, 2.0, None) is False


def test_haversine_km_known_distance():
    # Anaheim → Garden Grove is ~5 km.
    d = mg.haversine_km(33.8366, -117.9143, 33.7739, -117.9414)
    assert 5 < d < 9


# ── place_is_within_city (the country-agnostic gate) ──────────────────────────
CITY_ANAHEIM = {"matched": True, "place_id": "city_anaheim", "bounds": ANAHEIM, "lat": 33.83, "lng": -117.81}
CITY_SYDNEY = {"matched": True, "place_id": "city_sydney", "bounds": SYDNEY, "lat": -33.87, "lng": 151.21}


def _cand(**kw):
    base = {"matched": True, "place_id": "x", "result_types": ["neighborhood"], "lat": 33.85, "lng": -117.74}
    base.update(kw)
    return base


def test_within_city_accepts_us_neighborhood_inside_bounds():
    assert silo.place_is_within_city(_cand(place_id="ah"), CITY_ANAHEIM) is True


def test_within_city_accepts_au_suburb_that_is_its_own_locality():
    # Bondi geocodes as its OWN locality (not nested in Sydney) — still accepted
    # because its centre is inside Greater Sydney's footprint.
    bondi = _cand(place_id="bondi", result_types=["locality", "political"], lat=-33.8915, lng=151.2767)
    assert silo.place_is_within_city(bondi, CITY_SYDNEY) is True


def test_within_city_rejects_adjacent_city_outside_bounds():
    gg = _cand(place_id="gg", result_types=["locality", "political"], lat=33.7739, lng=-117.9414)
    assert silo.place_is_within_city(gg, CITY_ANAHEIM) is False


def test_within_city_rejects_centroid_fallback_same_place_id():
    # A bogus name snapped to the city itself → identical place_id.
    bogus = _cand(place_id="city_anaheim", lat=33.83, lng=-117.81)
    assert silo.place_is_within_city(bogus, CITY_ANAHEIM) is False


def test_within_city_rejects_oversized_region_even_if_centre_inside():
    county = _cand(place_id="oc", result_types=["administrative_area_level_2", "political"], lat=33.83, lng=-117.81)
    assert silo.place_is_within_city(county, CITY_ANAHEIM) is False


def test_within_city_radius_fallback_when_city_has_no_bounds():
    city = {"matched": True, "place_id": "c", "bounds": None, "lat": 33.83, "lng": -117.81}
    near = _cand(place_id="n", lat=33.85, lng=-117.74)   # ~7 km
    far = _cand(place_id="f", lat=34.40, lng=-117.81)     # ~63 km
    assert silo.place_is_within_city(near, city) is True
    assert silo.place_is_within_city(far, city) is False


def test_within_city_rejects_unmatched_or_no_coords():
    assert silo.place_is_within_city({"matched": False}, CITY_ANAHEIM) is False
    assert silo.place_is_within_city(_cand(lat=None, lng=None), CITY_ANAHEIM) is False
    assert silo.place_is_within_city(_cand(), {"matched": False}) is False


# ── _parse_area ───────────────────────────────────────────────────────────────
def test_parse_area_full_and_partial():
    assert silo._parse_area("Anaheim,California,United States") == ("Anaheim", "California", "United States")
    assert silo._parse_area("Anaheim, California, United States") == ("Anaheim", "California", "United States")
    assert silo._parse_area("Anaheim") == ("Anaheim", "", "")
    assert silo._parse_area("") == ("", "", "")


def test_parse_area_two_segments_is_city_country_not_state():
    assert silo._parse_area("London,United Kingdom") == ("London", "", "United Kingdom")


def _pg(*keywords):
    return [{"keyword": k, "supporting_keywords": []} for k in keywords]


def _kw(entry):
    return [p["keyword"] for p in entry["pages"]]


# ── _generate_service_pages (service-variation generation, mocked LLM) ────────
class _FakeLLM:
    def __init__(self, payload):
        self._payload = payload

    def call_tool(self, **kw):
        return self._payload


def test_generate_service_pages_groups_and_dedupes():
    llm = _FakeLLM({"silos": [
        {"name": "Availability", "pages": [
            {"keyword": "24 hour emergency plumber sydney",
             "supporting_keywords": ["24/7 emergency plumber sydney", "24 hour emergency plumber sydney"]},
            {"keyword": "after hours emergency plumber sydney", "supporting_keywords": []},
        ]},
        {"name": "Audience", "pages": [
            {"keyword": "commercial emergency plumber sydney", "supporting_keywords": []},
            {"keyword": "24 Hour Emergency Plumber Sydney", "supporting_keywords": []},  # cross-silo dup → dropped
        ]},
        {"name": "Empty", "pages": []},  # no pages → silo dropped
    ]})
    per_silo = silo._generate_service_pages("emergency plumber", "Sydney", llm)
    assert [s["silo"] for s in per_silo] == ["Availability", "Audience"]
    # supporting de-duped against the page's own keyword; plurals/phrasings kept.
    assert per_silo[0]["pages"][0] == {
        "keyword": "24 hour emergency plumber sydney",
        "supporting_keywords": ["24/7 emergency plumber sydney"],
    }
    assert [p["keyword"] for p in per_silo[0]["pages"]] == [
        "24 hour emergency plumber sydney", "after hours emergency plumber sydney"]
    # the case-insensitive cross-silo duplicate dropped → Audience keeps only commercial.
    assert [p["keyword"] for p in per_silo[1]["pages"]] == ["commercial emergency plumber sydney"]


# ── _discover_neighborhood_silo (orchestration, mocked) ───────────────────────
_CITY_Q = "Anaheim, California, United States"
_GEO = {
    _CITY_Q: CITY_ANAHEIM,
    "Anaheim Hills, Anaheim, California, United States":
        {"matched": True, "place_id": "ah", "result_types": ["neighborhood"], "lat": 33.85, "lng": -117.74},
    "West Anaheim, Anaheim, California, United States":
        {"matched": True, "place_id": "wa", "result_types": ["neighborhood"], "lat": 33.82, "lng": -117.92},
    "Garden Grove, Anaheim, California, United States":   # adjacent city, outside bounds
        {"matched": True, "place_id": "gg", "result_types": ["locality"], "lat": 33.7739, "lng": -117.9414},
    "Fakeville, Anaheim, California, United States":      # centroid fallback
        {"matched": True, "place_id": "city_anaheim", "result_types": ["locality"], "lat": 33.83, "lng": -117.81},
    "Orange County, Anaheim, California, United States":  # too big
        {"matched": True, "place_id": "oc", "result_types": ["administrative_area_level_2"], "lat": 33.83, "lng": -117.81},
}


def _run(coro):
    return asyncio.run(coro)


def _patch_keys(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "x", raising=False)
    monkeypatch.setattr(settings, "google_maps_api_key", "x", raising=False)


def _patch_geo(monkeypatch, geo):
    async def fake_geo(queries, **kw):
        return {q: geo[q] for q in queries}
    monkeypatch.setattr(mg, "forward_geocode_places", fake_geo)


def test_discover_keeps_only_verified_within_city(monkeypatch):
    _patch_keys(monkeypatch)
    monkeypatch.setattr(
        silo, "_propose_neighborhoods",
        lambda city, state, country, max_n: ["Anaheim Hills", "Garden Grove", "Fakeville", "West Anaheim", "Orange County"],
    )
    _patch_geo(monkeypatch, _GEO)

    entry, notes = _run(silo._discover_neighborhood_silo("plumber", _CITY_Q, [], supabase=None))
    assert entry["silo"] == silo._NEIGHBORHOOD_SILO
    # Garden Grove (outside), Fakeville (centroid), Orange County (too big) all dropped.
    assert _kw(entry) == ["plumber Anaheim Hills", "plumber West Anaheim"]
    assert notes == []


def test_discover_dedupes_against_existing_silos(monkeypatch):
    _patch_keys(monkeypatch)
    monkeypatch.setattr(
        silo, "_propose_neighborhoods",
        lambda city, state, country, max_n: ["Anaheim Hills", "West Anaheim"],
    )
    _patch_geo(monkeypatch, _GEO)

    per_silo = [{"silo": "Emergency Plumbing", "pages": _pg("Plumber Anaheim Hills")}]
    entry, _ = _run(silo._discover_neighborhood_silo("plumber", _CITY_Q, per_silo, supabase=None))
    assert _kw(entry) == ["plumber West Anaheim"]


def test_discover_skipped_without_maps_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "x", raising=False)
    monkeypatch.setattr(settings, "google_maps_api_key", "", raising=False)
    entry, notes = _run(silo._discover_neighborhood_silo("plumber", _CITY_Q, [], supabase=None))
    assert entry is None and notes and "geocoding not configured" in notes[0]


def test_discover_skipped_without_city(monkeypatch):
    _patch_keys(monkeypatch)
    entry, notes = _run(silo._discover_neighborhood_silo("plumber", "", [], supabase=None))
    assert entry is None and notes and "no city" in notes[0].lower()


def test_discover_skipped_when_city_unresolved(monkeypatch):
    _patch_keys(monkeypatch)
    monkeypatch.setattr(silo, "_propose_neighborhoods", lambda c, s, co, n: ["Anaheim Hills"])
    geo = {_CITY_Q: {"matched": False, "bounds": None, "lat": None},
           "Anaheim Hills, Anaheim, California, United States": _GEO["Anaheim Hills, Anaheim, California, United States"]}
    _patch_geo(monkeypatch, geo)
    entry, notes = _run(silo._discover_neighborhood_silo("plumber", _CITY_Q, [], supabase=None))
    assert entry is None and notes and "couldn't resolve the city" in notes[0]


def test_discover_note_when_nothing_verifies(monkeypatch):
    _patch_keys(monkeypatch)
    monkeypatch.setattr(silo, "_propose_neighborhoods", lambda c, s, co, n: ["Garden Grove"])
    _patch_geo(monkeypatch, _GEO)
    entry, notes = _run(silo._discover_neighborhood_silo("plumber", _CITY_Q, [], supabase=None))
    assert entry is None and notes and "verified" in notes[0].lower()

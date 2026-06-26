"""Unit tests for services.overpass — pure query-build and parse helpers."""

from __future__ import annotations

from services import overpass


def test_build_nearby_cities_query():
    q = overpass.build_nearby_cities_query(-33.87, 151.21, 16093, ("city", "town"))
    assert "node[\"place\"~\"^(city|town)$\"]" in q
    assert "(around:16093,-33.87,151.21)" in q
    assert q.startswith("[out:json]")
    assert q.rstrip().endswith("out;")


def test_parse_overpass_elements_prefers_en_and_dedupes():
    body = {
        "elements": [
            {"tags": {"name": "Parramatta", "place": "town"}, "lat": -33.81, "lon": 151.0},
            {"tags": {"name:en": "Newtown", "name": "Newtown AU"}, "lat": -33.9, "lon": 151.18},
            {"tags": {"name": "Parramatta"}, "lat": -33.81, "lon": 151.0},  # dup name
            {"tags": {"place": "city"}, "lat": 1.0, "lon": 2.0},  # no name → skipped
            {"tags": {"name": "NoCoords"}},  # missing lat/lon → skipped
        ]
    }
    out = overpass.parse_overpass_elements(body)
    names = [c["name"] for c in out]
    assert names == ["Parramatta", "Newtown"]
    assert out[1]["name"] == "Newtown"  # name:en preferred
    assert out[0]["place"] == "town"


def test_parse_overpass_elements_empty():
    assert overpass.parse_overpass_elements({}) == []
    assert overpass.parse_overpass_elements({"elements": []}) == []

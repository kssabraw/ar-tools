"""Unit tests for services.target_cities — pure helpers.

The network resolver (resolve_target_cities) needs geocoding/Overpass and isn't
exercised here; the slug/name + area parsing helpers are.
"""

from __future__ import annotations

import asyncio

from services import target_cities as tc


def test_parse_area():
    assert tc._parse_area("Sydney,New South Wales,Australia") == ("Sydney", "New South Wales", "Australia")
    assert tc._parse_area("London,United Kingdom") == ("London", "", "United Kingdom")
    assert tc._parse_area("Austin") == ("Austin", "", "")
    assert tc._parse_area("") == ("", "", "")


def test_slug_to_name():
    assert tc._slug_to_name("inner-west") == "Inner West"
    assert tc._slug_to_name("los_angeles") == "Los Angeles"
    assert tc._slug_to_name("parramatta") == "Parramatta"


def test_website_candidate_names_dedupes_and_titlecases():
    urls = [
        "https://acme.com/parramatta/",
        "https://acme.com/service-areas/inner-west/",
        "https://acme.com/PARRAMATTA/",  # dup (case-insensitive)
        "https://acme.com/",
    ]
    names = tc.website_candidate_names(urls)
    # Order: first-seen; segments include 'Service Areas' before 'Inner West'.
    assert "Parramatta" in names
    assert "Inner West" in names
    assert "Service Areas" in names
    # case-insensitive dedupe — Parramatta appears once
    assert names.count("Parramatta") == 1


def test_resolve_target_cities_radius_hard_bounds_authoritative_sources(monkeypatch):
    """A GBP service-area city is normally kept regardless of distance; an explicit
    center + radius HARD-BOUNDS it (owner ruling 2026-09-14): a far city is dropped."""
    async def _fake_geocode(queries, supabase=None):
        out = {}
        for q in queries:
            if "farcity" in q.lower():
                # ~78 km from (0, 0) — well beyond a 16 km radius.
                out[q] = {"matched": True, "place_id": "far", "result_types": ["locality"],
                          "lat": 0.5, "lng": 0.5, "bounds": None, "admin_area": "ST", "country": "US"}
            else:
                out[q] = {"matched": True, "place_id": "seed", "result_types": ["locality"],
                          "lat": 0.0, "lng": 0.0, "bounds": None, "admin_area": "ST", "country": "US"}
        return out

    async def _fake_nearby(lat, lng, radius_km):
        return []

    monkeypatch.setattr(tc.settings, "google_maps_api_key", "x")
    monkeypatch.setattr(tc.maps_geocode, "forward_geocode_places", _fake_geocode)
    monkeypatch.setattr(tc.overpass, "nearby_cities", _fake_nearby)
    client = {"gbp": {"service_area_places": ["FarCity"]}}

    # Legacy (no radius): the GBP service-area city is kept regardless of distance.
    cities, _ = asyncio.run(tc.resolve_target_cities(client, "Seedville,ST,US", 1, None))
    assert "FarCity" in [c["name"] for c in cities]

    # Hard bound: FarCity is ~78 km from the (0, 0) center → beyond 16 km → dropped.
    cities2, _ = asyncio.run(
        tc.resolve_target_cities(client, "Seedville,ST,US", 1, None, center=(0.0, 0.0), radius_km=16.09)
    )
    assert "FarCity" not in [c["name"] for c in cities2]

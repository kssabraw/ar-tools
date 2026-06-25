"""Unit tests for the Local SEO silo planner's geocoding-verified neighborhood
discovery (Module #2).

Pure logic + the discovery orchestration with the LLM proposal and the Google
forward-geocode call mocked — no network, no Anthropic. The verification gate
(`neighborhood_is_in_city`) and the forward-geocode parser are exercised
directly; `_discover_neighborhood_silo` is driven with stubbed proposal/geocode
to prove adjacent towns + centroid fallbacks are dropped and within-city
neighborhoods become "<service> <neighborhood>" page targets.
"""

import asyncio

from config import settings
from services import local_seo_silo as silo
from services import maps_geocode as mg


# ── parse_forward_result (maps_geocode) ───────────────────────────────────────
def test_parse_forward_result_extracts_city_types_geometry():
    results = [
        {
            "address_components": [
                {"long_name": "Anaheim Hills", "types": ["neighborhood", "political"]},
                {"long_name": "Anaheim", "types": ["locality", "political"]},
                {"long_name": "California", "types": ["administrative_area_level_1"]},
            ],
            "formatted_address": "Anaheim Hills, Anaheim, CA, USA",
            "geometry": {"location": {"lat": 33.85, "lng": -117.74}},
            "place_id": "abc",
            "types": ["neighborhood", "political"],
        }
    ]
    parsed = mg.parse_forward_result(results)
    assert parsed["matched"] is True
    assert parsed["city"] == "Anaheim"          # locality wins over the neighborhood component
    assert parsed["admin_area"] == "California"
    assert parsed["result_types"] == ["neighborhood", "political"]
    assert parsed["lat"] == 33.85 and parsed["lng"] == -117.74


def test_parse_forward_result_blank_on_no_results():
    parsed = mg.parse_forward_result(None)
    assert parsed["matched"] is False
    assert parsed["city"] is None and parsed["result_types"] == []


# ── neighborhood_is_in_city (the verification gate) ───────────────────────────
def test_in_city_accepts_neighborhood_in_target_city():
    parsed = {"matched": True, "city": "Anaheim", "result_types": ["neighborhood", "political"]}
    assert silo.neighborhood_is_in_city(parsed, "Anaheim") is True


def test_in_city_accepts_sublocality():
    parsed = {"matched": True, "city": "anaheim", "result_types": ["sublocality_level_1"]}
    assert silo.neighborhood_is_in_city(parsed, "Anaheim") is True  # case-insensitive


def test_in_city_rejects_adjacent_city():
    # Resolves to its own locality (a separate incorporated city) — not in Anaheim.
    parsed = {"matched": True, "city": "Garden Grove", "result_types": ["locality", "political"]}
    assert silo.neighborhood_is_in_city(parsed, "Anaheim") is False


def test_in_city_rejects_city_centroid_fallback():
    # Right city, but Google fell back to the locality (no neighborhood-level type)
    # — a bogus/unknown name, so it's dropped.
    parsed = {"matched": True, "city": "Anaheim", "result_types": ["locality", "political"]}
    assert silo.neighborhood_is_in_city(parsed, "Anaheim") is False


def test_in_city_rejects_unmatched():
    assert silo.neighborhood_is_in_city({"matched": False}, "Anaheim") is False
    assert silo.neighborhood_is_in_city({}, "Anaheim") is False


# ── _parse_area ───────────────────────────────────────────────────────────────
def test_parse_area_full_and_partial():
    assert silo._parse_area("Anaheim,California,United States") == ("Anaheim", "California", "United States")
    assert silo._parse_area("Anaheim, California, United States") == ("Anaheim", "California", "United States")
    assert silo._parse_area("Anaheim") == ("Anaheim", "", "")
    assert silo._parse_area("") == ("", "", "")


# ── _discover_neighborhood_silo (orchestration, mocked) ───────────────────────
_GEO = {
    "Anaheim Hills, Anaheim, California, United States":
        {"matched": True, "city": "Anaheim", "result_types": ["neighborhood", "political"]},
    "West Anaheim, Anaheim, California, United States":
        {"matched": True, "city": "Anaheim", "result_types": ["sublocality_level_1"]},
    "Garden Grove, Anaheim, California, United States":  # adjacent incorporated city
        {"matched": True, "city": "Garden Grove", "result_types": ["locality", "political"]},
    "Fakeville, Anaheim, California, United States":     # centroid fallback (no nbhd type)
        {"matched": True, "city": "Anaheim", "result_types": ["locality", "political"]},
}


def _run(coro):
    return asyncio.run(coro)


def _patch_keys(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "x", raising=False)
    monkeypatch.setattr(settings, "google_maps_api_key", "x", raising=False)


def test_discover_keeps_only_verified_within_city(monkeypatch):
    _patch_keys(monkeypatch)
    monkeypatch.setattr(
        silo, "_propose_neighborhoods",
        lambda city, state, max_n: ["Anaheim Hills", "Garden Grove", "West Anaheim", "Fakeville"],
    )

    async def fake_geo(queries, **kw):
        return {q: _GEO[q] for q in queries}

    monkeypatch.setattr(mg, "forward_geocode_places", fake_geo)

    entry, notes = _run(silo._discover_neighborhood_silo(
        "plumber", "Anaheim,California,United States", [], supabase=None,
    ))
    assert entry["silo"] == silo._NEIGHBORHOOD_SILO
    # Garden Grove (adjacent city) and Fakeville (centroid fallback) are dropped.
    assert entry["pages"] == ["plumber Anaheim Hills", "plumber West Anaheim"]
    assert notes == []


def test_discover_dedupes_against_existing_silos(monkeypatch):
    _patch_keys(monkeypatch)
    monkeypatch.setattr(
        silo, "_propose_neighborhoods",
        lambda city, state, max_n: ["Anaheim Hills", "West Anaheim"],
    )

    async def fake_geo(queries, **kw):
        return {q: _GEO[q] for q in queries}

    monkeypatch.setattr(mg, "forward_geocode_places", fake_geo)

    # The Fanout expansion already surfaced this page in another silo (case-insensitive).
    per_silo = [{"silo": "Emergency Plumbing", "pages": ["Plumber Anaheim Hills"]}]
    entry, _ = _run(silo._discover_neighborhood_silo(
        "plumber", "Anaheim,California,United States", per_silo, supabase=None,
    ))
    assert entry["pages"] == ["plumber West Anaheim"]


def test_discover_skipped_without_maps_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "x", raising=False)
    monkeypatch.setattr(settings, "google_maps_api_key", "", raising=False)
    entry, notes = _run(silo._discover_neighborhood_silo(
        "plumber", "Anaheim,California,United States", [], supabase=None,
    ))
    assert entry is None
    assert notes and "geocoding not configured" in notes[0]


def test_discover_skipped_without_city(monkeypatch):
    _patch_keys(monkeypatch)
    entry, notes = _run(silo._discover_neighborhood_silo("plumber", "", [], supabase=None))
    assert entry is None
    assert notes and "no city" in notes[0].lower()


def test_discover_note_when_nothing_verifies(monkeypatch):
    _patch_keys(monkeypatch)
    monkeypatch.setattr(silo, "_propose_neighborhoods", lambda city, state, max_n: ["Garden Grove"])

    async def fake_geo(queries, **kw):
        return {q: _GEO[q] for q in queries}

    monkeypatch.setattr(mg, "forward_geocode_places", fake_geo)
    entry, notes = _run(silo._discover_neighborhood_silo(
        "plumber", "Anaheim,California,United States", [], supabase=None,
    ))
    assert entry is None
    assert notes and "verified" in notes[0].lower()

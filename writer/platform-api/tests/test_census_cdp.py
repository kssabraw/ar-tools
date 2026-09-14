"""Unit tests for services/census_cdp.py (Coverage Audit Tier 3 — CDP enumeration).

The live TIGERweb / census.gov queries can't run in the sandbox (census.gov is
egress-blocked), so this covers the PURE decision helpers (layer pick, feature
parse, footprint bbox, containment pre-filter, county scope, axis assembly,
staleness) plus the `resolve_cdp_axis` orchestrator with every network call
(forward-geocode, county reverse-geocode, state CDP enumeration) mocked. The live
TIGERweb query itself is verified on the deployed worker after merge.
"""

import asyncio

import pytest

from services import census_cdp as cdp


# ── pick_cdp_layer ─────────────────────────────────────────────────────────────
def test_pick_cdp_layer_prefers_exact_census_designated_places():
    layers = [
        {"id": 30, "name": "Incorporated Places"},
        {"id": 32, "name": "Census Designated Places Labels"},  # label — skipped
        {"id": 36, "name": "Census Designated Places"},
        {"id": 38, "name": "American Indian Designated Places"},
    ]
    assert cdp.pick_cdp_layer(layers) == 36


def test_pick_cdp_layer_falls_back_to_designated_place_excluding_label_and_tribal():
    layers = [
        {"id": 1, "name": "Some Designated Place Labels"},  # label — skipped
        {"id": 2, "name": "Tribal Designated Place"},        # tribal — skipped
        {"id": 3, "name": "Other Designated Place"},         # fallback match
    ]
    assert cdp.pick_cdp_layer(layers) == 3


def test_pick_cdp_layer_none_when_absent():
    assert cdp.pick_cdp_layer([{"id": 1, "name": "Counties"}, {"id": 2, "name": "States"}]) is None
    assert cdp.pick_cdp_layer([]) is None


# ── parse_cdp_features ─────────────────────────────────────────────────────────
def test_parse_cdp_features_extracts_name_geoid_centroid():
    resp = {
        "features": [
            {"attributes": {"NAME": "Harrison", "GEOID": "3400123", "CENTLAT": "+40.75", "CENTLON": "-74.16"}},
            {"attributes": {"BASENAME": "Kearny", "GEOID": "3400234", "INTPTLAT": "+40.77", "INTPTLON": "-74.15"}},
            {"attributes": {"NAME": "", "CENTLAT": "+1", "CENTLON": "+1"}},        # no name — dropped
            {"attributes": {"NAME": "NoCoords", "GEOID": "x"}},                    # no centroid — dropped
        ],
        "exceededTransferLimit": True,
    }
    feats, exceeded = cdp.parse_cdp_features(resp)
    assert exceeded is True
    assert [f["name"] for f in feats] == ["Harrison", "Kearny"]
    assert feats[0]["lat"] == 40.75 and feats[0]["lng"] == -74.16
    assert feats[1]["lat"] == 40.77  # INTPTLAT fallback + leading '+' stripped


def test_parse_cdp_features_empty():
    feats, exceeded = cdp.parse_cdp_features({})
    assert feats == [] and exceeded is False


# ── footprint_bbox / point_in_bbox ─────────────────────────────────────────────
def test_footprint_bbox_bounds_and_pads():
    bbox = cdp.footprint_bbox([(40.0, -74.0), (40.5, -74.5)], pad_km=30.0)
    la_min, la_max, ln_min, ln_max = bbox
    # Padded outward beyond the raw min/max on every side.
    assert la_min < 40.0 and la_max > 40.5
    assert ln_min < -74.5 and ln_max > -74.0


def test_footprint_bbox_none_without_points():
    assert cdp.footprint_bbox([], 30.0) is None
    assert cdp.footprint_bbox([(None, None)], 30.0) is None


def test_point_in_bbox():
    bbox = (39.7, 40.97, -74.55, -73.6)
    assert cdp.point_in_bbox(40.0, -74.0, bbox) is True     # inside
    assert cdp.point_in_bbox(10.0, 10.0, bbox) is False     # far outside
    assert cdp.point_in_bbox(None, -74.0, bbox) is False    # missing coord
    assert cdp.point_in_bbox(40.0, -74.0, None) is False    # no bbox


# ── build_footprint_geos ───────────────────────────────────────────────────────
def test_build_footprint_geos_includes_seed_and_synthesizes_targets():
    seed_geo = {"matched": True, "place_id": "seedpid", "lat": 40.0, "lng": -74.0, "bounds": {"x": 1}}
    targets = [
        {"name": "Newark", "lat": 40.7, "lng": -74.17, "bounds": {"y": 1}, "place_id": "newarkpid"},
        {"name": "NoCoords", "lat": None, "lng": None},  # skipped
    ]
    geos = cdp.build_footprint_geos(seed_geo, targets)
    assert len(geos) == 2
    assert geos[0] is seed_geo
    assert geos[1]["matched"] is True and geos[1]["place_id"] == "newarkpid"
    assert geos[1]["result_types"] == []


# ── resolve_seed_place ──────────────────────────────────────────────────────────
def test_resolve_seed_place_prefers_geocode_locality_over_street_address():
    # A street-address business_location: _parse_area mis-reads the street as the
    # city; the geocode's own components carry the real place.
    seed_geo = {"matched": True, "city": "Fort Lauderdale", "admin_area": "Florida", "country": "United States"}
    city, state, country = cdp.resolve_seed_place(
        seed_geo, "2890 Marina Mile Blvd", "108 W State Rd 84 Suite", "FL 33312"
    )
    assert (city, state, country) == ("Fort Lauderdale", "Florida", "United States")


def test_resolve_seed_place_falls_back_to_parsed_when_geocode_missing_components():
    # A clean "City, State, Country" seed whose geocode carries no components →
    # unchanged (the parsed values win).
    city, state, country = cdp.resolve_seed_place(
        {"matched": True}, "Metropolis", "New York", "United States"
    )
    assert (city, state, country) == ("Metropolis", "New York", "United States")


def test_resolve_seed_place_none_geo_returns_parsed():
    assert cdp.resolve_seed_place(None, "Austin", "Texas", "United States") == (
        "Austin", "Texas", "United States",
    )


def test_build_footprint_geos_skips_unmatched_seed():
    geos = cdp.build_footprint_geos({"matched": False}, [])
    assert geos == []


# ── county_scope ───────────────────────────────────────────────────────────────
def test_county_scope_dedupes_counties_and_states():
    results = [("Hudson County", "34017"), ("Hudson County", "34017"), ("Essex County", "34013"), ("Kings County", "36047")]
    counties, states = cdp.county_scope(results)
    assert counties == ["34013", "34017", "36047"]
    assert states == ["34", "36"]


def test_county_scope_drops_invalid_fips():
    counties, states = cdp.county_scope([("x", "12"), ("y", ""), ("z", "abcde"), None])
    assert counties == [] and states == []


# ── assemble_cdp_axis ──────────────────────────────────────────────────────────
def test_assemble_cdp_axis_dedupes_sorts_and_caps():
    axis = cdp.assemble_cdp_axis(["Kearny", "harrison", "Harrison", "", "Belleville"], cap=2)
    # deduped case-insensitively, sorted by name, capped at 2.
    assert [a["name"] for a in axis] == ["Belleville", "harrison"]
    assert all(a["source"] == "census_cdp" for a in axis)


def test_assemble_cdp_axis_uncapped():
    axis = cdp.assemble_cdp_axis(["B", "A", "C"], cap=0)
    assert [a["name"] for a in axis] == ["A", "B", "C"]


# ── is_stale ───────────────────────────────────────────────────────────────────
def test_is_stale_zero_days_never_stale():
    assert cdp.is_stale("2000-01-01T00:00:00+00:00", 0) is False


def test_is_stale_unparseable_is_stale():
    assert cdp.is_stale("not-a-date", 365) is True


def test_is_stale_fresh_vs_old():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    assert cdp.is_stale(now, 365) is False
    assert cdp.is_stale("2000-01-01T00:00:00+00:00", 365) is True


# ── resolve_cdp_axis (orchestrator — network mocked) ───────────────────────────
def _set_maps_key(monkeypatch, value="key"):
    monkeypatch.setattr(cdp.settings, "google_maps_api_key", value, raising=False)
    monkeypatch.setattr(cdp.settings, "local_seo_neighborhood_radius_km", 30.0, raising=False)
    monkeypatch.setattr(cdp.settings, "coverage_cdp_max", 60, raising=False)
    monkeypatch.setattr(cdp.settings, "coverage_cdp_cache_days", 365, raising=False)


def test_resolve_cdp_axis_no_seed_degrades(monkeypatch):
    _set_maps_key(monkeypatch)
    axis, prov, city_names = asyncio.run(cdp.resolve_cdp_axis({}, "", 2840, object()))
    assert axis == [] and city_names == []
    assert any("no business location" in n.lower() for n in prov["notes"])


def test_resolve_cdp_axis_no_maps_key_degrades(monkeypatch):
    monkeypatch.setattr(cdp.settings, "google_maps_api_key", "", raising=False)
    axis, prov, city_names = asyncio.run(
        cdp.resolve_cdp_axis({}, "Metropolis, New York, United States", 2840, object())
    )
    assert axis == []
    assert city_names == ["Metropolis"]  # seed name still available for place vocab
    assert any("geocoding unavailable" in n.lower() for n in prov["notes"])


def _install_happy_path(monkeypatch, *, county=("Hudson County", "34017"), state_cdps=None):
    """Wire the network mocks for a full happy-path resolve_cdp_axis run."""
    from services import leadoff_counties, maps_geocode, target_cities

    async def _fake_forward(queries, *, supabase=None):
        out = {}
        for q in queries:
            if q.startswith("Metropolis"):  # the seed city
                out[q] = {
                    "matched": True, "place_id": "seedpid", "lat": 40.0, "lng": -74.0,
                    "bounds": {"ne_lat": 40.3, "ne_lng": -73.7, "sw_lat": 39.7, "sw_lng": -74.3},
                    "result_types": ["locality"],
                }
            else:  # a candidate CDP verification
                out[q] = {"matched": True, "place_id": f"cdppid:{q}", "lat": 40.05, "lng": -74.05, "result_types": ["locality"]}
        return out

    async def _fake_targets(client, seed_location, code, sb):
        return ([{"name": "Newark", "lat": 40.7, "lng": -74.17, "bounds": {"z": 1}, "place_id": "newarkpid"}], ["target note"])

    async def _fake_county(client, lat, lng):
        return county

    monkeypatch.setattr(maps_geocode, "forward_geocode_places", _fake_forward)
    monkeypatch.setattr(target_cities, "resolve_target_cities", _fake_targets)
    monkeypatch.setattr(leadoff_counties, "_county_for_coord", _fake_county)
    # Verification is now centroid-based (the synthetic candidate carries the CDP's
    # Census centroid; place_id is None). A centroid near the footprint (lat ~40) is
    # inside; FarAway (lat 10) is bbox-filtered before verification anyway.
    monkeypatch.setattr(
        maps_geocode, "place_is_within_city",
        lambda cand, city: 39.0 < (cand.get("lat") or 0.0) < 41.0,
    )
    # Cache warm → no TIGERweb network. Harrison is in the footprint bbox; FarAway isn't.
    default = [
        {"name": "Harrison", "geoid": "3400123", "lat": 40.02, "lng": -74.02},
        {"name": "FarAway", "geoid": "9999999", "lat": 10.0, "lng": 10.0},
    ]
    monkeypatch.setattr(cdp, "state_cdps_cached", lambda st, days: state_cdps if state_cdps is not None else default)


def test_resolve_cdp_axis_happy_path(monkeypatch):
    _set_maps_key(monkeypatch)
    _install_happy_path(monkeypatch)
    axis, prov, city_names = asyncio.run(
        cdp.resolve_cdp_axis({}, "Metropolis, New York, United States", 2840, object())
    )
    # Only the in-footprint, containment-verified CDP survives.
    assert [a["name"] for a in axis] == ["Harrison"]
    assert axis[0]["source"] == "census_cdp"
    assert city_names == ["Metropolis", "Newark"]  # place vocab: seed + target
    assert prov["states"] == ["34"]
    assert prov["counties"] == ["34017"]
    assert prov["candidates"] == 1  # FarAway pre-filtered out by the bbox
    assert prov["verified"] == 1
    assert "target note" in prov["notes"]


def test_resolve_cdp_axis_no_counties_degrades(monkeypatch):
    _set_maps_key(monkeypatch)
    _install_happy_path(monkeypatch, county=None)  # county reverse-geocode returns nothing
    axis, prov, city_names = asyncio.run(
        cdp.resolve_cdp_axis({}, "Metropolis, New York, United States", 2840, object())
    )
    assert axis == []
    assert city_names == ["Metropolis", "Newark"]  # still usable as place vocab
    assert any("couldn't resolve the service-area counties" in n.lower() for n in prov["notes"])


def test_resolve_cdp_axis_no_cdps_in_footprint_degrades(monkeypatch):
    _set_maps_key(monkeypatch)
    # Every enumerated CDP sits far outside the footprint bbox → zero candidates.
    _install_happy_path(monkeypatch, state_cdps=[{"name": "FarAway", "lat": 10.0, "lng": 10.0}])
    axis, prov, city_names = asyncio.run(
        cdp.resolve_cdp_axis({}, "Metropolis, New York, United States", 2840, object())
    )
    assert axis == []
    assert prov["candidates"] == 0
    assert any("no cdps found within the service-area footprint" in n.lower() for n in prov["notes"])


def test_resolve_cdp_axis_adopts_geocode_city_for_street_address(monkeypatch):
    """A street-address business_location: the seed geocode's own locality/admin/
    country replace the mis-parsed comma-split, and a CITY-level re-geocode (with
    real bounds) becomes the containment footprint — so CDPs verify instead of the
    axis collapsing against a rooftop box (the WheelHouse IT Fort Lauderdale bug)."""
    from services import leadoff_counties, maps_geocode, target_cities

    _set_maps_key(monkeypatch)
    street = "2890 Marina Mile Blvd, 108 W State Rd 84 Suite, Fort Lauderdale, FL 33312"
    city_query = "Fort Lauderdale, Florida, United States"
    seen: dict = {"queries": []}

    async def _fake_forward(queries, *, supabase=None):
        out = {}
        for q in queries:
            seen["queries"].append(q)
            if q == street:  # raw seed geocode → a rooftop point WITH real components
                out[q] = {
                    "matched": True, "city": "Fort Lauderdale", "admin_area": "Florida",
                    "country": "United States", "place_id": "roofpid", "lat": 40.0, "lng": -74.0,
                    "bounds": {"ne_lat": 40.001, "ne_lng": -73.999, "sw_lat": 39.999, "sw_lng": -74.001},
                    "result_types": ["street_address"],
                }
            elif q == city_query:  # clean city re-geocode → a CITY-sized footprint
                out[q] = {
                    "matched": True, "city": "Fort Lauderdale", "admin_area": "Florida",
                    "country": "United States", "place_id": "citypid", "lat": 40.0, "lng": -74.0,
                    "bounds": {"ne_lat": 40.3, "ne_lng": -73.7, "sw_lat": 39.7, "sw_lng": -74.3},
                    "result_types": ["locality"],
                }
            else:  # a candidate CDP verification (query carries the clean state/country)
                out[q] = {"matched": True, "place_id": f"cdppid:{q}", "lat": 40.05, "lng": -74.05, "result_types": ["locality"]}
        return out

    async def _fake_targets(client, seed_location, code, sb):
        return ([], [])  # no target cities → the seed footprint must carry the verify

    async def _fake_county(client, lat, lng):
        return ("Broward County", "12011")

    monkeypatch.setattr(maps_geocode, "forward_geocode_places", _fake_forward)
    monkeypatch.setattr(target_cities, "resolve_target_cities", _fake_targets)
    monkeypatch.setattr(leadoff_counties, "_county_for_coord", _fake_county)
    # Centroid-based verification (place_id None): Plantation's centroid (lat ~40) is
    # inside the city footprint.
    monkeypatch.setattr(
        maps_geocode, "place_is_within_city",
        lambda cand, city: 39.0 < (cand.get("lat") or 0.0) < 41.0,
    )
    monkeypatch.setattr(
        cdp, "state_cdps_cached",
        lambda st, days: [{"name": "Plantation", "geoid": "1200123", "lat": 40.02, "lng": -74.02}],
    )

    axis, prov, city_names = asyncio.run(cdp.resolve_cdp_axis({}, street, 1015027, object()))

    # The mis-parsed street address is replaced by the geocoded city everywhere.
    assert prov["seed_city"] == "Fort Lauderdale"
    assert city_names == ["Fort Lauderdale"]
    assert prov["states"] == ["12"]  # Florida
    # A city-level re-geocode ran (distinct from the raw street geocode).
    assert city_query in seen["queries"]
    # The CDP verified against the city footprint (would have been 0 vs the rooftop box).
    assert [a["name"] for a in axis] == ["Plantation"]
    assert prov["verified"] == 1
    # CDPs are verified by their authoritative Census centroid — NOT by a per-CDP
    # forward-geocode — so no "<CDP>, <state>" query is ever issued (this is what
    # keeps a multi-state footprint's non-seed-state CDPs from being mis-queried).
    assert "Plantation, Florida, United States" not in seen["queries"]


# ── regression: adversarial-review fixes ──────────────────────────────────────
def test_resolve_cdp_axis_does_not_cache_empty_enumeration(monkeypatch):
    """Finding #1: a transient TIGERweb failure ([]) must NOT be written to the
    per-state cache — else every client in the state is served zero CDPs for
    coverage_cdp_cache_days (365) until the row goes stale."""
    _set_maps_key(monkeypatch)
    _install_happy_path(monkeypatch)  # base mocks (forward-geocode / targets / county)
    monkeypatch.setattr(cdp, "state_cdps_cached", lambda st, days: None)  # force the fetch path

    async def _fake_layer(hc):
        return 36

    async def _empty_fetch(hc, st, layer_id):
        return []  # simulated transient TIGERweb failure

    writes: list = []
    monkeypatch.setattr(cdp, "_resolve_cdp_layer", _fake_layer)
    monkeypatch.setattr(cdp, "_fetch_state_cdps", _empty_fetch)
    monkeypatch.setattr(cdp, "_write_state_cdps", lambda sb, st, cdps: writes.append((st, cdps)))

    axis, prov, city_names = asyncio.run(
        cdp.resolve_cdp_axis({}, "Metropolis, New York, United States", 2840, object())
    )
    assert writes == []  # the empty enumeration is never cached
    assert axis == []
    assert any("not cached" in n.lower() for n in prov["notes"])


def test_resolve_cdp_axis_verifies_cross_state_cdp(monkeypatch):
    """Finding #2: a CDP in a NON-seed state of a multi-state footprint (Kansas City
    straddles MO/KS) is verified by its authoritative centroid — never mis-queried
    with the seed's state, which previously dropped it."""
    from services import leadoff_counties, maps_geocode, target_cities

    _set_maps_key(monkeypatch)

    async def _fake_forward(queries, *, supabase=None):
        # Only the seed is forward-geocoded now (CDPs verify by centroid).
        return {
            q: {
                "matched": True, "place_id": "seedpid", "lat": 40.0, "lng": -74.0,
                "bounds": {"ne_lat": 40.5, "ne_lng": -73.5, "sw_lat": 39.5, "sw_lng": -74.5},
                "result_types": ["locality"],
            }
            for q in queries
        }

    async def _fake_targets(client, seed_location, code, sb):
        return ([{"name": "Overland Park", "lat": 40.1, "lng": -74.1,
                  "bounds": {"ne_lat": 40.3, "ne_lng": -73.9, "sw_lat": 39.9, "sw_lng": -74.3},
                  "place_id": "opid"}], [])

    async def _fake_county(client, lat, lng):
        # seed centre → Missouri (29); the KS target centre → Kansas (20).
        return ("Jackson County", "29095") if lat == 40.0 else ("Johnson County", "20091")

    monkeypatch.setattr(maps_geocode, "forward_geocode_places", _fake_forward)
    monkeypatch.setattr(target_cities, "resolve_target_cities", _fake_targets)
    monkeypatch.setattr(leadoff_counties, "_county_for_coord", _fake_county)
    monkeypatch.setattr(
        maps_geocode, "place_is_within_city",
        lambda cand, city: 39.0 < (cand.get("lat") or 0.0) < 41.0,
    )

    def _cache(st, days):
        # The in-footprint CDP lives in KS (20); MO (29) has none in-footprint.
        return [{"name": "Shawnee", "geoid": "2000123", "lat": 40.05, "lng": -74.05}] if st == "20" else []

    monkeypatch.setattr(cdp, "state_cdps_cached", _cache)

    axis, prov, city_names = asyncio.run(
        cdp.resolve_cdp_axis({}, "Kansas City, Missouri, United States", 2840, object())
    )
    assert prov["states"] == ["20", "29"]  # both states resolved
    assert [a["name"] for a in axis] == ["Shawnee"]  # the KS CDP verified despite seed=Missouri
    assert prov["verified"] == 1


def test_fetch_state_cdps_offset_advances_by_raw_count(monkeypatch):
    """Finding #3: pagination advances resultOffset by the SERVER's returned row
    count, not the parsed (post-filter) count, so dropped rows don't cause the tail
    to be re-requested."""
    calls: list = []
    page1 = {
        "features": [
            {"attributes": {"NAME": "Alpha", "GEOID": "1", "CENTLAT": "+40.0", "CENTLON": "-74.0"}},
            {"attributes": {"NAME": "NoCoord", "GEOID": "2"}},  # dropped by parse (no centroid)
        ],
        "exceededTransferLimit": True,
    }
    page2 = {
        "features": [{"attributes": {"NAME": "Beta", "GEOID": "3", "CENTLAT": "+40.1", "CENTLON": "-74.1"}}],
        "exceededTransferLimit": False,
    }
    pages = [page1, page2]

    async def _fake_get_json(client, url, params):
        calls.append(params["resultOffset"])
        idx = len(calls) - 1
        return pages[idx] if idx < len(pages) else {"features": [], "exceededTransferLimit": False}

    monkeypatch.setattr(cdp, "_get_json", _fake_get_json)
    out = asyncio.run(cdp._fetch_state_cdps(object(), "12", 36))
    # page-2 offset is the RAW count of page 1 (2), NOT the parsed count (1).
    assert calls == [0, 2]
    assert [c["name"] for c in out] == ["Alpha", "Beta"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

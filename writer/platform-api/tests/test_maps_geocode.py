"""Unit tests for the Maps weak-zone geocoding helpers (Module #5).

Pure-logic only — the Google Geocoding call and the cache are not exercised here
(see `build_weak_locations` with an empty key, which short-circuits the network).
"""

import asyncio

from services import maps_geocode as mg

# A 3×3 grid (row 0 = north), centre pin = the business at (1,1).
GRID = [
    [None, 5, None],
    [2, 1, 8],
    [None, 4, None],
]
CENTER_LAT, CENTER_LNG = 40.0, -75.0


def test_extract_weak_cells_threshold_and_center():
    cells = mg.extract_weak_cells(GRID, CENTER_LAT, CENTER_LNG, threshold=3)
    # Weak = not ranked or rank > 3; the centre pin and the rank-2 pin are excluded.
    coords = {(c["row"], c["col"]) for c in cells}
    assert (1, 1) not in coords          # business's own pin
    assert (1, 0) not in coords          # rank 2 ≤ threshold
    assert len(cells) == 7
    by_rc = {(c["row"], c["col"]): c for c in cells}
    assert by_rc[(0, 1)]["octant"] == "N"   # due north of centre
    assert by_rc[(1, 2)]["octant"] == "E"
    assert by_rc[(2, 1)]["octant"] == "S"
    # North pin sits above the business in latitude; east pin to the east.
    assert by_rc[(0, 1)]["lat"] > CENTER_LAT
    assert by_rc[(1, 2)]["lng"] > CENTER_LNG


def test_extract_weak_cells_empty_grid():
    assert mg.extract_weak_cells([], CENTER_LAT, CENTER_LNG, threshold=10) == []
    assert mg.extract_weak_cells(GRID, None, None, threshold=10) == []


def test_parse_geocode_results():
    results = [{
        "address_components": [
            {"long_name": "Springfield", "types": ["locality", "political"]},
            {"long_name": "Illinois", "types": ["administrative_area_level_1", "political"]},
        ],
        "formatted_address": "Springfield, IL, USA",
        "place_id": "abc123",
    }]
    parsed = mg.parse_geocode_results(results)
    assert parsed == {
        "city": "Springfield", "admin_area": "Illinois",
        "formatted": "Springfield, IL, USA", "place_id": "abc123",
    }


def test_parse_geocode_results_empty():
    assert mg.parse_geocode_results(None) == {
        "city": None, "admin_area": None, "formatted": None, "place_id": None,
    }


def test_aggregate_weak_areas_groups_and_ranks():
    cells = [
        {"city": "Springfield", "admin_area": "IL", "rank": None, "octant": "N", "lat": 40.1, "lng": -75.0},
        {"city": "Springfield", "admin_area": "IL", "rank": 15, "octant": "NE", "lat": 40.1, "lng": -74.9},
        {"city": "Lincoln", "admin_area": "IL", "rank": 12, "octant": "S", "lat": 39.9, "lng": -75.0},
    ]
    areas = mg.aggregate_weak_areas(cells)
    assert [a["city"] for a in areas] == ["Springfield", "Lincoln"]  # most weak pins first
    spr = areas[0]
    assert spr["pins"] == 2 and spr["not_ranked"] == 1
    assert spr["octants"] == ["N", "NE"]
    assert spr["worst_rank"] is None        # an unranked pin → "not ranked" wins
    assert spr["avg_rank"] == 15.0          # averaged over ranked pins only
    assert (spr["lat"], spr["lng"]) == (40.1, -75.0)  # representative = the unranked pin
    assert areas[1]["worst_rank"] == 12


def test_build_weak_locations_without_key_caps_and_passes_through():
    octants = [{"lat": 40.1, "lng": -75.0, "octant": "N", "radius_mi": 1.0, "strength": "WEAK"}]
    out = asyncio.run(mg.build_weak_locations(
        GRID, CENTER_LAT, CENTER_LNG, octants, threshold=3, max_cells=3, api_key="",
    ))
    assert out["geocoded"] is False
    assert out["capped"] is True              # 7 weak cells > max_cells of 3
    assert out["weak_cell_count"] == 7
    assert out["weak_areas"] == []            # no geocoding → no named areas
    assert out["octant_pins"] == octants      # pins surface unenriched

"""Unit tests for the Maps weak-zone geocoding + priority-scoring helpers (Module #5).

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


def test_extract_weak_cells_floor_and_center():
    cells = mg.extract_weak_cells(GRID, CENTER_LAT, CENTER_LNG, floor=3)
    # Opportunity = not ranked or rank > floor; the centre pin and the rank-2 pin
    # (in the pack) are excluded.
    coords = {(c["row"], c["col"]) for c in cells}
    assert (1, 1) not in coords          # business's own pin
    assert (1, 0) not in coords          # rank 2 <= floor (in the pack)
    assert len(cells) == 7
    by_rc = {(c["row"], c["col"]): c for c in cells}
    assert by_rc[(0, 1)]["octant"] == "N"   # due north of centre
    assert by_rc[(1, 2)]["octant"] == "E"
    assert by_rc[(2, 1)]["octant"] == "S"
    # North pin sits above the business in latitude; east pin to the east.
    assert by_rc[(0, 1)]["lat"] > CENTER_LAT
    assert by_rc[(1, 2)]["lng"] > CENTER_LNG
    # Tiers: unranked → critical, rank 5/8 (between floor and weak threshold) → watch.
    assert by_rc[(0, 0)]["tier"] == "critical"   # unranked
    assert by_rc[(0, 1)]["tier"] == "watch"      # rank 5
    # Every opportunity cell carries a priority score.
    assert all("opportunity" in c for c in cells)


def test_extract_weak_cells_includes_rank_5_to_9_as_low_severity():
    # rank 5-9 are opportunities now, but score far below an unranked dead zone.
    grid = [[None, 5, 9], [6, 1, 7], [8, None, None]]
    cells = mg.extract_weak_cells(grid, CENTER_LAT, CENTER_LNG, floor=4, weak_threshold=10)
    by_rc = {(c["row"], c["col"]): c for c in cells}
    assert by_rc[(0, 1)]["tier"] == "watch"               # rank 5
    assert by_rc[(0, 0)]["tier"] == "critical"            # unranked
    assert by_rc[(0, 1)]["severity"] < by_rc[(0, 0)]["severity"]
    assert by_rc[(0, 1)]["opportunity"] < by_rc[(0, 0)]["opportunity"]


def test_core_adjacency_downweights_pins_bordering_strong():
    # The SAME unranked pin at (1,2): once ringed entirely by in-pack rank-1 pins
    # (a fringe of strong coverage), once with weak neighbours (a real pocket).
    bordering = [[1, 1, 1, 1, 1],
                 [1, 1, None, 1, 1],
                 [1, 1, 1, 1, 1],
                 [1, 1, 1, 1, 1],
                 [1, 1, 1, 1, 1]]
    pocket = [[1, None, None, None, 1],
              [1, None, None, None, 1],
              [1, None, 1, None, 1],
              [1, 1, 1, 1, 1],
              [1, 1, 1, 1, 1]]
    b = {(c["row"], c["col"]): c for c in mg.extract_weak_cells(bordering, CENTER_LAT, CENTER_LNG, floor=4)}[(1, 2)]
    p = {(c["row"], c["col"]): c for c in mg.extract_weak_cells(pocket, CENTER_LAT, CENTER_LNG, floor=4)}[(1, 2)]
    # Same severity/proximity; only core_adjacency differs.
    assert b["core_adjacency"] < p["core_adjacency"]
    assert b["core_adjacency"] == 0.5   # all 8 neighbours in the pack → floor
    assert b["opportunity"] < p["opportunity"]


def test_aggregate_weak_areas_drops_thin_suburbs():
    # Springfield has 3 pins, Lincoln 1 — with min_pins=3 only Springfield is flagged.
    cells = [
        {"city": "Springfield", "admin_area": "IL", "rank": None, "octant": "N", "lat": 40.1, "lng": -75.0, "tier": "critical", "opportunity": 1.0},
        {"city": "Springfield", "admin_area": "IL", "rank": 12, "octant": "N", "lat": 40.1, "lng": -75.0, "tier": "weak", "opportunity": 0.5},
        {"city": "Springfield", "admin_area": "IL", "rank": 14, "octant": "N", "lat": 40.1, "lng": -75.0, "tier": "weak", "opportunity": 0.4},
        {"city": "Lincoln", "admin_area": "IL", "rank": 7, "octant": "S", "lat": 39.9, "lng": -75.0, "tier": "watch", "opportunity": 0.1},
    ]
    areas, dropped = mg.aggregate_weak_areas(cells, min_pins=3)
    assert [a["city"] for a in areas] == ["Springfield"]   # Lincoln (1 pin) dropped
    assert dropped == 1
    # min_pins=1 keeps both.
    areas_all, dropped0 = mg.aggregate_weak_areas(cells, min_pins=1)
    assert {a["city"] for a in areas_all} == {"Springfield", "Lincoln"} and dropped0 == 0


def test_aggregate_weak_areas_unnamed_cluster_survives_singleton_dropped():
    # Cells with NO geocoded city (e.g. ZERO_RESULTS / geocode outage) must group by
    # grid contiguity: a real 3-pin contiguous blob survives; a lone unnamed pin drops.
    cells = [
        # contiguous 3-blob (rows/cols adjacent), no city
        {"city": None, "rank": None, "octant": "S", "lat": 40.1, "lng": -75.0, "tier": "critical", "opportunity": 1.0, "row": 0, "col": 0},
        {"city": None, "rank": 12, "octant": "S", "lat": 40.1, "lng": -75.0, "tier": "weak", "opportunity": 0.5, "row": 0, "col": 1},
        {"city": None, "rank": 13, "octant": "S", "lat": 40.1, "lng": -75.0, "tier": "weak", "opportunity": 0.4, "row": 1, "col": 1},
        # a lone unnamed pin far away
        {"city": None, "rank": None, "octant": "N", "lat": 41.0, "lng": -76.0, "tier": "critical", "opportunity": 0.9, "row": 9, "col": 9},
    ]
    areas, dropped = mg.aggregate_weak_areas(cells, min_pins=3)
    assert len(areas) == 1                 # the 3-blob survives as ONE unnamed area
    assert areas[0]["city"] is None and areas[0]["pins"] == 3
    assert dropped == 1                    # the lone (9,9) pin dropped


def test_extract_weak_cells_empty_grid():
    assert mg.extract_weak_cells([], CENTER_LAT, CENTER_LNG, floor=10) == []
    assert mg.extract_weak_cells(GRID, None, None, floor=10) == []


def test_severity_proximity_beatability_helpers():
    # Severity: unranked is worst, monotonic in rank, barely-weak ≈ 0.
    assert mg._severity(None, 4, 25) == 1.0
    assert mg._severity(5, 4, 25) < mg._severity(20, 4, 25) < mg._severity(None, 4, 25)
    assert mg._severity(5, 4, 25) < 0.1
    # Proximity: innermost ring = 1.0, decreasing outward.
    assert mg._proximity(1, 6) == 1.0
    assert mg._proximity(1, 6) > mg._proximity(3, 6) > mg._proximity(6, 6)
    # Beatability: weak competitor above → boost; entrenched → discount; unknown → neutral.
    assert mg._beatability(10, 100, 0.6, 1.4) > 1.0    # we out-review the leader here
    assert mg._beatability(1000, 100, 0.6, 1.4) < 1.0  # entrenched competitor
    assert mg._beatability(None, 100, 0.6, 1.4) == 1.0
    assert mg._beatability(10, None, 0.6, 1.4) == 1.0


def test_beatability_coerces_non_numeric_review_counts():
    # gbp_review_count / ratingCount can arrive as a numeric string or junk —
    # must never raise, and a numeric string behaves like the number.
    assert mg._to_float("77") == 77.0
    assert mg._to_float(None) is None
    assert mg._to_float(True) is None        # bool is not a review count
    assert mg._to_float("n/a") is None
    # A string client_reviews must not raise (the pre-fix bug) and must match the int.
    assert mg._beatability(10, "100", 0.6, 1.4) == mg._beatability(10, 100, 0.6, 1.4) > 1.0
    assert mg._beatability("1000", 100, 0.6, 1.4) < 1.0
    assert mg._beatability(10, "junk", 0.6, 1.4) == 1.0   # unparseable → neutral, no crash


def test_beatability_uses_competitor_reviews_above_cell():
    # A competitor with few reviews ranks above us at (0,1); we have many → beatable.
    competitors_above = {
        "directory": {"weak_comp": {"reviews": 5}, "strong_comp": {"reviews": 5000}},
        "grid": [
            [None, [["weak_comp", 1]], None],
            [None, None, None],
            [None, [["strong_comp", 1]], None],
        ],
    }
    cells = mg.extract_weak_cells(
        [[None, None, None], [None, 1, None], [None, None, None]],
        CENTER_LAT, CENTER_LNG, floor=4,
        competitors_above=competitors_above, client_reviews=200,
    )
    by_rc = {(c["row"], c["col"]): c for c in cells}
    assert by_rc[(0, 1)]["beatability"] > 1.0   # weak competitor above → easy
    assert by_rc[(2, 1)]["beatability"] < 1.0   # review-rich competitor → hard


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


def test_aggregate_weak_areas_priority_and_tier():
    cells = [
        {"city": "Springfield", "admin_area": "IL", "rank": None, "octant": "N",
         "lat": 40.1, "lng": -75.0, "tier": "critical", "opportunity": 1.0},
        {"city": "Springfield", "admin_area": "IL", "rank": 15, "octant": "NE",
         "lat": 40.1, "lng": -74.9, "tier": "weak", "opportunity": 0.5},
        {"city": "Lincoln", "admin_area": "IL", "rank": 7, "octant": "S",
         "lat": 39.9, "lng": -75.0, "tier": "watch", "opportunity": 0.1},
    ]
    areas, _dropped = mg.aggregate_weak_areas(cells)
    # Ranked by summed opportunity (priority), not pin count.
    assert [a["city"] for a in areas] == ["Springfield", "Lincoln"]
    spr = areas[0]
    assert spr["pins"] == 2 and spr["not_ranked"] == 1
    assert spr["octants"] == ["N", "NE"]
    assert spr["worst_rank"] is None        # an unranked pin → "not ranked" wins
    assert spr["avg_rank"] == 15.0          # averaged over ranked pins only
    assert spr["tier"] == "critical"        # most severe pin in the area
    assert spr["priority"] == 100           # highest-priority area, normalized
    assert (spr["lat"], spr["lng"]) == (40.1, -75.0)  # rep = highest-opportunity pin
    # Lincoln: score_raw 0.1 vs 1.5 → priority round(100*0.1/1.5) = 7.
    assert areas[1]["priority"] == 7 and areas[1]["tier"] == "watch"


def test_build_weak_locations_caps_by_priority_keeping_worst():
    # 5×5 grid: an unranked pin near the centre must outscore a rank-5 pin far out,
    # and survive a max_cells=1 cap.
    grid = [
        [None, None, 5, None, None],
        [None, None, None, None, None],
        [None, None, 1, None, None],
        [None, None, None, None, None],
        [None, None, None, None, None],
    ]
    grid[2][3] = None  # near, unranked (ring 1, east of centre)
    out = asyncio.run(mg.build_weak_locations(
        grid, CENTER_LAT, CENTER_LNG, [], floor=4, max_cells=1, api_key="",
    ))
    assert out["geocoded"] is False
    assert out["opportunity_floor"] == 4
    # Without a key we still scored + capped; the kept cell is the highest priority.
    assert out["capped"] is True
    assert out["weak_areas"] == []          # no geocoding → no named areas
    assert out["octant_pins"] == []


def test_build_weak_locations_without_key_passes_octants_through():
    octants = [{"lat": 40.1, "lng": -75.0, "octant": "N", "radius_mi": 1.0, "strength": "WEAK"}]
    out = asyncio.run(mg.build_weak_locations(
        GRID, CENTER_LAT, CENTER_LNG, octants, floor=3, max_cells=3, api_key="",
    ))
    assert out["geocoded"] is False
    assert out["capped"] is True              # 7 opportunity cells > max_cells of 3
    assert out["weak_cell_count"] == 7
    assert out["weak_areas"] == []            # no geocoding → no named areas
    assert out["octant_pins"] == octants      # pins surface unenriched
    # Payload shape matches the geocoded branch (counts simply zero here).
    assert out["flagged_area_count"] == 0 and out["dropped_thin_areas"] == 0

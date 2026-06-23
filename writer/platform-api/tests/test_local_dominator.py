"""Unit tests for the Local Dominator geo-grid pure helpers (no I/O)."""

from __future__ import annotations

from services import local_dominator


# ---------------------------------------------------------------------------
# summarize_grid
# ---------------------------------------------------------------------------
def test_summarize_grid_counts_and_average():
    # Raw ranks are 0-INDEXED (0 = 1st place). Not-ranked pins are negative (-1)
    # or null. All metrics are reported 1-based (display = raw + 1).
    content = [
        [0, 1, 2],
        [3, None, 10],
        [-1, -1, 4],
    ]
    s = local_dominator.summarize_grid(content)
    assert s["total_pins"] == 9
    assert s["found_pins"] == 6          # raw 0,1,2,3,10,4 → display 1,2,3,4,11,5
    assert s["top3_pins"] == 3           # display 1,2,3 (raw 0,1,2)
    assert s["top10_pins"] == 5          # display 1,2,3,4,5 (raw 10→11 excluded)
    assert s["computed_average"] == round((1 + 2 + 3 + 4 + 11 + 5) / 6, 2)


def test_to_display_grid_is_one_based_with_nulls():
    content = [[0, 1, -1], [None, 9, 2]]
    assert local_dominator.to_display_grid(content) == [[1, 2, None], [None, 10, 3]]


def test_summarize_grid_empty_and_all_unranked():
    assert local_dominator.summarize_grid([]) == {
        "total_pins": 0, "found_pins": 0, "top3_pins": 0, "top10_pins": 0, "computed_average": None,
    }
    s = local_dominator.summarize_grid([[-1, None], [-1, -1]])
    assert s["total_pins"] == 4 and s["found_pins"] == 0 and s["computed_average"] is None


# ---------------------------------------------------------------------------
# build_scan_request
# ---------------------------------------------------------------------------
def test_build_scan_request_maps_radius_to_grid_params():
    config = {
        "center_lat": 26.0481, "center_lng": -80.1819, "radius_miles": 5,
        "shape": "circle", "google_place_id": "ChIJabc", "resource_category": "googleMaps",
        "serp_device": "desktop",
    }
    body = local_dominator.build_scan_request(config, ["plumber", "emergency plumber"])
    assert body["grid_size"] == 11          # 5 mi @ 1-mile spacing
    assert body["distance"] == 1609         # 1 mile in metres
    assert body["latitude"] == 26.0481 and body["longitude"] == -80.1819
    assert body["shape"] == "square"  # square lattice, masked to a circle in the UI
    assert body["google_place_id"] == "ChIJabc"
    assert body["search_terms"] == ["plumber", "emergency plumber"]
    assert body["resource_category"] == "googleMaps" and body["serp_device"] == "desktop"


def test_build_scan_request_defaults_shape_and_surface():
    config = {
        "center_lat": 1.0, "center_lng": 2.0, "radius_miles": 3,
        "google_place_id": "p", "shape": None, "resource_category": None, "serp_device": None,
    }
    body = local_dominator.build_scan_request(config, ["x"])
    assert body["grid_size"] == 7           # 3 mi
    assert body["shape"] == "square"  # square lattice, masked to a circle in the UI
    assert body["resource_category"] == "googleMaps"
    assert body["serp_device"] == "desktop"

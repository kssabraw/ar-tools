"""Unit tests for the Maps geo-grid geometry (pure, no I/O)."""

from __future__ import annotations

import math

from services import maps_grid


# ---------------------------------------------------------------------------
# grid_size / pin_count for the supported presets (radius @ 1-mile spacing)
# ---------------------------------------------------------------------------
def test_grid_size_for_presets():
    assert maps_grid.grid_size_for(3) == 7
    assert maps_grid.grid_size_for(5) == 11
    assert maps_grid.grid_size_for(7) == 15


def test_pin_count_for_presets():
    assert maps_grid.pin_count_for(3) == 49
    assert maps_grid.pin_count_for(5) == 121
    assert maps_grid.pin_count_for(7) == 225


def test_grid_size_always_odd_so_business_is_centered():
    for r in maps_grid.SUPPORTED_RADII_MILES:
        assert maps_grid.grid_size_for(r) % 2 == 1


def test_invalid_inputs_raise():
    for bad in (0, -1):
        try:
            maps_grid.grid_size_for(bad)
            assert False, "expected ValueError"
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# distance / params
# ---------------------------------------------------------------------------
def test_distance_meters_is_one_mile():
    assert maps_grid.distance_meters(1) == 1609


def test_grid_params():
    assert maps_grid.grid_params(3) == {"grid_size": 7, "distance": 1609}
    assert maps_grid.grid_params(7) == {"grid_size": 15, "distance": 1609}


# ---------------------------------------------------------------------------
# generate_grid_points
# ---------------------------------------------------------------------------
def test_point_count_matches_grid_size_squared():
    pts = maps_grid.generate_grid_points(40.0, -74.0, 3)
    assert len(pts) == 49


def test_center_pin_is_the_business_location():
    pts = maps_grid.generate_grid_points(40.0, -74.0, 3)
    center = next(p for p in pts if p.offset_north_mi == 0 and p.offset_east_mi == 0)
    assert center.row == 3 and center.col == 3  # 7×7 grid → index 3 is the middle
    assert math.isclose(center.lat, 40.0) and math.isclose(center.lng, -74.0)


def test_corner_offsets_and_latitude_spacing():
    pts = maps_grid.generate_grid_points(40.0, -74.0, 3)
    # North edge is +3 miles; 1 mile ≈ 1/69 degree latitude.
    north_edge = [p for p in pts if p.row == 6]
    assert all(p.offset_north_mi == 3 for p in north_edge)
    assert math.isclose(north_edge[0].lat, 40.0 + 3.0 / 69.0, rel_tol=1e-9)


def test_longitude_spacing_widens_with_latitude():
    # A degree of longitude shrinks toward the poles, so a 1-mile east step is a
    # larger Δlng at 60°N than at the equator.
    near_eq = maps_grid.generate_grid_points(1.0, 0.0, 3)
    high_lat = maps_grid.generate_grid_points(60.0, 0.0, 3)

    def east_step(points):
        center = next(p for p in points if p.offset_north_mi == 0 and p.offset_east_mi == 0)
        one_east = next(p for p in points if p.offset_north_mi == 0 and p.offset_east_mi == 1)
        return one_east.lng - center.lng

    assert east_step(high_lat) > east_step(near_eq)

"""Tests for the pinned grid-geometry generator.

The expected values here are computed BY HAND from the geometry, not read off the implementation.
That is the same rule the golden scorecard fixtures follow: a fixture regenerated from the code it
tests asserts only that the code is self-consistent, and geometry fails in exactly the way that
hides behind self-consistency — a shifted ordering renders every historical heatmap against the
wrong coordinates while every number stays plausible and every pixel still draws.

The row census below (1, 7, 9, 9, 9, 11, 9, 9, 9, 7, 1) was derived from i^2 + j^2 <= 25 over the
integer lattice, independently of anything in `geometry.py`.
"""

from __future__ import annotations

import math

import pytest

from api.services import geometry
from api.services.geometry import GEOMETRY_VERSION, UnknownGeometryVersion, generate_points

# Points per row, north to south, for radius 5 / spacing 1.
#   |dy|=5 -> dx=0                      -> 1
#   |dy|=4 -> dx^2 <= 9,  |dx| <= 3     -> 7
#   |dy|=3 -> dx^2 <= 16, |dx| <= 4     -> 9
#   |dy|=2 -> dx^2 <= 21, |dx| <= 4     -> 9
#   |dy|=1 -> dx^2 <= 24, |dx| <= 4     -> 9
#   |dy|=0 -> dx^2 <= 25, |dx| <= 5     -> 11
ROW_CENSUS = [1, 7, 9, 9, 9, 11, 9, 9, 9, 7, 1]


# --- the count ----------------------------------------------------------------------------------


def test_the_grid_holds_81_points_not_89():
    """The number the specs disagree about. 81 is what a 1-mile lattice clipped to a 5-mile radius
    contains; 89 is an estimate no construction produces (ISSUES I-025)."""
    assert geometry.point_count(radius_miles=5, spacing_miles=1) == 81
    assert sum(ROW_CENSUS) == 81


def test_the_count_is_not_any_of_the_alternatives():
    """Pinned against the specific wrong answers, so a change toward one of them is named rather
    than showing up as an unexplained off-by-ten."""
    count = geometry.point_count(radius_miles=5, spacing_miles=1)
    assert count != 121, "the bounding box is being returned unclipped"
    assert count != 91, "a hexagonal lattice has replaced the square one"
    assert count != 41, "concentric rings have replaced the lattice"


def test_row_census_matches_the_hand_computed_geometry():
    points = generate_points(34.0, -118.0, 5, 1)
    rows: dict[float, int] = {}
    for p in points:
        rows[p.dy_miles] = rows.get(p.dy_miles, 0) + 1
    # Sorted north to south.
    assert [rows[dy] for dy in sorted(rows, reverse=True)] == ROW_CENSUS


def test_point_count_matches_a_generated_grid():
    """`expected_points` is written from `point_count` and compared against real captures by the
    §9a.3 completeness check. If the two disagree by even one, every snapshot reads as incomplete
    and is excluded from scoring."""
    for radius, spacing in ((5, 1), (5, 0.5), (3, 1), (10, 2), (5, 0.75)):
        assert geometry.point_count(radius, spacing) == len(
            generate_points(34.0, -118.0, radius, spacing)
        )


# --- ordering -----------------------------------------------------------------------------------


def test_point_seq_is_zero_based_and_dense():
    points = generate_points(34.0, -118.0, 5, 1)
    assert [p.point_seq for p in points] == list(range(81))


def test_ordering_is_row_major_from_the_north_west():
    """Reporting spec §4.1. Latitude never increases as point_seq grows, and within a row longitude
    always does."""
    points = generate_points(34.0, -118.0, 5, 1)
    for a, b in zip(points, points[1:]):
        assert a.lat >= b.lat - 1e-12
        if math.isclose(a.lat, b.lat):
            assert b.lng > a.lng


def test_first_and_last_points_are_the_poles_of_the_grid():
    """The round-trip the reporting spec requires: regenerate an old snapshot's coordinates and
    confirm the count and the first/last coordinates.

    Both are hand-derived: the northmost row (dy = +5) admits only dx = 0, because 5^2 + dx^2 <= 25
    forces it, and the southmost row mirrors it. So the grid opens and closes on the centre
    meridian, exactly 5/69 of a degree above and below the centre latitude.
    """
    points = generate_points(34.0, -118.0, 5, 1)
    first, last = points[0], points[-1]

    assert first.lng == pytest.approx(-118.0, abs=1e-12)
    assert last.lng == pytest.approx(-118.0, abs=1e-12)
    assert first.lat == pytest.approx(34.0 + 5 / 69.0, abs=1e-12)
    assert last.lat == pytest.approx(34.0 - 5 / 69.0, abs=1e-12)
    assert first.dy_miles == 5 and first.dx_miles == 0
    assert last.dy_miles == -5 and last.dx_miles == 0


def test_the_centre_point_is_present_and_at_the_centre():
    points = generate_points(34.0522, -118.2437, 5, 1)
    centre = [p for p in points if p.dx_miles == 0 and p.dy_miles == 0]
    assert len(centre) == 1
    assert centre[0].lat == pytest.approx(34.0522, abs=1e-12)
    assert centre[0].lng == pytest.approx(-118.2437, abs=1e-12)
    # Middle of an 81-point grid, and the middle of its row.
    assert centre[0].point_seq == 40


# --- projection ---------------------------------------------------------------------------------


def test_longitude_is_narrowed_by_latitude():
    """A degree of longitude is ~57 miles at LA's 34°, not 69. Without the cosine the grid is ~17%
    too wide there and the '5-mile radius' is not one."""
    equator = generate_points(0.0, 0.0, 5, 1)
    la = generate_points(34.0, 0.0, 5, 1)

    eq_span = max(p.lng for p in equator) - min(p.lng for p in equator)
    la_span = max(p.lng for p in la) - min(p.lng for p in la)

    assert la_span > eq_span
    assert la_span == pytest.approx(eq_span / math.cos(math.radians(34.0)), rel=1e-9)


def test_latitude_step_is_independent_of_longitude():
    for lng in (-118.0, 0.0, 151.0):
        points = generate_points(34.0, lng, 5, 1)
        assert points[0].lat == pytest.approx(34.0 + 5 / 69.0, abs=1e-12)


def test_every_point_is_inside_the_radius():
    for radius, spacing in ((5, 1), (5, 0.75), (7, 2)):
        for p in generate_points(34.0, -118.0, radius, spacing):
            assert p.distance_miles <= radius + 1e-6


def test_a_point_exactly_on_the_radius_is_included():
    """dx = 5, dy = 0 at radius 5 sits precisely on the boundary. Whether it survives must not
    depend on float rounding — a point flipping in or out RENUMBERS every point_seq after it,
    silently re-mapping every historical rank_vector."""
    points = generate_points(34.0, -118.0, 5, 1)
    on_boundary = [p for p in points if math.isclose(p.distance_miles, 5.0, abs_tol=1e-9)]

    # TWELVE, not four. The four axis extremes (0,±5) and (±5,0), plus eight more from the 3-4-5
    # Pythagorean triple: (±3,±4) and (±4,±3) are also exactly 5 miles out. This grid is unusually
    # sensitive to the clip comparison for that reason — 12 of its 81 points sit precisely on the
    # boundary, so a strict `<` instead of `<=`, or a missing tolerance, would not shave one point
    # off the edge but fifteen percent of the grid.
    assert len(on_boundary) == 12
    assert {(p.dx_miles, p.dy_miles) for p in on_boundary} == {
        (0, 5), (0, -5), (5, 0), (-5, 0),
        (3, 4), (3, -4), (-3, 4), (-3, -4),
        (4, 3), (4, -3), (-4, 3), (-4, -3),
    }


def test_the_bounding_box_covers_the_circle_for_non_integer_spacing():
    """radius 5 / spacing 0.75 divides to 6.67. Flooring gives ±4.5 miles and shaves the outer ring
    off every grid — which reads as uniform market weakness, not as a bug."""
    points = generate_points(34.0, -118.0, 5, 0.75)
    assert max(p.distance_miles for p in points) > 4.5


# --- versioning ---------------------------------------------------------------------------------


def test_current_version_is_registered():
    assert GEOMETRY_VERSION in geometry._GENERATORS


def test_an_unknown_version_raises_rather_than_falling_back():
    """The tempting recovery — use the current generator — is the failure the registry exists to
    prevent. It would decode a historical vector against coordinates that were never used to
    collect it and produce a picture instead of an error."""
    with pytest.raises(UnknownGeometryVersion):
        generate_points(34.0, -118.0, 5, 1, version="v99")
    with pytest.raises(UnknownGeometryVersion):
        geometry.point_count(5, 1, version="v99")


def test_v1_is_pinned_by_value_not_by_reference():
    """v1's output is frozen here as literal numbers. If someone edits `_generate_v1` in place
    instead of adding v2, this fails — which is the whole point of a pinned generator."""
    points = generate_points(34.0, -118.0, 5, 1, version="v1")

    assert len(points) == 81
    # seq 1 opens the dy=+4 row at dx=-3 (4^2 + 3^2 = 25, so dx=-3 is the westmost survivor).
    assert points[1].dx_miles == -3
    assert points[1].dy_miles == 4
    # seq 35..45 is the dy=0 row: the only row 11 wide.
    row_zero = [p for p in points if p.dy_miles == 0]
    assert len(row_zero) == 11
    assert [p.point_seq for p in row_zero] == list(range(35, 46))


# --- guards -------------------------------------------------------------------------------------


def test_non_positive_parameters_are_refused():
    for radius, spacing in ((0, 1), (-5, 1), (5, 0), (5, -1)):
        with pytest.raises(ValueError):
            generate_points(34.0, -118.0, radius, spacing)


def test_expected_points_fits_a_smallint():
    """`scan_snapshot.expected_points` is a smallint. The default grid is nowhere near it, but a
    submarket configured with fine spacing could overflow — worth knowing where the edge is."""
    assert geometry.point_count(5, 1) < 32767
    assert geometry.point_count(5, 0.25) < 32767

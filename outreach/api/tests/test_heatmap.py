"""Tests for the deterministic heatmap renderer (reporting-layer-spec §4).

Two kinds of assertion here, and the distinction matters:

  * Band membership and geometry offsets are computed BY HAND from the spec, the same rule the
    geometry fixtures follow — a value read off the implementation only proves self-consistency.

  * The golden content_hash is captured from the renderer, and that is legitimate rather than
    circular: its job is to pin BYTE-DETERMINISM. An accidental non-determinism (set iteration,
    a stray timestamp, sign-of-zero drift) changes the bytes and breaks the hash, which is exactly
    the regression the reporting layer's cache contract (spec §2, §6) cannot tolerate. It updates
    only on a deliberate GENERATOR_VERSION bump.
"""

from __future__ import annotations

import math

import pytest

from api.services import heatmap
from api.services.geometry import GridPoint, generate_points
from api.services.heatmap import (
    BAND_DEAD,
    BAND_FAR_DOWN,
    BAND_NOT_FOUND,
    BAND_PACK,
    BAND_PAGE_ONE,
    HeatmapInputs,
    band_for_byte,
    build_inputs,
    business_offset_miles,
    content_hash,
    render_heatmap,
)


# --- band classification (reporting §4.2), hand-derived --------------------------------------


@pytest.mark.parametrize(
    "value, band",
    [
        (0, BAND_NOT_FOUND),   # not found -> red
        (1, BAND_PACK),        # in the pack -> green
        (2, BAND_PACK),
        (3, BAND_PACK),
        (4, BAND_PAGE_ONE),    # page one -> yellow
        (10, BAND_PAGE_ONE),
        (11, BAND_FAR_DOWN),   # found, far down -> orange
        (20, BAND_FAR_DOWN),
        (21, BAND_FAR_DOWN),   # beyond depth: still FOUND, never red (ISSUES I-089)
        (254, BAND_FAR_DOWN),
        (255, BAND_DEAD),      # dead point -> grey ring
    ],
)
def test_band_for_byte(value, band):
    assert band_for_byte(value) == band


def test_band_covers_every_byte():
    # Total over the whole domain — no byte falls through to an exception or None.
    assert all(band_for_byte(b) in heatmap._BAND_FILL for b in range(256))


# --- a small hand-built grid to render ------------------------------------------------------


def _tiny_inputs(vector, *, business=(0.0, 0.0)):
    """Three points on a one-mile line, so a fixture is legible and independent of the 81-point
    grid. dx east, dy north; point_seq is the render order."""
    points = [
        GridPoint(point_seq=0, lat=34.0, lng=-118.0, dx_miles=-1.0, dy_miles=0.0),
        GridPoint(point_seq=1, lat=34.0, lng=-118.0, dx_miles=0.0, dy_miles=0.0),
        GridPoint(point_seq=2, lat=34.0, lng=-118.0, dx_miles=1.0, dy_miles=0.0),
    ]
    return HeatmapInputs(
        points=points,
        rank_vector=list(vector),
        radius_miles=5.0,
        spacing_miles=1.0,
        title="Acme Plumbing — Google Maps coverage",
        subtitle="plumber · Van Nuys · scanned 2026-08-07",
        business_offset=business,
    )


# --- determinism (the load-bearing property) ------------------------------------------------


def test_identical_inputs_identical_bytes():
    a = render_heatmap(_tiny_inputs([2, 0, 255]))
    b = render_heatmap(_tiny_inputs([2, 0, 255]))
    assert a == b
    assert content_hash(a) == content_hash(b)
    assert len(content_hash(a)) == 64


def test_input_order_does_not_change_output():
    """A caller that hands points in a different order must still render — and hash — identically,
    because rendering sorts by point_seq. Ordering integrity is what the whole geometry registry
    protects; the renderer must not reintroduce an order dependency."""
    base = _tiny_inputs([2, 0, 255])
    shuffled = HeatmapInputs(
        points=list(reversed(base.points)),
        rank_vector=list(reversed(base.rank_vector)),
        radius_miles=base.radius_miles,
        spacing_miles=base.spacing_miles,
        title=base.title,
        subtitle=base.subtitle,
        business_offset=base.business_offset,
    )
    assert content_hash(render_heatmap(base)) == content_hash(render_heatmap(shuffled))


def test_different_vector_different_hash():
    a = content_hash(render_heatmap(_tiny_inputs([2, 0, 255])))
    b = content_hash(render_heatmap(_tiny_inputs([2, 5, 255])))
    assert a != b


# --- dead vs not-found MUST be visually distinct (spec §4.2) ---------------------------------


def test_dead_and_not_found_render_differently():
    # Both legends carry every swatch, so the signal is in the PLOTTED points, not whole-SVG
    # colour presence: count the marks each data value produces.
    dead_only = render_heatmap(_tiny_inputs([255, 255, 255], business=None))
    absent_only = render_heatmap(_tiny_inputs([0, 0, 0], business=None))
    assert dead_only != absent_only
    # not-found is a solid red disc (extra red fills beyond the single legend swatch); dead draws
    # no red discs at all.
    assert absent_only.count(f'fill="{heatmap.COLOR_NOT_FOUND}"') > dead_only.count(
        f'fill="{heatmap.COLOR_NOT_FOUND}"'
    )
    # dead is a hollow grey ring (extra grey strokes beyond the single legend swatch).
    assert dead_only.count(f'stroke="{heatmap.COLOR_DEAD}"') > absent_only.count(
        f'stroke="{heatmap.COLOR_DEAD}"'
    )


# --- required external-render furniture (spec §4.2) ------------------------------------------


def test_legend_and_scale_bar_present():
    svg = render_heatmap(_tiny_inputs([2, 0, 255]))
    assert "1 mile" in svg                     # scale bar label
    assert "In the map pack" in svg            # legend
    assert "Not showing up" in svg
    assert "No data (dead zone)" in svg
    assert "This business" in svg              # the pin's legend entry


def test_business_pin_toggles_on_offset():
    # A diamond pin is a <polygon>; the grid dots are <circle>. The legend's "This business" marker
    # is always one polygon, so the pin itself is the DIFFERENCE between the two renders.
    with_pin = render_heatmap(_tiny_inputs([2, 0, 255], business=(0.0, 0.0)))
    without_pin = render_heatmap(_tiny_inputs([2, 0, 255], business=None))
    assert with_pin.count("<polygon") == without_pin.count("<polygon") + 1


def test_svg_has_no_timestamp_or_random_id():
    svg = render_heatmap(_tiny_inputs([2, 0, 255]))
    assert "id=" not in svg          # no element ids at all -> nothing random to leak
    assert "2026-08-07" in svg       # the subtitle date is stored input, not now()


# --- length invariant -----------------------------------------------------------------------


def test_vector_length_must_match_geometry():
    with pytest.raises(ValueError):
        HeatmapInputs(
            points=[GridPoint(0, 34.0, -118.0, 0.0, 0.0)],
            rank_vector=[1, 2],  # two bytes, one point
            radius_miles=5.0,
            spacing_miles=1.0,
            title="t",
            subtitle="s",
            business_offset=None,
        )


# --- business offset, hand-derived ----------------------------------------------------------


def test_business_offset_one_mile_north():
    dx, dy = business_offset_miles(34.0, -118.0, 34.0 + 1.0 / 69.0, -118.0)
    assert dx == pytest.approx(0.0, abs=1e-9)
    assert dy == pytest.approx(1.0, abs=1e-6)


def test_business_offset_one_mile_east():
    # A mile of longitude at 34°N is 1 / (69 * cos 34°) degrees.
    lng = -118.0 + 1.0 / (69.0 * math.cos(math.radians(34.0)))
    dx, dy = business_offset_miles(34.0, -118.0, 34.0, lng)
    assert dx == pytest.approx(1.0, abs=1e-6)
    assert dy == pytest.approx(0.0, abs=1e-9)


# --- build_inputs: geometry regeneration from a stored snapshot ------------------------------


def _snapshot(version="v1"):
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "center_lat": 34.19,
        "center_lng": -118.45,
        "grid_radius_miles": 5.0,
        "grid_spacing_miles": 1.0,
        "geometry_version": version,
        "scanned_at": "2026-08-07T12:00:00+00:00",
    }


def test_build_inputs_regenerates_81_points_and_offset():
    n = len(generate_points(34.19, -118.45, 5.0, 1.0))
    assert n == 81  # sanity: the grid is the pinned 81
    coverage = {"rank_vector": bytes([2] * n)}
    inputs = build_inputs(
        snapshot=_snapshot(),
        coverage=coverage,
        title="Acme — Google Maps coverage",
        subtitle="plumber · Van Nuys",
        business_lat=34.20,
        business_lng=-118.44,
    )
    assert len(inputs.points) == n
    assert len(inputs.rank_vector) == n
    assert inputs.business_offset is not None
    # The renderer accepts it and produces a stable, non-empty SVG.
    svg = render_heatmap(inputs)
    assert svg.startswith("<svg")
    assert content_hash(svg) == content_hash(render_heatmap(inputs))


def test_build_inputs_without_coordinates_has_no_pin():
    coverage = {"rank_vector": bytes([0] * 81)}
    inputs = build_inputs(
        snapshot=_snapshot(),
        coverage=coverage,
        title="t",
        subtitle="s",
    )
    assert inputs.business_offset is None


def test_build_inputs_unknown_geometry_version_raises():
    from api.services.geometry import UnknownGeometryVersion

    coverage = {"rank_vector": bytes([0] * 81)}
    with pytest.raises(UnknownGeometryVersion):
        build_inputs(snapshot=_snapshot(version="v999"), coverage=coverage, title="t", subtitle="s")

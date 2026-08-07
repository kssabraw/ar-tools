"""Tests for the comparison renderers — reporting-layer-spec §4.3 (`heatmap_pair`, `heatmap_delta`).

Same discipline as `test_heatmap.py`: delta-band membership and the guard decisions are computed BY
HAND from the spec (a value read off the implementation would only prove self-consistency), while
determinism is pinned by comparing a render to itself. The delta view is "the visual form of the
strongest pitch signal" (spec §4.3) and the one a prospect can most easily disprove, so its guards
and its inverted-rank legend get the most scrutiny here.
"""

from __future__ import annotations

import pytest

from api.services import heatmap as h
from api.services.geometry import GridPoint
from api.services.heatmap import (
    BAND_DELTA_DEAD,
    BAND_DELTA_IMPROVED,
    BAND_DELTA_UNCHANGED,
    BAND_DELTA_WORSENED,
    DeltaInputs,
    DeltaNotRenderable,
    HeatmapInputs,
    PairInputs,
    assert_delta_renderable,
    build_delta_inputs,
    build_pair_inputs,
    content_hash,
    delta_band,
    render_delta,
    render_pair,
    span_days,
)

# --- delta band classification (reporting §4.3, §7a), hand-derived ----------------------------
#
# THE TRAP: rank is inverted. "Improved" means the rank NUMBER went down, and "not found" (byte 0)
# is worse than the deepest real position. Every row below is reasoned from that, not read off code.


@pytest.mark.parametrize(
    "before, after, band, why",
    [
        (0, 0, BAND_DELTA_UNCHANGED, "absent in both — still not ranking is not a decline"),
        (2, 2, BAND_DELTA_UNCHANGED, "same pack rank"),
        (5, 2, BAND_DELTA_IMPROVED, "5 -> 2: rank number fell, so it improved"),
        (2, 5, BAND_DELTA_WORSENED, "2 -> 5: rank number rose, so it worsened"),
        (0, 2, BAND_DELTA_IMPROVED, "was not found, now ranking — improvement"),
        (2, 0, BAND_DELTA_WORSENED, "was ranking, now gone — the worst kind of decline"),
        (11, 4, BAND_DELTA_IMPROVED, "far down -> page one"),
        (0, 20, BAND_DELTA_IMPROVED, "not found -> found far down still beats absent"),
        (20, 0, BAND_DELTA_WORSENED, "found far down -> not found"),
        (255, 2, BAND_DELTA_DEAD, "dead in the before snapshot — change undefined"),
        (2, 255, BAND_DELTA_DEAD, "dead in the after snapshot — change undefined"),
        (255, 255, BAND_DELTA_DEAD, "dead in both"),
    ],
)
def test_delta_band(before, after, band, why):
    assert delta_band(before, after) == band, why


def test_delta_band_total_over_domain():
    # No (before, after) byte pair falls through to an exception or an unknown band.
    valid = {BAND_DELTA_IMPROVED, BAND_DELTA_WORSENED, BAND_DELTA_UNCHANGED, BAND_DELTA_DEAD}
    for b in (0, 1, 3, 10, 20, 254, 255):
        for a in (0, 1, 3, 10, 20, 254, 255):
            assert delta_band(b, a) in valid


def test_absent_in_both_is_never_worsened():
    # The spec is explicit: a point absent in both snapshots MUST render neutral, never red.
    assert delta_band(0, 0) != BAND_DELTA_WORSENED
    assert delta_band(0, 0) == BAND_DELTA_UNCHANGED


# --- render guards (reporting §4.3, PRD §9a.2), hand-derived -----------------------------------

_OK = dict(
    provider_before="dataforseo",
    provider_after="dataforseo",
    scanned_before="2026-05-01T00:00:00+00:00",
    scanned_after="2026-05-16T00:00:00+00:00",  # 15 days — inside the 45-day default
    max_span_days=45,
    drift_suppressed=False,
)


def test_guard_passes_within_bounds():
    assert_delta_renderable(**_OK)  # does not raise


def test_guard_refuses_span_over_max():
    kw = {**_OK, "scanned_after": "2026-08-01T00:00:00+00:00"}  # ~92 days
    with pytest.raises(DeltaNotRenderable) as exc:
        assert_delta_renderable(**kw)
    assert exc.value.reason.startswith("span_exceeds_max")


def test_guard_refuses_provider_boundary():
    kw = {**_OK, "provider_after": "serpapi"}
    with pytest.raises(DeltaNotRenderable) as exc:
        assert_delta_renderable(**kw)
    assert exc.value.reason.startswith("provider_boundary")


def test_guard_refuses_suppressed_drift():
    kw = {**_OK, "drift_suppressed": True}
    with pytest.raises(DeltaNotRenderable) as exc:
        assert_delta_renderable(**kw)
    assert exc.value.reason == "drift_suppressed"


def test_guard_checks_drift_before_parsing_timestamps():
    # The two certain refusals precede the timestamp parse, so a suppressed delta is refused even
    # with a malformed timestamp — a render is never attempted on an untrustworthy comparison.
    kw = {**_OK, "drift_suppressed": True, "scanned_after": "not-a-timestamp"}
    with pytest.raises(DeltaNotRenderable) as exc:
        assert_delta_renderable(**kw)
    assert exc.value.reason == "drift_suppressed"


def test_span_days_is_symmetric_and_correct():
    a, b = "2026-05-01T00:00:00+00:00", "2026-05-16T00:00:00+00:00"
    assert span_days(a, b) == pytest.approx(15.0)
    assert span_days(b, a) == pytest.approx(15.0)  # absolute — order-independent


# --- a small hand-built delta to render -------------------------------------------------------


def _tiny_delta(before, after, *, business=(0.0, 0.0)):
    points = [
        GridPoint(point_seq=0, lat=34.0, lng=-118.0, dx_miles=-1.0, dy_miles=0.0),
        GridPoint(point_seq=1, lat=34.0, lng=-118.0, dx_miles=0.0, dy_miles=0.0),
        GridPoint(point_seq=2, lat=34.0, lng=-118.0, dx_miles=1.0, dy_miles=0.0),
    ]
    return DeltaInputs(
        points=points,
        before_vector=list(before),
        after_vector=list(after),
        radius_miles=5.0,
        spacing_miles=1.0,
        title="Change in coverage — Acme Plumbing",
        subtitle="plumber · Van Nuys · 2026-05-01 → 2026-05-16",
        business_offset=business,
    )


def test_delta_render_is_deterministic():
    a = render_delta(_tiny_delta([0, 5, 255], [2, 2, 255]))
    b = render_delta(_tiny_delta([0, 5, 255], [2, 2, 255]))
    assert a == b
    assert content_hash(a) == content_hash(b)


def test_delta_legend_is_directional_only_no_numbers():
    # Spec §7a: the delta legend MUST use directional language and MUST NOT show rank numbers.
    for _band, label in h._DELTA_LEGEND_ORDER:
        assert not any(ch.isdigit() for ch in label), f"delta legend label has a number: {label!r}"
    svg = render_delta(_tiny_delta([0, 0, 0], [2, 2, 2]))
    assert "Rank improved" in svg and "Rank worsened" in svg and "No change" in svg
    # The STATE legend's numbered labels must not leak into a delta render.
    assert "In the map pack" not in svg
    assert "(1–3)" not in svg


def test_delta_is_visually_distinct_from_state():
    # Spec §7a: the delta view MUST be distinguishable from a state heatmap on the same page. Its
    # frame is dashed and its plot field is tinted — neither appears in a state render.
    svg = render_delta(_tiny_delta([2, 2, 2], [1, 1, 1]))
    assert "stroke-dasharray" in svg
    assert 'fill="#f4f6fb"' in svg
    state = h.render_heatmap(
        HeatmapInputs(
            points=[GridPoint(0, 34.0, -118.0, 0.0, 0.0)],
            rank_vector=[2],
            radius_miles=5.0,
            spacing_miles=1.0,
            title="t",
            subtitle="s",
            business_offset=None,
        )
    )
    assert "stroke-dasharray" not in state


def test_delta_absent_in_both_draws_no_red():
    # Every point absent in both -> all neutral. No red "worsened" disc anywhere (the legend swatch
    # for worsened is the only red mark, so a clean render has exactly one).
    neutral = render_delta(_tiny_delta([0, 0, 0], [0, 0, 0], business=None))
    worsened = render_delta(_tiny_delta([2, 2, 2], [0, 0, 0], business=None))
    red = f'fill="{h.COLOR_NOT_FOUND}"'
    assert neutral.count(red) == 1  # legend swatch only
    assert worsened.count(red) > neutral.count(red)  # actual worsened discs appear


def test_delta_dead_in_either_is_a_ring_not_a_disc():
    dead = render_delta(_tiny_delta([255, 255, 255], [2, 2, 2], business=None))
    # Dead points render as hollow grey rings (stroke), never coloured discs.
    assert dead.count(f'stroke="{h.COLOR_DEAD}"') > 1  # rings + legend swatch


def test_delta_business_pin_toggles():
    with_pin = render_delta(_tiny_delta([2, 2, 2], [1, 1, 1], business=(0.0, 0.0)))
    without = render_delta(_tiny_delta([2, 2, 2], [1, 1, 1], business=None))
    assert with_pin.count("<polygon") == without.count("<polygon") + 1


def test_delta_length_invariant():
    with pytest.raises(ValueError):
        DeltaInputs(
            points=[GridPoint(0, 34.0, -118.0, 0.0, 0.0)],
            before_vector=[1, 2],  # two bytes, one point
            after_vector=[1, 2],
            radius_miles=5.0,
            spacing_miles=1.0,
            title="t",
            subtitle="s",
            business_offset=None,
        )


# --- pair -------------------------------------------------------------------------------------


def _panel(vec, title, subtitle):
    points = [
        GridPoint(0, 34.0, -118.0, -1.0, 0.0),
        GridPoint(1, 34.0, -118.0, 0.0, 0.0),
        GridPoint(2, 34.0, -118.0, 1.0, 0.0),
    ]
    return HeatmapInputs(
        points=points,
        rank_vector=list(vec),
        radius_miles=5.0,
        spacing_miles=1.0,
        title=title,
        subtitle=subtitle,
        business_offset=(0.0, 0.0),
    )


def test_pair_requires_shared_extent():
    left = _panel([0, 0, 0], "Before", "2026-05-01")
    wide = HeatmapInputs(
        points=left.points,
        rank_vector=[0, 0, 0],
        radius_miles=8.0,  # different extent
        spacing_miles=1.0,
        title="After",
        subtitle="2026-05-16",
        business_offset=(0.0, 0.0),
    )
    with pytest.raises(ValueError):
        PairInputs(left=left, right=wide)


def test_pair_is_deterministic_and_labels_both_dates():
    pair = PairInputs(
        left=_panel([0, 0, 0], "Before", "plumber · Van Nuys · 2026-05-01"),
        right=_panel([2, 2, 2], "After", "plumber · Van Nuys · 2026-05-16"),
    )
    a = render_pair(pair)
    b = render_pair(pair)
    assert a == b
    assert "2026-05-01" in a and "2026-05-16" in a  # both panels labelled with their dates
    # One shared legend, not two.
    assert a.count("In the map pack (1–3)") == 1
    assert a.count("This business") == 1


# --- build helpers (the DB read) --------------------------------------------------------------


def _snap(snap_id, ts):
    return {
        "id": snap_id,
        "center_lat": 34.19,
        "center_lng": -118.45,
        "grid_radius_miles": 5.0,
        "grid_spacing_miles": 1.0,
        "geometry_version": "v1",
        "scanned_at": ts,
    }


def test_build_delta_inputs_happy_path():
    n = 81
    di = build_delta_inputs(
        snapshot_before=_snap("b", "2026-05-01T00:00:00+00:00"),
        coverage_before={"rank_vector": bytes([0] * n)},
        snapshot_after=_snap("a", "2026-05-16T00:00:00+00:00"),
        coverage_after={"rank_vector": bytes([2] * n)},
        title="Change in coverage",
        subtitle="plumber · Van Nuys · May 1 → May 16",
        max_span_days=45,
        business_lat=34.20,
        business_lng=-118.44,
    )
    assert len(di.points) == n
    assert di.business_offset is not None
    svg = render_delta(di)
    assert svg.startswith("<svg")


def test_build_delta_inputs_enforces_span_guard():
    n = 81
    with pytest.raises(DeltaNotRenderable) as exc:
        build_delta_inputs(
            snapshot_before=_snap("b", "2026-01-01T00:00:00+00:00"),
            coverage_before={"rank_vector": bytes([0] * n)},
            snapshot_after=_snap("a", "2026-06-01T00:00:00+00:00"),  # far over 45 days
            coverage_after={"rank_vector": bytes([2] * n)},
            title="t",
            subtitle="s",
            max_span_days=45,
        )
    assert exc.value.reason.startswith("span_exceeds_max")


def test_build_delta_inputs_rejects_geometry_mismatch():
    n = 81
    bad_after = _snap("a", "2026-05-16T00:00:00+00:00")
    bad_after["center_lat"] = 35.0  # different grid centre
    with pytest.raises(DeltaNotRenderable) as exc:
        build_delta_inputs(
            snapshot_before=_snap("b", "2026-05-01T00:00:00+00:00"),
            coverage_before={"rank_vector": bytes([0] * n)},
            snapshot_after=bad_after,
            coverage_after={"rank_vector": bytes([2] * n)},
            title="t",
            subtitle="s",
            max_span_days=45,
        )
    assert exc.value.reason.startswith("geometry_mismatch")


def test_build_pair_inputs_happy_path():
    n = 81
    pair = build_pair_inputs(
        snapshot_before=_snap("b", "2026-05-01T00:00:00+00:00"),
        coverage_before={"rank_vector": bytes([0] * n)},
        snapshot_after=_snap("a", "2026-05-16T00:00:00+00:00"),
        coverage_after={"rank_vector": bytes([2] * n)},
        title_before="Before — May 1",
        subtitle_before="plumber · Van Nuys · 2026-05-01",
        title_after="After — May 16",
        subtitle_after="plumber · Van Nuys · 2026-05-16",
    )
    assert len(pair.left.points) == n and len(pair.right.points) == n
    svg = render_pair(pair)
    assert "Before — May 1" in svg and "After — May 16" in svg

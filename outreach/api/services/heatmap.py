"""Deterministic heatmap renderer — reporting-layer-spec §4.

The only genuinely new component of the reporting layer. Input is a DECODED `rank_vector` (one
byte per grid point in point_seq order) plus the snapshot's geometry — no raw `grid_result` — so a
historical heatmap renders forever from `prospect_coverage` alone (spec §4, and the acceptance
criterion "Heatmaps render from `prospect_coverage` alone, with no raw `grid_result` present").

DETERMINISM IS A HARD REQUIREMENT, not a nicety. The reporting layer caches artifacts in R2 keyed
by `content_hash` and cites a render made in March in a conversation held in June (spec §2, §6).
So this module has NO `now()`, NO random ids, NO unsorted iteration, and every coordinate is
formatted to a fixed precision. Regenerating with identical inputs MUST produce a byte-for-byte
identical SVG, and therefore an identical `content_hash`. `tests/test_heatmap.py` pins that.

The byte encoding is the producer's, from `coverage_rollup` and storage/reporting §4.2:

    0        not found          red
    1..3     in the pack        green
    4..10    page one           yellow
    11..254  found, far down    orange   (see FAR_DOWN note — 21+ is unreachable at scan_depth=20)
    255      dead point         faint grey ring, visually distinct from "not found"

Dead vs not-found MUST be distinguishable: conflating them overstates the prospect's pain in the
one direction a prospect can catch, so `255` renders as a hollow grey ring and `0` as a solid red
disc. The business's own pin renders last, on top, in a distinct shape and colour.

No map background in v1. Spec §4.5 makes a map background the DEFAULT for prospect-facing renders,
but the tile provider is an OPEN decision (spec §8 — licensing, not cost), and §4.5 also requires
tile failure to fall back to the no-background render. So no-background is a correct, shippable
starting point and the tile layer slots in behind the same geometry later without changing the
point layer or the hash contract for internal renders.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

from .coverage_rollup import BYTE_ABSENT, BYTE_DEAD, decode_rank_vector
from .geometry import MILES_PER_DEGREE_LAT, GridPoint, generate_points

# Bump only for a change that alters the RENDERED BYTES for identical inputs — a colour, a layout,
# a label. Stamped onto `report_artifact.generator_version` so a cached artifact records which
# renderer drew it, and a renderer change and a geometry change are told apart (spec §2). Distinct
# from `geometry.GEOMETRY_VERSION`, which pins point ORDERING; the two move independently.
GENERATOR_VERSION = "v1"

# --- colour scale (reporting §4.2) ------------------------------------------------------------
#
# Named once here so the legend and the points cannot drift apart — the legend swatch for a band
# and the fill for a point in that band read the same constant.
COLOR_PACK = "#2c9c3f"        # 1..3   in the pack
COLOR_PAGE_ONE = "#f2c744"    # 4..10  page one, below the pack
COLOR_FAR_DOWN = "#ea8f3a"    # 11+    found, far down
COLOR_NOT_FOUND = "#d24b3f"   # 0      not found
COLOR_DEAD = "#c9c9c9"        # 255    dead point — rendered as a hollow ring, never a disc
COLOR_BUSINESS = "#1b2a4a"    # the prospect's own pin
COLOR_TEXT = "#222222"
COLOR_FRAME = "#9aa0a6"

# Band keys, in legend order. A pure classifier maps a byte to one of these; render and legend both
# read the SAME map, so a point and its swatch can never disagree.
BAND_PACK = "pack"
BAND_PAGE_ONE = "page_one"
BAND_FAR_DOWN = "far_down"
BAND_NOT_FOUND = "not_found"
BAND_DEAD = "dead"

_BAND_FILL = {
    BAND_PACK: COLOR_PACK,
    BAND_PAGE_ONE: COLOR_PAGE_ONE,
    BAND_FAR_DOWN: COLOR_FAR_DOWN,
    BAND_NOT_FOUND: COLOR_NOT_FOUND,
    BAND_DEAD: COLOR_DEAD,
}

# Bands drawn as a hollow ring rather than a filled disc. Dead points MUST be a ring so "no data
# here" is never read as a coloured measurement (reporting §4.2).
_STATE_RING_BANDS = frozenset({BAND_DEAD})

# What the legend says for each band, in order. "11+" not "11–20" deliberately: `scan_depth` is
# config, and while it is 20 today a deeper scan would produce ranks past 20 that are still
# genuinely FOUND (never red). Folding 21+ into far_down is the cheapest-to-reverse reading of a
# spec gap (reporting §4.2 stops at 20) — logged as ISSUES I-089. If 11–20 vs 21+ ever needs to be
# split, it is a new band + a version bump, not a silent recolour of history.
_LEGEND_ORDER = [
    (BAND_PACK, "In the map pack (1–3)"),
    (BAND_PAGE_ONE, "Page one (4–10)"),
    (BAND_FAR_DOWN, "Found, far down (11+)"),
    (BAND_NOT_FOUND, "Not showing up"),
    (BAND_DEAD, "No data (dead zone)"),
]


def band_for_byte(value: int) -> str:
    """One rank_vector byte -> its colour band. Pure, total over 0..255.

    Order matters: the two reserved bytes are tested first, then the rank ranges. Everything from
    11 up is far_down — see the FAR_DOWN note above for why 21+ is not its own band.
    """
    if value == BYTE_DEAD:
        return BAND_DEAD
    if value == BYTE_ABSENT:
        return BAND_NOT_FOUND
    if 1 <= value <= 3:
        return BAND_PACK
    if 4 <= value <= 10:
        return BAND_PAGE_ONE
    return BAND_FAR_DOWN


# --- geometry helpers -------------------------------------------------------------------------


def business_offset_miles(
    center_lat: float, center_lng: float, biz_lat: float, biz_lng: float
) -> tuple[float, float]:
    """The business's (dx east, dy north) offset from the grid centre, in miles.

    Uses the SAME flat 69-miles-per-degree approximation the lattice is built on (`geometry`), so
    the pin lands in the same projected space as the grid points. A more accurate geodesy would
    put the pin fractionally off the grid it is meant to sit inside.
    """
    dy = (biz_lat - center_lat) * MILES_PER_DEGREE_LAT
    dx = (biz_lng - center_lng) * MILES_PER_DEGREE_LAT * math.cos(math.radians(center_lat))
    return dx, dy


# --- inputs -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class HeatmapInputs:
    """Everything the renderer needs, already resolved. Building this is where the DB read lives;
    rendering from it is pure, so a fixture is a `HeatmapInputs` with a hand-built vector."""

    points: list[GridPoint]
    rank_vector: list[int]                       # one byte per point, point_seq order
    radius_miles: float
    spacing_miles: float
    title: str
    subtitle: str
    business_offset: tuple[float, float] | None  # (dx east, dy north) miles, or None

    def __post_init__(self) -> None:
        if len(self.points) != len(self.rank_vector):
            raise ValueError(
                f"rank_vector has {len(self.rank_vector)} bytes but geometry has "
                f"{len(self.points)} points — wrong geometry_version or a decode error"
            )


def build_inputs(
    *,
    snapshot: dict[str, Any],
    coverage: dict[str, Any],
    title: str,
    subtitle: str,
    business_lat: float | None = None,
    business_lng: float | None = None,
) -> HeatmapInputs:
    """Assemble `HeatmapInputs` from a `scan_snapshot` row and a `prospect_coverage` row.

    Regenerates coordinates through the pinned generator using the snapshot's STORED
    `geometry_version` — never the current default (CLAUDE.md: regenerating a historical snapshot
    with the current generator is the exact failure the registry exists to prevent). The centre is
    the snapshot's own recorded `center_lat/lng` (ISSUES I-078), not the mutable submarket centre.
    """
    radius = float(snapshot["grid_radius_miles"])
    spacing = float(snapshot["grid_spacing_miles"])
    points = generate_points(
        float(snapshot["center_lat"]),
        float(snapshot["center_lng"]),
        radius,
        spacing,
        version=snapshot["geometry_version"],
    )
    vector = decode_rank_vector(coverage["rank_vector"])

    offset: tuple[float, float] | None = None
    if business_lat is not None and business_lng is not None:
        offset = business_offset_miles(
            float(snapshot["center_lat"]),
            float(snapshot["center_lng"]),
            float(business_lat),
            float(business_lng),
        )

    return HeatmapInputs(
        points=points,
        rank_vector=vector,
        radius_miles=radius,
        spacing_miles=spacing,
        title=title,
        subtitle=subtitle,
        business_offset=offset,
    )


# --- rendering --------------------------------------------------------------------------------

# Fixed layout constants. Every one is deterministic; none is read from the clock or the
# environment. Changing any of them changes the rendered bytes and MUST bump GENERATOR_VERSION.
_PX_PER_MILE = 34
_MARGIN = 24
_TITLE_H = 46
_LEGEND_H = 64
_POINT_R_FACTOR = 0.42        # dot radius as a fraction of one spacing step
_BUSINESS_R = 9


def _fmt(value: float) -> str:
    """Fixed-precision coordinate formatting — the determinism workhorse.

    `f"{-0.0:.1f}"` is `"-0.0"`, which differs by a byte from `"0.0"` and would split the hash of
    two mathematically identical renders. `+ 0.0` normalises the sign of zero.
    """
    return f"{value + 0.0:.1f}"


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# --- shared plot primitives -------------------------------------------------------------------
#
# Extracted so the single, pair, and delta renderers draw points, frames, scale bars, pins and
# legends through ONE code path. Each returns the exact SVG fragment its inline predecessor
# emitted, so `render_heatmap`'s bytes — and therefore every already-cited content_hash — are
# unchanged by the extraction (proven by `test_heatmap.py`'s determinism pins and the reference
# hashes captured before the refactor). A `Projector` maps (dx east, dy north) miles to pixels for
# a given plot origin, so a pair can place two plots side by side with two projectors.

def _projector(plot_x0: float, plot_y0: float, plot_w: int, plot_h: int, px: int):
    """A closure mapping miles-from-centre to pixels within one plot box. dx east -> +x, dy north
    -> -y (SVG y grows downward)."""
    cx = plot_x0 + plot_w / 2.0
    cy = plot_y0 + plot_h / 2.0

    def to_px(dx_miles: float, dy_miles: float) -> tuple[float, float]:
        return cx + dx_miles * px, cy - dy_miles * px

    return to_px


def _point_radius(spacing_miles: float, px: int) -> float:
    return max(3.0, spacing_miles * px * _POINT_R_FACTOR)


def _draw_frame(plot_x0: float, plot_y0: float, plot_w: int, plot_h: int) -> str:
    return (
        f'<rect x="{_fmt(plot_x0)}" y="{_fmt(plot_y0)}" width="{plot_w}" height="{plot_h}" '
        f'fill="none" stroke="{COLOR_FRAME}" stroke-width="1"/>'
    )


def _draw_marks(
    marks: list[tuple[GridPoint, str]],
    to_px,
    point_r: float,
    *,
    ring_bands: frozenset[str],
    fill_map: dict[str, str],
) -> list[str]:
    """Draw one disc (or hollow ring, for a band in `ring_bands`) per point, in point_seq order.

    `marks` MUST already be sorted by point_seq — sorting is the caller's job so the ordering
    contract lives next to where the vector is paired with its geometry. A ring band renders as a
    hollow stroke so a "no data here" point can never be read as a coloured measurement."""
    out: list[str] = []
    for point, band in marks:
        x, y = to_px(point.dx_miles, point.dy_miles)
        if band in ring_bands:
            out.append(
                f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="{_fmt(point_r * 0.7)}" '
                f'fill="none" stroke="{fill_map[band]}" stroke-width="2" opacity="0.9"/>'
            )
        else:
            out.append(
                f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="{_fmt(point_r)}" '
                f'fill="{fill_map[band]}" stroke="#ffffff" stroke-width="1" opacity="0.92"/>'
            )
    return out


def _draw_scale_bar(plot_x0: float, plot_y0: float, plot_h: int, px: int) -> list[str]:
    bar_len = px  # one mile
    bar_x = plot_x0 + 10
    bar_y = plot_y0 + plot_h - 12
    return [
        f'<line x1="{_fmt(bar_x)}" y1="{_fmt(bar_y)}" x2="{_fmt(bar_x + bar_len)}" '
        f'y2="{_fmt(bar_y)}" stroke="{COLOR_TEXT}" stroke-width="2"/>',
        f'<text x="{_fmt(bar_x + bar_len + 6)}" y="{_fmt(bar_y + 4)}" font-size="11" '
        f'fill="{COLOR_TEXT}">1 mile</text>',
    ]


def _draw_business_pin(bx: float, by: float, r: int = _BUSINESS_R) -> str:
    """A diamond, distinct from every round grid dot, in a strong contrasting colour."""
    diamond = (
        f"{_fmt(bx)},{_fmt(by - r)} {_fmt(bx + r)},{_fmt(by)} "
        f"{_fmt(bx)},{_fmt(by + r)} {_fmt(bx - r)},{_fmt(by)}"
    )
    return (
        f'<polygon points="{diamond}" fill="{COLOR_BUSINESS}" stroke="#ffffff" stroke-width="2"/>'
    )


def _draw_legend(
    legend_order: list[tuple[str, str]],
    legend_y: float,
    x0: float,
    *,
    ring_bands: frozenset[str],
    fill_map: dict[str, str],
    include_business: bool,
) -> list[str]:
    """Swatches + labels along the bottom band, then (optionally) the business marker. The swatch
    for a band reads the SAME `fill_map` the points do, so a legend can never disagree with the
    plot. The advance is a deterministic function of label length — no text measurement."""
    out: list[str] = []
    lx = x0
    for band, label in legend_order:
        if band in ring_bands:
            out.append(
                f'<circle cx="{_fmt(lx + 6)}" cy="{_fmt(legend_y - 4)}" r="6" fill="none" '
                f'stroke="{fill_map[band]}" stroke-width="2"/>'
            )
        else:
            out.append(
                f'<circle cx="{_fmt(lx + 6)}" cy="{_fmt(legend_y - 4)}" r="6" '
                f'fill="{fill_map[band]}" stroke="#ffffff" stroke-width="1"/>'
            )
        out.append(
            f'<text x="{_fmt(lx + 18)}" y="{_fmt(legend_y)}" font-size="12" '
            f'fill="{COLOR_TEXT}">{_esc(label)}</text>'
        )
        lx += 18 + 7.4 * len(label) + 20  # deterministic advance; no text measurement

    if include_business:
        out.append(
            f'<polygon points="{_fmt(lx + 6)},{_fmt(legend_y - 10)} {_fmt(lx + 12)},{_fmt(legend_y - 4)} '
            f'{_fmt(lx + 6)},{_fmt(legend_y + 2)} {_fmt(lx)},{_fmt(legend_y - 4)}" '
            f'fill="{COLOR_BUSINESS}" stroke="#ffffff" stroke-width="1.5"/>'
        )
        out.append(
            f'<text x="{_fmt(lx + 18)}" y="{_fmt(legend_y)}" font-size="12" '
            f'fill="{COLOR_TEXT}">This business</text>'
        )
    return out


def _svg_open(width: int, height: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Helvetica,Arial,sans-serif">'
    )


def _title_block(title: str, subtitle: str, x: float) -> list[str]:
    out = [
        f'<text x="{_fmt(x)}" y="26" font-size="18" font-weight="bold" '
        f'fill="{COLOR_TEXT}">{_esc(title)}</text>'
    ]
    if subtitle:
        out.append(
            f'<text x="{_fmt(x)}" y="42" font-size="12" fill="{COLOR_FRAME}">'
            f'{_esc(subtitle)}</text>'
        )
    return out


def _state_marks(inp: HeatmapInputs) -> list[tuple[GridPoint, str]]:
    """(point, state band) for every point, sorted by point_seq. Sorting here means a caller that
    reordered inputs still renders — and hashes — identically."""
    return sorted(
        ((p, band_for_byte(v)) for p, v in zip(inp.points, inp.rank_vector, strict=True)),
        key=lambda m: m[0].point_seq,
    )


# --- rendering --------------------------------------------------------------------------------


def render_heatmap(inp: HeatmapInputs) -> str:
    """The SVG for one prospect at one snapshot. Pure and deterministic.

    Row/point iteration is in point_seq order (the generator's order), floats are fixed-precision,
    and there are no ids or timestamps — so identical inputs yield identical bytes.
    """
    px = _PX_PER_MILE
    plot_w = int(round(2 * inp.radius_miles * px))
    plot_h = plot_w
    width = plot_w + 2 * _MARGIN
    height = _TITLE_H + plot_h + _LEGEND_H + 2 * _MARGIN

    plot_x0 = _MARGIN
    plot_y0 = _MARGIN + _TITLE_H
    to_px = _projector(plot_x0, plot_y0, plot_w, plot_h, px)
    point_r = _point_radius(inp.spacing_miles, px)

    parts: list[str] = [_svg_open(width, height)]
    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>')
    parts.extend(_title_block(inp.title, inp.subtitle, _MARGIN))
    parts.append(_draw_frame(plot_x0, plot_y0, plot_w, plot_h))
    parts.extend(
        _draw_marks(
            _state_marks(inp), to_px, point_r, ring_bands=_STATE_RING_BANDS, fill_map=_BAND_FILL
        )
    )
    parts.extend(_draw_scale_bar(plot_x0, plot_y0, plot_h, px))
    if inp.business_offset is not None:
        parts.append(_draw_business_pin(*to_px(*inp.business_offset)))
    parts.extend(
        _draw_legend(
            _LEGEND_ORDER,
            plot_y0 + plot_h + 22,
            _MARGIN,
            ring_bands=_STATE_RING_BANDS,
            fill_map=_BAND_FILL,
            include_business=True,
        )
    )
    parts.append("</svg>")
    return "".join(parts)


def content_hash(svg: str) -> str:
    """The cache key and reproducibility check — sha256 of the rendered bytes (spec §2, §6)."""
    return hashlib.sha256(svg.encode("utf-8")).hexdigest()


# ==============================================================================================
# Comparison renderers — reporting-layer-spec §4.3
#
# `heatmap_pair`  — two snapshots side by side, shared colour scale and extent (case-study drafts
#                   and client before/after). Both panels label their snapshot dates.
# `heatmap_delta` — per-point CHANGE between two snapshots. Green where rank improved, red where it
#                   worsened, neutral where unchanged. The visual form of the strongest pitch
#                   signal, so it carries the most guards.
# ==============================================================================================

# --- delta bands (reporting §4.3, §7a) --------------------------------------------------------
#
# THE TRAP (spec §7a): rank is inverted — "improved" means the rank NUMBER went down. So the legend
# uses directional language only and shows no rank numbers, and the classifier compares an EFFECTIVE
# rank in which "not found" (byte 0) is worse than any real position.
BAND_DELTA_IMPROVED = "delta_improved"
BAND_DELTA_WORSENED = "delta_worsened"
BAND_DELTA_UNCHANGED = "delta_unchanged"
BAND_DELTA_DEAD = "delta_dead"

COLOR_DELTA_UNCHANGED = "#b9c0cb"  # neutral grey — distinct from the dead ring's lighter grey

_DELTA_FILL = {
    BAND_DELTA_IMPROVED: COLOR_PACK,       # green — same green as "in the pack"
    BAND_DELTA_WORSENED: COLOR_NOT_FOUND,  # red   — same red as "not found"
    BAND_DELTA_UNCHANGED: COLOR_DELTA_UNCHANGED,
    BAND_DELTA_DEAD: COLOR_DEAD,
}
_DELTA_RING_BANDS = frozenset({BAND_DELTA_DEAD})

# Directional language ONLY — no raw ranks, no numeric deltas (spec §7a).
_DELTA_LEGEND_ORDER = [
    (BAND_DELTA_IMPROVED, "Rank improved"),
    (BAND_DELTA_WORSENED, "Rank worsened"),
    (BAND_DELTA_UNCHANGED, "No change"),
    (BAND_DELTA_DEAD, "No data (dead zone)"),
]

# A found ranking, however deep, is a real position; "not found" is worse than the deepest. Larger
# than any real byte (254) so absent always compares as the worst outcome.
_ABSENT_EFFECTIVE_RANK = 1000


def _effective_rank(value: int) -> int:
    return _ABSENT_EFFECTIVE_RANK if value == BYTE_ABSENT else value


def delta_band(before: int, after: int) -> str:
    """Classify one point's change from `before` byte to `after` byte. Pure, total over 0..255².

    - Dead in EITHER snapshot -> `delta_dead` (the change is undefined where a point wasn't
      measured). Rendered as a ring, never coloured.
    - Absent in BOTH -> `unchanged`. "Still not ranking" is not a decline and MUST render neutral,
      never red (spec §7a).
    - Otherwise compare effective ranks: a lower after-rank is an improvement (green), a higher one
      is a decline (red), equal is neutral.
    """
    if before == BYTE_DEAD or after == BYTE_DEAD:
        return BAND_DELTA_DEAD
    if before == BYTE_ABSENT and after == BYTE_ABSENT:
        return BAND_DELTA_UNCHANGED
    eb, ea = _effective_rank(before), _effective_rank(after)
    if ea < eb:
        return BAND_DELTA_IMPROVED
    if ea > eb:
        return BAND_DELTA_WORSENED
    return BAND_DELTA_UNCHANGED


# --- delta render guards (reporting §4.3, PRD §9a.2) ------------------------------------------


class DeltaNotRenderable(Exception):
    """A delta comparison the guards refuse — never rendered as a picture, because a wrong delta is
    the one a prospect can most easily disprove. Carries a machine-readable `reason`."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _parse_ts(value: Any) -> "datetime":
    from datetime import datetime

    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def span_days(scanned_before: Any, scanned_after: Any) -> float:
    """Absolute gap in days between two snapshot timestamps."""
    delta = _parse_ts(scanned_after) - _parse_ts(scanned_before)
    return abs(delta.total_seconds()) / 86400.0


def assert_delta_renderable(
    *,
    provider_before: str,
    provider_after: str,
    scanned_before: Any,
    scanned_after: Any,
    max_span_days: int,
    drift_suppressed: bool,
) -> None:
    """Raise `DeltaNotRenderable` when a delta MUST NOT be drawn (spec §4.3):

    - drift suppression fired for this prospect (PRD §9a.2) — the delta is not trustworthy;
    - the two snapshots crossed a provider boundary — the numbers are not comparable;
    - the gap exceeds `max_delta_span_days` — a wide gap attributes several intervals' change to
      one.

    Order is deliberate: the two cheapest, most-certain refusals (a boolean and a string compare)
    come before the timestamp parse, so a suppressed or cross-provider delta is refused even if a
    timestamp is malformed.
    """
    if drift_suppressed:
        raise DeltaNotRenderable("drift_suppressed")
    if provider_before != provider_after:
        raise DeltaNotRenderable(f"provider_boundary:{provider_before}!={provider_after}")
    gap = span_days(scanned_before, scanned_after)
    if gap > max_span_days:
        raise DeltaNotRenderable(f"span_exceeds_max:{gap:.1f}>{max_span_days}")


# --- pair -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PairInputs:
    """Two `HeatmapInputs` for the same subject at two snapshots, rendered side by side. They MUST
    share extent (radius, spacing, point count) so the two panels are directly comparable — a pair
    across different geometry would invite a false read."""

    left: HeatmapInputs
    right: HeatmapInputs

    def __post_init__(self) -> None:
        if (
            self.left.radius_miles != self.right.radius_miles
            or self.left.spacing_miles != self.right.spacing_miles
            or len(self.left.points) != len(self.right.points)
        ):
            raise ValueError(
                "pair panels must share geometry (extent) — a before/after across different "
                "grids is not comparable (reporting §4.3)"
            )


def render_pair(pair: PairInputs) -> str:
    """Two state heatmaps side by side under a shared legend. Pure and deterministic.

    Both panels use the SAME colour scale and the SAME extent, and each is titled with its own
    snapshot date (the caller puts the date in each panel's subtitle). One legend serves both."""
    px = _PX_PER_MILE
    left, right = pair.left, pair.right
    plot_w = int(round(2 * left.radius_miles * px))
    plot_h = plot_w
    point_r = _point_radius(left.spacing_miles, px)

    width = 2 * plot_w + 3 * _MARGIN
    height = _TITLE_H + plot_h + _LEGEND_H + 2 * _MARGIN
    plot_y0 = _MARGIN + _TITLE_H
    left_x0 = _MARGIN
    right_x0 = _MARGIN + plot_w + _MARGIN

    parts: list[str] = [_svg_open(width, height)]
    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>')

    for inp, x0 in ((left, left_x0), (right, right_x0)):
        to_px = _projector(x0, plot_y0, plot_w, plot_h, px)
        parts.extend(_title_block(inp.title, inp.subtitle, x0))
        parts.append(_draw_frame(x0, plot_y0, plot_w, plot_h))
        parts.extend(
            _draw_marks(
                _state_marks(inp), to_px, point_r, ring_bands=_STATE_RING_BANDS, fill_map=_BAND_FILL
            )
        )
        parts.extend(_draw_scale_bar(x0, plot_y0, plot_h, px))
        if inp.business_offset is not None:
            parts.append(_draw_business_pin(*to_px(*inp.business_offset)))

    parts.extend(
        _draw_legend(
            _LEGEND_ORDER,
            plot_y0 + plot_h + 22,
            _MARGIN,
            ring_bands=_STATE_RING_BANDS,
            fill_map=_BAND_FILL,
            include_business=True,
        )
    )
    parts.append("</svg>")
    return "".join(parts)


# --- delta ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DeltaInputs:
    """A per-point CHANGE between two snapshots of one subject, on shared geometry. The guards
    (`assert_delta_renderable`) run in `build_delta_inputs` BEFORE this is constructed, so a
    `DeltaInputs` that exists is one that passed them."""

    points: list[GridPoint]
    before_vector: list[int]
    after_vector: list[int]
    radius_miles: float
    spacing_miles: float
    title: str
    subtitle: str
    business_offset: tuple[float, float] | None

    def __post_init__(self) -> None:
        if not (len(self.points) == len(self.before_vector) == len(self.after_vector)):
            raise ValueError(
                f"delta vectors ({len(self.before_vector)}/{len(self.after_vector)}) and geometry "
                f"({len(self.points)}) disagree — wrong geometry_version or a decode error"
            )


def _delta_marks(inp: DeltaInputs) -> list[tuple[GridPoint, str]]:
    return sorted(
        (
            (p, delta_band(b, a))
            for p, b, a in zip(
                inp.points, inp.before_vector, inp.after_vector, strict=True
            )
        ),
        key=lambda m: m[0].point_seq,
    )


def render_delta(inp: DeltaInputs) -> str:
    """The change picture. Pure and deterministic.

    Made visually distinct from a state heatmap (spec §7a) by a tinted plot field and a dashed
    frame, so the two are not confused when they share a page. The legend is directional only."""
    px = _PX_PER_MILE
    plot_w = int(round(2 * inp.radius_miles * px))
    plot_h = plot_w
    width = plot_w + 2 * _MARGIN
    height = _TITLE_H + plot_h + _LEGEND_H + 2 * _MARGIN
    plot_x0 = _MARGIN
    plot_y0 = _MARGIN + _TITLE_H
    to_px = _projector(plot_x0, plot_y0, plot_w, plot_h, px)
    point_r = _point_radius(inp.spacing_miles, px)

    parts: list[str] = [_svg_open(width, height)]
    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>')
    parts.extend(_title_block(inp.title, inp.subtitle, _MARGIN))
    # Distinct-from-state treatment: a faint tinted field behind the plot, and a dashed frame.
    parts.append(
        f'<rect x="{_fmt(plot_x0)}" y="{_fmt(plot_y0)}" width="{plot_w}" height="{plot_h}" '
        f'fill="#f4f6fb"/>'
    )
    parts.append(
        f'<rect x="{_fmt(plot_x0)}" y="{_fmt(plot_y0)}" width="{plot_w}" height="{plot_h}" '
        f'fill="none" stroke="{COLOR_FRAME}" stroke-width="1" stroke-dasharray="4 3"/>'
    )
    parts.extend(
        _draw_marks(
            _delta_marks(inp), to_px, point_r, ring_bands=_DELTA_RING_BANDS, fill_map=_DELTA_FILL
        )
    )
    parts.extend(_draw_scale_bar(plot_x0, plot_y0, plot_h, px))
    if inp.business_offset is not None:
        parts.append(_draw_business_pin(*to_px(*inp.business_offset)))
    parts.extend(
        _draw_legend(
            _DELTA_LEGEND_ORDER,
            plot_y0 + plot_h + 22,
            _MARGIN,
            ring_bands=_DELTA_RING_BANDS,
            fill_map=_DELTA_FILL,
            include_business=True,
        )
    )
    parts.append("</svg>")
    return "".join(parts)


# --- build helpers (the DB read; rendering above stays pure) ----------------------------------


def _require_same_geometry(snap_a: dict[str, Any], snap_b: dict[str, Any]) -> None:
    """A pair/delta only makes sense on identical geometry. Geometry is immutable per submarket
    (CLAUDE.md), so two snapshots of the same submarket already match — this catches a caller that
    paired snapshots from different submarkets, which would silently map one vector onto the
    other's coordinates."""
    for field in ("geometry_version", "grid_radius_miles", "grid_spacing_miles",
                  "center_lat", "center_lng"):
        if snap_a.get(field) != snap_b.get(field):
            raise DeltaNotRenderable(f"geometry_mismatch:{field}")


def build_pair_inputs(
    *,
    snapshot_before: dict[str, Any],
    coverage_before: dict[str, Any],
    snapshot_after: dict[str, Any],
    coverage_after: dict[str, Any],
    title_before: str,
    subtitle_before: str,
    title_after: str,
    subtitle_after: str,
    business_lat: float | None = None,
    business_lng: float | None = None,
) -> PairInputs:
    """Assemble a before/after `PairInputs` from two snapshots + coverage rows (left = before)."""
    _require_same_geometry(snapshot_before, snapshot_after)
    left = build_inputs(
        snapshot=snapshot_before,
        coverage=coverage_before,
        title=title_before,
        subtitle=subtitle_before,
        business_lat=business_lat,
        business_lng=business_lng,
    )
    right = build_inputs(
        snapshot=snapshot_after,
        coverage=coverage_after,
        title=title_after,
        subtitle=subtitle_after,
        business_lat=business_lat,
        business_lng=business_lng,
    )
    return PairInputs(left=left, right=right)


def build_delta_inputs(
    *,
    snapshot_before: dict[str, Any],
    coverage_before: dict[str, Any],
    snapshot_after: dict[str, Any],
    coverage_after: dict[str, Any],
    title: str,
    subtitle: str,
    max_span_days: int,
    business_lat: float | None = None,
    business_lng: float | None = None,
    provider_before: str = "dataforseo",
    provider_after: str = "dataforseo",
    drift_suppressed: bool = False,
) -> DeltaInputs:
    """Assemble a `DeltaInputs`, enforcing every delta guard first (spec §4.3).

    `provider_*` default to the single provider in use today; `scan_snapshot` carries no provider
    column yet, so the boundary guard is a mechanism awaiting a second provider (ISSUES I-091).
    `drift_suppressed` is supplied by the caller — it is False until `prospect_delta` exists to
    source it (session protocol: build the consumer, do not pull the drift subsystem forward).
    """
    _require_same_geometry(snapshot_before, snapshot_after)
    assert_delta_renderable(
        provider_before=provider_before,
        provider_after=provider_after,
        scanned_before=snapshot_before["scanned_at"],
        scanned_after=snapshot_after["scanned_at"],
        max_span_days=max_span_days,
        drift_suppressed=drift_suppressed,
    )
    points = generate_points(
        float(snapshot_after["center_lat"]),
        float(snapshot_after["center_lng"]),
        float(snapshot_after["grid_radius_miles"]),
        float(snapshot_after["grid_spacing_miles"]),
        version=snapshot_after["geometry_version"],
    )
    offset: tuple[float, float] | None = None
    if business_lat is not None and business_lng is not None:
        offset = business_offset_miles(
            float(snapshot_after["center_lat"]),
            float(snapshot_after["center_lng"]),
            float(business_lat),
            float(business_lng),
        )
    return DeltaInputs(
        points=points,
        before_vector=decode_rank_vector(coverage_before["rank_vector"]),
        after_vector=decode_rank_vector(coverage_after["rank_vector"]),
        radius_miles=float(snapshot_after["grid_radius_miles"]),
        spacing_miles=float(snapshot_after["grid_spacing_miles"]),
        title=title,
        subtitle=subtitle,
        business_offset=offset,
    )

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


def render_heatmap(inp: HeatmapInputs) -> str:
    """The SVG for one prospect at one snapshot. Pure and deterministic.

    Row/point iteration is in point_seq order (the generator's order), floats are fixed-precision,
    and there are no ids or timestamps — so identical inputs yield identical bytes.
    """
    px = _PX_PER_MILE
    extent = inp.radius_miles
    plot_w = int(round(2 * extent * px))
    plot_h = plot_w

    width = plot_w + 2 * _MARGIN
    height = _TITLE_H + plot_h + _LEGEND_H + 2 * _MARGIN

    # Plot origin (top-left of the square plot area) and its centre in pixels.
    plot_x0 = _MARGIN
    plot_y0 = _MARGIN + _TITLE_H
    cx = plot_x0 + plot_w / 2.0
    cy = plot_y0 + plot_h / 2.0

    def to_px(dx_miles: float, dy_miles: float) -> tuple[float, float]:
        # dx east -> +x; dy north -> -y (SVG y grows downward).
        return cx + dx_miles * px, cy - dy_miles * px

    point_r = max(3.0, inp.spacing_miles * px * _POINT_R_FACTOR)

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Helvetica,Arial,sans-serif">'
    )
    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>')

    # Title + subtitle.
    parts.append(
        f'<text x="{_fmt(_MARGIN)}" y="26" font-size="18" font-weight="bold" '
        f'fill="{COLOR_TEXT}">{_esc(inp.title)}</text>'
    )
    if inp.subtitle:
        parts.append(
            f'<text x="{_fmt(_MARGIN)}" y="42" font-size="12" fill="{COLOR_FRAME}">'
            f'{_esc(inp.subtitle)}</text>'
        )

    # Plot frame.
    parts.append(
        f'<rect x="{_fmt(plot_x0)}" y="{_fmt(plot_y0)}" width="{plot_w}" height="{plot_h}" '
        f'fill="none" stroke="{COLOR_FRAME}" stroke-width="1"/>'
    )

    # Grid points, in point_seq order (already the generator's order; sorted defensively so a
    # caller that reordered inputs still renders — and hashes — identically).
    ordered = sorted(
        zip(inp.points, inp.rank_vector, strict=True), key=lambda pv: pv[0].point_seq
    )
    for point, value in ordered:
        x, y = to_px(point.dx_miles, point.dy_miles)
        band = band_for_byte(value)
        if band == BAND_DEAD:
            # Hollow ring — unmistakably "no data here", never confused with a red "not found".
            parts.append(
                f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="{_fmt(point_r * 0.7)}" '
                f'fill="none" stroke="{COLOR_DEAD}" stroke-width="2" opacity="0.9"/>'
            )
        else:
            parts.append(
                f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="{_fmt(point_r)}" '
                f'fill="{_BAND_FILL[band]}" stroke="#ffffff" stroke-width="1" opacity="0.92"/>'
            )

    # Scale bar — one mile, bottom-left inside the plot.
    bar_len = px  # one mile
    bar_x = plot_x0 + 10
    bar_y = plot_y0 + plot_h - 12
    parts.append(
        f'<line x1="{_fmt(bar_x)}" y1="{_fmt(bar_y)}" x2="{_fmt(bar_x + bar_len)}" '
        f'y2="{_fmt(bar_y)}" stroke="{COLOR_TEXT}" stroke-width="2"/>'
    )
    parts.append(
        f'<text x="{_fmt(bar_x + bar_len + 6)}" y="{_fmt(bar_y + 4)}" font-size="11" '
        f'fill="{COLOR_TEXT}">1 mile</text>'
    )

    # Business pin — LAST, so it sits on top of the grid. A diamond, distinct from every round
    # grid dot, in a strong contrasting colour with a white outline.
    if inp.business_offset is not None:
        bx, by = to_px(*inp.business_offset)
        r = _BUSINESS_R
        diamond = (
            f"{_fmt(bx)},{_fmt(by - r)} {_fmt(bx + r)},{_fmt(by)} "
            f"{_fmt(bx)},{_fmt(by + r)} {_fmt(bx - r)},{_fmt(by)}"
        )
        parts.append(
            f'<polygon points="{diamond}" fill="{COLOR_BUSINESS}" stroke="#ffffff" '
            f'stroke-width="2"/>'
        )

    # Legend — swatches + labels, then the business marker, along the bottom band.
    legend_y = plot_y0 + plot_h + 22
    lx = _MARGIN
    for band, label in _LEGEND_ORDER:
        if band == BAND_DEAD:
            parts.append(
                f'<circle cx="{_fmt(lx + 6)}" cy="{_fmt(legend_y - 4)}" r="6" fill="none" '
                f'stroke="{COLOR_DEAD}" stroke-width="2"/>'
            )
        else:
            parts.append(
                f'<circle cx="{_fmt(lx + 6)}" cy="{_fmt(legend_y - 4)}" r="6" '
                f'fill="{_BAND_FILL[band]}" stroke="#ffffff" stroke-width="1"/>'
            )
        parts.append(
            f'<text x="{_fmt(lx + 18)}" y="{_fmt(legend_y)}" font-size="12" '
            f'fill="{COLOR_TEXT}">{_esc(label)}</text>'
        )
        lx += 18 + 7.4 * len(label) + 20  # deterministic advance; no text measurement

    parts.append(
        f'<polygon points="{_fmt(lx + 6)},{_fmt(legend_y - 10)} {_fmt(lx + 12)},{_fmt(legend_y - 4)} '
        f'{_fmt(lx + 6)},{_fmt(legend_y + 2)} {_fmt(lx)},{_fmt(legend_y - 4)}" '
        f'fill="{COLOR_BUSINESS}" stroke="#ffffff" stroke-width="1.5"/>'
    )
    parts.append(
        f'<text x="{_fmt(lx + 18)}" y="{_fmt(legend_y)}" font-size="12" '
        f'fill="{COLOR_TEXT}">This business</text>'
    )

    parts.append("</svg>")
    return "".join(parts)


def content_hash(svg: str) -> str:
    """The cache key and reproducibility check — sha256 of the rendered bytes (spec §2, §6)."""
    return hashlib.sha256(svg.encode("utf-8")).hexdigest()

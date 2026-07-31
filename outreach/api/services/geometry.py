"""Grid geometry — the pinned, versioned generator.

Coordinates are NOT stored anywhere. `grid_result` deliberately has no lat/lng (storage spec §5),
and `prospect_coverage.rank_vector` is one byte per point ordered by `point_seq` with nothing to
say where those points are. Every coordinate in this system is regenerated on demand from
`scan_snapshot.{center, grid_radius_miles, grid_spacing_miles}` plus `point_seq`, through this
module.

That makes ORDERING the load-bearing property, and it is why the version registry below exists
rather than a bare version string. A version string that merely labels whatever the current code
does is not a pin: change the ordering, bump the label, and every historical `rank_vector` is
now decoded against coordinates that were never used to collect it — silently, with the heatmap
still rendering and every number still plausible. `_GENERATORS` keeps each version's function
callable forever, so a snapshot stamped `v1` regenerates through `v1` no matter what later
versions do.

**Geometry is immutable from the first scan.** Changing a submarket's centre, radius or spacing
invalidates every prior snapshot for it and resets its delta history. Names are editable;
geometry is not. `seeding.check_geometry_change` enforces that for submarkets; this module is the
other half — the shape, given those parameters.

---

THE POINT COUNT: 81, not 89.

`README.md` and PRD §8b describe an "89-point geogrid" over a 5-mile radius at 1-mile spacing
(the PRD hedges it as "~89"). No construction produces 89. This one produces **81**, and 81 is
what the specification that actually defines the generator asks for — reporting spec §4.1:

    Square lattice covering the bounding box, row-major from NW corner,
    clipped to distance <= radius_miles from centre.

A 1-mile lattice bounded by a 5-mile radius contains 81 points; counted by row from the north
they run 1, 7, 9, 9, 9, 11, 9, 9, 9, 7, 1. The alternatives were checked rather than assumed:
a hexagonal lattice at the same spacing gives 91 (and pi*25*2/sqrt(3) = 90.7 is the likeliest
origin of a remembered "89"), concentric 8-point rings give 41, and the unclipped 11x11 bounding
box gives 121. 89 is none of them.

The count is not a parameter. It is an OUTPUT of (radius, spacing, lattice, clip), all four of
which the specs fix. So this is a correction to an arithmetic estimate, not a choice between
designs — but it is an immutable one from the first scan onward, so it is recorded in
DECISIONS.md and ISSUES I-025 rather than just fixed. See those before changing it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterator

# Stamped onto `scan_snapshot.geometry_version` at scan time and used to select the generator when
# regenerating coordinates for a historical snapshot. Bump ONLY for a change that alters point
# ORDERING or membership, and never apply the change retroactively.
GEOMETRY_VERSION = "v1"

# Miles per degree of latitude. Fixed by the reporting spec's formula, not by a better geodesy —
# the point ordering must match what that spec defines, and any more accurate constant would
# shift borderline points and renumber everything after them.
MILES_PER_DEGREE_LAT = 69.0

# Relative tolerance on the clip comparison. A point sitting exactly on the radius (dx=5, dy=0 at
# radius 5) must be included deterministically. Without a tolerance, whether `dx*dx + dy*dy <= r*r`
# holds for a non-integer spacing depends on float rounding — and a point flipping in or out does
# not just change the count, it RENUMBERS every point_seq after it, which silently re-maps every
# historical rank_vector. Cheap insurance against an expensive, invisible failure.
_CLIP_EPSILON = 1e-9


@dataclass(frozen=True)
class GridPoint:
    """One scan point. `dx_miles`/`dy_miles` are the offsets the clip was computed from — kept so
    a caller (the rollup's `centroid_dist_at_loss`, the heatmap's scale bar) never has to re-derive
    distance from coordinates and risk disagreeing with the generator about what is inside."""

    point_seq: int
    lat: float
    lng: float
    dx_miles: float
    dy_miles: float

    @property
    def distance_miles(self) -> float:
        return math.hypot(self.dx_miles, self.dy_miles)


class UnknownGeometryVersion(ValueError):
    """Raised when a snapshot names a generator this build does not have.

    Loud on purpose. The tempting recovery — fall back to the current generator — is the exact
    failure the version registry exists to prevent: it would render historical vectors against
    coordinates that were never used to collect them, and produce a picture rather than an error.
    """


def _steps(radius_miles: float, spacing_miles: float) -> int:
    """Half-width of the bounding box, in lattice steps.

    CEIL, not floor. The box must COVER the circle before clipping — with radius 5 and spacing
    0.75, floor would give 6 steps (±4.5 miles) and quietly shave the outer ring off every grid,
    depressing coverage denominators in a way that looks like uniform market weakness.
    """
    if spacing_miles <= 0:
        raise ValueError("spacing_miles must be positive")
    if radius_miles <= 0:
        raise ValueError("radius_miles must be positive")
    return int(math.ceil(radius_miles / spacing_miles - _CLIP_EPSILON))


def _generate_v1(
    center_lat: float,
    center_lng: float,
    radius_miles: float,
    spacing_miles: float,
) -> Iterator[GridPoint]:
    """v1 — reporting-layer-spec §4.1, verbatim.

    Square lattice over the bounding box, row-major from the NW corner (north to south, then west
    to east within each row), clipped to `distance <= radius_miles`, `point_seq` zero-based over
    the surviving points.

    The clip measures the FLAT mile offsets, not a great-circle distance over the generated
    coordinates. The coordinates themselves come from the spec's flat 69-miles-per-degree
    approximation, so the flat offsets are exactly the distances that approximation implies;
    measuring them any other way would disagree with the lattice that produced them and could flip
    a borderline point. More accurate is not the goal here — reproducible is.
    """
    lat_step = spacing_miles / MILES_PER_DEGREE_LAT
    # cos(latitude) narrows a degree of longitude away from the equator. At LA's 34° a degree of
    # longitude is ~57 miles, not 69; without this the grid would be ~17% too wide there and the
    # "5-mile radius" would not be one.
    lng_step = spacing_miles / (MILES_PER_DEGREE_LAT * math.cos(math.radians(center_lat)))

    steps = _steps(radius_miles, spacing_miles)
    limit = radius_miles * radius_miles * (1.0 + _CLIP_EPSILON)

    seq = 0
    for row in range(2 * steps + 1):
        # row 0 is the NORTHERNMOST — row-major from the NW corner.
        dy_steps = steps - row
        dy_miles = dy_steps * spacing_miles
        for col in range(2 * steps + 1):
            dx_steps = col - steps
            dx_miles = dx_steps * spacing_miles

            if dx_miles * dx_miles + dy_miles * dy_miles > limit:
                continue

            yield GridPoint(
                point_seq=seq,
                lat=center_lat + dy_steps * lat_step,
                lng=center_lng + dx_steps * lng_step,
                dx_miles=dx_miles,
                dy_miles=dy_miles,
            )
            seq += 1


# Every version ever shipped stays here, callable. Deleting an entry orphans every snapshot that
# names it — the vectors survive and become undecodable, which is worse than either keeping the
# function or having never written it.
_GENERATORS: dict[str, Callable[[float, float, float, float], Iterator[GridPoint]]] = {
    "v1": _generate_v1,
}


def generate_points(
    center_lat: float,
    center_lng: float,
    radius_miles: float = 5.0,
    spacing_miles: float = 1.0,
    version: str = GEOMETRY_VERSION,
) -> list[GridPoint]:
    """The grid for one submarket, ordered by `point_seq`.

    `version` defaults to current for a NEW scan; regenerating a historical snapshot MUST pass
    that snapshot's stored `geometry_version` instead of relying on the default.
    """
    generator = _GENERATORS.get(version)
    if generator is None:
        raise UnknownGeometryVersion(
            f"no generator for geometry_version {version!r} — "
            f"this build has {sorted(_GENERATORS)}"
        )
    return list(generator(center_lat, center_lng, radius_miles, spacing_miles))


def point_count(
    radius_miles: float = 5.0,
    spacing_miles: float = 1.0,
    version: str = GEOMETRY_VERSION,
) -> int:
    """How many points a grid holds, without building it.

    Independent of centre — the clip is on mile offsets, and latitude only stretches the longitude
    step, never the membership. That is what lets `scan_snapshot.expected_points` be known before
    a scan starts, which is what §9a.3's completeness check compares against.
    """
    if version != "v1" and version not in _GENERATORS:
        raise UnknownGeometryVersion(
            f"no generator for geometry_version {version!r} — "
            f"this build has {sorted(_GENERATORS)}"
        )
    # Counted through the generator rather than by a closed form. A closed form would be a second
    # definition of membership, and the two would eventually disagree about a boundary point —
    # at which point expected_points and the actual grid differ by one, every snapshot reads as
    # incomplete, and the cause is a rounding difference in a formula nobody thought was load-bearing.
    return sum(1 for _ in _GENERATORS[version](0.0, 0.0, radius_miles, spacing_miles))

"""Geo-grid geometry for the Maps / local-pack ranker (Module #5).

Pure, vendor-agnostic helpers — no I/O, exhaustively unit-tested. Convert a
client's chosen coverage (a radius around the business + a fixed pin spacing)
into both:

  - the provider's grid parameters (`grid_size` = pins per side, `distance` =
    metres between pins), which is how Local Dominator (and most geo-grid SERP
    APIs) configure a square scan; and
  - the explicit list of pin coordinates (lat/lng per row/col), which we store
    and render as the heatmap regardless of the provider.

Coverage presets (decided with the user): the user picks a 3 / 5 / 7-mile
radius, with a pin every 1 mile, centred on the business location.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

METERS_PER_MILE = 1609.344
# Degrees of latitude per mile (≈ constant); longitude is scaled by cos(lat).
_MILES_PER_DEGREE_LAT = 69.0

# Radius (miles) → the supported coverage presets. Spacing is fixed at 1 mile.
SUPPORTED_RADII_MILES = (3, 5, 7)
PIN_SPACING_MILES = 1.0


@dataclass(frozen=True)
class GridPoint:
    row: int          # 0 = south edge … grid_size-1 = north edge
    col: int          # 0 = west edge … grid_size-1 = east edge
    lat: float
    lng: float
    offset_north_mi: float  # signed miles from the business (north positive)
    offset_east_mi: float   # signed miles from the business (east positive)


def grid_size_for(radius_miles: float, spacing_miles: float = PIN_SPACING_MILES) -> int:
    """Pins per side for a square grid covering ±radius at the given spacing.

    Always odd, so the business sits on the centre pin. e.g. radius 3 @ 1 mi → 7
    (a 7×7 grid: offsets −3..+3 miles); radius 5 → 11; radius 7 → 15.
    """
    if radius_miles <= 0 or spacing_miles <= 0:
        raise ValueError("radius and spacing must be positive")
    half = int(round(radius_miles / spacing_miles))
    return 2 * half + 1


def pin_count_for(radius_miles: float, spacing_miles: float = PIN_SPACING_MILES) -> int:
    """Total pins (= cost driver) for a square grid: grid_size²."""
    n = grid_size_for(radius_miles, spacing_miles)
    return n * n


def distance_meters(spacing_miles: float = PIN_SPACING_MILES) -> int:
    """Provider `distance` param — metres between adjacent pins (rounded)."""
    return round(spacing_miles * METERS_PER_MILE)


def grid_params(radius_miles: float, spacing_miles: float = PIN_SPACING_MILES) -> dict:
    """The provider-facing square-grid params for a coverage preset."""
    return {
        "grid_size": grid_size_for(radius_miles, spacing_miles),
        "distance": distance_meters(spacing_miles),
    }


def generate_grid_points(
    center_lat: float,
    center_lng: float,
    radius_miles: float,
    spacing_miles: float = PIN_SPACING_MILES,
) -> list[GridPoint]:
    """The explicit lat/lng of every pin in the square grid, row-major.

    Uses an equirectangular offset (good to well under a metre at these
    sub-10-mile distances): latitude shifts by miles/69; longitude by
    miles/(69·cos(lat)), so east–west spacing stays a true mile away from the
    equator.
    """
    n = grid_size_for(radius_miles, spacing_miles)
    center_index = n // 2
    deg_lat_per_mile = 1.0 / _MILES_PER_DEGREE_LAT
    cos_lat = math.cos(math.radians(center_lat))
    # Guard the poles (cos → 0); clamp so longitude maths stays finite.
    deg_lng_per_mile = 1.0 / (_MILES_PER_DEGREE_LAT * max(cos_lat, 1e-6))

    points: list[GridPoint] = []
    for row in range(n):
        offset_north_mi = (row - center_index) * spacing_miles
        for col in range(n):
            offset_east_mi = (col - center_index) * spacing_miles
            points.append(
                GridPoint(
                    row=row,
                    col=col,
                    lat=center_lat + offset_north_mi * deg_lat_per_mile,
                    lng=center_lng + offset_east_mi * deg_lng_per_mile,
                    offset_north_mi=offset_north_mi,
                    offset_east_mi=offset_east_mi,
                )
            )
    return points

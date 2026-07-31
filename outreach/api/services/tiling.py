"""Tile fan-out, place_id deduplication, and submarket assignment.

The brief asks for tiling "by submarket centroid with overlapping radii". The Outscraper API has
no radius parameter — `coordinates` sets a search CENTRE and nothing bounds the area (ISSUES
I-017). So a tile is one query per (category x submarket centroid), overlap between adjacent
tiles is real but implicit, and dedup on place_id is what makes the overlap harmless.

The consequence worth stating plainly: coverage completeness is not guaranteed by construction.
The only observable proxy is the overlap rate between tiles — if adjacent tiles return disjoint
sets, the tiling is too sparse and the market has holes in it. `DedupeStats` exists to make that
visible rather than assumed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .outscraper_client import TileRequest
from .parser import ParsedPlace

EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True)
class Submarket:
    id: str
    name: str
    center_lat: float
    center_lng: float


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def build_query(category: str, place: str, region: str = "") -> str:
    """The query text for one tile.

    The region qualifier is not decoration. A calibration pull for "plumber, Downtown Los Angeles"
    with no coordinates and no region returned businesses in JERSEY CITY, NEW JERSEY — Outscraper
    resolves ambiguous place names against its own server location, and most submarket names
    ("Torrance", "Whittier", "Burbank") exist in several states. A market full of the wrong
    state's businesses would look perfectly well-formed and be entirely worthless.
    """
    parts = [category, place]
    if region:
        parts.append(region)
    return ", ".join(parts)


def build_tiles(
    *,
    categories: Sequence[str],
    submarkets: Sequence[Submarket],
    market_name: str,
    region: str = "",
) -> list[TileRequest]:
    """One query per category x submarket centroid.

    Geography is pinned twice, deliberately: `coordinates` biases the search centre, and the
    region qualifier in the query text disambiguates the place name. Neither alone is sufficient
    — the text alone demonstrably lands in the wrong state, and coordinates are a bias rather
    than a bound.
    """
    tiles: list[TileRequest] = []

    for category in categories:
        for submarket in submarkets:
            tiles.append(
                TileRequest(
                    query=build_query(category, submarket.name, region),
                    coordinates=f"{submarket.center_lat},{submarket.center_lng}",
                    submarket_id=submarket.id,
                    label=f"{category} @ {submarket.name}",
                )
            )

    if not submarkets:
        # Degenerate fallback: no submarkets defined means no tiling is possible and the market
        # is pulled as a single query. Google caps a single query area at ~400 results, so this
        # WILL under-cover anything larger than a small town. It exists so the pipeline is
        # runnable for a smoke test, not so a real market can be ingested without submarkets.
        tiles = [
            TileRequest(
                query=build_query(category, market_name, region),
                label=f"{category} @ {market_name}",
            )
            for category in categories
        ]

    return tiles


@dataclass
class DedupeStats:
    total_returned: int = 0
    unique_places: int = 0
    duplicates_dropped: int = 0
    unparseable: int = 0
    per_tile_counts: dict[str, int] = field(default_factory=dict)

    @property
    def overlap_rate(self) -> float:
        """Share of returned rows that were already seen from another tile.

        Near zero across adjacent tiles means the tiling is too sparse to trust as full coverage.
        """
        if self.total_returned == 0:
            return 0.0
        return self.duplicates_dropped / self.total_returned


@dataclass
class DedupedPlace:
    place: ParsedPlace
    first_seen_tile: str
    seen_in_tiles: list[str] = field(default_factory=list)


def dedupe_on_place_id(
    tile_places: Iterable[tuple[TileRequest, list[dict[str, Any]]]],
    *,
    parse: Any,
) -> tuple[dict[str, DedupedPlace], DedupeStats]:
    """Collapse overlapping tiles onto one row per place_id.

    First writer wins for the parsed payload. `seen_in_tiles` keeps the full provenance so the
    overlap is measurable rather than discarded.
    """
    deduped: dict[str, DedupedPlace] = {}
    stats = DedupeStats()

    for tile, places in tile_places:
        label = tile.label or tile.query
        stats.per_tile_counts[label] = len(places)

        for raw in places:
            stats.total_returned += 1
            parsed = parse(raw)

            if parsed is None:
                # No place_id or no name. Never fabricate one — grid results join on place_id,
                # so an invented value silently matches nothing forever.
                stats.unparseable += 1
                continue

            existing = deduped.get(parsed.place_id)
            if existing is None:
                deduped[parsed.place_id] = DedupedPlace(
                    place=parsed, first_seen_tile=label, seen_in_tiles=[label]
                )
            else:
                stats.duplicates_dropped += 1
                if label not in existing.seen_in_tiles:
                    existing.seen_in_tiles.append(label)

    stats.unique_places = len(deduped)
    return deduped, stats


def nearest_submarket(
    lat: float | None, lng: float | None, submarkets: Sequence[Submarket]
) -> str | None:
    """Assign a prospect to the submarket whose centroid is closest.

    Chosen over "the tile that found it" because tile order is an implementation detail — a place
    returned by three overlapping tiles would otherwise get whichever one happened to be polled
    first, and re-running the ingest could reassign it. Nearest-centroid is deterministic and
    depends only on geometry, which is immutable (ISSUES I-021).
    """
    if lat is None or lng is None or not submarkets:
        return None

    return min(
        submarkets,
        key=lambda s: haversine_miles(lat, lng, s.center_lat, s.center_lng),
    ).id

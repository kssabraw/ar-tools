"""Define markets, submarkets and keywords from a JSON definition file.

This is a multi-market system, not a one-off. A market-vertical is defined in
`outreach/markets/<slug>.json`, checked into the repo, and applied idempotently — so adding the
tenth city is the same act as adding the first, and the definitions are reviewable in a diff.

THE IMMUTABILITY INVARIANT IS ENFORCED HERE, NOT JUST DOCUMENTED.

Grid geometry (a submarket's centre, radius, spacing) is immutable once scanning begins. Changing
it invalidates every prior snapshot for that submarket and resets its delta history — which is
the single most expensive mistake available in this codebase, because it destroys data that took
months of cycles to accumulate and cannot be recomputed. `seed_market` refuses a geometry change
to any submarket that has been scanned, and requires an explicit override flag to touch one that
has not.

Names are editable. Always. A name is a label on the query text, not a coordinate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger(__name__)

# Fields whose change invalidates history. Everything else about a submarket is editable.
GEOMETRY_FIELDS: tuple[str, ...] = (
    "center_lat",
    "center_lng",
    "grid_radius_miles",
    "grid_spacing_miles",
)


class GeometryLocked(RuntimeError):
    """A scanned submarket's geometry cannot be changed. Create a new submarket instead."""


@dataclass
class SubmarketDefinition:
    name: str
    center_lat: float
    center_lng: float
    grid_radius_miles: float = 5.0
    grid_spacing_miles: float = 1.0

    def geometry(self) -> dict[str, float]:
        return {f: float(getattr(self, f)) for f in GEOMETRY_FIELDS}


@dataclass
class MarketDefinition:
    name: str
    center_lat: float
    center_lng: float
    radius_miles: float
    # Outscraper query categories for the base pull. NOT the same thing as `keyword`, even when
    # the strings coincide: categories drive the Stage A1 listing pull, keywords drive Phase 2
    # SERP and geogrid scanning. Keeping them separate costs one JSON key and avoids a conflation
    # that would be painful to unpick later.
    categories: list[str] = field(default_factory=list)
    keywords: list[dict[str, Any]] = field(default_factory=list)
    submarkets: list[SubmarketDefinition] = field(default_factory=list)
    scan_interval_days: int = 15

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MarketDefinition":
        return cls(
            name=data["name"],
            center_lat=float(data["center_lat"]),
            center_lng=float(data["center_lng"]),
            radius_miles=float(data["radius_miles"]),
            categories=list(data.get("categories", [])),
            keywords=list(data.get("keywords", [])),
            submarkets=[SubmarketDefinition(**s) for s in data.get("submarkets", [])],
            scan_interval_days=int(data.get("scan_interval_days", 15)),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "MarketDefinition":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def validate_definition(definition: MarketDefinition) -> list[str]:
    """Cheap sanity checks. Returns problems; empty means fine.

    Deliberately catches the two mistakes that are expensive rather than every mistake that is
    possible: coordinates that are obviously wrong, and submarkets that do not sit inside the
    market they claim to belong to.
    """
    problems: list[str] = []

    if not definition.categories:
        problems.append("no categories — Stage A1 would have nothing to query")

    if not -90 <= definition.center_lat <= 90 or not -180 <= definition.center_lng <= 180:
        problems.append(f"market centre out of range: {definition.center_lat},{definition.center_lng}")

    if not definition.submarkets:
        problems.append(
            "no submarkets — the tiler degrades to one query per category, which Google caps "
            "at ~400 results and which will silently under-cover anything larger than a town"
        )

    seen: set[str] = set()
    for sub in definition.submarkets:
        if sub.name.strip().lower() in seen:
            problems.append(f"duplicate submarket name: {sub.name}")
        seen.add(sub.name.strip().lower())

        if not -90 <= sub.center_lat <= 90 or not -180 <= sub.center_lng <= 180:
            problems.append(f"submarket {sub.name}: centre out of range")
            continue

        # Imported lazily to keep this module free of the tiling dependency at import time.
        from .tiling import haversine_miles

        distance = haversine_miles(
            definition.center_lat, definition.center_lng, sub.center_lat, sub.center_lng
        )
        if distance > definition.radius_miles + sub.grid_radius_miles:
            problems.append(
                f"submarket {sub.name} sits {distance:.1f} miles from the market centre, "
                f"outside the {definition.radius_miles}-mile market radius — check the coordinates"
            )

    return problems


def geometry_diff(existing: dict[str, Any], incoming: SubmarketDefinition) -> dict[str, tuple]:
    """Which geometry fields differ, as {field: (old, new)}. Empty means identical."""
    wanted = incoming.geometry()
    changed: dict[str, tuple] = {}

    for field_name, new_value in wanted.items():
        old_value = existing.get(field_name)
        if old_value is None:
            continue
        if abs(float(old_value) - new_value) > 1e-9:
            changed[field_name] = (float(old_value), new_value)

    return changed


def check_geometry_change(
    existing: dict[str, Any], incoming: SubmarketDefinition, *, allow_unscanned_change: bool
) -> dict[str, tuple]:
    """Decide whether a geometry change may proceed.

    Raises GeometryLocked when the submarket has been scanned. A scanned submarket's geometry is
    load-bearing for every snapshot taken against it; the correct move is a NEW submarket, which
    starts its own history, not an edit that silently orphans the old one.
    """
    changed = geometry_diff(existing, incoming)
    if not changed:
        return {}

    scanned = existing.get("last_scanned_at") is not None
    summary = ", ".join(f"{f}: {old} -> {new}" for f, (old, new) in changed.items())

    if scanned:
        raise GeometryLocked(
            f"submarket {existing.get('name')!r} has been scanned "
            f"(last_scanned_at={existing.get('last_scanned_at')}) and its geometry is immutable. "
            f"Refused: {summary}. Every prior snapshot for this submarket is measured against "
            f"the current geometry, and changing it resets delta history. Create a new submarket "
            f"instead."
        )

    if not allow_unscanned_change:
        raise GeometryLocked(
            f"submarket {existing.get('name')!r} geometry would change ({summary}) and it has "
            f"not been scanned yet, so this is still safe — but it must be deliberate. "
            f"Re-run with allow_geometry_change=True to proceed."
        )

    logger.warning(
        "changing geometry of an unscanned submarket",
        extra={"submarket": existing.get("name"), "changes": summary},
    )
    return changed


@dataclass
class SeedReport:
    market_id: str
    market_created: bool = False
    submarkets_created: int = 0
    submarkets_updated: int = 0
    keywords_upserted: int = 0
    geometry_changes: dict[str, dict] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def seed_market(
    client: Any,
    definition: MarketDefinition,
    *,
    allow_geometry_change: bool = False,
) -> SeedReport:
    """Apply a market definition idempotently. Safe to re-run; refuses unsafe geometry edits."""
    problems = validate_definition(definition)
    if any("out of range" in p for p in problems):
        raise ValueError(f"invalid market definition: {problems}")

    # -- market ---------------------------------------------------------------------------
    existing = (
        client.table("market").select("*").eq("name", definition.name).limit(1).execute().data
    )

    market_payload = {
        "name": definition.name,
        "center_lat": definition.center_lat,
        "center_lng": definition.center_lng,
        "radius_miles": definition.radius_miles,
        "scan_interval_days": definition.scan_interval_days,
    }

    if existing:
        market_id = existing[0]["id"]
        client.table("market").update(market_payload).eq("id", market_id).execute()
        report = SeedReport(market_id=market_id, problems=problems)
    else:
        created = client.table("market").insert(market_payload).execute().data[0]
        market_id = created["id"]
        report = SeedReport(market_id=market_id, market_created=True, problems=problems)

    # -- submarkets -----------------------------------------------------------------------
    current = (
        client.table("submarket").select("*").eq("market_id", market_id).execute().data or []
    )
    by_name = {row["name"].strip().lower(): row for row in current}

    for sub in definition.submarkets:
        key = sub.name.strip().lower()
        row = by_name.get(key)

        if row is None:
            client.table("submarket").insert(
                {"market_id": market_id, "name": sub.name, **sub.geometry()}
            ).execute()
            report.submarkets_created += 1
            continue

        changed = check_geometry_change(
            row, sub, allow_unscanned_change=allow_geometry_change
        )
        if changed:
            report.geometry_changes[sub.name] = changed
            client.table("submarket").update(sub.geometry()).eq("id", row["id"]).execute()
            report.submarkets_updated += 1

    # -- keywords -------------------------------------------------------------------------
    # Nothing reads these until Phase 2 scanning; they are defined now so the market definition
    # is complete in one place (ISSUES I-023).
    keyword_rows = [
        {
            "market_id": market_id,
            "term": k["term"] if isinstance(k, dict) else str(k),
            "is_primary": bool(k.get("is_primary", False)) if isinstance(k, dict) else False,
        }
        for k in definition.keywords
    ]
    if keyword_rows:
        client.table("keyword").upsert(keyword_rows, on_conflict="market_id,term").execute()
        report.keywords_upserted = len(keyword_rows)

    for problem in problems:
        logger.warning("market definition warning", extra={"market": definition.name, "problem": problem})

    return report


def load_definitions(directory: str | Path) -> list[tuple[Path, MarketDefinition]]:
    """Every market definition in a directory, sorted by filename."""
    return [
        (path, MarketDefinition.from_file(path))
        for path in sorted(Path(directory).glob("*.json"))
    ]


def submarket_rows_to_tiling(rows: Sequence[dict[str, Any]]) -> list:
    """Adapt stored submarket rows into the tiler's Submarket objects."""
    from .tiling import Submarket

    return [
        Submarket(
            id=row["id"],
            name=row["name"],
            center_lat=float(row["center_lat"]),
            center_lng=float(row["center_lng"]),
        )
        for row in rows
    ]

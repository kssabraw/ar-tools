"""Market definition tests — mostly the geometry immutability guard.

Changing a scanned submarket's geometry destroys delta history that took months of cycles to
accumulate and cannot be recomputed. It is the most expensive mistake available in this codebase,
so the guard gets more test attention than the happy path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.services.seeding import (  # noqa: E402
    GeometryLocked,
    MarketDefinition,
    SubmarketDefinition,
    check_geometry_change,
    geometry_diff,
    validate_definition,
)


def sub(**overrides) -> SubmarketDefinition:
    base = dict(name="Overland Park", center_lat=38.9822, center_lng=-94.6708)
    base.update(overrides)
    return SubmarketDefinition(**base)


def existing_row(scanned: bool = False, **overrides) -> dict:
    row = {
        "id": "sm-1",
        "name": "Overland Park",
        "center_lat": 38.9822,
        "center_lng": -94.6708,
        "grid_radius_miles": 5.0,
        "grid_spacing_miles": 1.0,
        "last_scanned_at": "2026-07-15T00:00:00Z" if scanned else None,
    }
    row.update(overrides)
    return row


def market(**overrides) -> MarketDefinition:
    base = dict(
        name="Kansas City, MO — Plumbing",
        center_lat=39.0997,
        center_lng=-94.5786,
        radius_miles=25,
        categories=["plumber"],
        submarkets=[sub()],
    )
    base.update(overrides)
    return MarketDefinition(**base)


# --- geometry immutability ---------------------------------------------------------------


def test_identical_geometry_is_not_a_change():
    assert geometry_diff(existing_row(), sub()) == {}
    assert check_geometry_change(existing_row(scanned=True), sub(), allow_unscanned_change=False) == {}


def test_scanned_submarket_refuses_a_centre_change():
    with pytest.raises(GeometryLocked, match="immutable"):
        check_geometry_change(
            existing_row(scanned=True), sub(center_lat=38.99), allow_unscanned_change=False
        )


def test_scanned_submarket_refuses_even_with_the_override():
    """The override exists for UNSCANNED submarkets. It must not unlock a scanned one — there is
    no flag that makes destroying delta history acceptable; the answer is a new submarket."""
    with pytest.raises(GeometryLocked, match="immutable"):
        check_geometry_change(
            existing_row(scanned=True), sub(grid_radius_miles=7), allow_unscanned_change=True
        )


@pytest.mark.parametrize(
    "change",
    [
        {"center_lat": 38.99},
        {"center_lng": -94.60},
        {"grid_radius_miles": 7},
        {"grid_spacing_miles": 0.5},
    ],
)
def test_every_geometry_field_is_locked_after_scanning(change):
    with pytest.raises(GeometryLocked):
        check_geometry_change(
            existing_row(scanned=True), sub(**change), allow_unscanned_change=False
        )


def test_unscanned_submarket_requires_an_explicit_override():
    with pytest.raises(GeometryLocked, match="must be deliberate"):
        check_geometry_change(
            existing_row(scanned=False), sub(center_lat=38.99), allow_unscanned_change=False
        )


def test_unscanned_submarket_change_proceeds_with_the_override():
    changed = check_geometry_change(
        existing_row(scanned=False), sub(center_lat=38.99), allow_unscanned_change=True
    )
    assert "center_lat" in changed
    assert changed["center_lat"] == (38.9822, 38.99)


def test_renaming_is_never_blocked():
    """Names are a label on the query text, not a coordinate. Always editable."""
    renamed = sub(name="Overland Park South")
    assert check_geometry_change(
        existing_row(scanned=True), renamed, allow_unscanned_change=False
    ) == {}


# --- validation ---------------------------------------------------------------------------


def test_a_well_formed_market_has_no_problems():
    assert validate_definition(market()) == []


def test_missing_categories_is_flagged():
    assert any("categories" in p for p in validate_definition(market(categories=[])))


def test_missing_submarkets_is_flagged():
    problems = validate_definition(market(submarkets=[]))
    assert any("no submarkets" in p for p in problems)


def test_submarket_far_outside_the_market_is_flagged():
    """A transposed sign or a digit slip puts a submarket in another state. Cheap to catch here,
    expensive to notice after a paid pull returns nothing recognisable."""
    stray = sub(name="Wrong State", center_lat=34.0522, center_lng=-118.2437)  # Los Angeles
    problems = validate_definition(market(submarkets=[stray]))
    assert any("outside the" in p for p in problems)


def test_duplicate_submarket_names_are_flagged():
    problems = validate_definition(market(submarkets=[sub(), sub()]))
    assert any("duplicate" in p for p in problems)


def test_out_of_range_coordinates_are_flagged():
    assert any("out of range" in p for p in validate_definition(market(center_lat=200)))


# --- file loading -------------------------------------------------------------------------


def test_the_example_definition_parses_and_validates():
    path = Path(__file__).resolve().parents[2] / "markets" / "EXAMPLE-kansas-city-plumbing.json"
    definition = MarketDefinition.from_file(path)

    assert definition.categories
    assert len(definition.submarkets) == 8
    assert validate_definition(definition) == []


def test_defaults_are_applied_for_omitted_geometry(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(
        json.dumps(
            {
                "name": "M",
                "center_lat": 39.0,
                "center_lng": -94.0,
                "radius_miles": 25,
                "categories": ["plumber"],
                "submarkets": [{"name": "S", "center_lat": 39.0, "center_lng": -94.0}],
            }
        )
    )
    definition = MarketDefinition.from_file(path)
    assert definition.submarkets[0].grid_radius_miles == 5.0
    assert definition.submarkets[0].grid_spacing_miles == 1.0
    assert definition.scan_interval_days == 15

"""Unit tests for octant-based hyper-local GBP pin selection (pure, no I/O)."""

from __future__ import annotations

import math

from services import maps_octants
from services.maps_octants import (
    EDGE_SPREAD_DEG,
    MIN_DISTANCE_M,
    dest_point,
    haversine_meters,
    select_octant_pins,
)

CENTER = {"lat": 40.0, "lng": -74.0}

# Base bearing per octant (no azimuth offset).
_BASE_BEARING = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}


def _sector(name, *, cells, ranked, top3=0, top10=0, gt10=0, avg_rank=None,
            cov3=0.0, cov10=0.0):
    return {
        "sector": name, "cells": cells, "ranked": ranked, "top3": top3,
        "top10": top10, "gt10": gt10, "avg_rank": avg_rank,
        "coverage_pct_top3": cov3, "coverage_pct_top10": cov10,
    }


def _overall(name, *, cells, ranked, top3=0, top10=0, gt10=0, avg_rank=None,
             cov3=0.0, cov10=0.0):
    return {
        "sector": name, "cells": cells, "ranked": ranked,
        "not_ranked": cells - ranked, "top3": top3, "top10": top10,
        "gt10": gt10, "avg_rank": avg_rank,
        "coverage_pct_top3": cov3, "coverage_pct_top10": cov10,
    }


def make_heatmap():
    """3 rings × 8 sectors. SW/SE/W/NW clearly WEAK; N/NE strong; E/S MED-ish."""
    # WEAK octants: ranked=0 (SW, W) or gt10>0 / avg>=11 (SE, NW).
    weak_unranked = lambda n: _sector(n, cells=4, ranked=0)            # WEAK (ranked==0)
    weak_gt10 = lambda n: _sector(n, cells=4, ranked=3, top10=1, gt10=2, avg_rank=14)  # WEAK
    strong = lambda n: _sector(n, cells=4, ranked=4, top3=4, top10=4, avg_rank=1.5)    # strong→None
    med = lambda n: _sector(n, cells=4, ranked=4, top3=1, top10=2, avg_rank=6)         # MED

    def ring_sectors():
        return [
            strong("N"), strong("NE"),
            med("E"), med("S"),
            weak_unranked("SW"), weak_gt10("SE"),
            weak_unranked("W"), weak_gt10("NW"),
        ]

    ring_summaries = []
    for ring, radius in ((1, 1609.0), (2, 3218.0), (3, 4827.0)):
        ring_summaries.append({
            "ring": ring, "radius_m": radius,
            "radius_mi": round(radius / 1609.344, 2),
            "cells": 32, "ranked": 16, "top3": 8, "top10": 12, "gt10": 4,
            "avg_rank": 7.0, "coverage_pct_top3": 25.0, "coverage_pct_top10": 37.5,
            "sectors": ring_sectors(),
        })

    # sectors_overall — weakness order driven by coverage_pct_top3 (asc).
    # Weakest top3 coverage to strongest: SW/W (0), SE/NW (5), E/S (25), N/NE (90).
    sectors_overall = [
        _overall("N", cells=12, ranked=12, top3=11, top10=12, cov3=90.0, cov10=100.0),
        _overall("NE", cells=12, ranked=12, top3=10, top10=12, cov3=90.0, cov10=100.0),
        _overall("E", cells=12, ranked=12, top3=3, top10=6, cov3=25.0, cov10=50.0),
        _overall("S", cells=12, ranked=12, top3=3, top10=6, cov3=25.0, cov10=50.0),
        _overall("SE", cells=12, ranked=9, top3=1, top10=3, gt10=6, avg_rank=14, cov3=5.0, cov10=25.0),
        _overall("SW", cells=12, ranked=0, top3=0, top10=0, cov3=0.0, cov10=0.0),
        _overall("W", cells=12, ranked=0, top3=0, top10=0, cov3=0.0, cov10=0.0),
        _overall("NW", cells=12, ranked=9, top3=1, top10=3, gt10=6, avg_rank=14, cov3=5.0, cov10=25.0),
    ]

    return {
        "center": dict(CENTER),
        "azimuth_offset_deg": 0,
        "ring_summaries": ring_summaries,
        "sectors_overall": sectors_overall,
    }


def _bearing_within_spread(octant, bearing):
    base = _BASE_BEARING[octant]
    diff = abs((bearing - base + 180) % 360 - 180)
    return diff <= EDGE_SPREAD_DEG + 1e-6


# ---------------------------------------------------------------------------
# 1. R1 — 4-octants
# ---------------------------------------------------------------------------
def test_r1_four_octants():
    hm = make_heatmap()
    res = select_octant_pins(hm, "R1")
    assert res["ok"] is True
    assert len(res["points"]) == 4
    octs = [p["octant"] for p in res["points"]]
    assert len(set(octs)) == 4  # 4 distinct octants
    for p in res["points"]:
        assert isinstance(p["lat"], float) and isinstance(p["lng"], float)
        assert _bearing_within_spread(p["octant"], p["bearing_deg"])
    # Weakest octants (SW, W, then SE/NW) should be chosen first.
    assert "SW" in octs and "W" in octs
    assert res["debug"]["ruleBehavior"] == "4-octants"


# ---------------------------------------------------------------------------
# 2. R5 — 2-far-apart
# ---------------------------------------------------------------------------
def test_r5_two_far_apart():
    hm = make_heatmap()
    res = select_octant_pins(hm, "R5")
    assert res["ok"] is True
    assert len(res["points"]) == 2
    a, b = res["points"]
    dist = haversine_meters(a, b)
    assert dist >= MIN_DISTANCE_M
    assert res["debug"]["pair_distance_m"] is not None
    assert res["debug"]["pair_distance_m"] >= MIN_DISTANCE_M


# ---------------------------------------------------------------------------
# 3. R8 — none
# ---------------------------------------------------------------------------
def test_r8_none():
    hm = make_heatmap()
    res = select_octant_pins(hm, "R8")
    assert res["ok"] is True
    assert res["points"] == []
    assert "0 coordinates" in res["reason"]
    assert res["debug"]["ruleBehavior"] == "none"


# ---------------------------------------------------------------------------
# 4. External weak override (restrict)
# ---------------------------------------------------------------------------
def test_external_weak_restrict_abbr():
    hm = make_heatmap()
    res = select_octant_pins(hm, "R1", weak_octants=["SW", "SE"])
    assert res["ok"] is True
    assert res["debug"]["external_weak_applied"] is True
    for p in res["points"]:
        assert p["octant"] in {"SW", "SE"}


def test_external_weak_full_names_nested_mixed_case():
    hm = make_heatmap()
    res = select_octant_pins(
        hm, "R1", weak_octants_full=[["Southwest", "southeast"]]
    )
    assert res["ok"] is True
    assert res["debug"]["external_weak_applied"] is True
    assert res["debug"]["external_weak_octants"] == ["SW", "SE"]
    for p in res["points"]:
        assert p["octant"] in {"SW", "SE"}


# ---------------------------------------------------------------------------
# 5. Guard branches
# ---------------------------------------------------------------------------
def test_missing_center():
    res = select_octant_pins({"ring_summaries": []}, "R1")
    assert res["ok"] is False
    assert res["points"] == []
    assert res["reason"] == "Missing/invalid heatmap center"


def test_missing_rule_code():
    hm = make_heatmap()
    res = select_octant_pins(hm, "")
    assert res["ok"] is False
    assert res["points"] == []
    assert res["used_rule"] is None
    assert "rule_code is required" in res["reason"]


# ---------------------------------------------------------------------------
# 6. Geometry sanity
# ---------------------------------------------------------------------------
def test_dest_point_one_mile_away():
    dp = dest_point(CENTER["lat"], CENTER["lng"], 45.0, 1609.0)
    dist = haversine_meters(CENTER, dp)
    assert math.isclose(dist, 1609.0, abs_tol=5.0)
    assert isinstance(dp["lat"], float) and isinstance(dp["lng"], float)

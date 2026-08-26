"""LeadOff GBP Placement Advisor — the demand-aware "where should the GBP live"
pure core (plan: docs/modules/leadoff-gbp-placement-plan-v1_0.md §3/§6).

The gravity read the competition-only proximity signal is missing: an octant can
be empty of ranked competitors because it is empty of *people*. Placement quality
is `reachable demand ÷ nearby competitive pressure` — for a candidate point `c`:

    demand_access(c)   = Σ_bg  households(bg) × demand_multiplier(bg) × 1/(1 + d(c,bg)/D_DEMAND)
    pressure(c)        = Σ_pin max(reviews,1)                        × 1/(1 + d(c,pin)/D_DECAY)
    placement_score(c) = 100 × norm(demand_access) × (1 − norm(pressure))

`1/(1+d/2mi)` decay + `max(reviews,1)` weighting are VERBATIM the proximity
plan's §1.2 formula — one vocabulary, one calibration story. `norm()` is min-max
over the market's OWN candidate lattice, so a score is market-relative (like
Rankability) and NEVER comparable across markets — the UI must say so.

This module is a PURE, input-agnostic core (zero imports from impure LeadOff
modules), so the post-client geo-grid stack can later feed it geo-grid + client
data by import, not port. Geometry + the 1-mile lattice are reused from the
existing pure helpers (`leadoff_proximity.haversine_miles`, `maps_grid`).

Honesty guards live with the caller (thin-data floors, market-relative copy,
real-staffed-location wording, no dollars in v1 — plan §7); this file only does
the deterministic math and the narrative lines.
"""
from __future__ import annotations

from typing import Any, Optional

from services.leadoff_proximity import haversine_miles
from services.maps_grid import PIN_SPACING_MILES, generate_grid_points

# The demand-side decay is intentionally larger than the pressure decay:
# customers travel farther than pack-proximity reaches. Both are config knobs
# (plan §10); these defaults match config.py so the pure core is usable
# stand-alone (tests) without importing settings.
_DEFAULT_DEMAND_DECAY_MILES = 5.0
_DEFAULT_PRESSURE_DECAY_MILES = 2.0     # locked to proximity's §1.2 decay
# Legible "households reachable" catchment for the zone card (unweighted count
# of block groups whose centroid sits within this radius of the zone).
_HOUSEHOLDS_CATCHMENT_MILES = 5.0


# ── Small pure helpers ────────────────────────────────────────────────────────

def _minmax_norm(x: float, lo: float, hi: float) -> float:
    """Min-max to [0,1]; a flat distribution (hi<=lo) maps everything to 0 —
    no point stands out, so no point scores demand/relief on that axis."""
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


def _old_housing_share(bg: dict[str, Any]) -> float:
    """Share of housing units built before 1980 from the B25034 buckets
    (pre-1980 = an older stock → more roof/plumbing/chimney work). 0 when the
    buckets are absent/empty. The bucket keys are the ACS variable names."""
    buckets = bg.get("housing_age") or {}
    if not isinstance(buckets, dict):
        return 0.0
    total = 0
    old = 0
    for key, raw in buckets.items():
        try:
            v = int(raw)
        except (TypeError, ValueError):
            continue
        if v < 0:            # ACS jam/no-data sentinels
            continue
        if key.upper().endswith("_001E"):   # the bucket total, not a bucket
            continue
        total += v
        # pre-1980 buckets: _007E (1970-79) … _011E (1939 or earlier)
        num = _bucket_number(key)
        if num is not None and 7 <= num <= 11:
            old += v
    return (old / total) if total > 0 else 0.0


def _bucket_number(key: str) -> Optional[int]:
    """'B25034_007E' → 7; None when unparseable."""
    try:
        return int(key.split("_")[1][:3])
    except (IndexError, ValueError):
        return None


# ── Demand surface (pre-computes each block group's household weight) ──────────

def build_demand_surface(blockgroups: list[dict[str, Any]], *,
                         income_weight: float = 0.0,
                         housing_age_weight: float = 0.0) -> list[dict[str, Any]]:
    """Attach a `weighted_households` figure to every block group with a valid
    centroid + household count. `demand_multiplier` = 1 + income_weight·norm(income)
    + housing_age_weight·norm(old-housing-share), min-max normalized across the
    market's own block groups.

    With BOTH weights 0 (the v1 default until calibration, plan §3), the
    multiplier is EXACTLY 1.0 for every block group, so the surface is pure
    households — a property the parity test pins.
    """
    valid = [bg for bg in blockgroups
             if bg.get("lat") is not None and bg.get("lng") is not None
             and (bg.get("households") or 0) > 0]
    if not valid:
        return []

    use_income = income_weight != 0
    use_age = housing_age_weight != 0
    incomes = [bg.get("median_income") for bg in valid
               if bg.get("median_income") is not None] if use_income else []
    inc_lo, inc_hi = (min(incomes), max(incomes)) if incomes else (0.0, 0.0)
    if use_age:
        for bg in valid:
            bg["_old_share"] = _old_housing_share(bg)
        shares = [bg["_old_share"] for bg in valid]
        age_lo, age_hi = min(shares), max(shares)
    else:
        age_lo = age_hi = 0.0

    out: list[dict[str, Any]] = []
    for bg in valid:
        mult = 1.0
        if use_income and bg.get("median_income") is not None:
            mult += income_weight * _minmax_norm(
                float(bg["median_income"]), inc_lo, inc_hi)
        if use_age:
            mult += housing_age_weight * _minmax_norm(
                bg.get("_old_share", 0.0), age_lo, age_hi)
        out.append({
            "geoid": bg.get("geoid"),
            "lat": float(bg["lat"]),
            "lng": float(bg["lng"]),
            "households": int(bg["households"]),
            "weighted_households": int(bg["households"]) * mult,
            "demand_multiplier": round(mult, 4),
        })
    return out


# ── The two gravity sums (pure) ───────────────────────────────────────────────

def demand_access(lat: float, lng: float, surface: list[dict[str, Any]],
                  decay_miles: float) -> float:
    """Σ weighted_households × 1/(1 + d/D_DEMAND) over the demand surface."""
    total = 0.0
    for bg in surface:
        d = haversine_miles(lat, lng, bg["lat"], bg["lng"])
        total += bg["weighted_households"] * (1.0 / (1.0 + d / decay_miles))
    return total


def pressure(lat: float, lng: float, pins: list[dict[str, Any]],
             decay_miles: float) -> float:
    """Σ max(reviews,1) × 1/(1 + d/D_DECAY) over the competitor GBP pins —
    review-weighted prominence, distance-decayed (proximity §1.2, verbatim)."""
    total = 0.0
    for p in pins:
        lat2, lng2 = p.get("lat"), p.get("lng")
        if lat2 is None or lng2 is None:
            continue
        d = haversine_miles(lat, lng, float(lat2), float(lng2))
        reviews = max(int(p.get("review_count") or p.get("reviews") or 0), 1)
        total += reviews * (1.0 / (1.0 + d / decay_miles))
    return total


def households_within(lat: float, lng: float, surface: list[dict[str, Any]],
                      miles: float) -> int:
    """Legible catchment number for a card: unweighted households whose block-
    group centroid sits within `miles` of the point."""
    return sum(bg["households"] for bg in surface
               if haversine_miles(lat, lng, bg["lat"], bg["lng"]) <= miles)


def nearest_competitor_miles(lat: float, lng: float,
                             pins: list[dict[str, Any]]) -> Optional[float]:
    """Distance to the closest competitor GBP, or None when the field is empty."""
    ds = [haversine_miles(lat, lng, float(p["lat"]), float(p["lng"]))
          for p in pins if p.get("lat") is not None and p.get("lng") is not None]
    return round(min(ds), 1) if ds else None


# ── Grid scoring (the candidate lattice) ──────────────────────────────────────

def score_grid(center_lat: float, center_lng: float,
               surface: list[dict[str, Any]], pins: list[dict[str, Any]], *,
               radius_miles: float,
               spacing_miles: float = PIN_SPACING_MILES,
               demand_decay_miles: float = _DEFAULT_DEMAND_DECAY_MILES,
               pressure_decay_miles: float = _DEFAULT_PRESSURE_DECAY_MILES,
               ) -> dict[str, Any]:
    """Score every cell of the centred 1-mile lattice over the analysis radius.

    Returns {cells, norm} where each cell carries its raw sums, the market-
    relative normalized components, and the 0-100 placement score; `norm` is the
    min-max context (the market's demand/pressure extremes) so `score_point` can
    place an arbitrary point on the SAME scale.
    """
    points = generate_grid_points(center_lat, center_lng, radius_miles,
                                  spacing_miles)
    raw = []
    for pt in points:
        da = demand_access(pt.lat, pt.lng, surface, demand_decay_miles)
        pr = pressure(pt.lat, pt.lng, pins, pressure_decay_miles)
        raw.append((pt, da, pr))

    das = [r[1] for r in raw]
    prs = [r[2] for r in raw]
    da_lo, da_hi = min(das), max(das)
    pr_lo, pr_hi = min(prs), max(prs)

    cells = []
    for pt, da, pr in raw:
        nd = _minmax_norm(da, da_lo, da_hi)
        npr = _minmax_norm(pr, pr_lo, pr_hi)
        cells.append({
            "row": pt.row, "col": pt.col,
            "lat": round(pt.lat, 6), "lng": round(pt.lng, 6),
            "demand_access": round(da, 2),
            "pressure": round(pr, 2),
            "demand_norm": round(nd, 4),
            "pressure_norm": round(npr, 4),
            "score": round(100 * nd * (1 - npr), 1),
        })
    return {
        "cells": cells,
        "norm": {"demand_lo": da_lo, "demand_hi": da_hi,
                 "pressure_lo": pr_lo, "pressure_hi": pr_hi,
                 "demand_decay_miles": demand_decay_miles,
                 "pressure_decay_miles": pressure_decay_miles},
    }


def score_point(lat: float, lng: float, surface: list[dict[str, Any]],
                pins: list[dict[str, Any]], grid: dict[str, Any]) -> dict[str, Any]:
    """Score one arbitrary point (dropped pin / pasted address) on the market's
    scale, with its percentile vs the cell-score distribution, the nearest
    competitor, and its reachable-household catchment. Pure — takes the already
    computed `grid` so it uses the SAME normalization constants as the zones."""
    nrm = grid["norm"]
    da = demand_access(lat, lng, surface, nrm["demand_decay_miles"])
    pr = pressure(lat, lng, pins, nrm["pressure_decay_miles"])
    nd = _minmax_norm(da, nrm["demand_lo"], nrm["demand_hi"])
    npr = _minmax_norm(pr, nrm["pressure_lo"], nrm["pressure_hi"])
    score = round(100 * nd * (1 - npr), 1)

    cell_scores = [c["score"] for c in grid["cells"]]
    at_or_below = sum(1 for s in cell_scores if s <= score)
    percentile = round(100 * at_or_below / len(cell_scores)) if cell_scores else None

    return {
        "lat": round(lat, 6), "lng": round(lng, 6),
        "score": score,
        "percentile": percentile,
        "demand_norm": round(nd, 4),
        "pressure_norm": round(npr, 4),
        "households_reachable": households_within(
            lat, lng, surface, _HOUSEHOLDS_CATCHMENT_MILES),
        "nearest_competitor_miles": nearest_competitor_miles(lat, lng, pins),
    }


# ── Zone selection + narrative ────────────────────────────────────────────────

def select_zones(cells: list[dict[str, Any]], *, zone_count: int,
                 min_separation_miles: float) -> list[dict[str, Any]]:
    """Greedy top-N cells with a minimum-separation spacing so two adjacent cells
    don't both surface — a neighborhood-sized answer, not a cluster of pins
    (owner ruling 2026-08-25). Highest score first; a candidate is skipped when
    it sits within `min_separation_miles` of an already-chosen zone."""
    ordered = sorted(cells, key=lambda c: -c["score"])
    chosen: list[dict[str, Any]] = []
    for c in ordered:
        if c["score"] <= 0:
            break
        if all(haversine_miles(c["lat"], c["lng"], z["lat"], z["lng"])
               >= min_separation_miles for z in chosen):
            chosen.append(c)
            if len(chosen) >= zone_count:
                break
    return chosen


def zone_narrative(zone: dict[str, Any]) -> str:
    """Plain-English placement line for a zone card (pure). Names the reachable
    demand + the competitive read; the locality name is added by the caller
    after reverse-geocoding, so this stays input-agnostic."""
    hh = zone.get("households_reachable")
    near = zone.get("nearest_competitor_miles")
    parts = [f"Scores {zone['score']:g}/100 here (best in this market)."
             if zone.get("is_top")
             else f"Scores {zone['score']:g}/100 here."]
    if hh:
        parts.append(f"≈{hh:,} households within "
                     f"{int(_HOUSEHOLDS_CATCHMENT_MILES)} miles.")
    npr = zone.get("pressure_norm")
    if npr is not None:
        band = ("light" if npr < 0.34 else "moderate" if npr < 0.67 else "heavy")
        tail = f"Competitive pressure is {band}"
        if near is not None:
            tail += f" — nearest competitor {near:g} mi away"
        parts.append(tail + ".")
    return " ".join(parts)


def build_zones(center_lat: float, center_lng: float,
                surface: list[dict[str, Any]], pins: list[dict[str, Any]], *,
                radius_miles: float,
                spacing_miles: float = PIN_SPACING_MILES,
                demand_decay_miles: float = _DEFAULT_DEMAND_DECAY_MILES,
                pressure_decay_miles: float = _DEFAULT_PRESSURE_DECAY_MILES,
                zone_count: int = 4,
                min_separation_miles: float = 2.0) -> dict[str, Any]:
    """The full pure pipeline: score the lattice → pick spaced zones → enrich each
    with its reachable households, nearest competitor, and narrative line. The
    caller (impure) reverse-geocodes each zone's `lat/lng` to a locality name and
    drops zones that name to nothing (water/unpopulated land)."""
    grid = score_grid(center_lat, center_lng, surface, pins,
                      radius_miles=radius_miles, spacing_miles=spacing_miles,
                      demand_decay_miles=demand_decay_miles,
                      pressure_decay_miles=pressure_decay_miles)
    zones = select_zones(grid["cells"], zone_count=zone_count,
                         min_separation_miles=min_separation_miles)
    for i, z in enumerate(zones):
        z["rank"] = i + 1
        z["is_top"] = i == 0
        z["households_reachable"] = households_within(
            z["lat"], z["lng"], surface, _HOUSEHOLDS_CATCHMENT_MILES)
        z["nearest_competitor_miles"] = nearest_competitor_miles(
            z["lat"], z["lng"], pins)
        z["narrative"] = zone_narrative(z)
    return {
        "zones": zones,
        "grid": grid,
        "block_groups": len(surface),
        "pins": len(pins),
        "radius_miles": radius_miles,
        "catchment_miles": _HOUSEHOLDS_CATCHMENT_MILES,
        "note": ("Scores are relative to THIS market only (min-max over the "
                 "market's own 1-mile lattice) — never compare a score across "
                 "markets. Zones name the best area to establish a real, "
                 "staffed location; Google requires a GBP address to be a "
                 "genuine premises."),
    }

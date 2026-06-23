"""Geo-grid analytics rollups for the Maps Local Rank Analysis report (Module #5).

Pure, I/O-free, exhaustively unit-tested. Turns a stored per-keyword `rank_grid`
(the 1-based display grid: `rank_grid[row][col]` = the business's rank at that
pin, `None` = not ranked) into the distance-ring and compass-sector (octant)
aggregates the report and the octant pin generator consume.

Grid orientation (the Local Dominator `content` grid, reading order):
  row 0 = NORTH edge … row n-1 = SOUTH edge
  col 0 = WEST  edge … col n-1 = EAST  edge
so a pin's signed offset from the business is `north = center - row`,
`east = col - center` (in miles, at the fixed 1-mile pin spacing). Only pins
inside the inscribed circle are counted, matching the circular heatmap + every
other rollup (see `local_dominator.summarize_grid`).
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Optional

METERS_PER_MILE = 1609.344

# 8 compass octants, clockwise from North. Index = round(bearing / 45) % 8.
OCTANTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
OCTANT_FULL = {
    "N": "North", "NE": "Northeast", "E": "East", "SE": "Southeast",
    "S": "South", "SW": "Southwest", "W": "West", "NW": "Northwest",
}

# A ring's Top-3 coverage falling below this (%) marks the performance horizon —
# the distance band where local-pack visibility collapses.
HORIZON_TOP3_PCT = 20.0


def _pct(num: int, denom: int) -> float:
    return round(num / denom * 100, 2) if denom else 0.0


def _metrics(ranks: list[Optional[float]]) -> dict:
    """Roll a list of per-pin ranks (None = not ranked) into coverage metrics."""
    cells = len(ranks)
    ranked = [r for r in ranks if r is not None]
    top3 = sum(1 for r in ranked if r <= 3)
    top10 = sum(1 for r in ranked if r <= 10)
    return {
        "cells": cells,
        "ranked": len(ranked),
        "not_ranked": cells - len(ranked),
        "top3": top3,
        "top10": top10,
        "gt10": len(ranked) - top10,
        "avg_rank": round(mean(ranked), 2) if ranked else None,
        "coverage_pct_top3": _pct(top3, cells),
        "coverage_pct_top10": _pct(top10, cells),
    }


def _octant_for(offset_north: float, offset_east: float, azimuth_offset_deg: float = 0.0) -> Optional[str]:
    """The compass octant a pin falls in, or None for the dead-centre pin."""
    if offset_north == 0 and offset_east == 0:
        return None
    bearing = (math.degrees(math.atan2(offset_east, offset_north)) + azimuth_offset_deg) % 360
    return OCTANTS[round(bearing / 45) % 8]


def _in_circle_cells(rank_grid: list[list], azimuth_offset_deg: float = 0.0) -> list[dict]:
    """Every in-circle pin as {ring, sector, rank}. `ring` folds the centre pin
    into ring 1 (innermost), so rings run 1..R with no noisy single-pin ring 0."""
    n = max((len(r) for r in (rank_grid or [])), default=0)
    if n == 0:
        return []
    center = (n - 1) / 2
    radius_sq = (n / 2) ** 2
    cells: list[dict] = []
    for ri, row in enumerate(rank_grid or []):
        for ci, cell in enumerate(row or []):
            if (ri - center) ** 2 + (ci - center) ** 2 > radius_sq:
                continue  # outside the inscribed circle — not shown
            north = center - ri
            east = ci - center
            dist = math.hypot(north, east)
            rank = float(cell) if isinstance(cell, (int, float)) else None
            cells.append({
                "ring": max(1, round(dist)),
                "sector": _octant_for(north, east, azimuth_offset_deg),
                "rank": rank,
            })
    return cells


def build_geogrid_analytics(rank_grid: list[list], azimuth_offset_deg: float = 0.0) -> dict:
    """Distance-ring + compass-sector rollups for one keyword's rank grid.

    Returns:
      {
        "azimuth_offset_deg": float,
        "overall": <metrics>,
        "ring_summaries": [ {ring, radius_m, radius_mi, **metrics,
                             "sectors": [ {sector, **metrics}, ... ]}, ... ],
        "sectors_overall": [ {sector, sector_full, **metrics}, ... ],  # weakest→strongest
        "performance_horizon": {ring, radius_mi, coverage_pct_top3} | None,
        "best_directions":   [ {sector, sector_full, avg_rank, coverage_pct_top3}, ... ],
        "weakest_directions":[ {sector, sector_full, avg_rank, coverage_pct_top3}, ... ],
      }
    """
    cells = _in_circle_cells(rank_grid, azimuth_offset_deg)
    overall = _metrics([c["rank"] for c in cells])

    # ── Rings (innermost → outermost) ──
    ring_ids = sorted({c["ring"] for c in cells})
    ring_summaries: list[dict] = []
    for ring in ring_ids:
        ring_cells = [c for c in cells if c["ring"] == ring]
        summary = {
            "ring": ring,
            "radius_m": round(ring * METERS_PER_MILE),
            "radius_mi": float(ring),
            **_metrics([c["rank"] for c in ring_cells]),
        }
        sectors = []
        for oct_name in OCTANTS:
            sec_cells = [c for c in ring_cells if c["sector"] == oct_name]
            if sec_cells:
                sectors.append({"sector": oct_name, **_metrics([c["rank"] for c in sec_cells])})
        summary["sectors"] = sectors
        ring_summaries.append(summary)

    # ── Sectors overall (across all rings) ──
    sectors_overall: list[dict] = []
    for oct_name in OCTANTS:
        sec_cells = [c for c in cells if c["sector"] == oct_name]
        if sec_cells:
            sectors_overall.append({
                "sector": oct_name,
                "sector_full": OCTANT_FULL[oct_name],
                **_metrics([c["rank"] for c in sec_cells]),
            })

    # Weakest → strongest: worst Top-3 coverage first, then worst avg rank
    # (unranked sectors sort to the weak end).
    def _weakness_key(s: dict) -> tuple:
        return (s["coverage_pct_top3"], s["coverage_pct_top10"],
                -(s["avg_rank"] if s["avg_rank"] is not None else 999))
    by_weakness = sorted(sectors_overall, key=_weakness_key)

    def _dir(s: dict) -> dict:
        return {"sector": s["sector"], "sector_full": s["sector_full"],
                "avg_rank": s["avg_rank"], "coverage_pct_top3": s["coverage_pct_top3"]}

    weakest = [_dir(s) for s in by_weakness[:3]]
    best = [_dir(s) for s in reversed(by_weakness[-3:])]

    # ── Performance horizon: first ring whose Top-3 coverage collapses ──
    horizon = None
    for r in ring_summaries:
        if r["ranked"] == 0 or r["coverage_pct_top3"] < HORIZON_TOP3_PCT:
            horizon = {"ring": r["ring"], "radius_mi": r["radius_mi"],
                       "coverage_pct_top3": r["coverage_pct_top3"]}
            break
    if horizon is None and ring_summaries:
        outer = ring_summaries[-1]
        horizon = {"ring": outer["ring"], "radius_mi": outer["radius_mi"],
                   "coverage_pct_top3": outer["coverage_pct_top3"]}

    return {
        "azimuth_offset_deg": azimuth_offset_deg,
        "overall": overall,
        "ring_summaries": ring_summaries,
        "sectors_overall": sectors_overall,
        "performance_horizon": horizon,
        "best_directions": best,
        "weakest_directions": weakest,
    }

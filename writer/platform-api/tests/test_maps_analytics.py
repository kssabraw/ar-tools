"""Unit tests for the geo-grid analytics rollups (Maps report Module #5)."""

from services import maps_analytics as ma


def _blank(n: int) -> list[list]:
    return [[None for _ in range(n)] for _ in range(n)]


def test_octant_orientation():
    # row 0 = north, col 0 = west; centre has no octant.
    assert ma._octant_for(0, 0) is None
    assert ma._octant_for(1, 0) == "N"      # due north
    assert ma._octant_for(-1, 0) == "S"     # due south
    assert ma._octant_for(0, 1) == "E"      # due east
    assert ma._octant_for(0, -1) == "W"     # due west
    assert ma._octant_for(1, 1) == "NE"
    assert ma._octant_for(-1, -1) == "SW"


def test_all_top1_full_coverage():
    n = 7
    grid = [[1 for _ in range(n)] for _ in range(n)]
    a = ma.build_geogrid_analytics(grid)
    assert a["overall"]["coverage_pct_top3"] == 100.0
    assert a["overall"]["avg_rank"] == 1.0
    # Never collapses → horizon falls on the outermost ring.
    rings = [r["ring"] for r in a["ring_summaries"]]
    assert a["performance_horizon"]["ring"] == max(rings)
    # 8 sectors all present, all strong.
    assert {s["sector"] for s in a["sectors_overall"]} == set(ma.OCTANTS)


def test_horizon_collapses_outside_inner_ring():
    n = 7
    grid = _blank(n)
    c = (n - 1) // 2
    # Rank 1 only at the centre + its 4 orthogonal neighbours (ring 1).
    grid[c][c] = 1
    grid[c - 1][c] = 1
    grid[c + 1][c] = 1
    grid[c][c - 1] = 1
    grid[c][c + 1] = 1
    a = ma.build_geogrid_analytics(grid)
    # Ring 1 has coverage; ring 2 collapses to 0% Top-3.
    ring2 = next(r for r in a["ring_summaries"] if r["ring"] == 2)
    assert ring2["coverage_pct_top3"] == 0.0
    assert a["performance_horizon"]["ring"] == 2


def test_ring_radius_metres():
    grid = [[1 for _ in range(7)] for _ in range(7)]
    a = ma.build_geogrid_analytics(grid)
    ring2 = next(r for r in a["ring_summaries"] if r["ring"] == 2)
    assert ring2["radius_m"] == round(2 * ma.METERS_PER_MILE)
    assert ring2["radius_mi"] == 2.0


def test_directional_asymmetry_ranks_weakest():
    # Strong in the east, blank in the west → west should sort weakest.
    n = 7
    c = (n - 1) // 2
    grid = _blank(n)
    for ri in range(n):
        for ci in range(c + 1, n):  # east half ranked 1st
            grid[ri][ci] = 1
    a = ma.build_geogrid_analytics(grid)
    weakest = [d["sector"] for d in a["weakest_directions"]]
    best = [d["sector"] for d in a["best_directions"]]
    assert "W" in weakest
    assert "E" in best

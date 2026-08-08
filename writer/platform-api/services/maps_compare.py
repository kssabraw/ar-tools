"""Make two geo-grid scans comparable when the grid geometry changed between
them.

The problem this solves: a client's radius is a per-client config read at scan
time, so widening 5 → 10 miles makes the very next scheduled scan measure a much
larger area. The added pins sit further from the business, where it ranks worse,
so coverage % falls and average rank worsens — with no change in ranking at all.
Diffed naively, that reads as a decline: it opens `maps_alerts`, sends a
notification, lands an Action Plan item and can open a response episode. In
front of a client, a measurement artifact presented as a ranking drop is worse
than no measurement.

The fix is exact rather than heuristic, because of how the grid is built
(`maps_grid`): every scan is a square lattice centred on the business with a
fixed 1-mile spacing and an odd side, so the pin at grid position
``(row - n//2, col - n//2)`` is the *same physical point* in an 11×11 (5-mile)
and a 21×21 (10-mile) scan. The smaller grid is therefore precisely the centred
sub-block of the larger one — cropping the larger scan to the smaller one's size
recovers a like-for-like measurement of the same ground, with no interpolation
and no estimation.

So: before diffing, crop both scans to their common (smaller) grid and recompute
the rollups from the cropped rank grid. Every downstream detector — rank drop,
coverage drop, lost pack, area decline, competitor surge — then compares the
same ground on both sides, without any of them needing to know geometry changed.

Deliberately NOT done here: rewriting the *levels* a scan reports. A 10-mile
scan is still reported as a 10-mile scan everywhere it's displayed — you widened
the grid to see more, so the reported picture should widen too. Only
*comparisons* are normalised. The trend chart marks the scan where geometry
changed, so a step in the line reads as "we started measuring a bigger area"
rather than as a fall.

Pure and unit-tested: no I/O, no DB.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Optional, Sequence

# Result fields recomputed from the cropped grid. Anything else on the row is
# carried through untouched.
_RECOMPUTED = ("total_pins", "found_pins", "top3_pins", "top10_pins", "average_rank")


def grid_side(grid: Optional[Sequence[Sequence[Any]]]) -> int:
    """Pins per side of a square grid (0 when absent/ragged-empty)."""
    if not grid:
        return 0
    return max((len(r) for r in grid if isinstance(r, (list, tuple))), default=0)


def crop_square(grid: Optional[Sequence[Sequence[Any]]], target_side: int):
    """The centred ``target_side × target_side`` sub-block of a square grid.

    Both sides are odd and share a centre pin, so the crop is symmetric and the
    surviving cells keep their real-world positions. Returns the grid unchanged
    when it's already the target size (or smaller, or unusable), so callers can
    apply this unconditionally.
    """
    side = grid_side(grid)
    if not side or target_side <= 0 or side <= target_side:
        return grid
    margin = (side - target_side) // 2
    if margin <= 0:
        return grid
    return [list(row[margin:margin + target_side]) for row in grid[margin:margin + target_side]]


def summarize_display_grid(grid: Optional[Sequence[Sequence[Any]]]) -> dict:
    """Roll a **display** rank grid (1-based ranks, None = not ranked) up into
    the same pin counts `local_dominator.summarize_grid` produces from the raw
    provider grid.

    Counts only pins inside the inscribed circle, with the identical rule, so a
    recomputed uncropped grid reproduces the stored numbers exactly (there's a
    test pinning that parity — if the two rules ever drift, normalised and
    unnormalised scans would silently disagree).
    """
    n = grid_side(grid)
    center = (n - 1) / 2
    radius_sq = (n / 2) ** 2
    ranks: list[int] = []
    total = 0
    top3 = top10 = 0
    for ri, row in enumerate(grid or []):
        for ci, cell in enumerate(row):
            if (ri - center) ** 2 + (ci - center) ** 2 > radius_sq:
                continue  # outside the circle — not shown, not counted
            total += 1
            if isinstance(cell, (int, float)):
                r = int(cell)
                ranks.append(r)
                if r <= 3:
                    top3 += 1
                if r <= 10:
                    top10 += 1
    return {
        "total_pins": total,
        "found_pins": len(ranks),
        "top3_pins": top3,
        "top10_pins": top10,
        "average_rank": round(mean(ranks), 2) if ranks else None,
    }


def radius_miles_for_side(side: Optional[int]) -> Optional[int]:
    """The radius a grid side corresponds to, for user-facing copy. Sides are
    ``2 * radius + 1`` at the fixed 1-mile spacing, so 11 → 5 miles."""
    return side // 2 if side else None


def normalize_result(row: dict, target_side: int) -> dict:
    """One per-keyword result row re-measured on the centred ``target_side`` grid.

    Crops both the rank grid and the per-pin `competitors_above` grid — a
    competitor's "pins where they outrank you" count is a raw pin tally, so
    leaving it at full size while the rank grid shrank would invent a surge.

    Metrics are recomputed even for a row that needed no crop (the smaller side
    of a resized pair). Both sides of a comparison must come from the *same*
    rule, and the stored values did not: the Local Dominator and DataForSEO
    providers each roll their own scans up, so mixing one stored figure with one
    recomputed figure would reintroduce a small artificial delta — exactly the
    thing this module exists to remove. A row with no stored grid can't be
    re-measured, so it's passed through untouched.
    """
    grid = row.get("rank_grid")
    if not grid_side(grid):
        return row
    cropped = crop_square(grid, target_side)
    out = {**row, "rank_grid": cropped, **summarize_display_grid(cropped)}
    if row.get("competitors_above"):
        out["competitors_above"] = crop_square(row["competitors_above"], target_side)
    return out


def common_side(*sides: Optional[int]) -> int:
    """The largest grid every scan in the set covers — i.e. the smallest side.
    Zero/None sides (a scan with no stored grid) are ignored."""
    known = [s for s in sides if s]
    return min(known) if known else 0


def normalize_pair(
    curr_results: Sequence[dict], prev_results: Sequence[dict]
) -> tuple[list[dict], list[dict], Optional[int]]:
    """Re-measure two scans' result rows onto their common grid, if they differ.

    Returns ``(curr, prev, normalized_to)`` where ``normalized_to`` is the grid
    side both were reduced to, or None when they already matched and nothing was
    touched. The sides are read from the stored grids rather than the scan rows'
    `grid_size` column, so a row whose grid is missing or an unexpected size is
    handled by what's actually there.
    """
    curr_side = common_side(*(grid_side(r.get("rank_grid")) for r in curr_results))
    prev_side = common_side(*(grid_side(r.get("rank_grid")) for r in prev_results))
    if not curr_side or not prev_side or curr_side == prev_side:
        return list(curr_results), list(prev_results), None
    target = min(curr_side, prev_side)
    return (
        [normalize_result(r, target) for r in curr_results],
        [normalize_result(r, target) for r in prev_results],
        target,
    )


def normalize_series(results: Sequence[dict]) -> tuple[list[dict], Optional[int]]:
    """Re-measure a whole series of result rows onto the common grid they all
    cover, for reads that compute deltas across a window (7/30/90-day periods)
    which may span a geometry change.

    Returns ``(rows, normalized_to)``; ``normalized_to`` is None when every row
    already shares a grid size, in which case the rows come back untouched.
    """
    sides = {grid_side(r.get("rank_grid")) for r in results}
    sides.discard(0)
    if len(sides) <= 1:
        return list(results), None
    target = min(sides)
    return [normalize_result(r, target) for r in results], target

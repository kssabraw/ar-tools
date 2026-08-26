"""Comparing two geo-grid scans across a grid resize.

The failure being prevented: widening a client's radius makes the next scheduled
scan measure a larger area, whose outer pins rank worse. Diffed naively that
reads as a ranking drop and reaches the client as an alert and an Action Plan
item. Because every grid is a centred, odd-sided, 1-mile lattice, the smaller
grid is exactly the centred sub-block of the larger, so the comparison can be
made honest by cropping rather than estimated away.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import maps_compare as mc  # noqa: E402
from services.local_dominator import summarize_grid  # noqa: E402


def ring_grid(side: int, inner: int = 1, outer: int = 20, strong_radius: int = 2) -> list[list[int]]:
    """A square display grid ranking `inner` within `strong_radius` MILES of the
    centre and `outer` beyond it — the real-world shape of local ranking.

    `strong_radius` is deliberately absolute, not a fraction of `side`: the
    business's strong zone is fixed geography, so widening the scan only adds
    weak outer pins. That is precisely what makes a resize look like a drop.
    """
    half = side // 2
    return [
        [inner if max(abs(r - half), abs(c - half)) <= strong_radius else outer for c in range(side)]
        for r in range(side)
    ]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def test_grid_side_reads_the_square_size():
    assert mc.grid_side(ring_grid(11)) == 11
    assert mc.grid_side([]) == 0
    assert mc.grid_side(None) == 0


def test_crop_takes_the_centred_sub_block():
    # Number every cell so the crop's position is checkable, not just its size.
    grid = [[r * 10 + c for c in range(5)] for r in range(5)]
    assert mc.crop_square(grid, 3) == [[11, 12, 13], [21, 22, 23], [31, 32, 33]]


def test_crop_preserves_the_centre_pin():
    # The business sits on the centre pin; a crop that shifted would compare
    # different ground and defeat the whole exercise.
    grid = [[0] * 21 for _ in range(21)]
    grid[10][10] = 99
    cropped = mc.crop_square(grid, 11)
    assert cropped[5][5] == 99


def test_crop_is_a_no_op_at_or_below_the_target_size():
    grid = ring_grid(11)
    assert mc.crop_square(grid, 11) is grid
    assert mc.crop_square(grid, 21) is grid
    assert mc.crop_square(None, 11) is None


def test_radius_miles_for_side():
    assert mc.radius_miles_for_side(11) == 5
    assert mc.radius_miles_for_side(21) == 10
    assert mc.radius_miles_for_side(0) is None
    assert mc.radius_miles_for_side(None) is None


# ---------------------------------------------------------------------------
# Rollup parity — the recomputed numbers must match what the scan stored.
# ---------------------------------------------------------------------------
def test_recomputed_rollup_matches_the_stored_one_exactly():
    # summarize_grid works on the RAW provider grid (0-based, -1 = unranked);
    # summarize_display_grid works on the stored display grid (1-based, None).
    # They must agree, or a normalised scan would silently disagree with an
    # unnormalised one on the same data.
    raw = [
        [0, 4, -1, 9, 2],
        [3, -1, 1, 12, 0],
        [7, 2, 0, 5, -1],
        [-1, 11, 6, 2, 8],
        [1, 0, 30, -1, 4],
    ]
    display = [[c + 1 if c >= 0 else None for c in row] for row in raw]
    stored = summarize_grid(raw)
    recomputed = mc.summarize_display_grid(display)
    assert recomputed["total_pins"] == stored["total_pins"]
    assert recomputed["found_pins"] == stored["found_pins"]
    assert recomputed["top3_pins"] == stored["top3_pins"]
    assert recomputed["top10_pins"] == stored["top10_pins"]
    assert recomputed["average_rank"] == stored["computed_average"]


def test_rollup_counts_only_pins_inside_the_circle():
    # A 5×5 square has 25 cells but the inscribed circle excludes the corners.
    assert mc.summarize_display_grid([[1] * 5 for _ in range(5)])["total_pins"] == 21


def test_rollup_handles_an_all_unranked_grid():
    out = mc.summarize_display_grid([[None] * 5 for _ in range(5)])
    assert out["found_pins"] == 0 and out["average_rank"] is None


# ---------------------------------------------------------------------------
# The actual defect: a widened grid must not read as a drop.
# ---------------------------------------------------------------------------
def _pct(row, key="top3_pins"):
    return 100.0 * row[key] / row["total_pins"]


def test_widening_the_radius_looks_like_a_collapse_when_compared_naively():
    # Establishes the bug this module exists to fix: same rankings on the shared
    # ground, but the wider scan's coverage is far lower.
    narrow = mc.summarize_display_grid(ring_grid(11))
    wide = mc.summarize_display_grid(ring_grid(21))
    assert _pct(wide) < _pct(narrow) - 10


def test_normalizing_the_pair_removes_the_phantom_drop():
    prev = [{"keyword": "plumber", "rank_grid": ring_grid(11)}]
    curr = [{"keyword": "plumber", "rank_grid": ring_grid(21)}]
    curr_n, prev_n, target = mc.normalize_pair(curr, prev)
    assert target == 11
    # Same ground, same ranks → identical metrics, so no detector can fire.
    for key in ("total_pins", "found_pins", "top3_pins", "top10_pins", "average_rank"):
        assert curr_n[0][key] == prev_n[0][key], key


def test_a_real_drop_still_survives_normalization():
    # The guard must not blunt genuine declines: same geometry change, but the
    # business actually lost the centre.
    prev = [{"keyword": "plumber", "rank_grid": ring_grid(11, inner=1)}]
    curr = [{"keyword": "plumber", "rank_grid": ring_grid(21, inner=15)}]
    curr_n, prev_n, _ = mc.normalize_pair(curr, prev)
    assert curr_n[0]["top3_pins"] < prev_n[0]["top3_pins"]


def test_matching_geometry_is_left_completely_untouched():
    # The overwhelmingly common case: no resize, so rows pass through as-is and
    # the stored numbers are used rather than recomputed.
    prev = [{"keyword": "plumber", "rank_grid": ring_grid(11), "top3_pins": 999}]
    curr = [{"keyword": "plumber", "rank_grid": ring_grid(11), "top3_pins": 888}]
    curr_n, prev_n, target = mc.normalize_pair(curr, prev)
    assert target is None
    assert curr_n[0]["top3_pins"] == 888 and prev_n[0]["top3_pins"] == 999


def test_narrowing_the_radius_is_handled_too():
    # 10 → 5 miles would otherwise show a phantom IMPROVEMENT.
    prev = [{"keyword": "plumber", "rank_grid": ring_grid(21)}]
    curr = [{"keyword": "plumber", "rank_grid": ring_grid(11)}]
    curr_n, prev_n, target = mc.normalize_pair(curr, prev)
    assert target == 11
    assert curr_n[0]["top3_pins"] == prev_n[0]["top3_pins"]


def test_competitors_above_is_cropped_alongside_the_rank_grid():
    # It's a raw per-pin tally, so leaving it full-size while the rank grid
    # shrank would invent a competitor surge.
    big = [[[["pid-1", 1]] for _ in range(21)] for _ in range(21)]
    small = [[[["pid-1", 1]] for _ in range(11)] for _ in range(11)]
    curr = [{"keyword": "k", "rank_grid": ring_grid(21), "competitors_above": big}]
    prev = [{"keyword": "k", "rank_grid": ring_grid(11), "competitors_above": small}]
    curr_n, _prev_n, _ = mc.normalize_pair(curr, prev)
    assert mc.grid_side(curr_n[0]["competitors_above"]) == 11


def test_a_missing_grid_disables_normalization_rather_than_guessing():
    prev = [{"keyword": "plumber", "top3_pins": 5, "total_pins": 10}]
    curr = [{"keyword": "plumber", "rank_grid": ring_grid(21)}]
    curr_n, prev_n, target = mc.normalize_pair(curr, prev)
    assert target is None
    assert prev_n[0]["top3_pins"] == 5


# ---------------------------------------------------------------------------
# Series normalization (the 7/30/90-day period deltas)
# ---------------------------------------------------------------------------
def test_a_series_spanning_a_resize_is_levelled_to_the_common_grid():
    rows = [
        {"keyword": "k", "rank_grid": ring_grid(11)},
        {"keyword": "k", "rank_grid": ring_grid(11)},
        {"keyword": "k", "rank_grid": ring_grid(21)},
    ]
    out, target = mc.normalize_series(rows)
    assert target == 11
    assert len({r["top3_pins"] for r in out}) == 1  # no step across the resize


def test_a_uniform_series_is_untouched():
    rows = [{"keyword": "k", "rank_grid": ring_grid(11), "top3_pins": 7} for _ in range(3)]
    out, target = mc.normalize_series(rows)
    assert target is None
    assert all(r["top3_pins"] == 7 for r in out)

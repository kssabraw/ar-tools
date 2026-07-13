"""Unit tests for the LeadOff peer-cohort field-strength engine (pure)."""
from services.leadoff_peer_cohort import (
    band_of,
    cohort_keys,
    compute_peer_signals,
    field_signal,
    quantile_edges,
    size_key,
)


class TestBands:
    def test_quantile_edges_quartiles(self):
        edges = quantile_edges(list(range(1, 101)), 4)
        assert len(edges) == 3
        assert edges[0] < edges[1] < edges[2]

    def test_quantile_edges_refuses_flat(self):
        assert quantile_edges([5, 5, 5, 5], 4) == []
        assert quantile_edges([1, 2], 4) == []          # < n values
        assert quantile_edges([None, None], 4) == []

    def test_band_of(self):
        edges = [50_000.0, 75_000.0, 100_000.0]
        assert band_of(40_000, edges) == 0
        assert band_of(60_000, edges) == 1
        assert band_of(90_000, edges) == 2
        assert band_of(120_000, edges) == 3
        assert band_of(None, edges) is None
        assert band_of(60_000, []) is None              # no edges → unbanded

    def test_size_key_prefers_tier_then_population(self):
        assert size_key("mid", 40_000, [10_000.0, 50_000.0]) == "t:mid"
        assert size_key(None, 40_000, [10_000.0, 50_000.0]) == "p:1"
        assert size_key(None, None, [10_000.0]) is None


class TestCohortKeys:
    def test_ladder_from_finest_to_coarsest(self):
        keys = cohort_keys("plumber", "t:mid", 2)
        assert keys == [("cat_size_inc", "plumber", "t:mid", 2),
                        ("cat_size", "plumber", "t:mid"),
                        ("cat", "plumber")]

    def test_missing_income_drops_finest_level(self):
        keys = cohort_keys("plumber", "t:mid", None)
        assert keys == [("cat_size", "plumber", "t:mid"), ("cat", "plumber")]

    def test_missing_size_leaves_only_category(self):
        assert cohort_keys("plumber", None, None) == [("cat", "plumber")]

    def test_no_category_no_cohort(self):
        assert cohort_keys("", "t:mid", 1) == []


class TestFieldSignal:
    def test_weaker_field_is_positive(self):
        # rev_win 5 vs cohort median 25 → easier than peers
        assert field_signal(5, 25) == 0.8

    def test_stronger_field_is_negative_and_clamped(self):
        assert field_signal(60, 20) == -1.0             # clamped at -1
        assert field_signal(30, 20) == -0.5

    def test_equal_is_zero(self):
        assert field_signal(20, 20) == 0.0

    def test_denom_floor_dampens_tiny_cohorts(self):
        # median 2 with floor 5: (2-0)/5 = 0.4, not (2-0)/2 = 1.0
        assert field_signal(0, 2, denom_floor=5.0) == 0.4

    def test_missing_inputs_none(self):
        assert field_signal(None, 20) is None
        assert field_signal(20, None) is None


class TestComputePeerSignals:
    def _cohort(self, rev_win, n=6, cat="plumber", tier="mid", income=60_000):
        """n comparable cities (same tier+income) at a fixed rev_win, plus one
        target city we vary."""
        rows = [{"city_id": 100 + i, "category_id": cat, "category": cat,
                 "rev_win": rev_win, "size_tier": tier, "population": 40_000,
                 "income": income} for i in range(n)]
        return rows

    def _spread(self):
        """A same-category board spread across income bands so quantile edges
        form (other-band cities won't pollute the 60k cohort's median)."""
        rows = []
        for i, inc in enumerate((30_000, 90_000, 120_000, 150_000)):
            rows.append({"city_id": 300 + i, "category_id": "plumber",
                         "category": "plumber", "rev_win": 15, "size_tier": "mid",
                         "population": 40_000, "income": inc})
        return rows

    def test_target_below_cohort_median_is_easier(self):
        rows = self._cohort(rev_win=30, n=6) + self._spread()
        rows.append({"city_id": 1, "category_id": "plumber", "category": "plumber",
                     "rev_win": 5, "size_tier": "mid", "population": 40_000,
                     "income": 60_000})
        out = compute_peer_signals(rows, min_peers=5)
        sig = out[(1, "plumber")]
        assert sig["peer_field"] > 0                      # weaker field → easier
        assert sig["cohort_level"] == "cat_size_inc"      # comparable size+income
        assert sig["cohort_median"] == 30.0               # the 6 same-band peers

    def test_falls_back_when_finest_cohort_too_small(self):
        # only 2 same-tier+income peers, but 6 same-category cities overall
        rows = []
        for i in range(6):
            rows.append({"city_id": 200 + i, "category_id": "roofer",
                         "category": "roofer", "rev_win": 40,
                         "size_tier": "big" if i < 2 else "small",
                         "population": 500_000 if i < 2 else 8_000,
                         "income": 90_000 if i < 2 else 45_000})
        rows.append({"city_id": 2, "category_id": "roofer", "category": "roofer",
                     "rev_win": 10, "size_tier": "big", "population": 500_000,
                     "income": 90_000})
        out = compute_peer_signals(rows, min_peers=5)
        sig = out[(2, "roofer")]
        # not enough big+high-income peers → widened to the whole category
        assert sig["cohort_level"] == "cat"
        assert sig["peer_field"] > 0

    def test_no_cohort_when_below_floor_everywhere(self):
        rows = [{"city_id": 3, "category_id": "niche", "category": "niche",
                 "rev_win": 10, "size_tier": "mid", "population": 40_000,
                 "income": 60_000}]
        assert compute_peer_signals(rows, min_peers=5) == {}

    def test_missing_income_still_cohorts_by_size(self):
        rows = self._cohort(rev_win=30, n=6, income=None)
        rows.append({"city_id": 4, "category_id": "plumber", "category": "plumber",
                     "rev_win": 8, "size_tier": "mid", "population": 40_000,
                     "income": None})
        out = compute_peer_signals(rows, min_peers=5)
        sig = out[(4, "plumber")]
        assert sig["cohort_level"] == "cat_size"          # income dropped
        assert sig["peer_field"] > 0

    def test_rows_without_rev_win_are_skipped(self):
        rows = self._cohort(rev_win=30, n=6)
        rows.append({"city_id": 5, "category_id": "plumber", "category": "plumber",
                     "rev_win": None, "size_tier": "mid", "population": 40_000,
                     "income": 60_000})
        out = compute_peer_signals(rows, min_peers=5)
        assert (5, "plumber") not in out

"""Unit tests for the LeadOff grade-all bulk sweep's pure logic (no Supabase, no
DataForSEO). The impure reads + the live per-city grade reuse leadoff_actions'
tested economics + leadoff_grade's tested helpers, so only the grade-all-specific
pure helpers are exercised here."""
from services.leadoff_grade_all import (
    COST_GRADE,
    estimate_cost,
    normalize_row,
    plan_live_budget,
    rank_rows,
    split_candidates,
)


def _city(cid, pop=20000, name=None, state="TX"):
    return {"city_id": cid, "city_name": name or f"City{cid}",
            "state_code": state, "population": pop}


class TestEstimateCost:
    def test_only_the_live_remainder_is_billed(self):
        assert estimate_cost(10) == round(10 * COST_GRADE, 2)

    def test_zero_and_negative_are_free(self):
        assert estimate_cost(0) == 0.0
        assert estimate_cost(-5) == 0.0


class TestPlanLiveBudget:
    def test_ceiling_caps_below_the_need(self):
        # $0.30 / $0.06 = 5 affordable, need 20 → grade 5
        assert plan_live_budget(20, 0.30) == 5

    def test_need_below_ceiling_grades_everything(self):
        assert plan_live_budget(3, 10.0) == 3

    def test_zero_ceiling_grades_nothing_live(self):
        assert plan_live_budget(50, 0.0) == 0

    def test_negative_ceiling_grades_nothing(self):
        assert plan_live_budget(50, -1.0) == 0

    def test_free_cost_each_grades_the_whole_need(self):
        assert plan_live_budget(50, 0.0, cost_each=0) == 50


class TestSplitCandidates:
    def test_partitions_by_cheapest_source_board_wins(self):
        cands = [_city(1), _city(2), _city(3), _city(4)]
        # city 1 is BOTH on board and cached → board wins (free either way, but
        # board is the canonical precomputed grade)
        split = split_candidates(cands, board_free_ids={1, 2}, cached_ids={1, 3})
        assert [c["city_id"] for c in split["on_board"]] == [1, 2]
        assert [c["city_id"] for c in split["cached"]] == [3]
        assert [c["city_id"] for c in split["needs_live"]] == [4]

    def test_order_is_preserved_within_buckets(self):
        cands = [_city(5, pop=90000), _city(6, pop=50000), _city(7, pop=10000)]
        split = split_candidates(cands, board_free_ids=set(), cached_ids=set())
        # population-desc order in → needs_live grades biggest markets first
        assert [c["city_id"] for c in split["needs_live"]] == [5, 6, 7]

    def test_empty_sets_are_all_live(self):
        cands = [_city(1), _city(2)]
        split = split_candidates(cands, set(), set())
        assert len(split["needs_live"]) == 2
        assert split["on_board"] == [] and split["cached"] == []


class TestNormalizeRow:
    def test_board_row_uses_regressed_demand(self):
        raw = {"city_id": 1, "city_name": "Austin", "state_code": "TX",
               "category": "Plumber", "grade": "B", "exp_val": 900,
               "value_mo": 1200, "rankab": 0.6, "roi": 5.0, "xdem": 56,
               "rev_win": 30, "rating": 4.5}
        row = normalize_row("board", raw, category_name="Plumber", population=95000)
        assert row["source"] == "board"
        assert row["demand"] == 56 and row["demand_basis"] == "regressed"
        assert row["population"] == 95000
        assert row["grade"] == "B" and row["exp_val"] == 900

    def test_live_row_uses_observed_demand(self):
        raw = {"city_id": 2, "city_name": "Waco", "state_code": "TX",
               "category": "Plumber", "grade": "C", "exp_val": 300,
               "vol": 40, "rankab": 0.4, "supply": 12, "thin_demand": False}
        row = normalize_row("live", raw, category_name="Plumber", population=None)
        assert row["source"] == "live"
        assert row["demand"] == 40 and row["demand_basis"] == "observed"
        assert row["supply"] == 12

    def test_category_falls_back_when_missing(self):
        row = normalize_row("live", {"city_id": 3}, category_name="Dumpster rental",
                            population=15000)
        assert row["category"] == "Dumpster rental"


class TestRankRows:
    def test_sorted_by_exp_val_desc(self):
        rows = [{"exp_val": 100, "city_name": "A"}, {"exp_val": 900, "city_name": "B"},
                {"exp_val": 500, "city_name": "C"}]
        assert [r["city_name"] for r in rank_rows(rows)] == ["B", "C", "A"]

    def test_none_exp_val_sinks_to_bottom(self):
        rows = [{"exp_val": None, "city_name": "Z"}, {"exp_val": 10, "city_name": "Y"}]
        assert [r["city_name"] for r in rank_rows(rows)] == ["Y", "Z"]

    def test_tie_break_value_mo_then_city(self):
        rows = [{"exp_val": 100, "value_mo": 5, "city_name": "B"},
                {"exp_val": 100, "value_mo": 9, "city_name": "A"},
                {"exp_val": 100, "value_mo": 5, "city_name": "A"}]
        # value_mo 9 first; then value_mo 5 ties broken by city name A < B
        assert [(r["value_mo"], r["city_name"]) for r in rank_rows(rows)] == [
            (9, "A"), (5, "A"), (5, "B")]

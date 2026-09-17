"""Unit tests for services.leadoff_export — the pure port of report.py's board
computation. Expected values are hand-computed from report.py's formulas."""
from services import leadoff_export as lx


def test_grade_for_score_bands():
    assert lx.grade_for_score(100) == "A+"
    assert lx.grade_for_score(99) == "A+"
    assert lx.grade_for_score(98.9) == "A"
    assert lx.grade_for_score(97) == "A"
    assert lx.grade_for_score(96.9) == "B+"
    assert lx.grade_for_score(94) == "B+"
    assert lx.grade_for_score(90) == "B"
    assert lx.grade_for_score(89.9) == "C"
    assert lx.grade_for_score(75) == "C"
    assert lx.grade_for_score(74.9) == "D"   # the veto cap lands in D, not C
    assert lx.grade_for_score(50) == "D"
    assert lx.grade_for_score(49.9) == "F"
    assert lx.grade_for_score(0) == "F"
    assert lx.grade_for_score(None) == "F"


def test_percentile_rank_average_ties():
    # pandas rank(pct=True)*100 with 'average' ties
    assert lx.percentile_rank([10, 20, 20, 30]) == [25.0, 62.5, 62.5, 100.0]
    assert lx.percentile_rank([5]) == [100.0]
    assert lx.percentile_rank([]) == []
    # all equal -> everyone at the average position (2.5/3)*100
    got = lx.percentile_rank([7, 7, 7])
    assert got == [round(100 * 2.0 / 3.0, 10)] * 3 or all(abs(g - 66.6667) < 0.01 for g in got)


def test_rankability():
    assert lx._rankability(10, 2) == 0.80
    assert lx._rankability(5, 0) == 0.93
    assert lx._rankability(0, 0) == 1.0      # empty field = fully winnable
    assert lx._rankability(None, None) == 1.0


def test_conf_bins():
    assert lx._conf(0) == "low"
    assert lx._conf(49) == "low"
    assert lx._conf(50) == "med"
    assert lx._conf(259) == "med"
    assert lx._conf(260) == "high"
    assert lx._conf(None) == "low"


def _demand_rows():
    return [
        {"category_id": "p", "city_name": "A", "state_code": "CA", "population": 100000, "demand_vol": 500},
        {"category_id": "p", "city_name": "B", "state_code": "CA", "population": 50000, "demand_vol": 100},
        {"category_id": "r", "city_name": "A", "state_code": "CA", "population": 100000, "demand_vol": 1000},
        {"category_id": "r", "city_name": "B", "state_code": "CA", "population": 50000, "demand_vol": 50},
    ]


def test_demand_fields_xdemand_and_ratio():
    d = lx._demand_fields(_demand_rows())
    # plumber median rate = median(0.005, 0.002) = 0.0035; roofer = 0.0055
    assert [r["xdemand"] for r in d] == [462, 119, 888, 106]
    assert [r["dem_ratio"] for r in d] == [1.43, 0.57, 1.82, 0.18]


def test_luck_park_adjusted():
    # city A dem_ratios 1.0/2.0/4.0 -> median 2.0 -> rels 0.5/1.0/2.0
    rows = [
        {"city_name": "A", "state_code": "CA"},
        {"city_name": "A", "state_code": "CA"},
        {"city_name": "A", "state_code": "CA"},
        {"city_name": "B", "state_code": "CA"},
    ]
    demand = [{"dem_ratio": 1.0}, {"dem_ratio": 2.0}, {"dem_ratio": 4.0}, {"dem_ratio": None}]
    assert lx._luck(rows, demand) == ["COLD?", "-", "HOT?", "-"]


def _board_inputs():
    master = [
        {"city_id": 1, "category_id": "p", "city_name": "A", "state_code": "CA",
         "population": 100000, "demand_vol": 500, "avg_top5_reviews": 10,
         "exact_cat_holders": 2, "opportunity_score_v3": 80.0, "low_coverage": False},
        {"city_id": 2, "category_id": "p", "city_name": "B", "state_code": "CA",
         "population": 50000, "demand_vol": 100, "avg_top5_reviews": 200,
         "exact_cat_holders": 40, "opportunity_score_v3": 40.0, "low_coverage": False},
        {"city_id": 1, "category_id": "r", "city_name": "A", "state_code": "CA",
         "population": 100000, "demand_vol": 1000, "avg_top5_reviews": 5,
         "exact_cat_holders": 1, "opportunity_score_v3": 90.0, "low_coverage": False},
        {"city_id": 2, "category_id": "r", "city_name": "B", "state_code": "CA",
         "population": 50000, "demand_vol": 50, "avg_top5_reviews": 5,
         "exact_cat_holders": 0, "opportunity_score_v3": 30.0, "low_coverage": True},
    ]
    fq = {
        (1, "p"): {"rev_to_win": 20, "top5_rating": 4.2, "name_match": 1},
        (2, "p"): {"rev_to_win": 30, "top5_rating": 3.5, "name_match": 0},
        (1, "r"): {"rev_to_win": 8, "top5_rating": 5.0, "name_match": 2},
    }
    cat_names = {"p": "plumber", "r": "roofer"}
    cpl = {"plumber": 50, "roofer": 80}
    return master, fq, cat_names, cpl


def test_build_board_rows_end_to_end():
    master, fq, cat_names, cpl = _board_inputs()
    out = lx.build_board_rows(master, fq, cat_names, cpl, as_of="2026-07")

    # thin (low_coverage) row 4 is excluded from OUTPUT
    assert len(out) == 3
    assert all(not (r["city_id"] == 2 and r["category"] == "roofer") for r in out)

    by = {(r["city_id"], r["category"]): r for r in out}
    r1, r2, r3 = by[(1, "plumber")], by[(2, "plumber")], by[(1, "roofer")]

    # exp_value ranking is over ALL 4 measured rows (thin included in the
    # denominator), so r1 (1840) is 3rd of 4 -> percentile 75, NOT 66.7 (3-row).
    assert r1["build"] == 75.0 and r1["grade"] == "C"
    assert r1["exp_val"] == 1840 and r1["value_mo"] == 2300
    assert r1["rankab"] == 0.80 and r1["xdem"] == 462
    assert r1["rev_win"] == 20.0 and r1["roi"] == 92.0   # 1840 / max(20,10)
    assert r1["rating"] == 4.2 and r1["namekw"] == 1.0 and r1["v3"] == 80.0

    assert r2["build"] == 25.0 and r2["grade"] == "F"
    assert r3["build"] == 100.0 and r3["grade"] == "A+" and r3["exp_val"] == 6337
    # rev_to_win 8 floors to 10 for roi only; rev_win column keeps the raw 8
    assert r3["rev_win"] == 8.0 and r3["roi"] == 633.7

    # every board column present + as_of stamped
    for r in out:
        for col in lx.BOARD_COLUMNS:
            assert col in r
        assert r["as_of"] == "2026-07"


def test_build_board_rows_no_lead_value_is_grade_f():
    master, fq, cat_names, _ = _board_inputs()
    # roofer has no CPL -> those rows get build 0 / grade F / value_mo None
    out = lx.build_board_rows(master, fq, cat_names, {"plumber": 50}, as_of="x")
    roofer = next(r for r in out if r["category"] == "roofer")
    assert roofer["build"] == 0.0 and roofer["grade"] == "F"
    assert roofer["value_mo"] is None
    assert roofer["exp_val"] == 0   # value-or-0 * rankab


def test_build_percentiles_monotonic():
    p = lx.build_percentiles([0, 100, 200, 300, 400])
    assert len(p) == 101
    assert p[0] == {"pct": 0.0, "exp_val": 0.0}
    assert p[100] == {"pct": 100.0, "exp_val": 400.0}
    vals = [row["exp_val"] for row in p]
    assert vals == sorted(vals)          # non-decreasing
    assert lx.build_percentiles([]) == []
    assert all(row["exp_val"] == 42.0 for row in lx.build_percentiles([42]))

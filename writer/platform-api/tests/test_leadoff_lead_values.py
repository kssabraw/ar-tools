"""Unit tests for the exclusive-CPL re-anchor ladder (valuation plan v1 step 1)."""
from services import leadoff_lead_values as llv


def test_geomean_and_formula():
    assert round(llv.geomean(60, 255)) == 124
    assert round(llv.geomean(500, 2250)) == 1061
    # spec §4 HVAC worked example lands inside Service Direct's $65–325 range
    v = llv.formula_cpl(3401, 0.44, 0.22)
    assert 65 <= v <= 340


def _row(name, cluster, lo, mid, hi):
    return {"category_name": name, "cluster": cluster,
            "cpl_low": lo, "cpl_mid": mid, "cpl_high": hi}


def test_rung1_direct_exclusive_range_lifts_emergency_trades():
    rows = llv.build_lead_values([
        _row("Water damage restoration service", "Restoration", 75, 138, 200),
        _row("Roofing contractor", "Roofing", 30, 75, 120),
        _row("Plumber", "Plumbing", 25, 50, 75),
    ])
    by = {r["category_name"]: r for r in rows}
    wd = by["Water damage restoration service"]
    assert wd["cpl_low"] == 500 and wd["cpl_high"] == 2250 and wd["cpl_mid"] == 1061
    assert wd["source"] == "service_direct_range" and wd["confidence"] == "high"
    # the whole point: exclusive re-anchor raises the emergency trades
    assert by["Roofing contractor"]["cpl_mid"] > 75
    assert by["Plumber"]["cpl_mid"] > 50


def test_rung2_observed_average_and_remodeling_tier():
    rows = llv.build_lead_values([
        _row("Flooring contractor", "Flooring", 25, 52, 80),
        _row("Kitchen remodeler", "Remodeling/Renovation", 40, 70, 100),
    ])
    by = {r["category_name"]: r for r in rows}
    fl = by["Flooring contractor"]
    assert fl["cpl_mid"] == 85 and fl["source"] == "service_direct_avg_2026"
    assert fl["confidence"] == "medium"
    rem = by["Kitchen remodeler"]
    assert rem["cpl_mid"] == 425 and rem["source"] == "cpl_tier"


def test_rung3_cluster_inheritance_uses_anchor_floor():
    rows = llv.build_lead_values([
        _row("Air duct cleaning service", "HVAC", 20, 40, 60),  # → HVAC floor
        _row("Home automation company", "Electrical/Home Tech", 30, 60, 90),
    ])
    by = {r["category_name"]: r for r in rows}
    duct = by["Air duct cleaning service"]
    hvac_low = llv.VERTICALS["hvac"][0]
    assert duct["cpl_mid"] == hvac_low            # mid = anchor floor (plan rule)
    assert duct["source"] == "cluster:hvac" and duct["confidence"] == "low"


def test_rung4_niche_keeps_manual_flagged_nothing_fabricated():
    rows = llv.build_lead_values([
        _row("Piano tuner", "Specialty/Niche", 15, 30, 45),
        _row("Moving company", "Moving", 25, 50, 75),
    ])
    by = {r["category_name"]: r for r in rows}
    for name, mid in (("Piano tuner", 30), ("Moving company", 50)):
        assert by[name]["cpl_mid"] == mid           # unchanged
        assert by[name]["source"] == "manual_estimate"
        assert by[name]["confidence"] == "low"


def test_unmapped_category_defaults_to_manual():
    rows = llv.build_lead_values([_row("Totally Unknown Trade", "Weird", 11, 22, 33)])
    r = rows[0]
    assert r["cpl_mid"] == 22 and r["source"] == "manual_estimate"


def test_diff_rows_sorted_by_multiplier_desc():
    old = [_row("Water damage restoration service", "Restoration", 75, 138, 200),
           _row("Piano tuner", "Specialty/Niche", 15, 30, 45)]
    new = llv.build_lead_values(old)
    diff = llv.diff_rows(old, new)
    assert diff[0]["category_name"] == "Water damage restoration service"
    assert diff[0]["mult"] > diff[-1]["mult"]
    piano = next(d for d in diff if d["category_name"] == "Piano tuner")
    assert piano["mult"] == 1.0


def test_summarize_counts_confidence_tiers():
    rows = llv.build_lead_values([
        _row("Plumber", "Plumbing", 25, 50, 75),            # high
        _row("Flooring contractor", "Flooring", 25, 52, 80),  # medium
        _row("Piano tuner", "Specialty/Niche", 15, 30, 45),  # low
    ])
    tally = llv.summarize(rows)
    assert tally == {"high": 1, "medium": 1, "low": 1}

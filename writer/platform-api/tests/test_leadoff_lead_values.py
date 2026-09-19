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


# ── HomeAdvisor rungs (job-value formula + observed lead range) ────────────────

def _ha(url, industry="", avg=None, n=0, lc_lo="", lc_hi=""):
    return {"url": url, "sub_job_title": "", "industry": industry,
            "job_value_avg": avg, "job_value_range_low": "", "job_value_range_high": "",
            "job_value_sample_n": n, "job_value_template": "A",
            "lead_cost_low": lc_lo, "lead_cost_high": lc_hi, "lead_cost_note": ""}


def test_no_homeadvisor_rows_is_byte_identical():
    # A manual category the formula WOULD ground stays manual when no CSV is passed.
    manual = _row("Deck builder", "Remodeling/Renovation", 37, 62, 93)
    without = llv.build_lead_values([manual])[0]
    with_none = llv.build_lead_values([manual], homeadvisor_rows=None)[0]
    assert without == with_none
    assert without["source"] == "manual_estimate" and without["cpl_mid"] == 62


def test_observed_lead_range_rung_fence():
    ha = [_ha("https://x/cost/fencing/privacy-fence/", "Fencing", 4300, 0, "55", "175")]
    r = llv.build_lead_values(
        [_row("Fence contractor", "Landscaping/Outdoor", 35, 58, 87)],
        homeadvisor_rows=ha)[0]
    assert r["source"] == "homeadvisor_lead_range" and r["confidence"] == "medium"
    assert r["cpl_low"] == 55 and r["cpl_high"] == 175
    assert r["cpl_mid"] == round(llv.geomean(55, 175))  # 98


def test_job_value_formula_rung_caps_high_ticket():
    # A big-ticket project trade → formula over-shoots → clamped to the cap.
    ha = [_ha("https://x/cost/swimming-pools-hot-tubs-and-saunas/build-a-swimming-pool/",
              "", 41835, 3035)]
    r = llv.build_lead_values(
        [_row("Swimming pool contractor", "Pool/Outdoor", 57, 95, 142)],
        homeadvisor_rows=ha, formula_cpl_cap=150)[0]
    assert r["source"] == "job_value_formula" and r["confidence"] == "low"
    assert r["cpl_mid"] == 150                       # clamped to the cap
    assert r["cpl_low"] == 90 and r["cpl_high"] == 225


def test_job_value_formula_rung_floors_low_ticket():
    ha = [_ha("https://x/cost/cleaning-services/clean-windows/", "", 218, 26006)]
    r = llv.build_lead_values(
        [_row("Window cleaning service", "Exterior", 19, 32, 48)],
        homeadvisor_rows=ha)[0]
    # 218 × 0.42 × 0.22 ≈ 20 — grounded low, above the floor
    assert r["source"] == "job_value_formula"
    assert r["cpl_mid"] == llv.job_value_formula_cpl(218)
    assert r["cpl_mid"] >= llv.FORMULA_CPL_FLOOR


def test_unmapped_manual_stays_manual_even_with_homeadvisor():
    ha = [_ha("https://x/cost/anything/", "", 5000, 100)]
    r = llv.build_lead_values(
        [_row("Piano tuner", "Specialty/Niche", 15, 30, 45)], homeadvisor_rows=ha)[0]
    assert r["source"] == "manual_estimate" and r["cpl_mid"] == 30


def test_job_value_formula_no_match_falls_through_to_manual():
    # Mapped category but the CSV has no matching sub-job → keep manual (no fabrication).
    ha = [_ha("https://x/cost/unrelated/thing/", "", 9999, 50)]
    r = llv.build_lead_values(
        [_row("Deck builder", "Remodeling/Renovation", 37, 62, 93)],
        homeadvisor_rows=ha)[0]
    assert r["source"] == "manual_estimate" and r["cpl_mid"] == 62


def test_weighted_job_value_prefers_samples_then_mean():
    rows = [_ha("a", avg=100, n=900), _ha("b", avg=200, n=100), _ha("c", avg=50, n=0)]
    # weighted by n>0: (100*900 + 200*100) / 1000 = 110 (the n=0 row is ignored)
    assert llv.weighted_job_value(rows) == 110
    # no sampled rows → simple mean of avgs
    assert llv.weighted_job_value([_ha("a", avg=100, n=0), _ha("b", avg=300, n=0)]) == 200
    assert llv.weighted_job_value([]) is None
    assert llv.weighted_job_value([_ha("a", avg=None, n=5)]) is None


def test_job_value_formula_cpl_clamp_math():
    assert llv.job_value_formula_cpl(1000, close_rate=0.42, margin_share=0.22) == 92
    assert llv.job_value_formula_cpl(999999) == llv.FORMULA_CPL_CAP
    assert llv.job_value_formula_cpl(10) == llv.FORMULA_CPL_FLOOR


def test_observed_range_none_when_industry_has_no_lead_cost():
    ha = [_ha("https://x/cost/garages/garage-door-prices/", "Garage door", 725, 0)]
    assert llv.observed_range("Garage door", ha) is None
    assert llv.observed_range("Nonexistent", ha) is None

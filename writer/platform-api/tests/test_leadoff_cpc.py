"""Unit tests for the per-market CPC local modifier (valuation plan v1 step 2)."""
from services import leadoff_cpc

B = {"lo": 0.7, "hi": 1.5, "min_cpc": 0.5}


def test_modifier_ratio_within_bounds():
    # market 1.5x the national median → 1.5x (at the cap)
    assert leadoff_cpc.cpc_modifier(45.0, 30.0, **B) == 1.5
    # market 1.2x → 1.2x
    assert leadoff_cpc.cpc_modifier(36.0, 30.0, **B) == 1.2


def test_modifier_clamped_high_and_low():
    assert leadoff_cpc.cpc_modifier(300.0, 30.0, **B) == 1.5   # hot market capped
    assert leadoff_cpc.cpc_modifier(5.0, 30.0, **B) == 0.7     # cold market floored


def test_missing_or_thin_cpc_is_neutral():
    assert leadoff_cpc.cpc_modifier(None, 30.0, **B) == 1.0
    assert leadoff_cpc.cpc_modifier(45.0, None, **B) == 1.0
    # a sub-min_cpc value on either side is noise → 1.0 (never penalizes)
    assert leadoff_cpc.cpc_modifier(0.2, 30.0, **B) == 1.0
    assert leadoff_cpc.cpc_modifier(45.0, 0.1, **B) == 1.0
    assert leadoff_cpc.cpc_modifier("bad", 30.0, **B) == 1.0


def test_modifier_for_reads_baseline_case_insensitively():
    baseline = {"roofing contractor": 20.0}
    assert leadoff_cpc.modifier_for(30.0, "Roofing Contractor", baseline, B) == 1.5
    # a category not in the baseline degrades to 1.0
    assert leadoff_cpc.modifier_for(30.0, "Unknown", baseline, B) == 1.0
    assert leadoff_cpc.modifier_for(30.0, None, baseline, B) == 1.0


def test_compute_baseline_rows_medians_by_category_name():
    master = [
        {"category_id": "r", "category_cpc": 10.0},
        {"category_id": "r", "category_cpc": 20.0},
        {"category_id": "r", "category_cpc": 30.0},
        {"category_id": "p", "category_cpc": 0},      # zero → skipped
        {"category_id": "p", "category_cpc": None},   # null → skipped
        {"category_id": "x", "category_cpc": 5.0},    # no name → skipped
    ]
    names = {"r": "Roofing contractor", "p": "Plumber"}
    rows = leadoff_cpc.compute_baseline_rows(master, names)
    by = {r["category_name"]: r for r in rows}
    assert by["Roofing contractor"]["median_cpc"] == 20.0
    assert by["Roofing contractor"]["n"] == 3
    # Plumber had only non-positive CPCs → no baseline row
    assert "Plumber" not in by

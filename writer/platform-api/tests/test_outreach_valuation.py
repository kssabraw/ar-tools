"""Pure-logic tests for the missed-opportunity valuation core (Phase A).

No network, no database, no config — the whole module is deterministic math from hand-built inputs.
What matters here: the chain arithmetic is exact and replayable, the two framings behave as designed
(ad-cost-equivalent is a single anchor that drops out when CPC is unknown; missed-revenue is a
low→high band driven by the two soft assumptions), and every "we can't value this" path returns an
explained absence rather than a fabricated zero.
"""
from services import outreach_valuation as ov


# --- pack_capture_rate_from_curve -------------------------------------------------------------


def test_pack_capture_rate_is_mean_over_pack_width():
    # Mean of the three pack positions: (0.33 + 0.11 + 0.07) / 3 = 0.17.
    rate = ov.pack_capture_rate_from_curve({"1": 0.33, "2": 0.11, "3": 0.07}, pack_size=3)
    assert round(rate, 4) == 0.17


def test_pack_capture_rate_counts_missing_positions_as_zero_share():
    # Only position 1 defined: mean over the FULL width of 3 = 0.33 / 3, not 0.33.
    rate = ov.pack_capture_rate_from_curve({"1": 0.33}, pack_size=3)
    assert round(rate, 4) == round(0.33 / 3, 4)


def test_pack_capture_rate_empty_curve_is_zero():
    assert ov.pack_capture_rate_from_curve({}, pack_size=3) == 0.0
    assert ov.pack_capture_rate_from_curve({"1": 0.3}, pack_size=0) == 0.0


# --- missed_fraction --------------------------------------------------------------------------


def test_missed_fraction_basic():
    assert ov.missed_fraction(81, 0) == 1.0
    assert round(ov.missed_fraction(81, 27), 4) == round(54 / 81, 4)
    assert ov.missed_fraction(10, 10) == 0.0


def test_missed_fraction_guards():
    assert ov.missed_fraction(0, 0) == 0.0          # no coverage
    assert ov.missed_fraction(10, 20) == 0.0        # in_pack > live clamps to 0 missed
    assert ov.missed_fraction(10, -3) == 1.0        # negative in_pack floored to 0


# --- resolve_assumptions ----------------------------------------------------------------------

_TABLE = {
    "plumber": {"close_rate_low": 0.2, "close_rate_high": 0.4, "job_value_low": 200, "job_value_high": 500},
    "plumbing contractor": {"close_rate_low": 0.25, "close_rate_high": 0.45, "job_value_low": 800, "job_value_high": 3000},
}
_GLOBAL = {"close_rate_low": 0.1, "close_rate_high": 0.3, "job_value_low": 150, "job_value_high": 400}


def test_resolve_assumptions_containment_match():
    a = ov.resolve_assumptions("Emergency Plumber Service", _TABLE, _GLOBAL)
    assert a.source == "category"
    assert a.vertical == "plumber"
    assert a.job_value_high == 500


def test_resolve_assumptions_prefers_longest_key():
    a = ov.resolve_assumptions("plumbing contractor", _TABLE, _GLOBAL)
    assert a.vertical == "plumbing contractor"
    assert a.job_value_high == 3000


def test_resolve_assumptions_unknown_falls_to_global():
    a = ov.resolve_assumptions("dog groomer", _TABLE, _GLOBAL)
    assert a.source == "global"
    assert a.vertical is None
    assert a.close_rate_high == 0.3


def test_resolve_assumptions_none_category_is_global():
    a = ov.resolve_assumptions(None, _TABLE, _GLOBAL)
    assert a.source == "global"


def test_resolve_assumptions_orders_inverted_band():
    table = {"x": {"close_rate_low": 0.5, "close_rate_high": 0.2, "job_value_low": 900, "job_value_high": 100}}
    a = ov.resolve_assumptions("x", table, _GLOBAL)
    assert a.close_rate_low == 0.2 and a.close_rate_high == 0.5
    assert a.job_value_low == 100 and a.job_value_high == 900


def test_resolve_assumptions_malformed_entry_falls_to_global():
    table = {"plumber": {"close_rate_low": 0.2}}  # missing fields
    a = ov.resolve_assumptions("plumber", table, _GLOBAL)
    assert a.source == "global"


# --- nice_round -------------------------------------------------------------------------------


def test_nice_round():
    assert ov.nice_round(340, 10) == 340
    assert ov.nice_round(3437, 100) == 3400
    assert ov.nice_round(3450, 100) == 3400 or ov.nice_round(3450, 100) == 3500  # banker's rounding
    assert ov.nice_round(-5, 10) == 0
    assert ov.nice_round(7, 0) == 7


# --- build_how_estimated ----------------------------------------------------------------------


def test_how_estimated_names_the_population_scaling_and_assumptions():
    line = ov.build_how_estimated(source="category", downscaled=True, has_cpc=True)
    assert "scaled to the local area by population" in line
    assert "this trade" in line


def test_how_estimated_global_source_says_conservative():
    line = ov.build_how_estimated(source="global", downscaled=False, has_cpc=False)
    assert "conservative" in line


# --- compute_valuation: the happy path --------------------------------------------------------

_ASSUME = ov.CategoryAssumptions(0.2, 0.4, 200, 500, source="category", vertical="plumber")


def test_compute_valuation_happy_path():
    # local_demand = 1000 * 0.5 = 500; missed_fraction = 1.0; pack_capture_rate = 0.17
    # missed_clicks = 500 * 1.0 * 0.17 = 85
    # ad_cost = 85 * 4.0 = 340 (nearest 10)
    # revenue_low  = 85 * 0.2 * 200 = 3400 ; revenue_high = 85 * 0.4 * 500 = 17000
    v = ov.compute_valuation(
        search_volume=1000, cpc=4.0, population_ratio=0.5,
        live_points=81, in_pack_points=0,
        assumptions=_ASSUME, pack_capture_rate=0.17,
    )
    assert v.available is True and v.reason is None
    assert round(v.missed_clicks_monthly, 2) == 85.0
    assert v.local_monthly_demand == 500
    assert v.ad_cost_equivalent_monthly == 340
    assert v.missed_revenue_low_monthly == 3400
    assert v.missed_revenue_high_monthly == 17000
    assert v.missed_revenue_low_monthly <= v.missed_revenue_high_monthly
    assert v.inputs["assumptions_source"] == "category"
    assert "population" in v.how_estimated


def test_compute_valuation_partial_gap():
    # 54 of 81 points missing → fraction 2/3; local_demand 500 → missed_clicks 500*(2/3)*0.17
    v = ov.compute_valuation(
        search_volume=1000, cpc=None, population_ratio=0.5,
        live_points=81, in_pack_points=27,
        assumptions=_ASSUME, pack_capture_rate=0.17,
    )
    assert v.available is True
    assert v.ad_cost_equivalent_monthly is None      # no CPC → anchor drops out
    assert v.missed_revenue_high_monthly is not None  # band still computes
    expected_clicks = 500 * (54 / 81) * 0.17
    assert round(v.missed_clicks_monthly, 4) == round(expected_clicks, 4)


# --- compute_valuation: explained absences ----------------------------------------------------


def test_not_fetched():
    v = ov.compute_valuation(
        search_volume=None, cpc=None, population_ratio=0.5,
        live_points=81, in_pack_points=0,
        assumptions=_ASSUME, pack_capture_rate=0.17, demand_fetched=False,
    )
    assert v.available is False and v.reason == "not_fetched"


def test_no_demand():
    for vol in (None, 0):
        v = ov.compute_valuation(
            search_volume=vol, cpc=4.0, population_ratio=0.5,
            live_points=81, in_pack_points=0,
            assumptions=_ASSUME, pack_capture_rate=0.17,
        )
        assert v.available is False and v.reason == "no_demand"


def test_no_local_scaling():
    v = ov.compute_valuation(
        search_volume=1000, cpc=4.0, population_ratio=None,
        live_points=81, in_pack_points=0,
        assumptions=_ASSUME, pack_capture_rate=0.17,
    )
    assert v.available is False and v.reason == "no_local_scaling"


def test_no_coverage():
    v = ov.compute_valuation(
        search_volume=1000, cpc=4.0, population_ratio=0.5,
        live_points=0, in_pack_points=0,
        assumptions=_ASSUME, pack_capture_rate=0.17,
    )
    assert v.available is False and v.reason == "no_coverage"


def test_not_missing_when_in_pack_everywhere():
    v = ov.compute_valuation(
        search_volume=1000, cpc=4.0, population_ratio=0.5,
        live_points=81, in_pack_points=81,
        assumptions=_ASSUME, pack_capture_rate=0.17,
    )
    assert v.available is False and v.reason == "not_missing"


# --- config parsers ---------------------------------------------------------------------------


def test_parse_ctr_curve():
    assert ov.parse_ctr_curve('{"1": 0.19, "2": 0.1}') == {"1": 0.19, "2": 0.1}
    assert ov.parse_ctr_curve("not json") == {}
    assert ov.parse_ctr_curve("") == {}
    assert ov.parse_ctr_curve('[1,2]') == {}          # non-dict
    assert ov.parse_ctr_curve('{"1": "x"}') == {}     # non-numeric dropped


def test_parse_category_table():
    table = ov.parse_category_table('{"plumber": {"close_rate_low": 0.2}}')
    assert table["plumber"]["close_rate_low"] == 0.2
    assert ov.parse_category_table("garbage") == {}
    assert ov.parse_category_table("") == {}


# --- in_pack_count_from_vector ----------------------------------------------------------------


def test_in_pack_count_from_vector():
    # 1..3 in pack; 0 = measured-absent; 4 = below pack; 255 = dead — only 1,2,3 count.
    assert ov.in_pack_count_from_vector([1, 2, 3, 4, 0, 255], pack_size=3) == 3
    assert ov.in_pack_count_from_vector([1, 1, 2], pack_size=3) == 3
    assert ov.in_pack_count_from_vector([], pack_size=3) == 0
    assert ov.in_pack_count_from_vector([1, 2, 3, 4], pack_size=1) == 1  # only rank 1


# --- spoken_line ------------------------------------------------------------------------------


def test_spoken_line_leads_with_band_then_anchor():
    v = ov.compute_valuation(
        search_volume=1000, cpc=4.0, population_ratio=0.5,
        live_points=81, in_pack_points=0,
        assumptions=_ASSUME, pack_capture_rate=0.17,
    )
    line = ov.spoken_line(v, keyword="plumber", submarket="Los Angeles")
    assert line is not None
    assert "$3,400" in line and "$17,000" in line           # the missed-revenue band leads
    assert "$340/mo to replace that traffic with Google Ads" in line  # the ad-cost anchor
    assert "plumber" in line and "Los Angeles" in line
    assert "Estimated from" in line                         # the how-we-estimated line


def test_spoken_line_none_when_unavailable():
    v = ov.compute_valuation(
        search_volume=None, cpc=None, population_ratio=0.5,
        live_points=81, in_pack_points=0,
        assumptions=_ASSUME, pack_capture_rate=0.17,
    )
    assert ov.spoken_line(v) is None

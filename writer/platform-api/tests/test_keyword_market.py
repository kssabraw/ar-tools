"""Unit tests for keyword market data + estimated-value (Module #4)."""

from __future__ import annotations

from services import keyword_market


def test_ctr_curve_known_positions():
    assert keyword_market.ctr_for_position(1) == 0.281
    assert keyword_market.ctr_for_position(10) == 0.017


def test_ctr_curve_buckets_and_absent():
    assert keyword_market.ctr_for_position(15) == 0.015
    assert keyword_market.ctr_for_position(35) == 0.005
    assert keyword_market.ctr_for_position(80) == 0.001
    assert keyword_market.ctr_for_position(None) == 0.0
    assert keyword_market.ctr_for_position(150) == 0.0


def test_ctr_rounds_fractional_position():
    # 3.2 → position 3
    assert keyword_market.ctr_for_position(3.2) == 0.106


def test_estimate_value_happy():
    # 1000 vol × CTR@3 (0.106) × $4 ≈ 424.0
    assert keyword_market.estimate_monthly_value(1000, 3.0, 4.0) == 424.0


def test_estimate_value_none_when_missing_inputs():
    assert keyword_market.estimate_monthly_value(None, 3.0, 4.0) is None
    assert keyword_market.estimate_monthly_value(1000, None, 4.0) is None
    assert keyword_market.estimate_monthly_value(1000, 3.0, None) is None
    assert keyword_market.estimate_monthly_value(0, 3.0, 4.0) is None


def test_parse_market_items():
    history = [{"year": 2025, "month": 6, "search_volume": 2600}]
    items = [
        {"keyword": "HVAC Repair", "search_volume": 2400, "cpc": 12.5, "competition": "HIGH",
         "monthly_searches": history},
        {"keyword": "no volume"},  # partial
        {"search_volume": 10},     # no keyword → skipped
    ]
    parsed = keyword_market.parse_market_items(items)
    assert parsed["hvac repair"] == {
        "search_volume": 2400, "cpc": 12.5, "competition": "HIGH",
        "monthly_searches": history,
    }
    assert parsed["no volume"]["search_volume"] is None
    assert "search_volume" not in parsed  # the keyword-less item didn't create a bogus key

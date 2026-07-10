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


# --- batch shaping: eligibility + chunking ----------------------------------
# A single keyword over DataForSEO's caps fails the WHOLE request ("Invalid
# Field: 'keywords'"), so ineligible keywords are filtered pre-call; >1000
# keywords are chunked into multiple requests.

def test_market_eligible_accepts_normal_keywords():
    assert keyword_market.market_eligible("emergency plumber sydney")
    assert keyword_market.market_eligible("who's the best plumber")
    assert keyword_market.market_eligible("a a a a a a a a a a")  # exactly 10 words


def test_market_eligible_rejects_over_caps():
    # The live failure case: a full conversational question.
    assert not keyword_market.market_eligible(
        "Who's the best IT support company near me for a law firm with strict compliance needs"
    )
    assert not keyword_market.market_eligible("x" * 81)                 # > 80 chars
    assert not keyword_market.market_eligible(" ".join(["word"] * 11))  # > 10 words
    assert not keyword_market.market_eligible("")
    assert not keyword_market.market_eligible("   ")


def test_partition_keeps_order_and_splits():
    long_kw = "x" * 100
    wordy_kw = " ".join(["w"] * 12)
    eligible, skipped = keyword_market.partition_market_keywords(
        ["good one", long_kw, "another good", wordy_kw]
    )
    assert eligible == ["good one", "another good"]
    assert skipped == [long_kw, wordy_kw]


def test_chunk_keywords_respects_cap():
    kws = [f"kw {i}" for i in range(2500)]
    chunks = keyword_market.chunk_keywords(kws, size=1000)
    assert [len(c) for c in chunks] == [1000, 1000, 500]
    assert chunks[0][0] == "kw 0" and chunks[2][-1] == "kw 2499"
    assert keyword_market.chunk_keywords([], size=1000) == []
    assert keyword_market.chunk_keywords(["a"], size=1000) == [["a"]]


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

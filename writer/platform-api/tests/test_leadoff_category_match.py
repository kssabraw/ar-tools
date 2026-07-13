"""Unit tests for the LeadOff category smart-search resolver (pure, no LLM)."""
from services.leadoff_category_match import (
    NO_DATA,
    normalize_state,
    resolve_llm_result,
    resolve_location,
)

CATS = ["Tree service", "Arborist and tree surgeon", "Plumber",
        "Roofing contractor", "Air conditioning repair service"]
TH = 0.85


class TestResolveLlmResult:
    def test_confident_exact_match(self):
        out = resolve_llm_result({"category": "Roofing contractor", "confidence": 0.95}, CATS, TH)
        assert out == {"matched": True, "category": "Roofing contractor",
                       "label": "Roofing contractor", "confidence": 0.95}

    def test_case_insensitive_match_returns_canonical(self):
        out = resolve_llm_result({"category": "roofing CONTRACTOR", "confidence": 0.9}, CATS, TH)
        assert out["matched"] is True
        assert out["category"] == "Roofing contractor"  # canonical casing

    def test_below_threshold_is_no_data(self):
        out = resolve_llm_result({"category": "Plumber", "confidence": 0.84}, CATS, TH)
        assert out["matched"] is False
        assert out["category"] is None
        assert out["label"] == NO_DATA
        assert out["confidence"] == 0.84  # confidence still surfaced

    def test_at_threshold_matches(self):
        out = resolve_llm_result({"category": "Plumber", "confidence": 0.85}, CATS, TH)
        assert out["matched"] is True and out["category"] == "Plumber"

    def test_none_sentinel_is_no_data(self):
        out = resolve_llm_result({"category": "NONE", "confidence": 0.99}, CATS, TH)
        assert out["matched"] is False and out["label"] == NO_DATA

    def test_category_not_in_list_is_no_data(self):
        out = resolve_llm_result({"category": "Dog walker", "confidence": 0.99}, CATS, TH)
        assert out["matched"] is False and out["category"] is None

    def test_missing_or_garbage_confidence_is_no_data(self):
        assert resolve_llm_result({"category": "Plumber"}, CATS, TH)["matched"] is False
        assert resolve_llm_result({"category": "Plumber", "confidence": "high"}, CATS, TH)["matched"] is False

    def test_confidence_clamped(self):
        out = resolve_llm_result({"category": "Plumber", "confidence": 1.7}, CATS, TH)
        assert out["confidence"] == 1.0 and out["matched"] is True

    def test_empty_result(self):
        out = resolve_llm_result(None, CATS, TH)
        assert out["matched"] is False and out["label"] == NO_DATA


class TestNormalizeState:
    def test_code_passthrough(self):
        assert normalize_state("OH") == "OH"
        assert normalize_state("oh") == "OH"
        assert normalize_state(" nj ") == "NJ"

    def test_full_name(self):
        assert normalize_state("Ohio") == "OH"
        assert normalize_state("new jersey") == "NJ"
        assert normalize_state("District of Columbia") == "DC"

    def test_unknown_is_none(self):
        assert normalize_state("Ontario") is None   # not a US state
        assert normalize_state("XX") is None
        assert normalize_state("") is None
        assert normalize_state(None) is None


class TestResolveLocation:
    def test_full_location(self):
        loc = resolve_location({"city": "Cleveland", "state": "Ohio",
                                "county": "Cuyahoga"})
        assert loc == {"city": "Cleveland", "state": "OH", "county": "Cuyahoga"}

    def test_strips_trailing_county_word(self):
        assert resolve_location({"county": "Hudson County"})["county"] == "Hudson"
        assert resolve_location({"county": "Orleans Parish"})["county"] == "Orleans"

    def test_empty_fields_become_none(self):
        loc = resolve_location({"city": "", "state": "", "county": "  "})
        assert loc == {"city": None, "state": None, "county": None}

    def test_bad_state_dropped_but_city_kept(self):
        # a location-only query with an unparseable state still keeps the city
        loc = resolve_location({"city": "Springfield", "state": "??"})
        assert loc["city"] == "Springfield" and loc["state"] is None

    def test_none_result(self):
        assert resolve_location(None) == {"city": None, "state": None,
                                          "county": None}

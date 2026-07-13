"""Unit tests for the LeadOff category smart-search resolver (pure, no LLM)."""
from services.leadoff_category_match import NO_DATA, resolve_llm_result

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

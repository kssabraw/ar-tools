"""Unit tests for brand-personality extraction (blog_media.visual_profile)."""
from services.blog_media.visual_profile import extract_brand_personality


def test_extracts_and_dedupes_personality_from_both_voices():
    bv = {
        "current_voice": {"personality": ["Authoritative and confident", "Direct and no-nonsense"]},
        "recommended_voice": {"personality": ["Uncompromising and results-driven", "Direct and no-nonsense", "Transparent and trustworthy"]},
    }
    out = extract_brand_personality(bv)
    # deduped (Direct and no-nonsense once), order preserved, lowercased
    assert out == (
        "authoritative and confident, direct and no-nonsense, "
        "uncompromising and results-driven, transparent and trustworthy"
    )


def test_missing_brand_voice_returns_default():
    assert extract_brand_personality(None) == "professional, clear, and credible"
    assert extract_brand_personality({}) == "professional, clear, and credible"
    assert extract_brand_personality({"current_voice": {}}) == "professional, clear, and credible"


def test_trailing_periods_stripped_and_case_insensitive_dedupe():
    bv = {
        "current_voice": {"personality": ["Confident.", "confident"]},
        "recommended_voice": {"personality": ["CONFIDENT"]},
    }
    assert extract_brand_personality(bv) == "confident"

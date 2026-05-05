"""Step 3.1 — Intent classifier keyword pattern pre-check (PRD v2.0.3)."""

from __future__ import annotations

import pytest

from models.brief import IntentSignals
from modules.brief.intent import _keyword_pattern_precheck, classify_intent


# ----------------------------------------------------------------------
# Direct pre-check tests (sync, no LLM)
# ----------------------------------------------------------------------

@pytest.mark.parametrize("kw,expected_intent,expected_conf", [
    # how-to (0.95)
    ("how to open a tiktok shop", "how-to", 0.95),
    ("How To Open a TikTok Shop", "how-to", 0.95),  # case-insensitive
    ("how do i set up a youtube channel", "how-to", 0.95),
    ("how can i lower my hvac bill", "how-to", 0.95),
    ("ways to reduce energy use", "how-to", 0.95),
    ("steps to install solar panels", "how-to", 0.95),
    ("guide to home insulation", "how-to", 0.95),
    # informational (0.90)
    ("what is a tiktok shop", "informational", 0.90),
    ("what are the best practices", "informational", 0.90),
    ("what does seo mean", "informational", 0.90),
    ("definition of permaculture", "informational", 0.90),
    # listicle (0.90)
    ("best hvac systems 2026", "listicle", 0.90),
    ("top mortgage lenders", "listicle", 0.90),
    ("10 ways to save energy", "listicle", 0.90),
    ("5 reasons to switch", "listicle", 0.90),
    ("20 tips for new sellers", "listicle", 0.90),
    # comparison (0.90)
    ("dogs vs cats", "comparison", 0.90),
    ("solar versus wind power", "comparison", 0.90),
    ("rent or buy a home", "comparison", 0.90),
    ("react compared to vue", "comparison", 0.90),
])
def test_pre_check_matches_pattern(kw, expected_intent, expected_conf):
    result = _keyword_pattern_precheck(kw)
    assert result is not None, f"expected match for {kw!r}"
    intent, conf = result
    assert intent == expected_intent
    assert conf == expected_conf


@pytest.mark.parametrize("kw", [
    "tiktok shop tutorial",
    "energy saving",
    "permaculture techniques",
    "hvac maintenance",
    "",
    "   ",
])
def test_pre_check_no_match(kw):
    """Keywords without a matching pattern should fall through."""
    assert _keyword_pattern_precheck(kw) is None


def test_pre_check_strips_and_lowercases():
    assert _keyword_pattern_precheck("  HOW TO Open a Shop  ") == ("how-to", 0.95)


def test_how_to_takes_precedence_over_other_prefixes():
    """A how-to phrasing that also contains 'best' or 'or' should still
    be classified as how-to, not listicle / comparison."""
    # "how to" wins over the substring "or" in "for"
    assert _keyword_pattern_precheck("how to choose the best loan or mortgage") == ("how-to", 0.95)


def test_listicle_num_pattern_requires_plural_noun():
    """Bare numbers without a following plural noun should NOT match
    the listicle pattern (avoids false positives on years, prices, etc.)"""
    # No plural noun after the number → no match
    assert _keyword_pattern_precheck("2026 hvac") is None
    # Plural noun → matches
    assert _keyword_pattern_precheck("2026 systems") == ("listicle", 0.90)


# ----------------------------------------------------------------------
# Full classify_intent flow — the pre-check must short-circuit
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_classify_intent_short_circuits_on_pre_check():
    """When the keyword matches the pre-check, classify_intent must NOT
    consult SERP signals, must NOT call the borderline-ecom LLM, and
    must set review_required=False even at confidence 0.95."""
    # Build SERP signals that would otherwise produce 'ecom' (the most
    # opinionated path) so we can verify the pre-check truly skipped them.
    signals = IntentSignals(shopping_box=True, news_box=False)

    intent, confidence, review = await classify_intent(
        keyword="how to open a tiktok shop",
        signals=signals,
        titles=["Buy TikTok Shop Now", "Shop Discount Codes"],
        top_3_domains=["amazon.com", "shopify.com", "etsy.com"],
    )
    assert intent == "how-to"
    assert confidence == 0.95
    assert review is False  # pre-check unambiguous patterns aren't reviewed


@pytest.mark.asyncio
async def test_classify_intent_falls_through_when_no_pattern_match():
    """When the pre-check doesn't match, the SERP-feature classifier
    runs as before."""
    signals = IntentSignals(news_box=True)
    intent, _, _ = await classify_intent(
        keyword="tiktok shop news",
        signals=signals,
        titles=[],
        top_3_domains=[],
    )
    assert intent == "news"


@pytest.mark.asyncio
async def test_classify_intent_override_beats_pre_check():
    """An explicit override always wins, even over a pre-check match."""
    intent, conf, review = await classify_intent(
        keyword="how to open a tiktok shop",
        signals=IntentSignals(),
        titles=[],
        top_3_domains=[],
        override="comparison",
    )
    assert intent == "comparison"
    assert conf == 1.0
    assert review is False


@pytest.mark.asyncio
async def test_classify_intent_pre_check_logs_match(caplog):
    with caplog.at_level("INFO", logger="modules.brief.intent"):
        await classify_intent(
            keyword="best hvac systems 2026",
            signals=IntentSignals(),
            titles=[],
            top_3_domains=[],
        )
    assert any(r.message == "intent.pre_check_matched" for r in caplog.records)

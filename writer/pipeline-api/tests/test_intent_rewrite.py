"""Step 11.5 — Intent Rewriter tests (PRD v2.4).

Covers the archetype-specific structural rewriting that runs after the
H2 set is finalized. Distinct from `test_brief_framing.py`, which tests
the shape-only validator that runs earlier.

Test surface:
- Pass-through for non-archetype intents (comparison/news/local-seo/etc.)
- Pass-through on empty H2 list
- Per-archetype rewriting (how-to / listicle / informational)
- Softened-flag threshold behavior
- LLM failure → no abort, no mutations
- Malformed LLM response → no abort, no mutations
- FAQ-in-rewrite hard rejection
- Per-H2 index preservation (only mutates the intended H2)
"""

from __future__ import annotations

import pytest

from modules.brief.graph import Candidate
from modules.brief.intent_rewrite import (
    ARCHETYPE_INTENTS,
    SOFTENED_CHANGE_RATIO,
    IntentRewriteResult,
    _change_ratio,
    rewrite_h2s_for_intent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _h2(text: str) -> Candidate:
    return Candidate(text=text, source="serp")  # type: ignore[arg-type]


def _mock_call(response):
    async def _call(system, user, **kw):
        if isinstance(response, Exception):
            raise response
        return response
    return _call


# ---------------------------------------------------------------------------
# _change_ratio unit tests
# ---------------------------------------------------------------------------


def test_change_ratio_identical_strings_zero():
    assert _change_ratio("Set Up Your Shop", "Set Up Your Shop") == 0.0


def test_change_ratio_full_replacement_one():
    assert _change_ratio("What is X", "Configure Y") >= SOFTENED_CHANGE_RATIO


def test_change_ratio_minor_edit_below_threshold():
    # "Set Up Your TikTok Shop" vs "Set Up Your Shop"  → tiny diff
    ratio = _change_ratio("Set Up Your TikTok Shop", "Set Up Your Shop")
    assert ratio < SOFTENED_CHANGE_RATIO


def test_change_ratio_empty_inputs():
    assert _change_ratio("", "") == 0.0
    assert _change_ratio("foo", "") == 1.0
    assert _change_ratio("", "foo") == 1.0


# ---------------------------------------------------------------------------
# Pass-through behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_passthrough_for_non_archetype_intent():
    """Comparison/news/local-seo etc. don't trigger the rewriter."""
    h2s = [_h2("Pricing"), _h2("Support"), _h2("Features")]
    original_texts = [c.text for c in h2s]
    result = await rewrite_h2s_for_intent(
        h2s, keyword="x vs y", title="X vs Y",
        intent="comparison",  # type: ignore[arg-type]
        llm_json_fn=_mock_call({"rewrites": []}),
    )
    assert result.passthrough is True
    assert result.llm_called is False
    assert result.rewritten_indices == []
    # No mutation
    assert [c.text for c in h2s] == original_texts


@pytest.mark.asyncio
async def test_passthrough_on_empty_h2_list():
    result = await rewrite_h2s_for_intent(
        [], keyword="kw", title="T", intent="how-to",
        llm_json_fn=_mock_call({"rewrites": []}),
    )
    assert result.passthrough is True


def test_archetype_intents_are_the_three_we_expect():
    assert ARCHETYPE_INTENTS == frozenset({"how-to", "listicle", "informational"})


# ---------------------------------------------------------------------------
# Per-archetype rewriting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_howto_question_h2s_get_rewritten_to_imperatives():
    """The TikTok ROI failure case: PAA-shaped Q&A H2s on a how-to article
    should be rewritten to action-leading imperatives."""
    h2s = [
        _h2("What Specific Product Listing Elements Have the Biggest Impact?"),
        _h2("How Should I Structure a Bundle?"),
        _h2("What Are the Most Common Reasons Carts Get Abandoned?"),
    ]
    response = {"rewrites": [
        {"index": 0, "text": "Optimize Product Listings for Maximum Conversion"},
        {"index": 1, "text": "Structure Bundles to Lift Average Order Value"},
        {"index": 2, "text": "Reduce Cart Abandonment Through Checkout Adjustments"},
    ]}
    result = await rewrite_h2s_for_intent(
        h2s, keyword="how to increase tiktok shop roi",
        title="How to Increase ROI for Your TikTok Shop",
        intent="how-to",
        llm_json_fn=_mock_call(response),
    )
    assert result.llm_called is True
    assert result.passthrough is False
    assert len(result.rewritten_indices) == 3
    # All three were significantly reframed → softened
    assert len(result.softened_indices) == 3
    assert h2s[0].text.startswith("Optimize")
    assert h2s[1].text.startswith("Structure")
    assert h2s[2].text.startswith("Reduce")


@pytest.mark.asyncio
async def test_listicle_h2s_get_value_leading_rewrites():
    h2s = [
        _h2("Tool A"),
        _h2("Tool B"),
        _h2("Tool C"),
    ]
    response = {"rewrites": [
        {"index": 0, "text": "1. Tool A — Best for Tight-Budget Teams"},
        {"index": 1, "text": "2. Tool B — Best for Enterprise Scale"},
        {"index": 2, "text": "3. Tool C — Best for Solo Creators"},
    ]}
    result = await rewrite_h2s_for_intent(
        h2s, keyword="best tools for x", title="Best Tools for X",
        intent="listicle",
        llm_json_fn=_mock_call(response),
    )
    assert len(result.rewritten_indices) == 3
    assert h2s[0].text.startswith("1. ")
    assert h2s[2].text.startswith("3. ")


@pytest.mark.asyncio
async def test_informational_first_h2_gets_cost_of_inaction_framing():
    h2s = [
        _h2("What Is Search Intent"),
        _h2("Types of Search Intent"),
        _h2("How to Identify Search Intent"),
    ]
    response = {"rewrites": [
        {"index": 0, "text": "Why Misreading Search Intent Quietly Tanks Your Rankings"},
        # H2s 1 and 2 don't change
        {"index": 1, "text": "Types of Search Intent"},
        {"index": 2, "text": "How to Identify Search Intent"},
    ]}
    result = await rewrite_h2s_for_intent(
        h2s, keyword="search intent", title="Understanding Search Intent",
        intent="informational",
        llm_json_fn=_mock_call(response),
    )
    assert 0 in result.rewritten_indices
    assert 1 not in result.rewritten_indices  # unchanged
    assert 2 not in result.rewritten_indices  # unchanged
    assert "Misreading" in h2s[0].text


# ---------------------------------------------------------------------------
# Softened flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minor_rewrite_is_not_softened():
    """A small text adjustment (below SOFTENED_CHANGE_RATIO) should be
    recorded as rewritten but NOT softened."""
    h2s = [_h2("Set Up Your TikTok Shop")]
    response = {"rewrites": [
        {"index": 0, "text": "Set Up Your Shop"},
    ]}
    result = await rewrite_h2s_for_intent(
        h2s, keyword="tiktok shop", title="How to Set Up TikTok Shop",
        intent="how-to",
        llm_json_fn=_mock_call(response),
    )
    assert 0 in result.rewritten_indices
    assert 0 not in result.softened_indices  # change ratio < 0.50


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_exception_does_not_abort_or_mutate():
    h2s = [_h2("What is X?"), _h2("How does X work?")]
    original_texts = [c.text for c in h2s]
    result = await rewrite_h2s_for_intent(
        h2s, keyword="x", title="What is X",
        intent="how-to",
        llm_json_fn=_mock_call(RuntimeError("boom")),
    )
    assert result.llm_called is True
    assert result.llm_failed is True
    assert result.rewritten_indices == []
    assert [c.text for c in h2s] == original_texts


@pytest.mark.asyncio
async def test_malformed_response_does_not_mutate():
    """LLM returns garbage that doesn't match the expected schema."""
    h2s = [_h2("What is X?")]
    original = h2s[0].text
    result = await rewrite_h2s_for_intent(
        h2s, keyword="x", title="X", intent="how-to",
        llm_json_fn=_mock_call({"unexpected": "shape"}),
    )
    assert result.llm_called is True
    assert result.rewritten_indices == []
    assert h2s[0].text == original


@pytest.mark.asyncio
async def test_response_with_no_rewrites_array():
    h2s = [_h2("What is X?")]
    original = h2s[0].text
    result = await rewrite_h2s_for_intent(
        h2s, keyword="x", title="X", intent="how-to",
        llm_json_fn=_mock_call({"rewrites": "not a list"}),
    )
    assert result.rewritten_indices == []
    assert h2s[0].text == original


@pytest.mark.asyncio
async def test_rewrite_containing_faq_is_rejected():
    """The universal-logic rule says H2s containing 'FAQ' must be
    rewritten away. If the LLM ignores that and produces a rewrite
    that STILL contains 'FAQ', we keep the original."""
    h2s = [_h2("Common Questions About X")]
    original = h2s[0].text
    response = {"rewrites": [
        {"index": 0, "text": "FAQ About X"},  # invalid — contains FAQ
    ]}
    result = await rewrite_h2s_for_intent(
        h2s, keyword="x", title="X", intent="how-to",
        llm_json_fn=_mock_call(response),
    )
    assert h2s[0].text == original
    assert 0 not in result.rewritten_indices


@pytest.mark.asyncio
async def test_partial_rewrites_only_mutate_specified_indices():
    """LLM returns rewrites for some H2s but not others; only the
    specified ones are mutated."""
    h2s = [
        _h2("What is X?"),
        _h2("Set Up X"),  # already action-leading
        _h2("How does X work?"),
    ]
    response = {"rewrites": [
        {"index": 0, "text": "Configure X for Your Use Case"},
        # index 1 omitted — already good
        {"index": 2, "text": "Understand How X Works Internally"},
    ]}
    result = await rewrite_h2s_for_intent(
        h2s, keyword="x", title="X", intent="how-to",
        llm_json_fn=_mock_call(response),
    )
    assert h2s[0].text == "Configure X for Your Use Case"
    assert h2s[1].text == "Set Up X"  # untouched
    assert h2s[2].text == "Understand How X Works Internally"
    assert result.rewritten_indices == [0, 2]


@pytest.mark.asyncio
async def test_invalid_index_in_response_is_skipped():
    h2s = [_h2("What is X?")]
    response = {"rewrites": [
        {"index": 0, "text": "Configure X"},
        {"index": 99, "text": "out of range"},
        {"index": "wrong type", "text": "ignored"},
    ]}
    result = await rewrite_h2s_for_intent(
        h2s, keyword="x", title="X", intent="how-to",
        llm_json_fn=_mock_call(response),
    )
    assert h2s[0].text == "Configure X"
    assert result.rewritten_indices == [0]


@pytest.mark.asyncio
async def test_empty_text_in_response_is_skipped():
    h2s = [_h2("What is X?")]
    original = h2s[0].text
    response = {"rewrites": [
        {"index": 0, "text": "   "},  # blank after strip
    ]}
    result = await rewrite_h2s_for_intent(
        h2s, keyword="x", title="X", intent="how-to",
        llm_json_fn=_mock_call(response),
    )
    assert h2s[0].text == original
    assert result.rewritten_indices == []

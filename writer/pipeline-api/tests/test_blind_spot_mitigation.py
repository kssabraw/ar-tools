"""Industry-blind-spot mitigation tests (PRD v2.6).

Covers four new features:
  - #1 Cross-domain analogy instruction in Authority Agent prompt
  - #3 LLM fan-out disagreement detection
  - #8 Customer review research via Perplexity
  - #2 Adversarial editorial critique
"""

from __future__ import annotations

import pytest

from modules.brief.authority import authority_gap_headings
from modules.brief.customer_review_research import (
    MIN_REVIEW_CITATIONS,
    _filter_review_citations,
    _parse_sections as _crr_parse_sections,
    _validate_citations as _crr_validate,
    research_customer_reviews,
)
from modules.brief.editorial_critique import (
    _validate_payload,
    generate_editorial_critique,
)
from modules.brief.llm_disagreement import (
    CONSENSUS_THRESHOLD,
    DisagreementAnalysis,
    analyze_fanout_disagreement,
)
from modules.brief.perplexity_client import PerplexityError, PerplexityUnavailable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_call(response):
    async def _call(*args, **kw):
        if isinstance(response, Exception):
            raise response
        return response

    return _call


def _mock_perplexity(payload):
    async def _call(*, system, user):
        if isinstance(payload, Exception):
            raise payload
        return payload

    return _call


def _perplexity_payload(content: str, citations: list[str]) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "citations": citations,
    }


# ===========================================================================
# #1 — Cross-domain analogy in Authority Agent prompt
# ===========================================================================


@pytest.mark.asyncio
async def test_authority_prompt_includes_cross_domain_perspective():
    """The Authority Agent system prompt MUST include the cross-domain
    analogy instruction so the LLM is pushed to surface angles from
    adjacent industries."""
    captured: dict = {}

    async def capturing(system, user, **kw):
        captured["system"] = system
        return {
            "headings": [
                {"text": "h1", "level": "H3", "scope_alignment_note": "in"},
                {"text": "h2", "level": "H3", "scope_alignment_note": "in"},
                {"text": "h3", "level": "H3", "scope_alignment_note": "in"},
            ]
        }

    await authority_gap_headings(
        keyword="kw",
        existing_headings=[],
        reddit_context=[],
        llm_json_fn=capturing,
    )
    sys = captured["system"]
    assert "CROSS-DOMAIN PERSPECTIVE" in sys
    # Spot-check that the rationale is included so future edits don't
    # accidentally strip the substantive guidance.
    assert "adjacent industr" in sys.lower()


# ===========================================================================
# #3 — LLM disagreement detector
# ===========================================================================


def test_disagreement_unavailable_when_only_one_llm():
    """Need at least 2 LLMs for any meaningful disagreement signal."""
    result = analyze_fanout_disagreement(
        {"llm_fanout_chatgpt": ["query a", "query b"]}
    )
    assert result.available is False
    assert result.contested_topics == []


def test_disagreement_skips_empty_sources():
    """Sources that returned no queries (e.g. failed LLM) shouldn't
    register as a separate LLM voting in the consensus calculation."""
    result = analyze_fanout_disagreement({
        "llm_fanout_chatgpt": ["topic alpha", "topic bravo"],
        "llm_fanout_claude": [],  # failed
        "llm_fanout_gemini": [],  # failed
    })
    assert result.available is False  # only 1 populated source


def test_disagreement_finds_contested_topics():
    """A topic surfaced by 1-of-4 LLMs is contested. The same topic
    surfaced by all 4 isn't."""
    result = analyze_fanout_disagreement({
        "llm_fanout_chatgpt": ["consensus topic", "edge topic from chatgpt"],
        "llm_fanout_claude": ["consensus topic", "another shared topic"],
        "llm_fanout_gemini": ["consensus topic", "another shared topic"],
        "llm_fanout_perplexity": ["consensus topic", "another shared topic"],
    })
    assert result.available is True
    contested_texts = {t.text for t in result.contested_topics}
    assert "edge topic from chatgpt" in contested_texts
    # "another shared topic" surfaced by 3/4 — at the consensus threshold,
    # so not contested
    assert "another shared topic" not in contested_texts
    # "consensus topic" surfaced by 4/4 — definitely not contested
    assert "consensus topic" not in contested_texts


def test_disagreement_score_prefers_rare_specific_topics():
    """A topic surfaced by 1 LLM scores higher than a topic surfaced
    by 2 LLMs (rarity), and multi-word phrases score higher than
    single tokens (specificity)."""
    result = analyze_fanout_disagreement({
        "llm_fanout_chatgpt": ["rare specific multi-word topic", "x"],
        "llm_fanout_claude": ["shared by two only"],
        "llm_fanout_gemini": ["shared by two only"],
        "llm_fanout_perplexity": ["another"],
    })
    by_text = {t.text: t for t in result.contested_topics}
    rare = by_text.get("rare specific multi-word topic")
    shared = by_text.get("shared by two only")
    assert rare is not None and shared is not None
    assert rare.score > shared.score


def test_disagreement_consensus_strength_calculation():
    """consensus_strength = consensus topics / total topics. Verify
    the math against a known input."""
    result = analyze_fanout_disagreement({
        "llm_fanout_chatgpt": ["a", "b", "c"],
        "llm_fanout_claude": ["a", "b", "c"],
        "llm_fanout_gemini": ["a", "b", "c"],
        "llm_fanout_perplexity": ["a", "b", "edge"],  # only 'edge' contested
    })
    # 3 unique topics meet consensus threshold (a, b, c each surfaced 4x);
    # 'edge' is contested. Total unique = 4. Consensus = 3/4 = 0.75.
    assert result.consensus_strength == pytest.approx(0.75)


# ===========================================================================
# #8 — Customer review research
# ===========================================================================


def _crr_good_markdown() -> str:
    return """# Customer Review Insights

## 1. Top Customer Frustrations
- Slow checkout flow on mobile [1]
- Unexpected shipping fees at the last step [2]

## 2. Reasons Customers Switch (Churn Signals)
- Switched to competitor X for better support [3]

## 3. Praised Strengths
- Clear product photography [4]

## 4. Unmet Needs & Feature Requests
- Wish-list export feature [5]

## 5. Marketing-vs-Reality Gaps
- Marketing says "free returns" but customers report restocking fees [1]

## 6. Regulatory / Risk / Trust Angles
- Some users report billing dispute resolution timelines [3]

## 7. Citations
1. https://www.trustpilot.com/review/example.com
2. https://www.g2.com/products/example/reviews
3. https://www.capterra.com/p/12345/Example/reviews/
4. https://www.trustradius.com/products/example
5. https://www.yelp.com/biz/example
"""


def _crr_good_citations() -> list[str]:
    return [
        "https://www.trustpilot.com/review/example.com",
        "https://www.g2.com/products/example/reviews",
        "https://www.capterra.com/p/12345/Example/reviews/",
        "https://www.trustradius.com/products/example",
        "https://www.yelp.com/biz/example",
    ]


def test_customer_review_filter_recognizes_review_platforms():
    citations = [
        "https://www.trustpilot.com/review/x",
        "https://www.g2.com/products/y/reviews",
        "https://www.capterra.com/p/123/y/",
        "https://example.com/blog/article",
        "https://www.yelp.com/biz/y",
        "https://random-blog.net/post",
    ]
    review = _filter_review_citations(citations)
    assert len(review) == 4


def test_customer_review_validates_minimum_citations():
    """Validation fails when fewer than MIN_REVIEW_CITATIONS review URLs."""
    too_few = [
        "https://www.trustpilot.com/review/x",
        "https://example.com/post",
    ]
    review, failure = _crr_validate(too_few)
    assert failure is not None
    assert "too_few_review_citations" in failure


def test_customer_review_validates_passes_with_enough():
    review, failure = _crr_validate(_crr_good_citations())
    assert failure is None
    assert len(review) == 5


def test_customer_review_parses_seven_sections():
    sections = _crr_parse_sections(_crr_good_markdown())
    assert len(sections) == 7
    assert "Top Customer Frustrations" in sections
    assert "Marketing-vs-Reality Gaps" in sections
    assert "Citations" in sections


@pytest.mark.asyncio
async def test_customer_review_happy_path():
    payload = _perplexity_payload(_crr_good_markdown(), _crr_good_citations())
    insights = await research_customer_reviews(
        "best crm software", perplexity_fn=_mock_perplexity(payload)
    )
    assert insights.available is True
    assert insights.fallback_reason is None
    assert insights.citation_count == 5
    assert len(insights.sections) == 7


@pytest.mark.asyncio
async def test_customer_review_unavailable_when_no_api_key():
    async def raise_unavailable(*, system, user):
        raise PerplexityUnavailable("PERPLEXITY_API_KEY not set")

    insights = await research_customer_reviews(
        "kw", perplexity_fn=raise_unavailable
    )
    assert insights.available is False
    assert insights.fallback_reason == "perplexity_unavailable"


@pytest.mark.asyncio
async def test_customer_review_falls_back_after_two_http_errors():
    err = PerplexityError("HTTP 500")
    insights = await research_customer_reviews(
        "kw",
        perplexity_fn=_mock_perplexity(err),
    )
    assert insights.available is False
    assert "perplexity_error" in (insights.fallback_reason or "")


# ===========================================================================
# #2 — Adversarial editorial critique
# ===========================================================================


def test_critique_validates_substantive_payload():
    payload = {
        "stale_framings": [
            "Most articles say X but the actual situation is Y.",
        ],
        "missing_angles": [
            "The H2 outline doesn't address pricing risk under contract X.",
        ],
        "contrarian_takes": [
            "Conventional approach Z may actually backfire because of ABC.",
        ],
        "overall_assessment": "The outline reads as solid but defaults to "
        "SERP-conventional framing in places where a stronger POV would "
        "differentiate the article.",
        "confidence": 0.7,
    }
    critique = _validate_payload(payload)
    assert critique is not None
    assert critique.available is True
    assert len(critique.stale_framings) == 1
    assert critique.confidence == 0.7


def test_critique_rejects_completely_empty_payload():
    """An LLM response with all empty arrays AND no overall assessment
    is treated as no useful signal — caller records fallback_reason."""
    payload = {
        "stale_framings": [],
        "missing_angles": [],
        "contrarian_takes": [],
        "overall_assessment": "",
        "confidence": 0.3,
    }
    critique = _validate_payload(payload)
    assert critique is None


def test_critique_clamps_confidence():
    payload = {
        "stale_framings": [],
        "missing_angles": ["something"],
        "contrarian_takes": [],
        "overall_assessment": "",
        "confidence": 5.0,  # out of range
    }
    critique = _validate_payload(payload)
    assert critique is not None
    assert critique.confidence == 1.0


def test_critique_drops_non_string_list_entries():
    payload = {
        "stale_framings": ["valid", 42, None, "also valid", ""],
        "missing_angles": [],
        "contrarian_takes": [],
        "overall_assessment": "x",
    }
    critique = _validate_payload(payload)
    assert critique is not None
    assert critique.stale_framings == ["valid", "also valid"]


@pytest.mark.asyncio
async def test_critique_returns_unavailable_on_empty_outline():
    """No H2s → no critique to make. Don't waste an LLM call."""
    result = await generate_editorial_critique(
        keyword="kw",
        intent="how-to",
        title="t",
        scope_statement="s",
        selected_h2_texts=[],
    )
    assert result.available is False
    assert result.fallback_reason == "empty_outline"


@pytest.mark.asyncio
async def test_critique_returns_unavailable_on_llm_exception():
    result = await generate_editorial_critique(
        keyword="kw",
        intent="how-to",
        title="t",
        scope_statement="s",
        selected_h2_texts=["H1", "H2"],
        llm_json_fn=_mock_call(RuntimeError("boom")),
    )
    assert result.available is False
    assert "llm_failed" in (result.fallback_reason or "")


@pytest.mark.asyncio
async def test_critique_happy_path():
    response = {
        "stale_framings": ["Stale 1"],
        "missing_angles": ["Missing 1"],
        "contrarian_takes": ["Contrarian 1"],
        "overall_assessment": "Solid but conventional.",
        "confidence": 0.65,
    }
    result = await generate_editorial_critique(
        keyword="kw",
        intent="how-to",
        title="t",
        scope_statement="s",
        selected_h2_texts=["H1", "H2"],
        llm_json_fn=_mock_call(response),
    )
    assert result.available is True
    assert result.stale_framings == ["Stale 1"]
    assert result.confidence == 0.65

"""Heading SEO Optimizer tests (PRD v2.6).

Covers:
- Pass-through when no H2/H3 candidates or no entities available
- Happy path — LLM returns rewrites, structure mutates, indices recorded
- Softened-flag threshold behavior
- Forbidden-term guard rejects rewrites that contain banned text
- LLM exception → no abort, no mutations
- Malformed response → no abort, no mutations
- Order/level mismatch in LLM response is skipped
- Per-zone target metadata is surfaced into the prompt
- Backward-compat zone exposure on ReconciledTerm
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from modules.writer.heading_seo_optimizer import (
    SOFTENED_CHANGE_RATIO,
    _change_ratio,
    _contains_forbidden,
    optimize_headings,
)
from modules.writer.reconciliation import (
    ReconciledTerm,
    _zones_for_term,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _heading(level: str, text: str, order: int) -> dict:
    return {"level": level, "text": text, "order": order, "type": "content", "source": "serp"}


def _entity_term(
    term: str,
    *,
    h2_target: int = 1,
    h2_max: int = 2,
    h3_target: int = 1,
    h3_max: int = 1,
    category: str = "concepts",
) -> ReconciledTerm:
    return ReconciledTerm(
        term=term,
        is_entity=True,
        entity_category=category,
        zones={
            "title": {"min": 0, "target": 1, "max": 1},
            "h1": {"min": 0, "target": 1, "max": 1},
            "h2": {"min": 0, "target": h2_target, "max": h2_max},
            "h3": {"min": 0, "target": h3_target, "max": h3_max},
            "paragraphs": {"min": 1, "target": 3, "max": 5},
        },
    )


def _non_entity_term(term: str) -> ReconciledTerm:
    return ReconciledTerm(term=term, is_entity=False)


def _mock_call(response):
    async def _call(system, user, **kw):
        if isinstance(response, Exception):
            raise response
        _call.last_user = user  # type: ignore[attr-defined]
        return response
    return _call


# ---------------------------------------------------------------------------
# _change_ratio sanity checks (mirrors intent_rewrite.py)
# ---------------------------------------------------------------------------


def test_change_ratio_identical_returns_zero():
    assert _change_ratio("Same text", "Same text") == 0.0


def test_change_ratio_empty_inputs():
    assert _change_ratio("", "") == 0.0
    assert _change_ratio("foo", "") == 1.0


# ---------------------------------------------------------------------------
# Forbidden-term guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,forbidden,expected", [
    ("We offer free consultations", ["free"], "free"),
    ("Optimize your funnel", ["free"], None),
    # Word boundary: "free" inside "freedom" must NOT match
    ("Path to freedom", ["free"], None),
    # Case-insensitive
    ("FREE shipping included", ["free"], "free"),
    # Empty list / empty text
    ("anything", [], None),
    ("", ["free"], None),
])
def test_contains_forbidden_word_boundary(text, forbidden, expected):
    assert _contains_forbidden(text, forbidden) == expected


# ---------------------------------------------------------------------------
# Pass-through behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_h2_h3_candidates_skips():
    """Heading structure with only an H1 and FAQ block has nothing to
    optimize — return original structure with reason populated."""
    structure = [
        {"level": "H1", "text": "Article H1", "order": 1, "type": "content", "source": "serp"},
        {"level": "H2", "text": "FAQs", "order": 2, "type": "faq-header", "source": "serp"},
    ]
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Some Entity")],
        forbidden_terms=[],
        llm_json_fn=_mock_call({"rewrites": []}),
    )
    assert result.skipped_reason == "no_h2_h3_candidates"
    assert result.llm_called is False
    assert result.heading_structure == structure


@pytest.mark.asyncio
async def test_no_entities_available_skips():
    """When SIE returned no terms across any of the three v1.4
    categories, skip silently. A single non-entity n-gram still
    populates the related_keywords bucket — so the LLM is invoked.
    Use an empty term list to verify the skip path."""
    structure = [_heading("H2", "Original H2", 1)]
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[],
        forbidden_terms=[],
        llm_json_fn=_mock_call({"rewrites": []}),
    )
    assert result.skipped_reason == "no_terms_available"
    assert result.llm_called is False


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_rewrites_h2_with_entity():
    """The canonical use case: H2 doesn't contain any entity; LLM
    rewrites it to add one; result mutates structure in place and
    records the rewritten index."""
    structure = [
        _heading("H2", "Set Up Your Shop", 1),
        _heading("H3", "Configure your settings", 2),
    ]
    response = {"rewrites": [
        {"order": 1, "level": "H2", "text": "Set Up Your TikTok Shop with GMV Max"},
        {"order": 2, "level": "H3", "text": "Configure your settings"},  # unchanged
    ]}
    result = await optimize_headings(
        structure,
        keyword="how to set up tiktok shop",
        reconciled_terms=[
            _entity_term("TikTok Shop"),
            _entity_term("GMV Max"),
        ],
        forbidden_terms=[],
        llm_json_fn=_mock_call(response),
    )
    assert result.llm_called is True
    assert 0 in result.rewritten_indices
    assert 1 not in result.rewritten_indices
    assert "TikTok Shop" in result.heading_structure[0]["text"]
    assert result.heading_structure[1]["text"] == "Configure your settings"


@pytest.mark.asyncio
async def test_softened_flag_threshold():
    """Significant rewrites (>50% character change) record `softened`."""
    structure = [_heading("H2", "Old", 1)]
    response = {"rewrites": [
        {"order": 1, "level": "H2", "text": "Completely Different Heading With Many Entities"},
    ]}
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Entity")],
        forbidden_terms=[],
        llm_json_fn=_mock_call(response),
    )
    assert 0 in result.rewritten_indices
    assert 0 in result.softened_indices


@pytest.mark.asyncio
async def test_minor_rewrite_not_softened():
    """A small text adjustment is rewritten but NOT softened."""
    structure = [_heading("H2", "Set Up Your TikTok Shop", 1)]
    response = {"rewrites": [
        {"order": 1, "level": "H2", "text": "Set Up Your TikTok Shop ROI"},
    ]}
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("ROI")],
        forbidden_terms=[],
        llm_json_fn=_mock_call(response),
    )
    assert 0 in result.rewritten_indices
    assert 0 not in result.softened_indices


# ---------------------------------------------------------------------------
# Forbidden-term guard end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rewrite_with_forbidden_term_is_rejected():
    """If the LLM ignores the forbidden list and produces a rewrite
    containing a banned term, the original heading is preserved."""
    structure = [_heading("H2", "Plan Your Shop Setup", 1)]
    response = {"rewrites": [
        {"order": 1, "level": "H2", "text": "Plan Your FREE Shop Setup with Best Tools"},
    ]}
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Best Tools")],
        forbidden_terms=["free"],
        llm_json_fn=_mock_call(response),
    )
    # Original preserved
    assert result.heading_structure[0]["text"] == "Plan Your Shop Setup"
    # Not in rewritten_indices because the rewrite was rejected
    assert 0 not in result.rewritten_indices


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_exception_does_not_mutate():
    structure = [_heading("H2", "Original H2", 1)]
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Some Entity")],
        forbidden_terms=[],
        llm_json_fn=_mock_call(RuntimeError("boom")),
    )
    assert result.llm_called is True
    assert result.llm_failed is True
    assert result.rewritten_indices == []
    assert result.heading_structure[0]["text"] == "Original H2"


@pytest.mark.asyncio
async def test_malformed_response_does_not_mutate():
    structure = [_heading("H2", "Original", 1)]
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Entity")],
        forbidden_terms=[],
        llm_json_fn=_mock_call({"unexpected_shape": True}),
    )
    assert result.rewritten_indices == []
    assert result.heading_structure[0]["text"] == "Original"


@pytest.mark.asyncio
async def test_empty_rewrite_text_skipped():
    structure = [_heading("H2", "Original", 1)]
    response = {"rewrites": [
        {"order": 1, "level": "H2", "text": "  "},  # whitespace only
    ]}
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Entity")],
        forbidden_terms=[],
        llm_json_fn=_mock_call(response),
    )
    assert result.heading_structure[0]["text"] == "Original"


@pytest.mark.asyncio
async def test_order_mismatch_in_llm_response_skipped():
    """LLM returns a rewrite with order=99 (doesn't match input). That
    rewrite is dropped and the matching original is preserved."""
    structure = [_heading("H2", "First", 1)]
    response = {"rewrites": [
        {"order": 99, "level": "H2", "text": "Mismatched"},
    ]}
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Entity")],
        forbidden_terms=[],
        llm_json_fn=_mock_call(response),
    )
    assert result.heading_structure[0]["text"] == "First"
    assert result.rewritten_indices == []


# ---------------------------------------------------------------------------
# Prompt content sanity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_carries_subheadings_aggregate_targets():
    """SIE v1.4 — the user prompt surfaces the H2+H3 aggregate target
    per category so the LLM knows what aggregate distinct count the
    rewrites should hit."""
    captured: dict = {}

    async def capturing(system, user, **kw):
        captured["user"] = user
        return {"rewrites": []}

    structure = [_heading("H2", "Original", 1)]
    await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[
            _entity_term("Entity One"),
            _entity_term("Entity Two"),
        ],
        forbidden_terms=[],
        subheadings_targets={
            "entities": 5, "related_keywords": 3, "keyword_variants": 1,
        },
        llm_json_fn=capturing,
    )
    user = captured["user"]
    assert "Entity One" in user
    # Aggregate targets serialized as JSON in the prompt.
    assert '"entities": 5' in user
    assert '"related_keywords": 3' in user
    assert '"keyword_variants": 1' in user


@pytest.mark.asyncio
async def test_prompt_carries_forbidden_terms():
    captured: dict = {}

    async def capturing(system, user, **kw):
        captured["user"] = user
        return {"rewrites": []}

    structure = [_heading("H2", "Original", 1)]
    await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Entity")],
        forbidden_terms=["free", "best", "guaranteed"],
        llm_json_fn=capturing,
    )
    user = captured["user"]
    assert "free" in user
    assert "best" in user


# ---------------------------------------------------------------------------
# ReconciledTerm zone exposure (regression — ensures _zones_for_term
# pulls all five zones not just paragraphs)
# ---------------------------------------------------------------------------


def test_zones_for_term_pulls_all_five_zones():
    usage_recs = [{
        "term": "TikTok Shop",
        "usage": {
            "title": {"min": 0, "target": 1, "max": 1},
            "h1": {"min": 0, "target": 1, "max": 1},
            "h2": {"min": 0, "target": 2, "max": 3},
            "h3": {"min": 0, "target": 1, "max": 2},
            "paragraphs": {"min": 2, "target": 5, "max": 8},
        },
    }]
    zones = _zones_for_term(usage_recs, "TikTok Shop")
    assert zones["title"]["target"] == 1
    assert zones["h2"]["target"] == 2
    assert zones["h2"]["max"] == 3
    assert zones["paragraphs"]["target"] == 5


def test_zones_for_term_missing_term_returns_zeros():
    usage_recs = [{"term": "Other Term", "usage": {"h2": {"target": 5}}}]
    zones = _zones_for_term(usage_recs, "Not In Recs")
    assert zones["h2"]["target"] == 0
    assert zones["paragraphs"]["target"] == 0
    assert set(zones.keys()) == {"title", "h1", "h2", "h3", "paragraphs"}


def test_zones_for_term_partial_zones_default_to_zero():
    """SIE rec missing some zones → those zones default to all-zero."""
    usage_recs = [{
        "term": "Term",
        "usage": {"h2": {"target": 3, "max": 4}},  # other zones absent
    }]
    zones = _zones_for_term(usage_recs, "Term")
    assert zones["h2"]["target"] == 3
    assert zones["title"]["target"] == 0
    assert zones["paragraphs"]["max"] == 0


# ---------------------------------------------------------------------------
# Robustness fixes — LLM type drift and pre-compiled forbidden regex
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_returns_order_as_string_still_matches():
    """LLM-side type drift: order returned as string instead of int.
    The normalization layer should coerce both sides to int so the
    lookup matches."""
    structure = [_heading("H2", "Original", 1)]
    response = {"rewrites": [
        # `order` as string — should still match input order=1
        {"order": "1", "level": "H2", "text": "Optimize Original With Entity"},
    ]}
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Entity")],
        forbidden_terms=[],
        llm_json_fn=_mock_call(response),
    )
    assert 0 in result.rewritten_indices
    assert "Entity" in result.heading_structure[0]["text"]


@pytest.mark.asyncio
async def test_llm_returns_level_lowercase_still_matches():
    """LLM-side case drift: level as lowercase 'h2' instead of 'H2'.
    Should still match."""
    structure = [_heading("H2", "Original", 1)]
    response = {"rewrites": [
        {"order": 1, "level": "h2", "text": "Optimize Original With Entity"},
    ]}
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Entity")],
        forbidden_terms=[],
        llm_json_fn=_mock_call(response),
    )
    assert 0 in result.rewritten_indices


@pytest.mark.asyncio
async def test_llm_returns_unknown_level_skipped_safely():
    """If LLM returns 'level': 'h4' (not a valid heading level), the
    normalization rejects the key and the rewrite is dropped."""
    structure = [_heading("H2", "Original", 1)]
    response = {"rewrites": [
        {"order": 1, "level": "h4", "text": "Should Be Rejected"},
    ]}
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Entity")],
        forbidden_terms=[],
        llm_json_fn=_mock_call(response),
    )
    assert result.heading_structure[0]["text"] == "Original"
    assert result.rewritten_indices == []


@pytest.mark.asyncio
async def test_llm_returns_non_numeric_order_skipped_safely():
    structure = [_heading("H2", "Original", 1)]
    response = {"rewrites": [
        {"order": "not a number", "level": "H2", "text": "Should Be Rejected"},
    ]}
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Entity")],
        forbidden_terms=[],
        llm_json_fn=_mock_call(response),
    )
    assert result.heading_structure[0]["text"] == "Original"


@pytest.mark.asyncio
async def test_none_reconciled_terms_treated_as_empty():
    """Defensive guard: None instead of [] for reconciled_terms must
    not raise — should skip with no_terms_available (v1.4)."""
    structure = [_heading("H2", "Original", 1)]
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=None,  # type: ignore[arg-type]
        forbidden_terms=[],
        llm_json_fn=_mock_call({"rewrites": []}),
    )
    assert result.skipped_reason == "no_terms_available"


@pytest.mark.asyncio
async def test_none_forbidden_terms_treated_as_empty():
    """Defensive guard: None for forbidden_terms must not raise."""
    structure = [_heading("H2", "Original", 1)]
    response = {"rewrites": [
        {"order": 1, "level": "H2", "text": "Optimize Original With Entity"},
    ]}
    result = await optimize_headings(
        structure,
        keyword="kw",
        reconciled_terms=[_entity_term("Entity")],
        forbidden_terms=None,  # type: ignore[arg-type]
        llm_json_fn=_mock_call(response),
    )
    assert 0 in result.rewritten_indices


def test_forbidden_pattern_dedupes_and_compiles_once():
    """Compiled pattern is built once per call regardless of duplicate
    terms in the input — same brand-voice term often shows up in both
    `banned_terms` and `filtered_terms.avoid`."""
    from modules.writer.heading_seo_optimizer import (
        _compile_forbidden_pattern,
        _match_forbidden_compiled,
    )

    pattern = _compile_forbidden_pattern(["free", "FREE", "free", "best"])
    assert pattern is not None
    # Both word forms still detected
    assert _match_forbidden_compiled("Get free shipping", pattern, ["free", "FREE", "best"]) == "free"
    assert _match_forbidden_compiled("The Best deal", pattern, ["free", "best"]) == "best"
    # Word boundary respected
    assert _match_forbidden_compiled("Path to freedom", pattern, ["free"]) is None


def test_forbidden_pattern_returns_none_for_empty_input():
    from modules.writer.heading_seo_optimizer import _compile_forbidden_pattern

    assert _compile_forbidden_pattern([]) is None
    assert _compile_forbidden_pattern(None) is None  # type: ignore[arg-type]
    assert _compile_forbidden_pattern(["", "", ""]) is None

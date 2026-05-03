"""Step 9 — H2-level authority gap support.

The Universal Authority Agent emits a `level: "H2" | "H3"` per heading.
H3-level gaps continue through Step 8.5b verification and the existing
attachment flow. H2-level gaps go through scope verification + framing
validation in pipeline.py and displace the lowest-priority MMR-selected
H2 if accepting them would exceed the intent template's max_h2_count.

These tests cover the parser side: extraction of `level`, default to H3
when absent, and the MAX_AUTHORITY_GAP_H2_PER_ARTICLE cap.
"""

from __future__ import annotations

import pytest

from modules.brief.authority import (
    MAX_AUTHORITY_GAP_H2_PER_ARTICLE,
    authority_gap_headings,
)


def _llm_mock(response):
    async def _mock(system, user, **kw):
        return response
    return _mock


@pytest.mark.asyncio
async def test_level_field_extracted_from_response():
    """Each emitted Candidate carries authority_gap_level matching the
    LLM's `level` field."""
    response = {"headings": [
        {"text": "Long-term ecosystem dynamics for sellers",
         "scope_alignment_note": "in-scope",
         "level": "H2"},
        {"text": "Cognitive biases that derail decisions",
         "scope_alignment_note": "in-scope",
         "level": "H3"},
        {"text": "Compliance documents to gather first",
         "scope_alignment_note": "in-scope",
         "level": "H3"},
    ]}
    cands = await authority_gap_headings(
        keyword="how to open a tiktok shop",
        existing_headings=["existing 1"],
        reddit_context=[],
        llm_json_fn=_llm_mock(response),
    )
    assert len(cands) == 3
    levels = [c.authority_gap_level for c in cands]
    assert levels == ["H2", "H3", "H3"]


@pytest.mark.asyncio
async def test_level_defaults_to_h3_when_missing():
    """Backward compat: legacy LLM responses without `level` default to
    H3 so older fixtures and prompt variants still work."""
    response = {"headings": [
        {"text": "Heading without level field",
         "scope_alignment_note": "in-scope"},
        {"text": "Second heading also missing level",
         "scope_alignment_note": "in-scope"},
        {"text": "Third heading missing level too",
         "scope_alignment_note": "in-scope"},
    ]}
    cands = await authority_gap_headings(
        keyword="kw",
        existing_headings=[],
        reddit_context=[],
        llm_json_fn=_llm_mock(response),
    )
    assert len(cands) == 3
    assert all(c.authority_gap_level == "H3" for c in cands)


@pytest.mark.asyncio
async def test_legacy_string_only_response_defaults_to_h3():
    """The parser still accepts the bare-string shape (used by older
    test fixtures); those candidates default to H3."""
    response = {"headings": [
        "First plain string heading",
        "Second plain string heading",
        "Third plain string heading",
    ]}
    cands = await authority_gap_headings(
        keyword="kw",
        existing_headings=[],
        reddit_context=[],
        llm_json_fn=_llm_mock(response),
    )
    assert len(cands) == 3
    assert all(c.authority_gap_level == "H3" for c in cands)


@pytest.mark.asyncio
async def test_invalid_level_value_falls_back_to_h3():
    """An unexpected `level` string (e.g. 'h4', 'h1', 'section') is
    treated as H3 — the parser only accepts the two valid literals."""
    response = {"headings": [
        {"text": "Heading with invalid level",
         "scope_alignment_note": "in-scope",
         "level": "h4"},
        {"text": "Heading with weird level",
         "scope_alignment_note": "in-scope",
         "level": "section"},
        {"text": "Heading with valid lowercase",
         "scope_alignment_note": "in-scope",
         "level": "h2"},
    ]}
    cands = await authority_gap_headings(
        keyword="kw",
        existing_headings=[],
        reddit_context=[],
        llm_json_fn=_llm_mock(response),
    )
    assert len(cands) == 3
    # First two reject to H3; third normalizes lowercase 'h2' to 'H2'
    assert cands[0].authority_gap_level == "H3"
    assert cands[1].authority_gap_level == "H3"
    assert cands[2].authority_gap_level == "H2"


@pytest.mark.asyncio
async def test_max_h2_cap_demotes_extras():
    """If the LLM emits more H2-level gaps than MAX_AUTHORITY_GAP_H2_PER_ARTICLE,
    the parser keeps the first N as H2 and demotes the rest to H3."""
    response = {"headings": [
        {"text": "First H2 candidate", "level": "H2",
         "scope_alignment_note": "in-scope"},
        {"text": "Second H2 candidate (will demote)", "level": "H2",
         "scope_alignment_note": "in-scope"},
        {"text": "Third H2 candidate (will demote)", "level": "H2",
         "scope_alignment_note": "in-scope"},
        {"text": "Native H3 candidate", "level": "H3",
         "scope_alignment_note": "in-scope"},
    ]}
    cands = await authority_gap_headings(
        keyword="kw",
        existing_headings=[],
        reddit_context=[],
        llm_json_fn=_llm_mock(response),
    )
    h2_count = sum(1 for c in cands if c.authority_gap_level == "H2")
    h3_count = sum(1 for c in cands if c.authority_gap_level == "H3")
    assert h2_count == MAX_AUTHORITY_GAP_H2_PER_ARTICLE
    assert h3_count == len(cands) - h2_count
    # First H2 wins; the others get demoted in order.
    assert cands[0].authority_gap_level == "H2"
    assert cands[1].authority_gap_level == "H3"
    assert cands[2].authority_gap_level == "H3"
    assert cands[3].authority_gap_level == "H3"


@pytest.mark.asyncio
async def test_prompt_includes_level_assignment_instructions():
    """The system prompt MUST instruct the LLM on level assignment so
    H2 vs H3 isn't an arbitrary choice."""
    captured: dict = {}

    async def capturing(system, user, **kw):
        captured["system"] = system
        return {"headings": [
            {"text": "h1", "level": "H3", "scope_alignment_note": "in"},
            {"text": "h2", "level": "H3", "scope_alignment_note": "in"},
            {"text": "h3", "level": "H3", "scope_alignment_note": "in"},
        ]}

    await authority_gap_headings(
        keyword="kw",
        existing_headings=[],
        reddit_context=[],
        llm_json_fn=capturing,
    )
    sys = captured["system"]
    assert "LEVEL ASSIGNMENT" in sys
    assert "H2" in sys and "H3" in sys
    # Cap reference so the LLM knows there's an outer limit.
    assert "ONE H2-level gap" in sys or "one H2" in sys.lower()


@pytest.mark.asyncio
async def test_prompt_includes_information_gain_discipline():
    """Information Gain Discipline tells the agent to fill gaps in the
    existing-coverage list, not restate it. Surfaces the differentiation
    surface explicitly rather than relying on the implicit dedup check."""
    captured: dict = {}

    async def capturing(system, user, **kw):
        captured["system"] = system
        return {"headings": [
            {"text": "h1", "level": "H3", "scope_alignment_note": "in"},
            {"text": "h2", "level": "H3", "scope_alignment_note": "in"},
            {"text": "h3", "level": "H3", "scope_alignment_note": "in"},
        ]}

    await authority_gap_headings(
        keyword="kw",
        existing_headings=["existing 1", "existing 2"],
        reddit_context=[],
        llm_json_fn=capturing,
    )
    sys = captured["system"]
    assert "INFORMATION GAIN DISCIPLINE" in sys
    # Anchors the gap-finding behavior to the existing-coverage list.
    assert "existing" in sys.lower() and "fill" in sys.lower()


@pytest.mark.asyncio
async def test_prompt_human_behavioral_pillar_has_fears_values_recommendations():
    """The Human/Behavioral pillar carries the three-bucket framing
    (fears/values/recommendations) borrowed from the Reddit research
    methodology so the agent surfaces concrete signals rather than
    generic 'psychological drivers'."""
    captured: dict = {}

    async def capturing(system, user, **kw):
        captured["system"] = system
        return {"headings": [
            {"text": "h1", "level": "H3", "scope_alignment_note": "in"},
            {"text": "h2", "level": "H3", "scope_alignment_note": "in"},
            {"text": "h3", "level": "H3", "scope_alignment_note": "in"},
        ]}

    await authority_gap_headings(
        keyword="kw",
        existing_headings=[],
        reddit_context=[],
        llm_json_fn=capturing,
    )
    sys = captured["system"]
    assert "FEARS" in sys
    assert "VALUES" in sys
    assert "RECOMMENDATIONS" in sys


# ---------------------------------------------------------------------------
# PRD v2.6 — Customer review insights wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_prompt_carries_customer_review_synthesis():
    """When `customer_review_insights_markdown` is supplied, the user
    prompt MUST surface it under a labeled section so the LLM knows
    to ground its Risk/Regulatory pillar and marketing-vs-reality
    angles against it."""
    captured: dict = {}

    async def capturing(system, user, **kw):
        captured["user"] = user
        return {"headings": [
            {"text": "h1", "level": "H3", "scope_alignment_note": "in"},
            {"text": "h2", "level": "H3", "scope_alignment_note": "in"},
            {"text": "h3", "level": "H3", "scope_alignment_note": "in"},
        ]}

    review_md = (
        "## 1. Top Customer Frustrations\n"
        "- Slow checkout flow on mobile\n"
        "## 5. Marketing-vs-Reality Gaps\n"
        "- Marketing claims free returns; customers report restocking fees\n"
    )
    await authority_gap_headings(
        keyword="kw",
        existing_headings=[],
        reddit_context=[],
        customer_review_insights_markdown=review_md,
        llm_json_fn=capturing,
    )
    user = captured["user"]
    assert "Customer review synthesis" in user
    assert "Top Customer Frustrations" in user
    assert "Marketing-vs-Reality Gaps" in user


@pytest.mark.asyncio
async def test_user_prompt_omits_customer_review_section_when_unavailable():
    """If no customer review insights are passed, the section should
    NOT appear in the prompt (don't waste tokens on empty headers)."""
    captured: dict = {}

    async def capturing(system, user, **kw):
        captured["user"] = user
        return {"headings": [
            {"text": "h1", "level": "H3", "scope_alignment_note": "in"},
            {"text": "h2", "level": "H3", "scope_alignment_note": "in"},
            {"text": "h3", "level": "H3", "scope_alignment_note": "in"},
        ]}

    await authority_gap_headings(
        keyword="kw",
        existing_headings=[],
        reddit_context=[],
        # customer_review_insights_markdown intentionally omitted
        llm_json_fn=capturing,
    )
    assert "Customer review synthesis" not in captured["user"]

"""Step 9 - Authority Agent scope-aware inputs (PRD v2.0.3)."""

from __future__ import annotations

import pytest

from modules.brief.authority import (
    MAX_SCOPE_ALIGNMENT_NOTE_LEN,
    authority_gap_headings,
)


def _llm_mock(*responses):
    iterator = iter(responses)

    async def _mock(system, user, **kw):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        return item

    return _mock


@pytest.mark.asyncio
async def test_authority_agent_passes_scope_into_prompt():
    """The agent's user prompt MUST include the title and scope_statement
    when those inputs are supplied (PRD v2.0.3 Step 9)."""
    captured: dict = {}

    async def capturing(system, user, **kw):
        captured["system"] = system
        captured["user"] = user
        # Three distinct heading texts (Levenshtein ratio > 0.15)
        return {"headings": [
            {"text": "Common cognitive biases that derail new sellers",
             "scope_alignment_note": "stays in-scope because ..."},
            {"text": "Tax compliance documents to gather before signup",
             "scope_alignment_note": "in-scope because ..."},
            {"text": "Long-term seller-account ecosystem patterns",
             "scope_alignment_note": "in-scope because ..."},
        ]}

    await authority_gap_headings(
        keyword="how to open a tiktok shop",
        existing_headings=["existing 1"],
        reddit_context=[],
        title="How to Open a TikTok Shop",
        scope_statement="Covers signup-through-first-listing. Does not cover post-launch operations.",
        intent_type="how-to",
        llm_json_fn=capturing,
    )

    # Title + scope + intent flow into the user prompt
    assert "How to Open a TikTok Shop" in captured["user"]
    assert "Does not cover post-launch operations" in captured["user"]
    assert "how-to" in captured["user"]

    # Scope discipline directive present in system prompt
    assert "SCOPE DISCIPLINE" in captured["system"]
    assert "scope_alignment_note" in captured["system"]


@pytest.mark.asyncio
async def test_authority_agent_returns_scope_alignment_notes_on_candidates():
    payload = {"headings": [
        {"text": "Common cognitive biases that derail new sellers",
         "scope_alignment_note": "In-scope: setup specifics"},
        {"text": "Tax compliance documents to gather before signup",
         "scope_alignment_note": "In-scope: form fields"},
        {"text": "Long-term seller-account ecosystem patterns",
         "scope_alignment_note": "In-scope: docs to gather"},
    ]}

    out = await authority_gap_headings(
        keyword="how to open a shop",
        existing_headings=[],
        reddit_context=[],
        title="t", scope_statement="s",
        intent_type="how-to",
        llm_json_fn=_llm_mock(payload),
    )

    assert len(out) == 3
    assert out[0].text == "Common cognitive biases that derail new sellers"
    assert out[0].source == "authority_gap_sme"
    assert out[0].exempt is True
    assert out[0].scope_alignment_note == "In-scope: setup specifics"


@pytest.mark.asyncio
async def test_authority_agent_truncates_long_scope_alignment_note():
    payload = {"headings": [
        {"text": "Common cognitive biases that derail new sellers",
         "scope_alignment_note": "x" * 500},
        {"text": "Tax compliance documents to gather before signup",
         "scope_alignment_note": ""},
        {"text": "Long-term seller-account ecosystem patterns",
         "scope_alignment_note": "ok"},
    ]}
    out = await authority_gap_headings(
        keyword="k", existing_headings=[], reddit_context=[],
        title="t", scope_statement="s", intent_type="how-to",
        llm_json_fn=_llm_mock(payload),
    )
    assert len(out[0].scope_alignment_note) <= MAX_SCOPE_ALIGNMENT_NOTE_LEN
    # Empty notes should normalize to None on the candidate
    assert out[1].scope_alignment_note is None


@pytest.mark.asyncio
async def test_authority_agent_backward_compat_with_string_payload():
    """Older mocks that returned a flat list of strings (legacy v2.0.x
    shape) still work - scope_alignment_note just stays None."""
    payload = {"headings": [
        "Common cognitive biases that derail new sellers",
        "Tax compliance documents to gather before signup",
        "Long-term seller-account ecosystem patterns",
    ]}
    out = await authority_gap_headings(
        keyword="k", existing_headings=[], reddit_context=[],
        llm_json_fn=_llm_mock(payload),
    )
    assert len(out) == 3
    assert out[0].text == "Common cognitive biases that derail new sellers"
    assert out[0].scope_alignment_note is None


@pytest.mark.asyncio
async def test_authority_agent_works_without_scope_inputs():
    """Backward compat: if scope_statement/title/intent_type aren't
    supplied, the agent still runs (just without scope guardrails)."""
    payload = {"headings": [
        {"text": "Common cognitive biases that derail new sellers",
         "scope_alignment_note": ""},
        {"text": "Tax compliance documents to gather before signup",
         "scope_alignment_note": ""},
        {"text": "Long-term seller-account ecosystem patterns",
         "scope_alignment_note": ""},
    ]}
    out = await authority_gap_headings(
        keyword="k", existing_headings=[], reddit_context=[],
        llm_json_fn=_llm_mock(payload),
    )
    assert len(out) == 3

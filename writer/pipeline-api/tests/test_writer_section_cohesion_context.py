"""Section cohesion context — verify each section prompt receives:
  (A) article_title + sibling_h2_titles + ▶ marker on current section
  (B) preceding_section_summaries built incrementally as the loop
      progresses through the body sections

Both are free additions (no extra LLM calls) that defend against
the most common cohesion failures: tonal drift section-to-section,
and repetition of setups/definitions that an earlier section
already established.
"""

from __future__ import annotations

import pytest

from modules.writer.banned_terms import build_banned_regex
from modules.writer.reconciliation import FilteredSIETerms
from modules.writer.sections import write_h2_group


def _capturing(response):
    captured = {}

    async def _call(system, user, **kw):
        captured["user"] = user
        return response

    return _call, captured


@pytest.mark.asyncio
async def test_section_prompt_carries_article_title(monkeypatch):
    call, captured = _capturing({
        "h2_body": " ".join(["w"] * 200),
        "h3_bodies": [],
    })
    monkeypatch.setattr("modules.writer.sections.claude_json", call)

    h2_item = {"order": 3, "text": "Optimize Your TikTok Shop ROI",
               "type": "content", "level": "H2"}
    await write_h2_group(
        keyword="kw", intent="how-to",
        h2_item=h2_item, h3_items=[],
        section_budgets={3: 300},
        filtered_terms=FilteredSIETerms(),
        citations=[], brand_voice_card=None,
        banned_regex=build_banned_regex([]),
        article_title="How to Increase ROI for Your TikTok Shop",
    )
    assert "ARTICLE_TITLE: How to Increase ROI for Your TikTok Shop" in captured["user"]


@pytest.mark.asyncio
async def test_section_prompt_carries_sibling_outline_with_current_marker(monkeypatch):
    call, captured = _capturing({"h2_body": " ".join(["w"] * 200), "h3_bodies": []})
    monkeypatch.setattr("modules.writer.sections.claude_json", call)

    siblings = [
        "Optimize Your TikTok Shop ROI",
        "Use Content Hooks That Convert",
        "Read Analytics Signals",
        "Improve Your Performance Score",
    ]
    h2_item = {"order": 4, "text": "Use Content Hooks That Convert",
               "type": "content", "level": "H2"}
    await write_h2_group(
        keyword="kw", intent="how-to",
        h2_item=h2_item, h3_items=[],
        section_budgets={4: 300},
        filtered_terms=FilteredSIETerms(),
        citations=[], brand_voice_card=None,
        banned_regex=build_banned_regex([]),
        sibling_h2_titles=siblings,
        current_h2_index=1,  # the second sibling
    )
    user = captured["user"]
    assert "ARTICLE_OUTLINE" in user
    # All siblings listed.
    for s in siblings:
        assert s in user
    # Current section marked with ▶.
    assert "▶ 2. Use Content Hooks That Convert" in user
    # Other siblings get a non-▶ marker.
    assert "  1. Optimize Your TikTok Shop ROI" in user
    assert "  3. Read Analytics Signals" in user


@pytest.mark.asyncio
async def test_section_prompt_carries_preceding_section_summaries(monkeypatch):
    call, captured = _capturing({"h2_body": " ".join(["w"] * 200), "h3_bodies": []})
    monkeypatch.setattr("modules.writer.sections.claude_json", call)

    summaries = [
        "Section 1 (Inventory Trap): Discusses cash-flow timing and SKU velocity tiers.",
        "Section 2 (Content Hooks): Covers video structure and CTA placement.",
    ]
    h2_item = {"order": 5, "text": "Read Analytics Signals",
               "type": "content", "level": "H2"}
    await write_h2_group(
        keyword="kw", intent="how-to",
        h2_item=h2_item, h3_items=[],
        section_budgets={5: 300},
        filtered_terms=FilteredSIETerms(),
        citations=[], brand_voice_card=None,
        banned_regex=build_banned_regex([]),
        preceding_section_summaries=summaries,
    )
    user = captured["user"]
    assert "PRECEDING_SECTIONS" in user
    assert "do NOT restate" in user
    assert "Inventory Trap" in user
    assert "Content Hooks" in user


@pytest.mark.asyncio
async def test_outline_skips_empty_sibling_titles_without_breaking_marker(monkeypatch):
    """Defensive: if an H2 in the brief has empty text, it must NOT
    render as a blank-numbered row, and the ▶ marker on a later
    section must stay on the section the writer actually intended.
    Regression for the h2_titles-filter bug where filtering empties
    re-indexed and misaligned current_h2_index."""
    call, captured = _capturing({"h2_body": " ".join(["w"] * 200), "h3_bodies": []})
    monkeypatch.setattr("modules.writer.sections.claude_json", call)

    siblings = [
        "Optimize ROI",
        "",  # an empty H2 in the brief — desync trap
        "Read Analytics",
        "Performance Score",
    ]
    h2_item = {"order": 6, "text": "Read Analytics",
               "type": "content", "level": "H2"}
    await write_h2_group(
        keyword="kw", intent="how-to",
        h2_item=h2_item, h3_items=[],
        section_budgets={6: 300},
        filtered_terms=FilteredSIETerms(),
        citations=[], brand_voice_card=None,
        banned_regex=build_banned_regex([]),
        sibling_h2_titles=siblings,
        current_h2_index=2,  # "Read Analytics" — third in the original list
    )
    user = captured["user"]
    # Empty entry must NOT produce a "  2. " line.
    assert "  2. " not in user
    assert "▶ 2. " not in user
    # ▶ marker stays on the original index 2 ("Read Analytics"), preserving
    # the writer's intended numbering rather than re-indexing.
    assert "▶ 3. Read Analytics" in user
    # First and fourth still rendered with their original indices.
    assert "  1. Optimize ROI" in user
    assert "  4. Performance Score" in user


@pytest.mark.asyncio
async def test_section_prompt_omits_cohesion_blocks_when_args_absent(monkeypatch):
    """Backward compat: legacy callers that don't pass the new kwargs
    get the old prompt shape — no ARTICLE_TITLE / ARTICLE_OUTLINE /
    PRECEDING_SECTIONS lines."""
    call, captured = _capturing({"h2_body": " ".join(["w"] * 200), "h3_bodies": []})
    monkeypatch.setattr("modules.writer.sections.claude_json", call)

    h2_item = {"order": 3, "text": "Some Section",
               "type": "content", "level": "H2"}
    await write_h2_group(
        keyword="kw", intent="how-to",
        h2_item=h2_item, h3_items=[],
        section_budgets={3: 300},
        filtered_terms=FilteredSIETerms(),
        citations=[], brand_voice_card=None,
        banned_regex=build_banned_regex([]),
    )
    user = captured["user"]
    assert "ARTICLE_TITLE" not in user
    assert "ARTICLE_OUTLINE" not in user
    assert "PRECEDING_SECTIONS" not in user


@pytest.mark.asyncio
async def test_first_section_has_no_preceding_summaries_subsequent_sections_do(monkeypatch):
    """Integration-style: simulate the running-summary loop from
    pipeline.py. Section #1's prompt has empty PRECEDING_SECTIONS
    (or omits the block); section #2's prompt carries section #1's
    summary; section #3's prompt carries both."""
    captured_users: list[str] = []

    async def _call(system, user, **kw):
        captured_users.append(user)
        return {"h2_body": "Body sentence one. Body continued.",
                "h3_bodies": []}

    monkeypatch.setattr("modules.writer.sections.claude_json", _call)

    siblings = ["A", "B", "C"]
    running: list[str] = []
    for idx, h2_text in enumerate(siblings):
        h2_item = {"order": 3 + idx, "text": h2_text,
                   "type": "content", "level": "H2"}
        result = await write_h2_group(
            keyword="kw", intent="how-to",
            h2_item=h2_item, h3_items=[],
            section_budgets={3 + idx: 300},
            filtered_terms=FilteredSIETerms(),
            citations=[], brand_voice_card=None,
            banned_regex=build_banned_regex([]),
            sibling_h2_titles=siblings,
            current_h2_index=idx,
            preceding_section_summaries=list(running),
        )
        # Append THIS section's heading-summary to the running list,
        # mirroring pipeline.py's _build_section_summaries usage.
        for s in result.sections:
            if s.level == "H2" and s.type == "content" and s.body:
                first = s.body.split(".")[0]
                running.append(f"{s.heading}: {first}")

    # Section #1: no PRECEDING_SECTIONS block (running was empty).
    assert "PRECEDING_SECTIONS" not in captured_users[0]
    # Section #2: running has one summary from section #1.
    assert "PRECEDING_SECTIONS" in captured_users[1]
    assert "A:" in captured_users[1]
    # Section #3: running has summaries from sections #1 and #2.
    assert "PRECEDING_SECTIONS" in captured_users[2]
    assert "A:" in captured_users[2]
    assert "B:" in captured_users[2]

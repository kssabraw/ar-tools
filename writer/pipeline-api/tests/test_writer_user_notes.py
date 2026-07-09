"""Per-run user notes (WriterRequest.user_notes) - verify the free-form
editorial guidance typed at run creation reaches the section, intro, and
conclusion prompts, and that absent notes leave the prompts unchanged.
"""

from __future__ import annotations

import pytest

from modules.writer.banned_terms import build_banned_regex
from modules.writer.conclusion import write_conclusion
from modules.writer.intro import write_intro
from modules.writer.reconciliation import FilteredSIETerms
from modules.writer.sections import write_h2_group

_NOTES = "Mention Zero Down Supply Chain Services as one of the top 10 best."


def _capturing(response):
    captured = {}

    async def _call(system, user, **kw):
        captured["user"] = user
        return response

    return _call, captured


@pytest.mark.asyncio
async def test_section_prompt_carries_user_notes(monkeypatch):
    call, captured = _capturing({"sections": [
        {"order": 3, "heading": "H", "body": " ".join(["w"] * 200)},
    ]})
    monkeypatch.setattr("modules.writer.sections.claude_json", call)

    h2_item = {"order": 3, "text": "Top Freight Audit Companies",
               "type": "content", "level": "H2"}
    await write_h2_group(
        keyword="kw", intent="listicle",
        h2_item=h2_item, h3_items=[],
        section_budgets={3: 300},
        filtered_terms=FilteredSIETerms(),
        citations=[], brand_voice_card=None,
        banned_regex=build_banned_regex([]),
        user_notes=_NOTES,
    )
    assert "USER_NOTES" in captured["user"]
    assert _NOTES in captured["user"]


@pytest.mark.asyncio
async def test_section_prompt_omits_notes_block_when_absent(monkeypatch):
    call, captured = _capturing({"sections": [
        {"order": 3, "heading": "H", "body": " ".join(["w"] * 200)},
    ]})
    monkeypatch.setattr("modules.writer.sections.claude_json", call)

    h2_item = {"order": 3, "text": "Top Freight Audit Companies",
               "type": "content", "level": "H2"}
    await write_h2_group(
        keyword="kw", intent="listicle",
        h2_item=h2_item, h3_items=[],
        section_budgets={3: 300},
        filtered_terms=FilteredSIETerms(),
        citations=[], brand_voice_card=None,
        banned_regex=build_banned_regex([]),
    )
    assert "USER_NOTES" not in captured["user"]


@pytest.mark.asyncio
async def test_intro_prompt_carries_user_notes(monkeypatch):
    call, captured = _capturing({"intro": " ".join(["w"] * 100)})
    monkeypatch.setattr("modules.writer.intro.claude_json", call)

    await write_intro(
        keyword="kw",
        title="10 Best Freight Audit Companies",
        scope_statement="",
        intent_type="listicle",
        h2_list=[],
        brand_voice_card=None,
        banned_regex=build_banned_regex([]),
        intro_order=0,
        user_notes=_NOTES,
    )
    assert "USER_NOTES" in captured["user"]
    assert _NOTES in captured["user"]


@pytest.mark.asyncio
async def test_conclusion_prompt_carries_user_notes(monkeypatch):
    call, captured = _capturing({"conclusion": ("kw " + " ".join(["w"] * 110)).strip()})
    monkeypatch.setattr("modules.writer.conclusion.claude_json", call)

    await write_conclusion(
        keyword="kw",
        intent_type="listicle",
        section_summaries=["point one", "point two"],
        brand_voice_card=None,
        banned_regex=build_banned_regex([]),
        conclusion_order=0,
        user_notes=_NOTES,
    )
    assert "USER_NOTES" in captured["user"]
    assert _NOTES in captured["user"]

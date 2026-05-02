"""Tests for the structured ICP fields added to BrandVoiceCard
(audience_personas, audience_verticals, audience_company_size) and
their prompt injection into section / intro / conclusion writers.

Pre-existing fields (audience_summary, audience_pain_points,
audience_goals) are also re-asserted to lock the new prompt shapes.
"""

from __future__ import annotations

import pytest

from models.writer import BrandVoiceCard
from modules.writer.banned_terms import build_banned_regex
from modules.writer.conclusion import write_conclusion
from modules.writer.distillation import _parse_card, is_card_empty
from modules.writer.intro import write_intro


# -----------------------------------------------------------------------
# Distillation parser
# -----------------------------------------------------------------------

def test_parse_card_extracts_structured_icp_fields():
    raw = {
        "audience_personas": ["VP of Growth", "Director of Marketing", "CMO"],
        "audience_verticals": ["Beauty", "Health & Wellness", "Pet Care"],
        "audience_company_size": "$20M+ ARR (sweet spot $30M–$100M)",
    }
    card = _parse_card(raw)
    assert card.audience_personas == ["VP of Growth", "Director of Marketing", "CMO"]
    assert card.audience_verticals == ["Beauty", "Health & Wellness", "Pet Care"]
    assert card.audience_company_size == "$20M+ ARR (sweet spot $30M–$100M)"


def test_parse_card_icp_fields_default_empty():
    """Older distillation payloads (no structured ICP fields) parse cleanly."""
    card = _parse_card({"tone_adjectives": ["clear"]})
    assert card.audience_personas == []
    assert card.audience_verticals == []
    assert card.audience_company_size == ""


def test_parse_card_icp_fields_capped():
    raw = {
        "audience_personas": [f"persona_{i}" for i in range(20)],
        "audience_verticals": [f"vertical_{i}" for i in range(20)],
        "audience_company_size": "X" * 200,
    }
    card = _parse_card(raw)
    assert len(card.audience_personas) == 8
    assert len(card.audience_verticals) == 12
    assert len(card.audience_company_size) <= 120


def test_is_card_empty_treats_icp_fields_as_signal():
    """A card whose only populated fields are the new ICP structured
    fields should NOT be considered empty."""
    card = BrandVoiceCard(audience_verticals=["Beauty"])
    assert is_card_empty(card) is False


# -----------------------------------------------------------------------
# Intro prompt receives ICP signals + goals
# -----------------------------------------------------------------------

def _fake(*responses):
    iterator = iter(responses)

    async def _call(system, user, **kw):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        _call.last_user = user  # type: ignore[attr-defined]
        return item

    _call.last_user = ""  # type: ignore[attr-defined]
    return _call


@pytest.mark.asyncio
async def test_intro_prompt_includes_personas_verticals_goals(monkeypatch):
    body = " ".join(["word"] * 100)
    fake = _fake({"intro": body})
    monkeypatch.setattr("modules.writer.intro.claude_json", fake)

    card = BrandVoiceCard(
        audience_summary="B2C marketing leaders",
        audience_personas=["VP Growth", "CMO"],
        audience_verticals=["Beauty", "Pet Care"],
        audience_company_size="$30M–$100M ARR",
        audience_goals=["Predictable acquisition", "Reduce paid social"],
    )
    await write_intro(
        keyword="kw", title="t", scope_statement="",
        intent_type="how-to", h2_list=["A", "B"],
        brand_voice_card=card, banned_regex=build_banned_regex([]),
        intro_order=1,
    )
    user = fake.last_user  # type: ignore[attr-defined]
    assert "VP Growth" in user and "CMO" in user
    assert "Beauty" in user and "Pet Care" in user
    assert "$30M–$100M ARR" in user
    assert "Predictable acquisition" in user
    assert "Promise beat should advance" in user


# -----------------------------------------------------------------------
# Conclusion prompt receives full ICP context
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conclusion_prompt_includes_pain_points_and_goals(monkeypatch):
    body = " ".join(["word"] * 100)
    fake = _fake({"conclusion": body})
    monkeypatch.setattr("modules.writer.conclusion.claude_json", fake)

    card = BrandVoiceCard(
        audience_summary="B2C marketing leaders",
        audience_personas=["VP Growth"],
        audience_verticals=["Beauty"],
        audience_pain_points=["Rising paid social CAC", "Measurement difficulty"],
        audience_goals=["Predictable acquisition", "Scale without big team"],
    )
    await write_conclusion(
        keyword="kw", intent_type="how-to",
        section_summaries=["Section A: foo"],
        brand_voice_card=card, banned_regex=build_banned_regex([]),
        conclusion_order=10,
    )
    user = fake.last_user  # type: ignore[attr-defined]
    assert "Rising paid social CAC" in user
    assert "Predictable acquisition" in user
    assert "closing should reinforce" in user
    assert "Beauty" in user


# -----------------------------------------------------------------------
# Section prompt receives ICP signals + goals + verticals directive
# -----------------------------------------------------------------------

def test_section_prompt_includes_full_icp_block():
    from modules.writer.sections import _build_section_user_prompt

    card = BrandVoiceCard(
        audience_summary="B2C marketing leaders",
        audience_personas=["VP Growth", "CMO"],
        audience_verticals=["Beauty", "Health & Wellness"],
        audience_company_size="$30M–$100M ARR",
        audience_pain_points=["Rising CAC"],
        audience_goals=["Predictable acquisition"],
    )
    prompt = _build_section_user_prompt(
        keyword="kw",
        intent="informational",
        h2_item={"order": 2, "text": "Some H2"},
        h3_items=[],
        section_budgets={2: 200},
        required_terms=[],
        excluded_terms=[],
        avoid_terms=[],
        forbidden_terms=[],
        citations=[],
        brand_voice_card=card,
        is_authority_gap_section=False,
    )
    assert "personas: VP Growth, CMO" in prompt
    assert "company size: $30M–$100M ARR" in prompt
    assert "verticals: Beauty, Health & Wellness" in prompt
    assert "ground it in one of these verticals" in prompt
    assert "goals" in prompt and "Predictable acquisition" in prompt
    assert "advance one of these" in prompt

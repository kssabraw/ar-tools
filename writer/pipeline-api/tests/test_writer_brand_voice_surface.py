"""Verify preferred_terms + discouraged_terms surface in every writer
prompt. Distillation extracts the brand's `do_say` vocabulary into
preferred_terms but the four writer prompt builders (sections, intro,
conclusion, faqs) used to drop it on the floor - leaving the LLM with
only forbidden_terms (negative signal) and no positive signal about
what the brand wants to sound like.
"""

from __future__ import annotations

import asyncio

import pytest

from models.writer import BrandVoiceCard
from modules.writer.banned_terms import build_banned_regex
from modules.writer.reconciliation import FilteredSIETerms


def _card_with_preferred() -> BrandVoiceCard:
    return BrandVoiceCard(
        brand_name="Ubiquitous",
        tone_adjectives=["Innovative", "Approachable", "Witty", "Confident"],
        voice_directives=[
            "Direct and authoritative with practical, execution-focused edge",
            "Confident without being hype-driven",
        ],
        preferred_terms=[
            "creators", "brand-safe", "ROI", "data-driven", "scalable",
            "paid amplification", "full-funnel", "whitelisting", "ROAS", "CPM",
        ],
        discouraged_terms=["magic", "guaranteed viral", "spam"],
        banned_terms=["Ubiquitous Influence"],
        audience_summary="B2C brands $20M+ ARR",
    )


def _capturing(response):
    captured = {}

    async def _call(system, user, **kw):
        captured["user"] = user
        captured["system"] = system
        return response

    return _call, captured


# ---------------------------------------------------------------------------
# sections.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_prompt_surfaces_preferred_and_discouraged_terms(monkeypatch):
    from modules.writer.sections import write_h2_group

    call, captured = _capturing({
        "h2_body": " ".join(["word"] * 250),
        "h3_bodies": [],
    })
    monkeypatch.setattr("modules.writer.sections.claude_json", call)

    h2_item = {"order": 2, "text": "Section Title", "type": "content", "level": "H2"}
    await write_h2_group(
        keyword="kw", intent="how-to",
        h2_item=h2_item, h3_items=[],
        section_budgets={2: 300},
        filtered_terms=FilteredSIETerms(),
        citations=[],
        brand_voice_card=_card_with_preferred(),
        banned_regex=build_banned_regex([]),
    )
    user = captured["user"]
    # Tone adjectives must be prominent.
    assert "Innovative" in user
    assert "Witty" in user
    # Preferred terms must appear.
    assert "FAVORED_PHRASING" in user.upper() or "favored phrasing" in user.lower()
    assert "creators" in user
    assert "ROI" in user
    assert "whitelisting" in user
    # Discouraged terms must appear distinct from banned.
    assert "DISCOURAGED" in user.upper() or "discouraged" in user.lower()
    assert "magic" in user


# ---------------------------------------------------------------------------
# intro.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intro_prompt_surfaces_preferred_and_discouraged_terms(monkeypatch):
    from modules.writer.intro import write_intro

    call, captured = _capturing({
        "agree_style_selected": "direct_thesis",
        "agree": " ".join(["word"] * 30),
        "promise": " ".join(["word"] * 27),
        "preview": " ".join(["word"] * 25),
    })
    monkeypatch.setattr("modules.writer.intro.claude_json", call)

    await write_intro(
        keyword="kw",
        title="Title",
        scope_statement="defines the scope",
        intent_type="how-to",
        h2_list=["A", "B", "C", "D"],
        brand_voice_card=_card_with_preferred(),
        banned_regex=build_banned_regex([]),
        intro_order=1,
    )
    user = captured["user"]
    assert "Innovative" in user and "Witty" in user
    assert "FAVORED_PHRASING" in user
    assert "ROI" in user
    assert "DISCOURAGED" in user
    assert "magic" in user


# ---------------------------------------------------------------------------
# conclusion.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conclusion_prompt_surfaces_preferred_and_discouraged_terms(monkeypatch):
    from modules.writer.conclusion import write_conclusion

    call, captured = _capturing({"conclusion": " ".join(["word"] * 100)})
    monkeypatch.setattr("modules.writer.conclusion.claude_json", call)

    await write_conclusion(
        keyword="kw",
        intent_type="how-to",
        section_summaries=["A: foo", "B: bar"],
        brand_voice_card=_card_with_preferred(),
        banned_regex=build_banned_regex([]),
        conclusion_order=10,
    )
    user = captured["user"]
    assert "Innovative" in user and "Witty" in user
    assert "FAVORED_PHRASING" in user
    assert "scalable" in user
    assert "DISCOURAGED" in user
    assert "magic" in user


# ---------------------------------------------------------------------------
# faqs.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_faq_prompt_surfaces_preferred_and_discouraged_terms(monkeypatch):
    from modules.writer.faqs import write_faqs

    call, captured = _capturing({"faqs": [
        {"question": "Q1?", "answer": "answer text " * 10},
    ]})
    monkeypatch.setattr("modules.writer.faqs.claude_json", call)

    await write_faqs(
        keyword="kw",
        faq_questions=["Q1?"],
        filtered_terms=FilteredSIETerms(),
        brand_voice_card=_card_with_preferred(),
        banned_regex=build_banned_regex([]),
    )
    user = captured["user"]
    assert "Innovative" in user and "Witty" in user
    assert "FAVORED_PHRASING" in user
    assert "creators" in user
    assert "DISCOURAGED" in user
    assert "magic" in user

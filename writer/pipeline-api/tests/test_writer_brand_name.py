"""Tests for the brand_name field added to BrandVoiceCard distillation
and its prompt injection into section/intro/conclusion writers.

Production observation that motivated this: even with a complete brand
voice card distilled (tone, banned terms, preferred terms, voice
directives), the resulting articles never explicitly mentioned the
brand. Adding a first-class brand_name field with a min-mention
directive in the prompts gives the LLM a concrete anchor to weave in.
"""

from __future__ import annotations

import pytest

from models.writer import BrandVoiceCard
from modules.writer.conclusion import write_conclusion
from modules.writer.distillation import _parse_card
from modules.writer.intro import write_intro
from modules.writer.banned_terms import build_banned_regex


# -----------------------------------------------------------------------
# Distillation parser
# -----------------------------------------------------------------------

def test_parse_card_extracts_brand_name():
    raw = {
        "brand_name": "Ubiquitous",
        "tone_adjectives": ["confident", "direct"],
        "voice_directives": ["use evidence anchors"],
    }
    card = _parse_card(raw)
    assert card.brand_name == "Ubiquitous"


def test_parse_card_brand_name_defaults_to_empty():
    """A distillation response that omits brand_name (legacy / older
    payload) should not break parsing."""
    raw = {"tone_adjectives": ["clear"]}
    card = _parse_card(raw)
    assert card.brand_name == ""


def test_parse_card_brand_name_trimmed_and_capped():
    raw = {"brand_name": "  Ubiquitous  " + ("X" * 200)}
    card = _parse_card(raw)
    # Trimmed of leading/trailing whitespace and capped at 120 chars.
    assert card.brand_name.startswith("Ubiquitous")
    assert len(card.brand_name) <= 120


def test_brand_voice_card_default_brand_name_is_empty():
    """The model's default value is an empty string, not None — keeps
    the prompt builder branches simple."""
    card = BrandVoiceCard()
    assert card.brand_name == ""


# -----------------------------------------------------------------------
# Intro prompt receives brand_name
# -----------------------------------------------------------------------

def _fake(*responses):
    iterator = iter(responses)

    async def _call(system, user, **kw):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        # Capture the user prompt so the test can assert on it.
        _call.last_user = user  # type: ignore[attr-defined]
        return item

    _call.last_user = ""  # type: ignore[attr-defined]
    return _call


@pytest.mark.asyncio
async def test_intro_prompt_includes_brand_name_when_present(monkeypatch):
    body = " ".join(["word"] * 100)
    fake = _fake({"intro": body})
    monkeypatch.setattr("modules.writer.intro.claude_json", fake)

    card = BrandVoiceCard(brand_name="Ubiquitous", tone_adjectives=["confident"])
    await write_intro(
        keyword="kw", title="t", scope_statement="",
        intent_type="how-to", h2_list=["A", "B"],
        brand_voice_card=card, banned_regex=build_banned_regex([]),
        intro_order=1,
    )
    user = fake.last_user  # type: ignore[attr-defined]
    assert "BRAND_NAME: Ubiquitous" in user
    assert "at most ONCE in the intro" in user.lower() or "at most once in the intro" in user.lower()


@pytest.mark.asyncio
async def test_intro_prompt_skips_brand_block_when_no_brand_name(monkeypatch):
    body = " ".join(["word"] * 100)
    fake = _fake({"intro": body})
    monkeypatch.setattr("modules.writer.intro.claude_json", fake)

    card = BrandVoiceCard(tone_adjectives=["confident"])  # no brand_name
    await write_intro(
        keyword="kw", title="t", scope_statement="",
        intent_type="how-to", h2_list=["A", "B"],
        brand_voice_card=card, banned_regex=build_banned_regex([]),
        intro_order=1,
    )
    user = fake.last_user  # type: ignore[attr-defined]
    assert "BRAND_NAME:" not in user


# -----------------------------------------------------------------------
# Conclusion prompt receives brand_name
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conclusion_prompt_includes_brand_name_when_present(monkeypatch):
    body = " ".join(["word"] * 100)
    fake = _fake({"conclusion": body})
    monkeypatch.setattr("modules.writer.conclusion.claude_json", fake)

    card = BrandVoiceCard(
        brand_name="Ubiquitous",
        tone_adjectives=["confident"],
        client_services=["TikTok influencer marketing"],
    )
    await write_conclusion(
        keyword="kw", intent_type="how-to",
        section_summaries=["Section A: foo", "Section B: bar"],
        brand_voice_card=card, banned_regex=build_banned_regex([]),
        conclusion_order=10,
    )
    user = fake.last_user  # type: ignore[attr-defined]
    assert "BRAND_NAME: Ubiquitous" in user
    assert "ONE brand mention" in user
    assert "TikTok influencer marketing" in user


# -----------------------------------------------------------------------
# Section prompt receives brand_name + min-mention directive
# -----------------------------------------------------------------------

def test_section_prompt_includes_brand_name_directive():
    """Direct unit test on the section prompt builder so we don't have
    to spin up the full write_h2_group loop."""
    from modules.writer.sections import _build_section_user_prompt

    card = BrandVoiceCard(
        brand_name="Ubiquitous",
        tone_adjectives=["confident"],
        client_services=["TikTok influencer marketing", "Paid ads management"],
    )
    prompt = _build_section_user_prompt(
        keyword="kw",
        intent="informational",
        h2_item={"order": 2, "text": "How TikTok Shop works"},
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
    assert "brand_name: Ubiquitous" in prompt
    assert "mention Ubiquitous 1–2 times" in prompt or "mention Ubiquitous 1-2 times" in prompt or "mention Ubiquitous 1–2 times total" in prompt
    assert "AT MOST 1 mention" in prompt
    assert "TikTok influencer marketing" in prompt


def test_section_prompt_omits_brand_block_when_no_brand_signals():
    """Backward compat: with no brand_name, no client_services, no
    client_locations, the CLIENT_CONTEXT block is absent."""
    from modules.writer.sections import _build_section_user_prompt

    card = BrandVoiceCard(tone_adjectives=["confident"])
    prompt = _build_section_user_prompt(
        keyword="kw",
        intent="informational",
        h2_item={"order": 2, "text": "How TikTok Shop works"},
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
    assert "CLIENT_CONTEXT" not in prompt
    assert "brand_name" not in prompt

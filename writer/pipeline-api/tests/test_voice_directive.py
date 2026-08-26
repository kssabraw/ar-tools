"""Unit tests for modules.writer.voice_directive — the write-time distinctiveness
directive shared by the blog/service article writer's intro, sections, and
conclusion prompts (the seam those three files previously lacked).

Pure + offline.
"""

from __future__ import annotations

from models.writer import BrandVoiceCard
from modules.writer.voice_directive import distinctiveness_directive


def _card(**overrides) -> BrandVoiceCard:
    return BrandVoiceCard(**overrides)


def test_none_card_emits_nothing():
    assert distinctiveness_directive(None) == ""


def test_directive_fires_for_any_card_and_states_the_name_swap_test():
    block = distinctiveness_directive(_card(tone_adjectives=["warm"]))
    assert "DISTINCTIVENESS" in block
    assert "swapping the brand" in block
    # generic-but-clean must be framed as a failure, mirroring the hardened judge
    assert "failure here, not a pass" in block


def test_directive_renders_the_distinctive_material_when_present():
    block = distinctiveness_directive(_card(
        differentiators=["50-year workmanship warranty", "only Malarkey-certified crew"],
        signature_phrases=["Roofs done right, rain or shine"],
    ))
    assert "50-year workmanship warranty" in block
    assert "only Malarkey-certified crew" in block
    assert '"Roofs done right, rain or shine"' in block


def test_thin_card_gets_the_directive_but_no_empty_field_lines():
    """A card with no differentiators/signature still gets the directive (it
    leans on the audience material elsewhere in the prompt) and must not emit a
    bare, valueless field label."""
    block = distinctiveness_directive(_card(person="first"))
    assert "DISTINCTIVENESS" in block
    assert "Differentiators to foreground" not in block
    assert "This brand's own words" not in block


def test_only_differentiators_or_only_signature_render_independently():
    diff_only = distinctiveness_directive(_card(differentiators=["24/7 emergency line"]))
    assert "Differentiators to foreground" in diff_only
    assert "This brand's own words" not in diff_only

    sig_only = distinctiveness_directive(_card(signature_phrases=["We climb so you don't have to"]))
    assert "This brand's own words" in sig_only
    assert "Differentiators to foreground" not in sig_only


def test_block_leads_with_a_blank_line_for_clean_prompt_separation():
    block = distinctiveness_directive(_card(tone_adjectives=["warm"]))
    assert block.startswith("\n")

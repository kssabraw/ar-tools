"""Tests for the separate H1 field added to title_scope (PRD v2.0
Step 3.5 extension).

The brief now emits BOTH a `title` (SEO/meta — browser tab, SERP) AND
an `h1` (on-page main heading). They may be the same string or differ
slightly. The H1 has a longer length cap (130 vs 100 chars) because
on-page headings are allowed to be more descriptive than SERP titles.
"""

from __future__ import annotations

import pytest

from modules.brief.title_scope import (
    BANNED_TITLE_PHRASES,
    MAX_H1_LEN,
    MAX_TITLE_LEN,
    TitleScopeOutput,
    _validate_payload,
    generate_title_and_scope,
)


# -----------------------------------------------------------------------
# Validator unit tests (sync)
# -----------------------------------------------------------------------

def test_validator_accepts_separate_h1():
    payload = {
        "title": "How to Increase TikTok Shop ROI",
        "h1": "How to Increase TikTok Shop ROI: Tactics That Actually Work",
        "scope_statement": "Covers ROI tactics. Does not cover paid ads setup.",
        "title_rationale": "Action-led; year omitted.",
    }
    ok, reason, parsed = _validate_payload(payload)
    assert ok, reason
    assert parsed.title == "How to Increase TikTok Shop ROI"
    assert parsed.h1 == "How to Increase TikTok Shop ROI: Tactics That Actually Work"


def test_validator_falls_back_h1_to_title_when_missing():
    """Backward compat: an LLM payload without an h1 field uses the title
    as the H1. Older briefs and legacy mocks continue to work."""
    payload = {
        "title": "How to Increase TikTok Shop ROI",
        "scope_statement": "Covers ROI tactics. Does not cover paid ads setup.",
        "title_rationale": "ok",
    }
    ok, _, parsed = _validate_payload(payload)
    assert ok
    assert parsed.h1 == parsed.title


def test_validator_falls_back_h1_to_title_when_empty_string():
    payload = {
        "title": "How to Increase TikTok Shop ROI",
        "h1": "   ",
        "scope_statement": "Covers ROI tactics. Does not cover paid ads setup.",
        "title_rationale": "ok",
    }
    ok, _, parsed = _validate_payload(payload)
    assert ok
    assert parsed.h1 == parsed.title


def test_validator_rejects_h1_over_length_cap():
    payload = {
        "title": "Short title",
        "h1": "X" * (MAX_H1_LEN + 1),
        "scope_statement": "Covers stuff. Does not cover other stuff.",
        "title_rationale": "ok",
    }
    ok, reason, parsed = _validate_payload(payload)
    assert not ok
    assert "h1_too_long" in reason


def test_validator_rejects_h1_with_banned_phrase():
    """The H1 inherits the same banned-phrase rules as the title."""
    payload = {
        "title": "Clean title",
        "h1": "Ultimate Guide to TikTok Shop",
        "scope_statement": "Covers stuff. Does not cover other stuff.",
        "title_rationale": "ok",
    }
    ok, reason, parsed = _validate_payload(payload)
    assert not ok
    assert "h1_contains_banned_phrase" in reason


def test_validator_h1_can_exceed_title_length_cap():
    """The H1 cap (130) is genuinely longer than the title cap (100)."""
    long_h1 = "X" * (MAX_TITLE_LEN + 25)  # over title cap, under H1 cap
    payload = {
        "title": "Short title",
        "h1": long_h1,
        "scope_statement": "Covers stuff. Does not cover other stuff.",
        "title_rationale": "ok",
    }
    ok, _, parsed = _validate_payload(payload)
    assert ok
    assert parsed.h1 == long_h1


def test_title_scope_output_has_h1_field():
    out = TitleScopeOutput(
        title="t",
        h1="h",
        scope_statement="Defines x. Does not cover y.",
        title_rationale="r",
    )
    assert out.title == "t"
    assert out.h1 == "h"


# -----------------------------------------------------------------------
# Full generate_title_and_scope flow with mocked LLM
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_emits_h1_when_llm_provides_it():
    payload = {
        "title": "How to Increase TikTok Shop ROI",
        "h1": "How to Increase TikTok Shop ROI: Tactics That Actually Work",
        "scope_statement": "Covers tactics. Does not cover paid ads setup.",
        "title_rationale": "ok",
    }

    async def _mock(system, user, **kw):
        return payload

    result = await generate_title_and_scope(
        seed_keyword="how to increase tiktok shop roi",
        intent_type="how-to",
        serp_titles=[], serp_h1s=[], meta_descriptions=[],
        fanout_response_bodies=[],
        llm_json_fn=_mock,
    )
    assert result.title == "How to Increase TikTok Shop ROI"
    assert result.h1 == "How to Increase TikTok Shop ROI: Tactics That Actually Work"
    assert result.title != result.h1


@pytest.mark.asyncio
async def test_generate_h1_falls_back_to_title_when_llm_omits_h1():
    """Backward compat for in-flight LLMs / older mocks that don't yet
    return the new h1 field."""
    payload = {
        "title": "How to Increase TikTok Shop ROI",
        "scope_statement": "Covers tactics. Does not cover paid ads setup.",
        "title_rationale": "ok",
    }

    async def _mock(system, user, **kw):
        return payload

    result = await generate_title_and_scope(
        seed_keyword="how to increase tiktok shop roi",
        intent_type="how-to",
        serp_titles=[], serp_h1s=[], meta_descriptions=[],
        fanout_response_bodies=[],
        llm_json_fn=_mock,
    )
    assert result.h1 == result.title

"""Tests for heading main-entity enforcement (heading_entity_enforcer.py, §X.4).

Entity-presence only, post-SEO-optimizer, H2-only, warn-and-accept.
The rewrite_fn is injected so no LLM is touched.
"""

from __future__ import annotations

import pytest

from modules.writer.heading_entity_enforcer import (
    enforce_heading_entities,
    is_entity_present,
)


def _h2(order: int, text: str) -> dict:
    return {"order": order, "level": "H2", "type": "content", "text": text}


# ---------------------------------------------------------------------------
# is_entity_present
# ---------------------------------------------------------------------------

def test_present_exact_substring():
    assert is_entity_present("Angel Number 327 Meaning", "angel number 327", []) is True


def test_present_token_subset_reorders():
    # word-order variant still counts
    assert is_entity_present("What 327 Angel Number Signals", "angel number 327", []) is True


def test_present_via_variant():
    assert is_entity_present("Cleansing Quartz at Home", "crystal", ["quartz"]) is True


def test_absent():
    assert is_entity_present("How to Get Started Quickly", "magnesium glycinate", []) is False


# ---------------------------------------------------------------------------
# enforce_heading_entities
# ---------------------------------------------------------------------------

async def _prefix_rewrite(heading: str, entity: str, forbidden: list[str]) -> str:
    return f"{entity}: {heading}"


@pytest.mark.asyncio
async def test_noop_when_main_entity_absent():
    hs = [_h2(1, "Some Heading Without Entity")]
    result = await enforce_heading_entities(hs, None, rewrite_fn=_prefix_rewrite)
    assert result.heading_structure == hs
    assert result.enforced_count == 0
    assert result.rewrites_applied == 0
    assert result.main_entity_used is None


@pytest.mark.asyncio
async def test_conforming_heading_untouched():
    hs = [_h2(1, "Angel Number 327 and Love")]
    me = {"canonical": "angel number 327", "variants": []}
    result = await enforce_heading_entities(hs, me, rewrite_fn=_prefix_rewrite)
    assert result.heading_structure[0]["text"] == "Angel Number 327 and Love"
    assert result.enforced_count == 1
    assert result.rewrites_applied == 0
    assert result.violation_count == 0


@pytest.mark.asyncio
async def test_nonconforming_heading_rewritten():
    hs = [_h2(1, "What It Means for Love")]
    me = {"canonical": "angel number 327", "variants": []}
    result = await enforce_heading_entities(hs, me, rewrite_fn=_prefix_rewrite)
    assert "angel number 327" in result.heading_structure[0]["text"].lower()
    assert result.rewrites_applied == 1
    assert result.enforced_count == 1
    assert result.violation_count == 0


@pytest.mark.asyncio
async def test_violation_when_rewrite_still_missing_entity():
    async def _bad_rewrite(heading, entity, forbidden):
        return "Still No Entity Here"

    hs = [_h2(1, "What It Means for Love")]
    me = {"canonical": "angel number 327", "variants": []}
    result = await enforce_heading_entities(hs, me, rewrite_fn=_bad_rewrite)
    # original kept, counted as violation, flagged for review
    assert result.heading_structure[0]["text"] == "What It Means for Love"
    assert result.violation_count == 1
    assert result.enforced_count == 0
    assert result.flagged and result.flagged[0]["order"] == 1


@pytest.mark.asyncio
async def test_rewrite_exception_is_warn_and_accept():
    async def _boom(heading, entity, forbidden):
        raise RuntimeError("llm down")

    hs = [_h2(1, "Unrelated Heading")]
    me = {"canonical": "creatine", "variants": []}
    result = await enforce_heading_entities(hs, me, rewrite_fn=_boom)
    assert result.heading_structure[0]["text"] == "Unrelated Heading"
    assert result.violation_count == 1


@pytest.mark.asyncio
async def test_h3_and_non_content_skipped():
    hs = [
        {"order": 1, "level": "H3", "type": "content", "text": "An H3 Without Entity"},
        {"order": 2, "level": "H2", "type": "faq-header", "text": "Frequently Asked Questions"},
        _h2(3, "Carries creatine already"),
    ]
    me = {"canonical": "creatine", "variants": []}
    result = await enforce_heading_entities(hs, me, rewrite_fn=_prefix_rewrite)
    # H3 + faq-header untouched and not counted; only the content H2 counts
    assert result.heading_structure[0]["text"] == "An H3 Without Entity"
    assert result.heading_structure[1]["text"] == "Frequently Asked Questions"
    assert result.enforced_count == 1
    assert result.rewrites_applied == 0


@pytest.mark.asyncio
async def test_empty_canonical_is_noop():
    hs = [_h2(1, "Some Heading")]
    me = {"canonical": "  ", "variants": []}
    result = await enforce_heading_entities(hs, me, rewrite_fn=_prefix_rewrite)
    assert result.heading_structure == hs
    assert result.main_entity_used is None

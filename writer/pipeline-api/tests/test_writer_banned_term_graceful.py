"""Regression tests for graceful degradation of body-content banned-term
leakage (Writer §4.4 - production fix).

Background: production runs were aborting with HTTP 422 when the section
LLM emitted a banned term in body content even after a single retry.
The brand voice card's banned_terms list is sometimes too aggressive
(distillation LLM categorizes soft preferences like "leverage" as
banned). Losing an entire run because the LLM can't avoid one
common word is too brittle.

New behavior:
  - Heading-level banned-term match → still hard abort (no change).
  - Body-content banned-term match after retry → log warning + ship
    article + surface offending terms in metadata.banned_terms_leaked_in_body.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from models.writer import (
    BrandVoiceCard,
    ClientContextInput,
    WriterMetadata,
    WriterRequest,
)
from modules.writer.banned_terms import BannedTermLeakage, build_banned_regex


def test_writer_metadata_has_banned_terms_leaked_field():
    """Schema additive: WriterMetadata gains banned_terms_leaked_in_body
    (default empty list)."""
    meta = WriterMetadata()
    assert meta.banned_terms_leaked_in_body == []
    meta = WriterMetadata(banned_terms_leaked_in_body=["leverage", "optimize"])
    assert meta.banned_terms_leaked_in_body == ["leverage", "optimize"]


def test_section_write_result_carries_leaked_terms():
    """SectionWriteResult.banned_terms_leaked is populated when the
    body-content retry fails."""
    from modules.writer.sections import SectionWriteResult

    result = SectionWriteResult(sections=[], banned_terms_leaked=["leverage"])
    assert result.banned_terms_leaked == ["leverage"]


@pytest.mark.asyncio
async def test_section_body_leakage_degrades_to_log_not_abort():
    """The section LLM emits a banned term twice. Old behavior: abort
    with BannedTermLeakage. New behavior: log + return result with
    banned_terms_leaked populated."""
    from modules.writer.sections import write_h2_group

    # Both attempts return the banned word in the body.
    payload = {
        "sections": [
            {"order": 2, "heading": "How to scale", "body": "Brands should leverage TikTok's algorithm to drive ROI."},
        ],
    }

    call_count = [0]

    async def fake_call(system, user, **kw):
        call_count[0] += 1
        return payload

    banned_regex = build_banned_regex(["leverage"])
    h2_item = {"order": 2, "text": "How to scale", "citation_ids": []}

    from modules.writer.reconciliation import FilteredSIETerms

    with patch("modules.writer.sections.claude_json", fake_call):
        result = await write_h2_group(
            keyword="kw", intent="how-to",
            h2_item=h2_item, h3_items=[],
            section_budgets={2: 200},
            filtered_terms=FilteredSIETerms(),
            citations=[],
            brand_voice_card=BrandVoiceCard(banned_terms=["leverage"]),
            banned_regex=banned_regex,
        )

    # Two attempts (initial + 1 retry) both leaked.
    assert call_count[0] == 2
    # Run did NOT abort - sections were returned.
    assert len(result.sections) >= 1
    # Leaked term is recorded for downstream metadata.
    assert "leverage" in result.banned_terms_leaked


@pytest.mark.asyncio
async def test_section_body_leakage_clears_when_retry_succeeds():
    """If the retry produces clean content, banned_terms_leaked stays empty."""
    from modules.writer.sections import write_h2_group

    payloads = iter([
        {"sections": [{"order": 2, "heading": "How to scale",
                       "body": "Brands should leverage TikTok's algorithm."}]},
        {"sections": [{"order": 2, "heading": "How to scale",
                       "body": "Brands should use TikTok's algorithm carefully."}]},
    ])

    async def fake_call(system, user, **kw):
        return next(payloads)

    banned_regex = build_banned_regex(["leverage"])
    h2_item = {"order": 2, "text": "How to scale", "citation_ids": []}

    from modules.writer.reconciliation import FilteredSIETerms

    with patch("modules.writer.sections.claude_json", fake_call):
        result = await write_h2_group(
            keyword="kw", intent="how-to",
            h2_item=h2_item, h3_items=[],
            section_budgets={2: 200},
            filtered_terms=FilteredSIETerms(),
            citations=[],
            brand_voice_card=BrandVoiceCard(banned_terms=["leverage"]),
            banned_regex=banned_regex,
        )

    assert result.banned_terms_leaked == []


@pytest.mark.asyncio
async def test_heading_level_banned_term_still_aborts():
    """Heading-level enforcement is unchanged: a banned term in any
    heading aborts the run with BannedTermLeakage. We verify by calling
    _scan_headings_for_banned directly."""
    from models.writer import ArticleSection
    from modules.writer.pipeline import _scan_headings_for_banned

    article = [
        ArticleSection(
            order=1, level="H1", type="content",
            heading="best premium hvac systems",
            body="",
        ),
    ]
    banned_regex = build_banned_regex(["premium"])

    with pytest.raises(BannedTermLeakage) as exc_info:
        _scan_headings_for_banned(article, banned_regex)
    assert exc_info.value.term == "premium"
    assert "H1" in exc_info.value.location

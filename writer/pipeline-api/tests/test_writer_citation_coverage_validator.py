"""Step 4F.1 Citation Coverage Validator (Writer PRD §4F.1, R7 + Phase 4)."""

from __future__ import annotations

import pytest

from models.writer import ArticleSection
from modules.writer.citation_coverage_validator import (
    CoverageValidationResult,
    validate_citation_coverage,
)
from modules.writer.reconciliation import FilteredSIETerms
from modules.writer.sections import SectionWriteResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _h2(order: int, heading: str, body: str = "") -> ArticleSection:
    return ArticleSection(
        order=order, level="H2", type="content",
        heading=heading, body=body,
        word_count=len(body.split()) if body else 0,
    )


def _h3(order: int, heading: str, body: str = "") -> ArticleSection:
    return ArticleSection(
        order=order, level="H3", type="content",
        heading=heading, body=body,
        word_count=len(body.split()) if body else 0,
    )


def _filtered_terms() -> FilteredSIETerms:
    return FilteredSIETerms(required=[], excluded=[], avoid=[])


def _make_retry_fn(retry_body: str):
    state = {"calls": 0, "directive": None}

    async def fake(*, h2_item, coverage_retry_directive=None, **kwargs):
        state["calls"] += 1
        state["directive"] = coverage_retry_directive
        sec = ArticleSection(
            order=h2_item["order"], level="H2", type="content",
            heading=h2_item.get("text", ""),
            body=retry_body,
            word_count=len(retry_body.split()),
        )
        return SectionWriteResult(sections=[sec])
    return fake, state


# ---------------------------------------------------------------------------
# No-op cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validator_no_op_on_empty_article():
    result = await validate_citation_coverage(
        [],
        keyword="k", intent="how-to",
        heading_structure=[], section_budgets={},
        filtered_terms=_filtered_terms(), citations=[],
        brand_voice_card=None, banned_regex=None,
    )
    assert result.retries_attempted == 0
    assert result.under_cited_sections == []


@pytest.mark.asyncio
async def test_validator_no_op_when_section_has_no_citable_claims():
    """A section with zero citable claims has 100% coverage by convention."""
    article = [_h2(1, "Topic", "Plain prose with no statistics.")]
    fake, state = _make_retry_fn("ignored")
    result = await validate_citation_coverage(
        article,
        keyword="k", intent="how-to",
        heading_structure=[
            {"order": 1, "text": "Topic", "level": "H2", "type": "content"},
        ],
        section_budgets={},
        filtered_terms=_filtered_terms(), citations=[],
        brand_voice_card=None, banned_regex=None,
        write_h2_group_fn=fake,
    )
    assert state["calls"] == 0
    assert result.retries_attempted == 0


@pytest.mark.asyncio
async def test_validator_no_op_when_coverage_at_or_above_threshold():
    """All citable claims have markers → no retry."""
    article = [_h2(
        1, "Topic",
        "Revenue rose 27% YoY.{{cit_001}} Growth continued.",
    )]
    fake, state = _make_retry_fn("ignored")
    result = await validate_citation_coverage(
        article,
        keyword="k", intent="how-to",
        heading_structure=[
            {"order": 1, "text": "Topic", "level": "H2", "type": "content"},
        ],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[{"citation_id": "cit_001"}],
        brand_voice_card=None, banned_regex=None,
        write_h2_group_fn=fake,
    )
    assert state["calls"] == 0


# ---------------------------------------------------------------------------
# Retry-clears-floor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validator_retries_under_cited_section_and_succeeds():
    """Section under threshold; retry adds markers; coverage clears."""
    article = [_h2(
        1, "Topic",
        # Two citable claims, zero cited → 0% coverage.
        "Revenue rose 27% YoY. Reported $100M in sales.",
    )]
    # Retry's body has both claims cited.
    retry_body = (
        "Revenue rose 27% YoY.{{cit_001}} Reported $100M in sales.{{cit_002}}"
    )
    fake, state = _make_retry_fn(retry_body)

    result = await validate_citation_coverage(
        article,
        keyword="k", intent="how-to",
        heading_structure=[
            {"order": 1, "text": "Topic", "level": "H2", "type": "content"},
        ],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[
            {"citation_id": "cit_001"},
            {"citation_id": "cit_002"},
        ],
        brand_voice_card=None, banned_regex=None,
        write_h2_group_fn=fake,
    )
    assert state["calls"] == 1
    assert result.retries_attempted == 1
    assert result.retries_succeeded == 1
    assert result.under_cited_sections == []
    # Article was replaced with retry body
    assert "{{cit_001}}" in result.validated_article[0].body
    assert "{{cit_002}}" in result.validated_article[0].body


# ---------------------------------------------------------------------------
# Retry-fails-then-soften
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validator_softens_operational_claims_when_retry_fails():
    """Retry doesn't clear; auto-soften kicks in for C7 operational claim."""
    article = [_h2(
        1, "Topic",
        "Use a 4-to-6 week refresh cadence for new listings.",
    )]
    # Retry returns the same uncited content (LLM couldn't add markers
    # because no citation pool was provided)
    retry_body = (
        "Use a 4-to-6 week refresh cadence for new listings."
    )
    fake, state = _make_retry_fn(retry_body)

    result = await validate_citation_coverage(
        article,
        keyword="k", intent="how-to",
        heading_structure=[
            {"order": 1, "text": "Topic", "level": "H2", "type": "content"},
        ],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[],  # no pool — soften is the only path
        brand_voice_card=None, banned_regex=None,
        write_h2_group_fn=fake,
    )
    assert result.retries_attempted == 1
    assert result.retries_succeeded == 0
    # Section was softened — operational phrase replaced
    body = result.validated_article[0].body
    assert "4-to-6 week refresh cadence" not in body
    assert "every few weeks" in body
    # Records appended
    assert len(result.operational_claims_softened) == 1
    assert result.operational_claims_softened[0]["rule"] == "duration-as-recommendation"
    assert len(result.under_cited_sections) == 1
    assert result.under_cited_sections[0]["section_order"] == 1
    assert result.under_cited_sections[0]["operational_claims_softened"] == 1


@pytest.mark.asyncio
async def test_validator_does_not_soften_c1_c6_claims_when_retry_fails():
    """C1 percent / C2 currency claims must NOT be softened — only
    C7-C9 operational claims are eligible."""
    article = [_h2(
        1, "Topic",
        "Revenue rose 27% YoY. Reported $100M in sales.",
    )]
    fake, state = _make_retry_fn("Revenue rose 27% YoY. Reported $100M in sales.")
    result = await validate_citation_coverage(
        article,
        keyword="k", intent="how-to",
        heading_structure=[
            {"order": 1, "text": "Topic", "level": "H2", "type": "content"},
        ],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[],
        brand_voice_card=None, banned_regex=None,
        write_h2_group_fn=fake,
    )
    body = result.validated_article[0].body
    # C1/C2 claims preserved verbatim — no soften
    assert "27%" in body
    assert "$100M" in body
    assert result.operational_claims_softened == []
    assert result.under_cited_sections[0]["operational_claims_softened"] == 0


# ---------------------------------------------------------------------------
# Retry-section-count-mismatch (Phase 3 fix #1 carries over)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validator_refuses_splice_on_section_count_mismatch():
    """If retry returns fewer sections than the original group, refuse
    the splice and fall through to soften on the original."""
    article = [
        _h2(1, "Topic", "Use a 4-week refresh cadence."),
        _h3(2, "Sub A", "child body"),
    ]

    async def fake_drop_h3(*, h2_item, **kwargs):
        sec = ArticleSection(
            order=1, level="H2", type="content", heading="Topic",
            body="Use a 4-week refresh cadence.{{cit_001}}",
            word_count=6,
        )
        return SectionWriteResult(sections=[sec])  # 1 section, not 1+1

    result = await validate_citation_coverage(
        article,
        keyword="k", intent="how-to",
        heading_structure=[
            {"order": 1, "text": "Topic", "level": "H2", "type": "content"},
            {"order": 2, "text": "Sub A", "level": "H3", "type": "content"},
        ],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[{"citation_id": "cit_001"}],
        brand_voice_card=None, banned_regex=None,
        write_h2_group_fn=fake_drop_h3,
    )
    # Original 2 sections preserved
    assert len(result.validated_article) == 2
    # Section was softened (since retry was refused)
    assert "4-week refresh cadence" not in result.validated_article[0].body


# ---------------------------------------------------------------------------
# Retry-call exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validator_handles_retry_exception_with_soften():
    """If retry raises, fall through to soften on original."""
    article = [_h2(
        1, "Topic",
        "Use a 30-day audit window before each release.",
    )]

    async def boom(**kwargs):
        raise RuntimeError("LLM outage")

    result = await validate_citation_coverage(
        article,
        keyword="k", intent="how-to",
        heading_structure=[
            {"order": 1, "text": "Topic", "level": "H2", "type": "content"},
        ],
        section_budgets={},
        filtered_terms=_filtered_terms(), citations=[],
        brand_voice_card=None, banned_regex=None,
        write_h2_group_fn=boom,
    )
    assert result.retries_attempted == 1
    assert result.retries_succeeded == 0
    body = result.validated_article[0].body
    assert "30-day audit window" not in body
    # Soften table maps "30-day audit window" via the C7 rule —
    # day-scale becomes "a brief window" or close.
    assert any(phrase in body for phrase in ("brief window", "couple of months"))

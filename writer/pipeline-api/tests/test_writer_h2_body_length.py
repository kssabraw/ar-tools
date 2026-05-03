"""Step 6.7 — Per-H2 Body Length Validator (Writer PRD v1.6 / Phase 3)."""

from __future__ import annotations

import pytest

from models.writer import ArticleSection
from modules.writer.h2_body_length import (
    H2BodyLengthResult,
    _collect_h2_groups,
    _word_count,
    validate_h2_body_lengths,
)
from modules.writer.reconciliation import FilteredSIETerms
from modules.writer.sections import SectionWriteResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _h2(order: int, heading: str, body: str = "") -> ArticleSection:
    return ArticleSection(
        order=order,
        level="H2",
        type="content",
        heading=heading,
        body=body,
        word_count=len(body.split()) if body else 0,
    )


def _h3(
    order: int,
    heading: str,
    body: str = "",
    *,
    parent_order: int | None = None,
) -> ArticleSection:
    return ArticleSection(
        order=order,
        level="H3",
        type="content",
        heading=heading,
        body=body,
        word_count=len(body.split()) if body else 0,
    )


def _faq_header(order: int) -> ArticleSection:
    return ArticleSection(
        order=order, level="H2", type="faq-header",
        heading="Frequently Asked Questions",
    )


def _faq_question(order: int, q: str) -> ArticleSection:
    return ArticleSection(
        order=order, level="H3", type="faq-question",
        heading=q, body="A short answer.",
    )


def _conclusion(order: int) -> ArticleSection:
    return ArticleSection(
        order=order, level="none", type="conclusion",
        heading=None, body="A wrap-up.",
    )


def _heading_struct(orders_to_text: dict[int, str], h3_parents: dict[int, str] | None = None) -> list[dict]:
    """Build a synthetic heading_structure aligned with the article."""
    out = []
    for order, text in orders_to_text.items():
        # Default H2 at this point — caller can override below.
        out.append({"order": order, "text": text, "level": "H2", "type": "content"})
    return out


def _filtered_terms() -> FilteredSIETerms:
    return FilteredSIETerms(required=[], excluded=[], avoid=[])


def _make_retry_fn(retry_body: str):
    """Build a fake `write_h2_group` that returns a single H2 section
    with the supplied body. Records its call count for inspection."""
    state = {"calls": 0, "captured_directive": None}

    async def fake(*, h2_item, length_retry_directive=None, **kwargs):
        state["calls"] += 1
        state["captured_directive"] = length_retry_directive
        sec = ArticleSection(
            order=h2_item["order"],
            level="H2",
            type="content",
            heading=h2_item.get("text", ""),
            body=retry_body,
            word_count=len(retry_body.split()),
        )
        return SectionWriteResult(sections=[sec])

    return fake, state


# ---------------------------------------------------------------------------
# _word_count + _collect_h2_groups
# ---------------------------------------------------------------------------


def test_word_count_strips_citation_markers():
    body = "Heat pump installations grew {{cit_001}} eleven percent year over year.{{cit_002}}"
    # Words after marker strip: "Heat pump installations grew  eleven percent year over year." → 9 words
    assert _word_count(body) == 9


def test_word_count_handles_empty():
    assert _word_count("") == 0
    assert _word_count("   ") == 0


def test_collect_h2_groups_pairs_h2_with_consecutive_h3s():
    article = [
        _h2(1, "Plan", "Plan body"),
        _h3(2, "Sub A", "A body"),
        _h3(3, "Sub B", "B body"),
        _h2(4, "Launch", "Launch body"),
        _h3(5, "Sub C", "C body"),
        _faq_header(6),
        _faq_question(7, "Q?"),
        _conclusion(8),
    ]
    groups = _collect_h2_groups(article)
    assert len(groups) == 2
    assert groups[0].h2_section.heading == "Plan"
    assert [s.heading for _, s in groups[0].children] == ["Sub A", "Sub B"]
    assert groups[1].h2_section.heading == "Launch"
    assert [s.heading for _, s in groups[1].children] == ["Sub C"]


def test_collect_h2_groups_excludes_faq_header_and_conclusion():
    article = [
        _h2(1, "Topic", "Body"),
        _faq_header(2),
        _faq_question(3, "Q?"),
        _conclusion(4),
    ]
    groups = _collect_h2_groups(article)
    # Only the content H2 is tracked; FAQ + conclusion are out of scope.
    assert len(groups) == 1
    assert groups[0].h2_section.heading == "Topic"
    assert groups[0].children == []


def test_collect_h2_groups_handles_empty():
    assert _collect_h2_groups([]) == []


# ---------------------------------------------------------------------------
# validate_h2_body_lengths — happy paths + retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validator_no_op_when_floor_is_zero():
    article = [_h2(1, "Topic", "short")]
    fake, _ = _make_retry_fn("ignored")

    result = await validate_h2_body_lengths(
        article,
        min_h2_body_words=0,  # disabled
        keyword="k",
        intent="how-to",
        heading_structure=[{"order": 1, "text": "Topic"}],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[],
        brand_voice_card=None,
        banned_regex=None,
        write_h2_group_fn=fake,
    )
    assert result.retries_attempted == 0
    assert result.under_length_h2_sections == []
    assert result.validated_article == article


@pytest.mark.asyncio
async def test_validator_no_op_when_all_groups_at_or_above_floor():
    long_body = "word " * 200  # 200 words
    article = [_h2(1, "Topic", long_body.strip())]
    fake, state = _make_retry_fn("ignored")

    result = await validate_h2_body_lengths(
        article,
        min_h2_body_words=120,
        keyword="k",
        intent="how-to",
        heading_structure=[{"order": 1, "text": "Topic"}],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[],
        brand_voice_card=None,
        banned_regex=None,
        write_h2_group_fn=fake,
    )
    assert result.retries_attempted == 0
    assert state["calls"] == 0  # LLM never invoked
    assert result.under_length_h2_sections == []


@pytest.mark.asyncio
async def test_validator_retries_under_length_h2():
    short_body = "Two sentences. Plus a stat: 27 percent."
    long_retry = "word " * 200  # well above the 120 floor
    article = [_h2(1, "Topic", short_body)]

    fake, state = _make_retry_fn(long_retry.strip())
    result = await validate_h2_body_lengths(
        article,
        min_h2_body_words=120,
        keyword="k",
        intent="how-to",
        heading_structure=[{"order": 1, "text": "Topic"}],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[],
        brand_voice_card=None,
        banned_regex=None,
        write_h2_group_fn=fake,
    )
    assert result.retries_attempted == 1
    assert result.retries_succeeded == 1
    assert state["calls"] == 1
    assert state["captured_directive"] is not None
    assert "120" in state["captured_directive"]
    # Under-length list is empty because the retry succeeded.
    assert result.under_length_h2_sections == []
    # Retry's body replaced the original.
    assert "word" in result.validated_article[0].body


@pytest.mark.asyncio
async def test_validator_accepts_and_flags_when_retry_still_short():
    short_body = "Two sentences. Plus a stat."
    still_short = "Slightly more words but still not enough to clear the floor."

    article = [_h2(1, "Topic", short_body)]
    fake, state = _make_retry_fn(still_short)

    result = await validate_h2_body_lengths(
        article,
        min_h2_body_words=120,
        keyword="k",
        intent="how-to",
        heading_structure=[{"order": 1, "text": "Topic"}],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[],
        brand_voice_card=None,
        banned_regex=None,
        write_h2_group_fn=fake,
    )
    assert result.retries_attempted == 1
    assert result.retries_succeeded == 0
    assert len(result.under_length_h2_sections) == 1
    entry = result.under_length_h2_sections[0]
    assert entry["section_order"] == 1
    assert entry["floor"] == 120
    assert entry["word_count"] < 120
    # The retry produced more words than the original, so the
    # validator accepted the retry's output.
    assert "Slightly more words" in result.validated_article[0].body


@pytest.mark.asyncio
async def test_validator_keeps_better_of_original_and_retry():
    """If the retry produces FEWER words than the original (rare but
    possible), the validator keeps the original."""
    article = [_h2(1, "Topic", "five word body here please ok")]  # 6 words
    fake, _ = _make_retry_fn("two words")  # 2 words

    result = await validate_h2_body_lengths(
        article,
        min_h2_body_words=120,
        keyword="k",
        intent="how-to",
        heading_structure=[{"order": 1, "text": "Topic"}],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[],
        brand_voice_card=None,
        banned_regex=None,
        write_h2_group_fn=fake,
    )
    assert result.under_length_h2_sections[0]["word_count"] == 6
    # Original preserved (retry was worse).
    assert result.validated_article[0].body == "five word body here please ok"


@pytest.mark.asyncio
async def test_validator_aggregates_h2_with_h3_word_counts():
    """Group word count includes H3 child bodies, so an H2 with a sparse
    parent body but rich H3s still passes."""
    article = [
        _h2(1, "Topic", "Short H2 body."),  # 3 words
        _h3(2, "Sub A", " ".join(["w"] * 100)),
        _h3(3, "Sub B", " ".join(["w"] * 100)),  # 200 words across H3s
    ]
    fake, state = _make_retry_fn("ignored")

    result = await validate_h2_body_lengths(
        article,
        min_h2_body_words=120,
        keyword="k",
        intent="how-to",
        heading_structure=[
            {"order": 1, "text": "Topic"},
            {"order": 2, "text": "Sub A"},
            {"order": 3, "text": "Sub B"},
        ],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[],
        brand_voice_card=None,
        banned_regex=None,
        write_h2_group_fn=fake,
    )
    # 3 + 100 + 100 = 203 words, well above 120 — no retry.
    assert state["calls"] == 0
    assert result.retries_attempted == 0


@pytest.mark.asyncio
async def test_validator_retry_failure_logs_and_flags():
    """If write_h2_group raises, the validator must not crash — it
    flags the section as under-length and continues."""
    article = [_h2(1, "Topic", "short")]

    async def boom(**kwargs):
        raise RuntimeError("LLM outage")

    result = await validate_h2_body_lengths(
        article,
        min_h2_body_words=120,
        keyword="k",
        intent="how-to",
        heading_structure=[{"order": 1, "text": "Topic"}],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[],
        brand_voice_card=None,
        banned_regex=None,
        write_h2_group_fn=boom,
    )
    assert result.retries_attempted == 1
    assert result.retries_succeeded == 0
    assert len(result.under_length_h2_sections) == 1
    # Original section preserved (retry crashed, no replacement applied).
    assert result.validated_article[0].body == "short"


@pytest.mark.asyncio
async def test_validator_retries_each_under_length_h2_independently():
    """Two H2s each below floor → two retries, independent outcomes."""
    article = [
        _h2(1, "Topic A", "short"),
        _h2(2, "Topic B", "also short"),
    ]
    fake, state = _make_retry_fn(" ".join(["w"] * 200))  # Both retries succeed

    result = await validate_h2_body_lengths(
        article,
        min_h2_body_words=120,
        keyword="k",
        intent="how-to",
        heading_structure=[
            {"order": 1, "text": "Topic A"},
            {"order": 2, "text": "Topic B"},
        ],
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[],
        brand_voice_card=None,
        banned_regex=None,
        write_h2_group_fn=fake,
    )
    assert state["calls"] == 2
    assert result.retries_attempted == 2
    assert result.retries_succeeded == 2
    assert result.under_length_h2_sections == []


@pytest.mark.asyncio
async def test_validator_skips_when_brief_heading_missing():
    """If we can't find the H2 in heading_structure (defensive), flag
    the section as under-length WITHOUT calling the LLM."""
    article = [_h2(1, "Topic", "short")]
    fake, state = _make_retry_fn("ignored")

    result = await validate_h2_body_lengths(
        article,
        min_h2_body_words=120,
        keyword="k",
        intent="how-to",
        heading_structure=[],  # no entries
        section_budgets={},
        filtered_terms=_filtered_terms(),
        citations=[],
        brand_voice_card=None,
        banned_regex=None,
        write_h2_group_fn=fake,
    )
    assert state["calls"] == 0
    assert result.retries_attempted == 0
    assert len(result.under_length_h2_sections) == 1

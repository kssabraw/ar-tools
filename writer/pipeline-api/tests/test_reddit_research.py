"""Reddit research module — Perplexity synthesis (PRD v2.4).

Covers:
- Section parsing on a representative Markdown response
- Citation validation (reddit ratio, minimum count)
- Fallback paths (Perplexity unavailable, HTTP error, empty content,
  validation failure on final attempt)
- Retry logic on validation failure
"""

from __future__ import annotations

import pytest

from modules.brief.perplexity_client import (
    PerplexityError,
    PerplexityUnavailable,
)
from modules.brief.reddit_research import (
    MIN_CITATIONS,
    MIN_REDDIT_CITATION_RATIO,
    _filter_reddit_citations,
    _parse_sections,
    _validate_citations,
    research_reddit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_payload(content: str, citations: list[str]) -> dict:
    """Mirror Perplexity's chat-completions response shape."""
    return {
        "choices": [
            {"message": {"role": "assistant", "content": content}}
        ],
        "citations": citations,
    }


def _good_markdown(keyword: str = "test topic") -> str:
    return f"""# Reddit Insights for {keyword}

## 1. Authentic Experience Signals
- Positive: real users describe X working well [1]
- Negative: pain point Y comes up repeatedly [2]

## 2. Common Fears & Concerns
- Fear of cost overruns [3]
- Fear of vendor lock-in [4]

## 3. What Redditors Value & Recommend
- Value transparency in pricing [5]
- Recommend reading reviews before signing [6]

## 4. Specific E-E-A-T Opportunities
- Add a section on hidden costs
- Surface real customer timelines

## 5. Information Gain vs. Competing Content
- Competitors miss the post-purchase support angle entirely

## 6. Emotional, Cultural & Experiential Insights
- Tone is skeptical; users have been burned before

## 7. Citations
1. https://www.reddit.com/r/test/comments/aaa/x/
2. https://www.reddit.com/r/test/comments/bbb/y/
3. https://www.reddit.com/r/test/comments/ccc/z/
4. https://www.reddit.com/r/test/comments/ddd/w/
5. https://www.reddit.com/r/test/comments/eee/v/
6. https://www.reddit.com/r/test/comments/fff/u/
"""


def _good_citations() -> list[str]:
    return [
        "https://www.reddit.com/r/test/comments/aaa/x/",
        "https://www.reddit.com/r/test/comments/bbb/y/",
        "https://www.reddit.com/r/test/comments/ccc/z/",
        "https://www.reddit.com/r/test/comments/ddd/w/",
        "https://www.reddit.com/r/test/comments/eee/v/",
        "https://www.reddit.com/r/test/comments/fff/u/",
    ]


def _mock_call(response):
    async def _call(*, system, user):
        if isinstance(response, Exception):
            raise response
        return response
    return _call


def _mock_calls(*responses):
    """Sequential responses across attempts."""
    iterator = iter(responses)

    async def _call(*, system, user):
        item = next(iterator)
        if isinstance(item, Exception):
            raise item
        return item

    return _call


# ---------------------------------------------------------------------------
# Section parser
# ---------------------------------------------------------------------------


def test_parse_sections_extracts_seven_sections():
    md = _good_markdown()
    sections = _parse_sections(md)
    assert len(sections) == 7
    assert "Authentic Experience Signals" in sections
    assert "Common Fears & Concerns" in sections
    assert "What Redditors Value & Recommend" in sections
    assert "Citations" in sections


def test_parse_sections_handles_missing_sections():
    """Permissive: returns whatever sections it can find."""
    md = """## 1. Only One Section
some content here
"""
    sections = _parse_sections(md)
    assert "Only One Section" in sections


def test_parse_sections_returns_empty_when_no_headers():
    sections = _parse_sections("just prose, no h2 headers at all")
    assert sections == {}


# ---------------------------------------------------------------------------
# Citation validation
# ---------------------------------------------------------------------------


def test_filter_reddit_citations_strips_non_reddit():
    citations = [
        "https://www.reddit.com/r/x/comments/aaa/",
        "https://example.com/article",
        "https://reddit.com/r/y/comments/bbb/",  # bare reddit.com
        "https://google.com/search?q=foo",
    ]
    reddit = _filter_reddit_citations(citations)
    assert len(reddit) == 2


def test_validate_citations_passes_with_six_reddit_urls():
    reddit, failure = _validate_citations(_good_citations())
    assert failure is None
    assert len(reddit) == 6


def test_validate_citations_fails_with_too_few():
    citations = ["https://www.reddit.com/r/x/comments/aaa/"] * 2
    reddit, failure = _validate_citations(citations)
    assert failure is not None
    assert "too_few_reddit_citations" in failure


def test_validate_citations_fails_when_non_reddit_dominates():
    citations = (
        ["https://www.reddit.com/r/x/comments/aaa/"] * 4
        + ["https://example.com/foo"] * 10
    )
    reddit, failure = _validate_citations(citations)
    # 4/14 = 0.29 < MIN_REDDIT_CITATION_RATIO (0.6)
    assert failure is not None
    assert "non_reddit_citations_dominate" in failure


def test_validate_citations_empty_returns_failure():
    reddit, failure = _validate_citations([])
    assert failure == "no_citations_returned"
    assert reddit == []


# ---------------------------------------------------------------------------
# research_reddit happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_research_reddit_happy_path():
    payload = _build_payload(_good_markdown(), _good_citations())
    insights = await research_reddit(
        "test keyword", perplexity_fn=_mock_call(payload)
    )
    assert insights.available is True
    assert insights.fallback_reason is None
    assert insights.citation_count == 6
    assert len(insights.sections) == 7
    assert "Authentic Experience Signals" in insights.sections


@pytest.mark.asyncio
async def test_research_reddit_returns_unavailable_when_no_api_key():
    """PerplexityUnavailable surfaces as available=False with the reason."""
    async def raise_unavailable(*, system, user):
        raise PerplexityUnavailable("PERPLEXITY_API_KEY not set")

    insights = await research_reddit(
        "kw", perplexity_fn=raise_unavailable
    )
    assert insights.available is False
    assert insights.fallback_reason == "perplexity_unavailable"
    assert insights.markdown_report == ""


@pytest.mark.asyncio
async def test_research_reddit_falls_back_on_http_error_after_retries():
    """Both attempts hit PerplexityError → returns available=False."""
    err = PerplexityError("HTTP 500: server error")
    insights = await research_reddit(
        "kw", perplexity_fn=_mock_calls(err, err)
    )
    assert insights.available is False
    assert insights.fallback_reason is not None
    assert "perplexity_error" in insights.fallback_reason


@pytest.mark.asyncio
async def test_research_reddit_retries_on_validation_failure_then_passes():
    """First attempt has too few reddit citations; second attempt passes."""
    bad_payload = _build_payload(
        _good_markdown(),
        ["https://example.com/x", "https://example.com/y"],  # zero reddit
    )
    good_payload = _build_payload(_good_markdown(), _good_citations())
    insights = await research_reddit(
        "kw", perplexity_fn=_mock_calls(bad_payload, good_payload)
    )
    assert insights.available is True
    assert insights.fallback_reason is None
    assert insights.citation_count == 6


@pytest.mark.asyncio
async def test_research_reddit_keeps_partial_synthesis_on_final_validation_fail():
    """If both attempts fail validation but synthesis content exists, we
    return available=True with the report and a populated fallback_reason
    so the caller can log low_coverage but still use the content."""
    bad_payload = _build_payload(
        _good_markdown(),
        ["https://www.reddit.com/r/x/comments/aaa/"],  # only 1 reddit
    )
    insights = await research_reddit(
        "kw", perplexity_fn=_mock_calls(bad_payload, bad_payload)
    )
    assert insights.available is True  # still surfaced for partial value
    assert insights.fallback_reason is not None
    assert "too_few_reddit_citations" in insights.fallback_reason


@pytest.mark.asyncio
async def test_research_reddit_fails_when_content_is_empty():
    payload = _build_payload("", _good_citations())
    insights = await research_reddit(
        "kw", perplexity_fn=_mock_calls(payload, payload)
    )
    assert insights.available is False
    assert insights.fallback_reason == "empty_content"


@pytest.mark.asyncio
async def test_research_reddit_to_dict_serialization():
    """to_dict() shape matches the RedditInsightsModel pydantic schema."""
    payload = _build_payload(_good_markdown(), _good_citations())
    insights = await research_reddit(
        "kw", perplexity_fn=_mock_call(payload)
    )
    d = insights.to_dict()
    assert set(d.keys()) == {
        "available",
        "markdown_report",
        "sections",
        "citations",
        "reddit_citations",
        "fallback_reason",
    }
    assert d["available"] is True
    assert isinstance(d["sections"], dict)
    assert isinstance(d["citations"], list)

"""Research & Citations pipeline tests with mocked external APIs."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from models.research import ResearchRequest


SAMPLE_BRIEF = {
    "keyword": "best hvac systems 2026",
    "intent_type": "informational-commercial",
    "intent_confidence": 0.85,
    "intent_review_required": False,
    "heading_structure": [
        {
            "level": "H1", "text": "best hvac systems 2026", "type": "content",
            "source": "serp", "order": 1, "heading_priority": 1.0,
        },
        {
            "level": "H2", "text": "Energy Efficiency Ratings Explained", "type": "content",
            "source": "serp", "order": 2, "heading_priority": 0.85,
        },
        {
            "level": "H3", "text": "Hidden costs homeowners overlook", "type": "content",
            "source": "authority_gap_sme", "order": 3, "heading_priority": 0.8,
        },
        {
            "level": "H2", "text": "Top HVAC Brand Comparisons", "type": "content",
            "source": "serp", "order": 4, "heading_priority": 0.75,
        },
        {
            "level": "H2", "text": "Frequently Asked Questions", "type": "faq-header",
            "source": "synthesized", "order": 5,
        },
        {
            "level": "H3", "text": "How long does an HVAC system last?", "type": "faq-question",
            "source": "synthesized", "order": 6,
        },
    ],
    "metadata": {
        "competitor_domains": ["competitor1.com", "competitor2.com"],
        "schema_version": "1.7",
    },
}


# Tier 1 source for one H2; Tier 3 for the other; PDF-style for the auth gap H3
SEARCH_RESULTS_BY_QUERY = {
    "default": [
        {"url": "https://www.energy.gov/energysaver/hvac-efficiency-guide",
         "title": "HVAC Efficiency Guide", "description": "Federal guidance on HVAC efficiency."},
        {"url": "https://www.consumerreports.org/hvac/best-hvac-systems",
         "title": "Best HVAC Systems 2026 from Consumer Reports",
         "description": "Comprehensive review of HVAC brands and their performance ratings."},
        {"url": "https://blog.somerandomdomain.com/hvac-comparison",
         "title": "HVAC Brand Comparison", "description": "Comparison of HVAC brands."},
    ],
}


SAMPLE_HTML = """
<html>
<head>
<title>HVAC Efficiency Guide - Department of Energy</title>
<meta property="article:published_time" content="2025-06-15T00:00:00Z">
<meta property="og:site_name" content="Department of Energy">
<meta name="author" content="DOE Energy Saver Team">
</head>
<body>
<h1>HVAC Efficiency Guide</h1>
<p>According to the Department of Energy, modern HVAC systems can be up to 50% more energy efficient than systems manufactured before 2006. The minimum SEER rating required for new central air conditioners is 14 in northern states and 15 in southern states.</p>
<p>The average homeowner spends $2,500 per year on heating and cooling costs, which represents about 48% of typical home energy use.</p>
<p>Heat pump installations grew by 11% year over year between 2023 and 2024, driven by federal tax credits of up to $2,000 under the Inflation Reduction Act.</p>
</body>
</html>
"""


def _fake_embedding(text: str, dim: int = 16) -> list[float]:
    vec = [0.0] * dim
    for i, ch in enumerate(text.lower()):
        vec[i % dim] += (ord(ch) % 19) / 19.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


async def fake_serp_organic_advanced(keyword, *args, **kwargs):
    return {"task": {}, "items": [
        {"type": "organic", **r} for r in SEARCH_RESULTS_BY_QUERY["default"]
    ]}


async def fake_fetch_many(urls, concurrency=6):
    from modules.research.fetcher import FetchedContent
    out = []
    for url in urls:
        if "energy.gov" in url:
            out.append(FetchedContent(
                url=url,
                success=True,
                html=SAMPLE_HTML,
                body_text=(
                    "According to the Department of Energy, modern HVAC systems can be up to 50% "
                    "more energy efficient than systems manufactured before 2006. "
                    "The minimum SEER rating required for new central air conditioners is 14 in "
                    "northern states and 15 in southern states. "
                    "The average homeowner spends $2,500 per year on heating and cooling costs, "
                    "which represents about 48% of typical home energy use. "
                    "Heat pump installations grew by 11% year over year between 2023 and 2024, "
                    "driven by federal tax credits of up to $2,000 under the Inflation Reduction Act."
                ),
                title="HVAC Efficiency Guide",
                author="DOE Energy Saver Team",
                publication="Department of Energy",
                published_iso="2025-06-15T00:00:00+00:00",
                language="en",
                final_url=url,
            ))
        elif "consumerreports.org" in url:
            out.append(FetchedContent(
                url=url,
                success=True,
                body_text=(
                    "Consumer Reports tested 25 HVAC brands in 2024 and found that Trane, Lennox, "
                    "and Carrier consistently scored 85 out of 100 or higher across reliability, "
                    "energy efficiency, and customer satisfaction metrics."
                ),
                title="Best HVAC Systems 2026",
                publication="Consumer Reports",
                published_iso="2024-11-01T00:00:00+00:00",
                language="en",
                final_url=url,
            ))
        else:
            out.append(FetchedContent(
                url=url,
                success=True,
                body_text=(
                    "HVAC comparison data for 2025. Most comparison sites note that Carrier units "
                    "carry a 10-year warranty, while Goodman warrants its compressors for 10 years."
                ),
                title="HVAC Brand Comparison",
                publication="Random Blog",
                published_iso="2025-03-01T00:00:00+00:00",
                language="en",
                final_url=url,
            ))
    return out


async def fake_embed_batch(texts):
    return [_fake_embedding(t) for t in texts]


async def fake_claude_json(system, user, **kwargs):
    sys_lower = system.lower()
    user_lower = user.lower()
    # Query generation
    if "query string" in sys_lower or "search query" in user_lower or "search queries" in user_lower:
        return ["hvac efficiency statistics", "energy department hvac guidance"]
    # Claim extraction
    if "extract" in sys_lower and "claim" in sys_lower:
        return [
            {
                "claim_text": "modern HVAC systems can be up to 50% more energy efficient than systems manufactured before 2006",
                "relevance_score": 0.92,
            },
            {
                "claim_text": "average homeowner spends $2,500 per year on heating and cooling costs",
                "relevance_score": 0.88,
            },
            # An invented stat that should fail numeric integrity
            {
                "claim_text": "heat pump installations grew by 99% year over year",
                "relevance_score": 0.85,
            },
        ]
    return []


@pytest.mark.asyncio
async def test_research_happy_path():
    from modules.research.pipeline import run_research

    req = ResearchRequest(
        run_id="test-research",
        keyword="best hvac systems 2026",
        brief_output=SAMPLE_BRIEF,
    )

    with (
        patch("modules.research.pipeline.dfs.serp_organic_advanced", fake_serp_organic_advanced),
        patch("modules.research.pipeline.fetch_many", fake_fetch_many),
        patch("modules.research.pipeline.embed_batch", fake_embed_batch),
        patch("modules.research.queries.claude_json", fake_claude_json),
        patch("modules.research.extraction.claude_json", fake_claude_json),
    ):
        result = await run_research(req)

    md = result.citations_metadata
    assert md.citations_schema_version == "1.1"
    # We have 2 H2s + 1 authority gap H3 = 3 targets
    assert md.h2s_with_citations + md.h2s_without_citations == 2
    # Must have at least 1 citation
    assert md.total_citations >= 1
    # Numeric integrity should have rejected the "99%" claim
    all_claim_texts = [c.claim_text for cit in result.citations for c in cit.claims]
    assert not any("99%" in t for t in all_claim_texts)
    # Heading structure must have citation_ids on every item
    for item in result.enriched_brief["heading_structure"]:
        assert "citation_ids" in item
        assert isinstance(item["citation_ids"], list)
    # Tier 1 found from energy.gov
    assert any(c.tier == 1 for c in result.citations)


@pytest.mark.asyncio
async def test_research_aborts_on_no_h2s():
    from modules.research.pipeline import ResearchError, run_research

    bad_brief = {
        "keyword": "test",
        "intent_type": "informational",
        "heading_structure": [
            {"level": "H1", "text": "Test", "type": "content", "source": "serp", "order": 1},
        ],
        "metadata": {"competitor_domains": []},
    }
    req = ResearchRequest(run_id="t", keyword="test", brief_output=bad_brief)
    with pytest.raises(ResearchError) as exc_info:
        await run_research(req)
    assert exc_info.value.code == "no_content_h2s"


def test_claim_verification():
    from modules.research.extraction import verify_claim

    source = (
        "The minimum SEER rating required for new central air conditioners is 14 in "
        "northern states and 15 in southern states. The average homeowner spends $2,500 "
        "per year on heating and cooling costs."
    )
    # Verbatim
    assert verify_claim(
        "minimum SEER rating required for new central air conditioners is 14",
        source,
    ) == "verbatim_match"
    # Numeric integrity violation — should reject
    assert verify_claim(
        "average homeowner spends $9,999 per year on heating",
        source,
    ) is None
    # No match at all
    assert verify_claim(
        "completely fabricated nonsense statement about ferrets",
        source,
    ) is None


def test_tier_classification():
    from modules.research.tiering import classify_tier, is_excluded, root_domain

    assert classify_tier("https://www.energy.gov/topic") == 1
    assert classify_tier("https://harvard.edu/research") == 1
    assert classify_tier("https://www.reuters.com/article") == 2
    assert classify_tier("https://random-blog.com/post") == 3
    assert is_excluded("https://en.wikipedia.org/Test", frozenset()) == "excluded_category"
    assert is_excluded("https://reddit.com/r/test", frozenset()) == "excluded_category"
    assert is_excluded("https://competitor.com/x", frozenset({"competitor.com"})) == "competitor_domain"
    assert is_excluded("http://insecure.com/x", frozenset()) == "http_only"
    assert root_domain("https://www.example.com/page") == "example.com"


def test_research_request_validation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ResearchRequest(run_id="r", keyword="", brief_output={})
    with pytest.raises(ValidationError):
        ResearchRequest(run_id="r", keyword="x" * 151, brief_output={})

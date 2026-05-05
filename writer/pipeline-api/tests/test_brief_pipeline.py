"""LEGACY v1.8 pipeline test — skipped during the v2.0 staged rollout.

The v2.0 orchestrator is built in Stage 9; the rewritten happy-path test
will live in test_brief_v2_pipeline.py with v2.0 fixtures (Fixtures A–G
from PRD §14.3).

Original docstring preserved below.
================================================================
Happy-path test for the Brief Generator pipeline.

Mocks all external APIs (DataForSEO, OpenAI embeddings, Anthropic) so the
test runs offline and deterministically. Verifies the pipeline produces a
schema-valid BriefResponse with the expected structural invariants.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "Legacy v1.8 pipeline test; v2.0 orchestrator is rebuilt in Stage 9.",
    allow_module_level=True,
)

import math
from typing import Any
from unittest.mock import patch

import pytest

from models.brief import BriefRequest


# ---- Fixture data ----

SERP_ITEMS = [
    {
        "type": "organic",
        "rank_absolute": 1,
        "url": "https://example.com/best-hvac-systems",
        "title": "Best HVAC Systems for 2026: Top Picks Reviewed",
        "description": "Comparing the leading HVAC systems for energy efficiency.",
    },
    {
        "type": "organic",
        "rank_absolute": 2,
        "url": "https://hvac-pro.com/buyers-guide",
        "title": "HVAC Buyers Guide: How to Choose the Right System",
        "description": "Choosing an HVAC system depends on home size and climate.",
    },
    {
        "type": "organic",
        "rank_absolute": 3,
        "url": "https://blog.hvac.com/energy-efficiency",
        "title": "Energy Efficient HVAC Systems Worth the Investment",
        "description": "SEER ratings explained for homeowners.",
    },
    {
        "type": "organic",
        "rank_absolute": 4,
        "url": "https://hvac-experts.com/installation-cost",
        "title": "Average HVAC Installation Cost in 2026",
        "description": "Installation prices vary by region and unit type.",
    },
    {
        "type": "organic",
        "rank_absolute": 5,
        "url": "https://techreviews.com/hvac-comparison",
        "title": "Carrier vs Trane vs Lennox HVAC Comparison",
        "description": "Side-by-side performance comparison of major brands.",
    },
    {
        "type": "people_also_ask",
        "items": [
            {"title": "What is the most efficient HVAC system?"},
            {"title": "How long does an HVAC system last?"},
            {"title": "Is geothermal HVAC worth it?"},
            {"title": "How much does HVAC installation cost?"},
        ],
    },
    {"type": "featured_snippet"},
]


REDDIT_ITEMS = [
    {
        "title": "Best HVAC system for a 2,500 sqft house?",
        "description": "Has anyone installed a heat pump in zone 5 climate?",
    },
    {
        "title": "Trane vs Carrier — which lasts longer?",
        "description": "I've heard mixed things about both. What's the consensus?",
    },
]

AUTOCOMPLETE = [
    "best hvac systems for the money",
    "best hvac systems consumer reports",
    "best hvac systems 2026 ratings",
]

SUGGESTIONS = [
    "energy efficient hvac systems",
    "split system hvac",
    "central hvac vs mini split",
    "hvac maintenance schedule",
]


def _fake_embedding(text: str, dim: int = 8) -> list[float]:
    """Deterministic pseudo-embedding from the text — stable across calls."""
    vec = [0.0] * dim
    for i, ch in enumerate(text.lower()):
        vec[i % dim] += (ord(ch) % 17) / 17.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


async def fake_serp_organic_advanced(*args, **kwargs):
    return {"task": {}, "items": SERP_ITEMS}


async def fake_serp_reddit(*args, **kwargs):
    return REDDIT_ITEMS


async def fake_autocomplete(*args, **kwargs):
    return AUTOCOMPLETE


async def fake_keyword_suggestions(*args, **kwargs):
    return SUGGESTIONS


async def fake_llm_response(keyword: str, model: str, **kwargs):
    """Return a small fan-out + body for each LLM."""
    return {
        "text": (
            f"For {keyword}, key subtopics include energy efficiency ratings, "
            "installation cost considerations, brand reliability comparisons, "
            "warranty coverage details, and ongoing maintenance requirements."
        ),
        "fan_out_queries": [
            "energy efficiency ratings for hvac systems",
            "how to compare hvac warranties",
            "hvac installation cost factors",
        ],
    }


async def fake_embed_batch(texts: list[str]) -> list[list[float]]:
    return [_fake_embedding(t) for t in texts]


async def fake_claude_json(system: str, user: str, **kwargs):
    """Return safe defaults based on what the prompt looks like for."""
    if "polish" in system.lower() or "rewrite" in system.lower():
        # Return empty list — leave headings as-is
        return []
    if "authority" in system.lower():
        return {
            "headings": [
                "Hidden costs homeowners overlook before installation",
                "Regional efficiency rebates and tax credit eligibility",
                "How HVAC efficiency standards evolve over the next decade",
            ]
        }
    if "implicit questions" in system.lower() or "concerns" in system.lower():
        return {
            "questions": [
                "How do I know if my contractor sized the unit correctly?",
                "What rebates exist for high-efficiency HVAC installations?",
            ]
        }
    if "subtopic" in system.lower() or "concepts" in system.lower():
        return [
            "energy efficiency ratings",
            "installation cost considerations",
            "warranty coverage details",
        ]
    if "intent" in system.lower():
        return {"intent": "informational-commercial"}
    if "tutorial" in system.lower() or "sequential" in system.lower():
        return {"order": list(range(20))}
    return {}


@pytest.mark.asyncio
async def test_run_brief_happy_path():
    from modules.brief.pipeline import run_brief

    req = BriefRequest(run_id="test-run", keyword="best hvac systems 2026")

    with (
        patch("modules.brief.pipeline.dataforseo.serp_organic_advanced", fake_serp_organic_advanced),
        patch("modules.brief.pipeline.dataforseo.serp_reddit", fake_serp_reddit),
        patch("modules.brief.pipeline.dataforseo.autocomplete", fake_autocomplete),
        patch("modules.brief.pipeline.dataforseo.keyword_suggestions", fake_keyword_suggestions),
        patch("modules.brief.pipeline.dataforseo.llm_response", fake_llm_response),
        patch("modules.brief.llm.embed_batch", fake_embed_batch),
        patch("modules.brief.scoring.embed_batch", fake_embed_batch),
        patch("modules.brief.faqs.embed_batch", fake_embed_batch),
        patch("modules.brief.scoring.claude_json", fake_claude_json),
        patch("modules.brief.intent.claude_json", fake_claude_json),
        patch("modules.brief.authority.claude_json", fake_claude_json),
        patch("modules.brief.faqs.claude_json", fake_claude_json),
        patch("modules.brief.pipeline.claude_json", fake_claude_json),
        patch("modules.brief.assembly.claude_json", fake_claude_json),
    ):
        result = await run_brief(req)

    # Schema invariants
    assert result.metadata.schema_version == "1.8"
    assert result.keyword == "best hvac systems 2026"

    # CQ PRD R1/R2 metadata fields are present
    assert hasattr(result.metadata, "semantic_dedup_threshold")
    assert hasattr(result.metadata, "semantic_dedup_collapses_count")
    assert hasattr(result.metadata, "sanitization_discards_count")
    assert hasattr(result, "spin_off_articles")

    # Has H1 (title-cased per Brief PRD v2.0.3 Step 11.x)
    h1s = [h for h in result.heading_structure if h.level == "H1"]
    assert len(h1s) == 1
    from titlecase import titlecase
    assert h1s[0].text == titlecase("best hvac systems 2026")
    # And the response's `title` field equals the H1 text (Writer v1.6 §4.5)
    assert result.title == h1s[0].text

    # Has at least one H2 of content type
    content_h2s = [h for h in result.heading_structure if h.level == "H2" and h.type == "content"]
    assert len(content_h2s) >= 1

    # FAQ section present
    faq_headers = [h for h in result.heading_structure if h.type == "faq-header"]
    assert len(faq_headers) == 1
    faq_qs = [h for h in result.heading_structure if h.type == "faq-question"]
    assert 3 <= len(faq_qs) <= 5

    # Authority gap headings tagged
    auth_h3s = [h for h in result.heading_structure if h.source == "authority_gap_sme"]
    assert len(auth_h3s) >= 1
    assert all(h.exempt for h in auth_h3s)

    # Metadata counts agree with structure
    assert result.metadata.h2_count == len(content_h2s)
    assert result.metadata.faq_count == len(faq_qs)


@pytest.mark.asyncio
async def test_run_brief_aborts_on_empty_serp():
    from modules.brief.pipeline import BriefError, run_brief

    async def empty_serp(*a, **kw):
        return {"task": {}, "items": []}

    req = BriefRequest(run_id="t", keyword="zzzzzzzzz")
    with patch("modules.brief.pipeline.dataforseo.serp_organic_advanced", empty_serp):
        with pytest.raises(BriefError) as exc_info:
            await run_brief(req)
    assert exc_info.value.code == "serp_no_results"


def test_brief_request_validation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        BriefRequest(run_id="r", keyword="")
    with pytest.raises(ValidationError):
        BriefRequest(run_id="r", keyword="x" * 151)

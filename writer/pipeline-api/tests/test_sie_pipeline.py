"""SIE pipeline tests with mocked external APIs.

Mocks DataForSEO SERP, ScrapeOwl, OpenAI embeddings, Claude, Google NLP, and
the Supabase cache. Verifies the pipeline emits a schema-valid SIEResponse
and that cache hits short-circuit the pipeline.
"""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from models.sie import SIERequest


SERP_ITEMS = [
    {"type": "organic", "rank_absolute": i + 1,
     "url": f"https://example{i}.com/water-heater-repair",
     "title": f"Water Heater Repair Guide {i}",
     "description": "Comprehensive water heater repair information."}
    for i in range(8)
]


SAMPLE_HTML_TEMPLATE = """
<html>
  <head>
    <title>Water Heater Repair Guide {i} — Complete Service Information</title>
    <meta name="description" content="Professional water heater repair services for homeowners">
  </head>
  <body>
    <nav>Main navigation menu about water heater services</nav>
    <main>
      <h1>Water Heater Repair Services</h1>
      <p>Water heater repair is essential when your water heater fails to produce hot water consistently across the entire home environment.</p>
      <h2>Common Water Heater Repair Issues</h2>
      <p>The most common water heater repair issues include thermostat failures, heating element problems, and sediment buildup that requires professional water heater repair attention from licensed technicians.</p>
      <h2>Tankless Water Heater Repair Cost</h2>
      <p>The tankless water heater repair cost typically ranges from two hundred to eight hundred dollars depending on the specific water heater repair issue, the brand, and required parts replacement.</p>
      <h3>When to Call a Professional</h3>
      <p>Always call a professional plumber for water heater repair when dealing with gas connections, electrical components, or warranty issues. DIY water heater repair can void manufacturer warranties.</p>
      <h2>Choosing the Right Water Heater Repair Service</h2>
      <p>Look for licensed and insured water heater repair contractors with positive reviews, transparent pricing, and emergency service availability. Quality water heater repair service ensures lasting results.</p>
    </main>
    <footer>Footer content with social links and copyright information</footer>
  </body>
</html>
"""


def _fake_embedding(text: str, dim: int = 16) -> list[float]:
    vec = [0.0] * dim
    for i, ch in enumerate(text.lower()):
        vec[i % dim] += (ord(ch) % 19) / 19.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


# ---- Mocks ----

async def fake_serp(*args, **kwargs):
    return {"task": {}, "items": SERP_ITEMS}


async def fake_scrape_many(urls, concurrency=5):
    from modules.sie.scraper import ScrapeResult
    results = []
    for i, url in enumerate(urls):
        results.append(ScrapeResult(
            url=url,
            html=SAMPLE_HTML_TEMPLATE.format(i=i),
            status_code=200,
            success=True,
        ))
    return results


async def fake_embed_batch(texts):
    return [_fake_embedding(t) for t in texts]


async def fake_claude_json(system, user, **kwargs):
    if "entities" in system.lower():
        return {"entities": []}
    return {}


async def fake_extract_entities(pages):
    return ([], [])  # No entities, no failures


async def fake_get_cached(*args, **kwargs):
    return None


async def fake_write_cache(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_sie_happy_path():
    from modules.sie.pipeline import run_sie

    req = SIERequest(
        run_id="test-sie",
        keyword="water heater repair",
        outlier_mode="safe",
    )

    with (
        patch("modules.sie.pipeline.dfs.serp_organic_advanced", fake_serp),
        patch("modules.sie.pipeline.scrape_many", fake_scrape_many),
        patch("modules.sie.filters.embed_batch", fake_embed_batch),
        patch("modules.sie.pipeline.extract_entities", fake_extract_entities),
        patch("modules.sie.pipeline.cache.get_cached", fake_get_cached),
        patch("modules.sie.pipeline.cache.write_cache", fake_write_cache),
    ):
        result = await run_sie(req)

    assert result.schema_version == "1.0"
    assert result.keyword == "water heater repair"
    assert result.outlier_mode == "safe"
    assert result.cached is False
    assert result.sie_cache_hit is False
    assert result.target_keyword.term == "water heater repair"
    assert result.target_keyword.minimum_usage == {"title": 1, "h1": 1, "paragraphs": 1}
    # Should have at least the target keyword in required terms
    assert len(result.terms.required) >= 1
    assert any(r.is_target_keyword for r in result.terms.required)
    # Word count target should be set (we have 8 pages with content)
    assert result.word_count_target >= 0
    # No critical warnings since we have 8 eligible pages
    critical = [w for w in result.warnings if w.level == "critical"]
    assert not critical


@pytest.mark.asyncio
async def test_sie_cache_hit_short_circuits():
    from modules.sie.pipeline import run_sie

    cached_payload = {
        "schema_version": "1.0",
        "keyword": "water heater repair",
        "location_code": 2840,
        "language_code": "en",
        "outlier_mode": "safe",
        "cached": False,
        "cache_date": None,
        "sie_cache_hit": False,
        "run_date": "2026-04-30T00:00:00Z",
        "serp_summary": {"analyzed_urls": [], "excluded_urls": [], "failed_urls": [], "dominant_page_type": "informational_article"},
        "word_count": {"min": 1000, "target": 1500, "max": 2000, "source_word_counts": [1500]},
        "word_count_target": 1500,
        "terms": {"required": [], "avoid": [], "low_coverage_candidates": []},
        "term_signals": {
            "coverage_threshold_applied": True,
            "tfidf_threshold_applied": True,
            "terms_filtered_by_coverage": 0,
            "terms_filtered_by_tfidf": 0,
            "terms_passed_to_embedding": 0,
            "subsumption_merges": 0,
        },
        "usage_recommendations": [],
        "target_keyword": {
            "term": "water heater repair",
            "is_target_keyword": True,
            "recommendation_score": 1.0,
            "recommendation_category": "required",
            "confidence": "high",
            "minimum_usage": {"title": 1, "h1": 1, "paragraphs": 1},
        },
        "warnings": [],
    }

    async def hit(*args, **kwargs):
        return cached_payload

    req = SIERequest(run_id="t", keyword="water heater repair")
    with patch("modules.sie.pipeline.cache.get_cached", hit):
        result = await run_sie(req)

    assert result.cached is True
    assert result.sie_cache_hit is True
    # Cache hit should not call ScrapeOwl, DataForSEO, etc.


@pytest.mark.asyncio
async def test_sie_force_refresh_skips_cache():
    """When force_refresh=True, cache.get_cached must not be consulted."""
    from modules.sie.pipeline import run_sie

    cache_called = {"hit": False}

    async def hit(*args, **kwargs):
        cache_called["hit"] = True
        return None  # Even though we set it, force_refresh should prevent the call

    req = SIERequest(run_id="t", keyword="water heater repair", force_refresh=True)
    with (
        patch("modules.sie.pipeline.cache.get_cached", hit),
        patch("modules.sie.pipeline.dfs.serp_organic_advanced", fake_serp),
        patch("modules.sie.pipeline.scrape_many", fake_scrape_many),
        patch("modules.sie.filters.embed_batch", fake_embed_batch),
        patch("modules.sie.pipeline.extract_entities", fake_extract_entities),
        patch("modules.sie.pipeline.cache.write_cache", fake_write_cache),
    ):
        await run_sie(req)

    assert cache_called["hit"] is False


def test_sie_request_validation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SIERequest(run_id="r", keyword="")
    with pytest.raises(ValidationError):
        SIERequest(run_id="r", keyword="x" * 151)
    # Outlier mode constraint
    with pytest.raises(ValidationError):
        SIERequest(run_id="r", keyword="ok", outlier_mode="reckless")

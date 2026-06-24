"""Tests for the Service Page Brief Generator (PRD §8 acceptance criteria).

All external calls (DataForSEO, ScrapeOwl, TextRazor/Google NLP via
extract_entities, Anthropic) are mocked — nothing hits the network. The real
deterministic helpers (parse_serp, classify_serp, extract_zones, assembly) run
so the wiring is exercised end-to-end.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.service_brief import (
    ClientContextInput,
    ResearchBundle,
    ServiceBriefRequest,
)
from modules.service_brief import serp as serp_mod
from modules.service_brief.competitor import teardown_competitors
from modules.service_brief.pipeline import run_service_brief
from modules.sie.entities import AggregatedEntity
from modules.sie.scraper import ScrapeResult

_PREFIX = "modules.service_brief"

_PAGE_HTML = (
    "<html><head><title>Drain Cleaning</title></head><body>"
    "<h1>Emergency Drain Cleaning Services</h1>"
    "<h2>Our Process</h2><p>We clean drains fast and reliably for homeowners "
    "across the city every single day of the week.</p>"
    "<h2>Transparent Pricing</h2><p>Transparent pricing for every job with a "
    "written quote upfront and absolutely no hidden fees at all.</p>"
    "</body></html>"
)


def _serp_items(local_pack: bool = False) -> list[dict]:
    items: list[dict] = []
    if local_pack:
        items.append({"type": "local_pack", "items": [{"title": "Acme Plumbing"}]})
    items += [
        {"type": "organic", "rank_absolute": 1,
         "url": "https://acmeplumbing.com/drain-cleaning",
         "title": "Drain Cleaning Services",
         "description": "We offer fast drain cleaning for homes."},
        {"type": "organic", "rank_absolute": 2,
         "url": "https://bobplumb.com/services/drains",
         "title": "Emergency Drain Cleaning",
         "description": "24/7 emergency drain service."},
        {"type": "organic", "rank_absolute": 3,
         "url": "https://www.yelp.com/biz/foo",
         "title": "Best plumbers near you",
         "description": "directory listing"},
        {"type": "organic", "rank_absolute": 4,
         "url": "https://blog.example.com/10-best-drain-cleaners",
         "title": "10 Best Drain Cleaners",
         "description": "a listicle"},
        {"type": "people_also_ask", "items": [
            {"title": "How much does drain cleaning cost?"},
            {"title": "Is professional drain cleaning safe?"},
        ]},
    ]
    return items


def _fake_scrape_many(urls, concurrency: int = 5):
    return [ScrapeResult(url=u, html=_PAGE_HTML, status_code=200, success=True) for u in urls]


def _fake_teardown_extract(system, user, **kwargs):
    """Haiku competitor-teardown extraction stub."""
    return {
        "sections": [
            {"heading": "Our Process", "section_type": "process", "approx_words": 180},
            {"heading": "Transparent Pricing", "section_type": "pricing", "approx_words": 150},
        ],
        "proof_assets": ["review"],
        "coverage": ["emergency drain cleaning", "hydro jetting"],
    }


def _fake_entities(pages, *, keyword=""):
    ent = AggregatedEntity(
        name="hydro jetting",
        avg_salience=0.42,
        pages_found=2,
        source_urls=["https://acmeplumbing.com/drain-cleaning"],
        ner_variants=["hydro jetting"],
        total_mentions=4,
        category="services",
    )
    return [ent], []


def _make_synthesis_stub():
    """Synthesis stub whose positioning angle is a function of the
    differentiator text in the prompt — proves the differentiator reaches
    synthesis and shapes the output (PRD §8.3)."""
    async def _fake(system, user, **kwargs):
        if "24-hour" in user or "on-call" in user:
            angle = "speed: guaranteed 24-hour response"
        elif "lowest price" in user or "price" in user:
            angle = "value: lowest transparent price in town"
        else:
            angle = "generic quality positioning"
        return {
            "positioning_angle": angle,
            "secondary_queries": ["same day drain cleaning"],
            "objections": [
                {"objection": "Will it cost too much?", "where_addressed": "Transparent Pricing"},
                {"objection": "Can they come fast?", "where_addressed": "Our Promise"},
            ],
            "sections": [
                {"heading": "Our Promise", "level": "H2",
                 "purpose": "Lead with the wedge",
                 "must_cover": ["response time", "guarantee"],
                 "proof_asset": "guarantee", "length_target": 0,
                 "citation_fit": False,
                 "divergence_note": f"Hero reframed around {angle} vs competitors' generic intro.",
                 # An accidental prose field that MUST be dropped by the schema:
                 "prose": "Call us now for the fastest drain cleaning in town!"},
                {"heading": "Transparent Pricing", "level": "H2",
                 "purpose": "Defuse the cost objection",
                 "must_cover": ["flat rate", "no hidden fees"],
                 "proof_asset": "stat", "length_target": 0, "citation_fit": False,
                 "divergence_note": None},
            ],
            "cta_strategy": "Sticky call button + inline quote form",
            "cta_placement": ["after hero", "end"],
            "objection_preemption_map": {"Will it cost too much?": "Transparent Pricing section"},
            "internal_links": ["water heater repair"],
            "faq_targets": ["How much does drain cleaning cost?"],
            "paa_targets": ["Is professional drain cleaning safe?"],
            "silo_candidates": [{"suggested_keyword": "hydro jetting service", "estimated_intent": "commercial"}],
        }
    return AsyncMock(side_effect=_fake)


def _request(differentiators) -> ServiceBriefRequest:
    return ServiceBriefRequest(
        run_id="run-1",
        service="Emergency Drain Cleaning",
        primary_query="emergency drain cleaning austin",
        location="Austin, TX",
        client_context=ClientContextInput(differentiators=differentiators),
    )


async def _run_pipeline(request, *, local_pack=False, cached_bundle=None):
    """Run the full pipeline with all external seams mocked."""
    serp_mock = AsyncMock(return_value={"items": _serp_items(local_pack=local_pack)})
    with patch(f"{_PREFIX}.research.serp_organic_advanced", serp_mock) as serp_patch, \
         patch(f"{_PREFIX}.research.autocomplete", AsyncMock(return_value=["how to unclog a drain"])), \
         patch(f"{_PREFIX}.research.extract_entities", AsyncMock(side_effect=_fake_entities)), \
         patch(f"{_PREFIX}.competitor.scrape_many", side_effect=_fake_scrape_many), \
         patch(f"{_PREFIX}.competitor.claude_json_model", AsyncMock(side_effect=_fake_teardown_extract)), \
         patch(f"{_PREFIX}.synthesis.claude_json_model", _make_synthesis_stub()), \
         patch(f"{_PREFIX}.cache.get_cached", AsyncMock(return_value=cached_bundle)), \
         patch(f"{_PREFIX}.cache.write_cache", AsyncMock()):
        result = await run_service_brief(request)
    return result, serp_patch


# ----------------------------------------------------------------------
# §8.1 — complete three-layer brief, no empty MUST fields
# ----------------------------------------------------------------------

async def test_happy_path_complete_brief():
    result, _ = await _run_pipeline(_request([{"claim": "24-hour response guarantee", "mechanism": "on-call crews", "type": "speed"}]))

    assert result.metadata.schema_version == "1.1"
    assert result.strategy.positioning_angle.strip()
    assert result.strategy.primary_query == "emergency drain cleaning austin"
    assert result.architecture, "architecture must have sections"
    for section in result.architecture:
        assert section.heading.strip()
        assert section.purpose.strip()
        assert section.length_target > 0  # budget distributed
    assert result.strategy.objections, "must surface objections"
    assert result.conversion.cta_strategy.strip()
    assert result.metadata.competitors_analyzed == 2  # yelp + listicle filtered out
    # Silo candidates carry an estimated_intent (consumed by silo_dedup).
    assert result.silo_candidates
    assert result.silo_candidates[0].estimated_intent == "commercial"


# ----------------------------------------------------------------------
# §8.2 — mode + length_band derived from the live SERP, not a static flag
# ----------------------------------------------------------------------

def test_mode_and_band_derived_from_serp():
    local = serp_mod.classify_serp(_serp_items(local_pack=True), location="Austin", has_local_pack=True)
    national = serp_mod.classify_serp(_serp_items(local_pack=False), location=None, has_local_pack=False)

    assert local.mode == "local_service"
    assert national.mode == "national_b2b"
    # Different SERP shapes yield different length bands (not a constant).
    assert local.length_band != national.length_band


def test_filter_drops_directories_and_listicles():
    urls = serp_mod.filter_service_page_urls(_serp_items())
    assert "https://acmeplumbing.com/drain-cleaning" in urls
    assert "https://bobplumb.com/services/drains" in urls
    assert all("yelp.com" not in u for u in urls)
    assert all("10-best" not in u for u in urls)


# ----------------------------------------------------------------------
# §8.3 — two clients, same service, different differentiators ->
#        materially different positioning + >=1 divergence each
# ----------------------------------------------------------------------

async def test_per_client_divergence():
    fast, _ = await _run_pipeline(_request([{"claim": "24-hour response guarantee", "mechanism": "on-call crews", "type": "speed"}]))
    cheap, _ = await _run_pipeline(_request([{"claim": "lowest price in town", "type": "price"}]))

    assert fast.strategy.positioning_angle != cheap.strategy.positioning_angle
    for brief in (fast, cheap):
        diverged = [s for s in brief.architecture if s.divergence_note]
        assert diverged, "each brief must show at least one structural divergence"


# ----------------------------------------------------------------------
# §8.4 — section-level directives only, zero sentence-level prose
# ----------------------------------------------------------------------

async def test_no_sentence_level_prose():
    result, _ = await _run_pipeline(_request([{"claim": "24-hour response guarantee", "type": "speed"}]))
    dumped = result.model_dump()
    banned = {"prose", "body", "copy", "draft", "content", "tagline", "headline"}

    def _walk(node):
        if isinstance(node, dict):
            assert not (set(node.keys()) & banned), f"prose field leaked: {set(node.keys()) & banned}"
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(dumped)


# ----------------------------------------------------------------------
# §8.5 — one unreachable competitor degrades gracefully (no raise)
# ----------------------------------------------------------------------

async def test_teardown_degrades_on_failed_competitor():
    urls = ["https://ok.com/a", "https://broken.com/b"]

    def _mixed_scrape(u, concurrency: int = 5):
        return [
            ScrapeResult(url="https://ok.com/a", html=_PAGE_HTML, status_code=200, success=True),
            ScrapeResult(url="https://broken.com/b", success=False, failure_reason="timeout"),
        ]

    with patch(f"{_PREFIX}.competitor.scrape_many", side_effect=_mixed_scrape), \
         patch(f"{_PREFIX}.competitor.claude_json_model", AsyncMock(side_effect=_fake_teardown_extract)):
        skeletons, zones, notes = await teardown_competitors(urls, max_pages=5)

    assert len(skeletons) == 1  # only the reachable page
    assert any("scrape_failed" in n for n in notes)


# ----------------------------------------------------------------------
# §8.6 — repeat run within TTL serves cached research, no SERP re-fetch
# ----------------------------------------------------------------------

async def test_cache_hit_skips_serp_fetch():
    # First, build a real bundle to use as the cached payload.
    first, _ = await _run_pipeline(_request([{"claim": "24-hour response guarantee", "type": "speed"}]))
    cached_bundle_payload = first.research_bundle.model_dump()

    result, serp_patch = await _run_pipeline(
        _request([{"claim": "24-hour response guarantee", "type": "speed"}]),
        cached_bundle=cached_bundle_payload,
    )

    # The SERP fetch must NOT have been called on the cache-hit run.
    serp_patch.assert_not_called()
    assert result.metadata.cache_hit is True
    # Synthesis still ran -> a full brief is produced.
    assert result.strategy.positioning_angle.strip()
    assert result.architecture


# ----------------------------------------------------------------------
# Bundle round-trips through the cache payload shape
# ----------------------------------------------------------------------

async def test_research_bundle_round_trips():
    first, _ = await _run_pipeline(_request([{"claim": "x", "type": "speed"}]))
    payload = first.research_bundle.model_dump()
    # Reconstructing from the cached dict must not raise.
    rebuilt = ResearchBundle(**payload)
    assert rebuilt.mode == first.research_bundle.mode


# ----------------------------------------------------------------------
# Location-page mode: section-per-service hub, location-anchored research
# ----------------------------------------------------------------------

def _location_request() -> ServiceBriefRequest:
    return ServiceBriefRequest(
        run_id="run-loc-1",
        service="Austin, TX",          # location carried as the service label
        primary_query="Austin, TX",    # keyword == location display
        location="Austin, TX",
        page_type="location",
        services=["Emergency Plumbing", "Drain Cleaning", "Water Heater Repair"],
        client_context=ClientContextInput(
            differentiators=[{"claim": "24-hour response guarantee", "type": "speed"}]
        ),
    )


def _location_synthesis_spy(captured: dict):
    """Records the system + user prompts and returns one section per service."""
    async def _fake(system, user, **kwargs):
        captured["system"] = system
        captured["user"] = user
        return {
            "positioning_angle": "the Austin team that answers within the hour",
            "secondary_queries": ["austin emergency plumber"],
            "objections": [{"objection": "Are they local?", "where_addressed": "Serving Austin"}],
            "sections": [
                {"heading": "Serving Austin", "level": "H2", "purpose": "Local intro",
                 "must_cover": ["Austin"], "length_target": 0},
                {"heading": "Emergency Plumbing in Austin", "level": "H2",
                 "purpose": "Service 1", "must_cover": ["emergency"], "length_target": 0},
                {"heading": "Drain Cleaning in Austin", "level": "H2",
                 "purpose": "Service 2", "must_cover": ["drains"], "length_target": 0},
                {"heading": "Water Heater Repair in Austin", "level": "H2",
                 "purpose": "Service 3", "must_cover": ["water heater"], "length_target": 0},
            ],
            "cta_strategy": "Call now",
            "cta_placement": ["end"],
            "faq_targets": ["Do you serve all of Austin?"],
            "silo_candidates": [],
        }
    return AsyncMock(side_effect=_fake)


async def test_location_mode_anchors_serp_and_uses_location_prompt():
    captured: dict = {}
    serp_mock = AsyncMock(return_value={"items": _serp_items(local_pack=True)})
    with patch(f"{_PREFIX}.research.serp_organic_advanced", serp_mock), \
         patch(f"{_PREFIX}.research.autocomplete", AsyncMock(return_value=[])), \
         patch(f"{_PREFIX}.research.extract_entities", AsyncMock(side_effect=_fake_entities)), \
         patch(f"{_PREFIX}.competitor.scrape_many", side_effect=_fake_scrape_many), \
         patch(f"{_PREFIX}.competitor.claude_json_model", AsyncMock(side_effect=_fake_teardown_extract)), \
         patch(f"{_PREFIX}.synthesis.claude_json_model", _location_synthesis_spy(captured)), \
         patch(f"{_PREFIX}.cache.get_cached", AsyncMock(return_value=None)) as get_cached, \
         patch(f"{_PREFIX}.cache.write_cache", AsyncMock()) as write_cache:
        result = await run_service_brief(_location_request())

    # Research is anchored on "<first service> <location>", not the bare keyword.
    assert serp_mock.call_args.args[0] == "Emergency Plumbing Austin, TX"
    # The location-hub synthesis prompt was used + carried the services list.
    assert "LOCATION landing page" in captured["system"]
    assert "services_to_cover" in captured["user"]
    assert "Drain Cleaning" in captured["user"]
    # Cache key is namespaced for location pages + uses the anchor query.
    assert get_cached.call_args.args == ("Emergency Plumbing Austin, TX", 2840, "location")
    assert write_cache.call_args.kwargs["page_type"] == "location"
    # One section per service (plus the local intro) is preserved in the brief.
    headings = [s.heading for s in result.architecture]
    assert "Emergency Plumbing in Austin" in headings
    assert "Water Heater Repair in Austin" in headings

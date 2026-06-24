"""Tests for the Service Page Writer module (mocked LLM)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from models.service_writer import ServiceWriterRequest
from models.writer import BrandVoiceCard, ClientContextInput
from modules.service_writer.jsonld import build_jsonld
from modules.service_writer.pipeline import run_service_writer
from modules.service_writer.render import render_html, render_markdown, render_wordpress
from models.service_writer import Block, WriterSection

_GEN = "modules.service_writer.generation.claude_json_model"
_DISTILL = "modules.service_writer.pipeline.distill_brand_voice"


def _brief() -> dict:
    return {
        "service": "Emergency Drain Cleaning",
        "primary_query": "emergency drain cleaning austin",
        "strategy": {
            "positioning_angle": "Guaranteed 24-hour response",
            "objections": [
                {"objection": "Will it cost too much?", "where_addressed": "Transparent Pricing"},
            ],
        },
        "architecture": [
            {"heading": "Our Promise", "level": "H2", "purpose": "Lead with the wedge",
             "must_cover": ["response time"], "proof_asset": "guarantee", "length_target": 120,
             "citation_fit": False, "divergence_note": "Hero reframed around speed."},
            {"heading": "Transparent Pricing", "level": "H2", "purpose": "Defuse cost objection",
             "must_cover": ["flat rate"], "proof_asset": "stat", "length_target": 120,
             "citation_fit": False, "divergence_note": None},
        ],
        "conversion": {
            "cta_strategy": "Sticky call button + inline quote",
            "cta_placement": ["after hero", "end"],
            "faq_targets": ["How fast can you come?"],
            "paa_targets": ["Is drain cleaning safe?"],
            "schema_types": ["Service", "FAQPage"],
            "internal_links": ["water heater repair"],
        },
    }


def _fake_llm_factory(banned_word: str | None = "cheap"):
    async def fake(system, user, **kwargs):
        if "SEO metadata" in system:
            return {"title": "Emergency Drain Cleaning | Acme",
                    "meta_description": "Fast 24/7 drain cleaning with a response guarantee.",
                    "cta_text": "Call Now"}
        if "answer FAQs" in system:
            return {"faqs": [{"question": "How fast can you come?", "answer": "Within the hour, day or night."}]}
        if "ONE section body" in system:
            if "BANNED terms" in user:
                return {"blocks": [
                    {"type": "paragraph", "text": "We deliver fast, reliable, guaranteed service."},
                    {"type": "list", "items": ["24/7 response", "Licensed technicians"]},
                ]}
            # First draft intentionally leaks the banned word.
            leak = f"Affordable {banned_word} service that is fast." if banned_word else "Affordable fast service."
            return {"blocks": [
                {"type": "paragraph", "text": leak},
                {"type": "cta", "text": "Book now"},
            ]}
        return {}
    return AsyncMock(side_effect=fake)


def _request(client_context: ClientContextInput | None) -> ServiceWriterRequest:
    return ServiceWriterRequest(
        run_id="run-1", service_brief_output=_brief(), client_context=client_context,
    )


async def test_happy_path_produces_all_renderings_and_jsonld():
    card = BrandVoiceCard(brand_name="Acme Plumbing", banned_terms=["cheap"], tone_adjectives=["confident"])
    ctx = ClientContextInput(brand_guide_text="Be confident.", icp_text="Homeowners")
    with patch(_GEN, _fake_llm_factory()), patch(_DISTILL, AsyncMock(return_value=card)):
        result = await run_service_writer(_request(ctx))

    assert result.title
    assert result.meta_description
    assert result.metadata.schema_version == "1.0"
    # architecture (2) + FAQ + CTA
    assert result.metadata.section_count == 4
    assert result.metadata.faq_count == 1
    # All three renderings present and shaped right.
    assert "## Our Promise" in result.renderings.markdown
    assert "<h2>Our Promise</h2>" in result.renderings.html
    assert "<!-- wp:heading -->" in result.renderings.wordpress
    assert "<!-- wp:paragraph -->" in result.renderings.wordpress
    # JSON-LD has both nodes.
    assert '"Service"' in result.schema_jsonld
    assert '"FAQPage"' in result.schema_jsonld
    assert result.metadata.brand_voice_card_used["brand_name"] == "Acme Plumbing"


async def test_banned_term_enforced_via_retry():
    card = BrandVoiceCard(brand_name="Acme", banned_terms=["cheap"])
    ctx = ClientContextInput(brand_guide_text="x")
    with patch(_GEN, _fake_llm_factory("cheap")), patch(_DISTILL, AsyncMock(return_value=card)):
        result = await run_service_writer(_request(ctx))
    assert "cheap" not in result.renderings.markdown.lower()


async def test_no_client_context_degrades():
    with patch(_GEN, _fake_llm_factory(None)), patch(_DISTILL, AsyncMock(return_value=None)):
        result = await run_service_writer(_request(None))
    assert "no_client_context" in result.metadata.degraded_notes
    assert result.renderings.markdown  # still produces output
    assert result.metadata.section_count >= 1


async def test_cta_section_always_present():
    with patch(_GEN, _fake_llm_factory(None)), patch(_DISTILL, AsyncMock(return_value=None)):
        result = await run_service_writer(_request(None))
    cta_sections = [s for s in result.sections if s.type == "cta"]
    assert len(cta_sections) == 1
    assert any(b.type == "cta" for b in cta_sections[0].blocks)


# ---- renderer unit tests ----

def _sample_sections() -> list[WriterSection]:
    return [WriterSection(order=1, level="H2", heading="Pricing", blocks=[
        Block(type="paragraph", text="Flat-rate pricing."),
        Block(type="list", items=["No hidden fees", "Free quote"]),
        Block(type="subheading", text="What you pay", level=3),
        Block(type="cta", text="Get a quote", href="/contact"),
    ])]


def test_render_markdown_shapes():
    md = render_markdown(_sample_sections())
    assert "## Pricing" in md
    assert "- No hidden fees" in md
    assert "### What you pay" in md
    assert "[Get a quote](/contact)" in md


def test_render_html_escapes_and_shapes():
    html = render_html([WriterSection(order=1, level="H2", heading="A & B", blocks=[
        Block(type="paragraph", text="x < y"),
    ])])
    assert "<h2>A &amp; B</h2>" in html
    assert "<p>x &lt; y</p>" in html


def test_render_wordpress_blocks():
    wp = render_wordpress(_sample_sections())
    assert "<!-- wp:list -->" in wp
    assert "<!-- wp:list-item -->" in wp
    assert "<!-- wp:buttons -->" in wp
    assert "wp-block-button__link" in wp


def test_jsonld_service_only_when_no_faqs():
    out = build_jsonld(service="Drain Cleaning", primary_query="drain cleaning", brand_name="Acme", faqs=[])
    assert '"Service"' in out
    assert '"FAQPage"' not in out

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


def test_reopt_directive_includes_issues_and_prior_headings():
    from modules.service_writer.generation import reopt_directive

    out = reopt_directive(
        [{"engine": "AEO", "issues": ["no FAQ section"], "recommendations": ["add 4-7 FAQs"]}],
        prior_sections=[{"heading": "Our Promise"}],
    )
    assert "no FAQ section" in out
    assert "add 4-7 FAQs" in out
    assert "Our Promise" in out
    assert reopt_directive([]) == ""


async def test_reoptimize_mode_runs_and_keeps_shape():
    ctx = ClientContextInput(brand_guide_text="Be confident.")
    req = ServiceWriterRequest(
        run_id="run-1",
        service_brief_output=_brief(),
        client_context=ctx,
        mode="reoptimize",
        deficiencies=[{"engine": "AEO", "engine_key": "aeo_llm_retrieval",
                       "issues": ["no FAQ"], "recommendations": ["add an FAQ section"]}],
        prior_sections=[{"order": 1, "level": "H2", "heading": "Our Promise", "blocks": []}],
    )
    with patch(_GEN, _fake_llm_factory(None)), patch(_DISTILL, AsyncMock(return_value=BrandVoiceCard(brand_name="Acme"))):
        result = await run_service_writer(req)

    assert any(n.startswith("reoptimize:") for n in result.metadata.degraded_notes)
    assert result.metadata.schema_version == "1.0"
    assert result.renderings.markdown and result.renderings.html and result.renderings.wordpress
    assert result.schema_jsonld


def test_jsonld_service_only_when_no_faqs():
    out = build_jsonld(service="Drain Cleaning", primary_query="drain cleaning", brand_name="Acme", faqs=[])
    assert '"Service"' in out
    assert '"FAQPage"' not in out


def test_jsonld_location_emits_a_service_node_per_service():
    import json

    out = build_jsonld(
        service="Austin, TX",
        primary_query="Austin, TX",
        brand_name="Acme",
        page_type="location",
        location="Austin, TX",
        services=["Emergency Plumbing", "Drain Cleaning", "Water Heater Repair"],
        faqs=[{"question": "Do you serve all of Austin?", "answer": "Yes."}],
    )
    graph = json.loads(out)["@graph"]
    service_nodes = [n for n in graph if n.get("@type") == "Service"]
    assert {n["name"] for n in service_nodes} == {
        "Emergency Plumbing", "Drain Cleaning", "Water Heater Repair",
    }
    # Each service node is served in the target area + carries the provider.
    assert all(n.get("areaServed") == "Austin, TX" for n in service_nodes)
    assert all(n.get("provider", {}).get("name") == "Acme" for n in service_nodes)
    assert any(n.get("@type") == "FAQPage" for n in graph)


async def test_location_mode_title_meta_leads_with_location():
    """A location page's title/meta frame the area + services, not a single service."""
    captured: dict = {}

    async def fake(system, user, **kwargs):
        if "SEO metadata" in system:
            captured["system"] = system
            captured["user"] = user
            return {"title": "Austin Plumbing Services | Acme",
                    "meta_description": "Acme serves Austin: emergency plumbing, drain cleaning.",
                    "cta_text": "Call Now"}
        if "answer FAQs" in system:
            return {"faqs": []}
        if "ONE section body" in system:
            return {"blocks": [{"type": "paragraph", "text": "We serve Austin."}]}
        return {}

    req = ServiceWriterRequest(
        run_id="run-loc",
        service_brief_output=_brief(),
        client_context=ClientContextInput(brand_guide_text="x"),
        page_type="location",
        location="Austin, TX",
        services=["Emergency Plumbing", "Drain Cleaning"],
    )
    with patch(_GEN, AsyncMock(side_effect=fake)), patch(_DISTILL, AsyncMock(return_value=BrandVoiceCard(brand_name="Acme"))):
        result = await run_service_writer(req)

    # The location metadata prompt (not the single-service one) was used.
    assert "LOCATION landing page" in captured["system"]
    assert "Austin, TX" in captured["user"]
    assert "Emergency Plumbing" in captured["user"]
    assert result.title == "Austin Plumbing Services | Acme"
    # The page's JSON-LD reflects the multi-service location shape.
    assert result.schema_jsonld.count('"Service"') == 2


def test_decision_fit_directive_renders_branches():
    from modules.service_writer.generation import decision_fit_directive

    out = decision_fit_directive({
        "applies": True,
        "branches": [
            {"condition": "the drain is fully blocked", "option": "emergency clearing"},
            {"condition": "it's draining slowly", "option": "scheduled maintenance"},
        ],
        "default_statement": "Call us and we'll triage.",
    })
    assert "DECISION-FIT" in out
    assert "If the drain is fully blocked: emergency clearing" in out
    assert "If it's draining slowly: scheduled maintenance" in out
    assert "Call us and we'll triage." in out
    # No map / fewer than 2 usable branches -> empty (no-op directive).
    assert decision_fit_directive(None) == ""
    assert decision_fit_directive({"applies": False, "branches": [
        {"condition": "a", "option": "x"}, {"condition": "b", "option": "y"}]}) == ""
    assert decision_fit_directive({"applies": True, "branches": [
        {"condition": "only one", "option": "x"}]}) == ""


async def test_decision_fit_woven_into_section_prompts():
    """A brief carrying a usable decision_fit map feeds the branches into every
    section's generation prompt and stamps decision_fit_rendered."""
    captured: list[str] = []

    async def fake(system, user, **kwargs):
        if "ONE section body" in system:
            captured.append(user)
            return {"blocks": [{"type": "paragraph", "text": "We serve Austin fast."}]}
        if "SEO metadata" in system:
            return {"title": "t", "meta_description": "m", "cta_text": "Call"}
        if "answer FAQs" in system:
            return {"faqs": []}
        return {}

    brief = _brief()
    brief["decision_fit"] = {
        "applies": True,
        "branches": [
            {"condition": "the drain is fully blocked", "option": "emergency clearing"},
            {"condition": "it's draining slowly", "option": "scheduled maintenance"},
        ],
        "default_statement": "Call us and we'll triage.",
    }
    req = ServiceWriterRequest(
        run_id="run-df", service_brief_output=brief,
        client_context=ClientContextInput(brand_guide_text="x"),
    )
    with patch(_GEN, AsyncMock(side_effect=fake)), patch(_DISTILL, AsyncMock(return_value=BrandVoiceCard(brand_name="Acme"))):
        result = await run_service_writer(req)

    assert result.metadata.decision_fit_rendered is True
    assert "decision_fit_rendered" in result.metadata.degraded_notes
    assert captured, "at least one section body was generated"
    assert all("If the drain is fully blocked: emergency clearing" in u for u in captured)


async def test_decision_fit_absent_when_brief_has_none():
    captured: list[str] = []

    async def fake(system, user, **kwargs):
        if "ONE section body" in system:
            captured.append(user)
            return {"blocks": [{"type": "paragraph", "text": "We serve Austin fast."}]}
        if "SEO metadata" in system:
            return {"title": "t", "meta_description": "m", "cta_text": "Call"}
        if "answer FAQs" in system:
            return {"faqs": []}
        return {}

    with patch(_GEN, AsyncMock(side_effect=fake)), patch(_DISTILL, AsyncMock(return_value=BrandVoiceCard(brand_name="Acme"))):
        result = await run_service_writer(_request(ClientContextInput(brand_guide_text="x")))

    assert result.metadata.decision_fit_rendered is False
    assert all("DECISION-FIT" not in u for u in captured)


def test_coerce_blocks_tolerates_bad_level():
    """A non-numeric `level` from the LLM must not discard the section's blocks."""
    from modules.service_writer.generation import _coerce_blocks

    blocks = _coerce_blocks([
        {"type": "subheading", "text": "Why us", "level": "three"},  # bad level
        {"type": "paragraph", "text": "Fast, reliable service."},
        {"type": "list", "items": ["24/7", "Licensed"]},
        {"type": "weird", "text": "falls back to paragraph"},  # unknown type
    ])
    assert len(blocks) == 4
    assert blocks[0].type == "subheading" and blocks[0].level == 3  # safe default
    assert blocks[3].type == "paragraph"

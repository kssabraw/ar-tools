"""Unit tests for the core-pages writer (home / about / contact).

Two things carry the weight here. First, the writer must never state a business
fact — the schema is what enforces that, so the tests assert the *shape* the
model can return, not the prose. Second, each kind produces exactly what its
template consumes: home's `sections`, about's markdown body, contact's intro
only — a mismatch there ships a page that silently falls back to a default.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services import website_core_pages as cp
from services import website_content


CLIENT = {"id": "c1", "name": "Acme Roofing", "differentiators": ["family-owned", "24/7"]}
WEBSITE = {
    "id": "w1",
    "client_id": "c1",
    "name": "Acme Roofing",
    "site_type": "local_business",
    "config": {"business": {"name": "Acme Roofing", "city": "Anaheim"}, "tagline": "Roofs done right"},
}
PAGES = [
    {"page_type": "service", "title": "Roof Repair"},
    {"page_type": "service", "title": "Roof Replacement"},
    {"page_type": "service", "title": "Roof Repair"},  # dup — collapses
    {"page_type": "location", "title": "Anaheim"},
    {"page_type": "sitemap", "title": "Sitemap"},  # not a service or city
]


class TestBusinessFacts:
    def test_services_and_cities_come_from_the_sites_own_pages(self):
        # A home page must not advertise a service the site does not have, so the
        # list is the site's real pages, deduped and order-preserved.
        facts = cp.business_facts(CLIENT, WEBSITE, PAGES)
        assert facts["services"] == ["Roof Repair", "Roof Replacement"]
        assert facts["cities"] == ["Anaheim"]

    def test_config_business_facts_win_over_the_client_row(self):
        # §4.5: a human-entered fact on the site config outranks GBP/client.
        facts = cp.business_facts(
            {"id": "c1", "name": "Wrong Name", "business_location": "Nowhere"},
            WEBSITE, PAGES,
        )
        assert facts["business_name"] == "Acme Roofing"
        assert facts["city"] == "Anaheim"

    def test_the_facts_block_omits_what_is_missing(self):
        # An unconfigured site must not hand the model a page of blank labels to
        # fill — that is exactly how a fact gets invented.
        block = cp._facts_block({"business_name": "Acme", "services": [], "city": ""})
        assert "Acme" in block
        assert "Primary city" not in block
        assert "Services offered" not in block

    def test_a_bare_site_still_produces_a_block(self):
        assert cp._facts_block({}) == "(no business facts on file)"


class TestContentShaping:
    def test_home_returns_sections_and_no_body(self):
        # index.astro reads `sections` from frontmatter and composes the body from
        # components, so home carries section copy and an empty body.
        content = cp._home_content(
            {"title": "Acme Roofing", "description": "Fast repair.",
             "sections": {"heroTitle": "Roofs done right", "ctaLabel": "Get a quote",
                          "unknownKey": "dropped"}}
        )
        assert content["body"] == ""
        assert content["frontmatter"]["sections"] == {
            "heroTitle": "Roofs done right", "ctaLabel": "Get a quote"
        }

    def test_home_with_no_usable_sections_is_an_error_not_a_blank_page(self):
        # Shipping empty sections would leave the page on template defaults while
        # the job reported success.
        with pytest.raises(cp.CorePageError, match="home_sections_empty"):
            cp._home_content({"title": "x", "description": "y", "sections": {"nope": "x"}})

    def test_about_requires_a_body(self):
        content = cp._about_content({"title": "About", "description": "Who we are", "body": "## Us\n\nHi."})
        assert content["body"].startswith("## Us")
        with pytest.raises(cp.CorePageError, match="about_body_empty"):
            cp._about_content({"title": "About", "description": "d", "body": "  "})

    def test_contact_is_title_and_intro_only(self):
        content = cp._contact_content({"title": "Contact Acme", "description": "Reach us."})
        assert content["body"] == ""
        assert content["title"] == "Contact Acme"

    def test_contact_defaults_a_title_rather_than_shipping_blank(self):
        assert cp._contact_content({"description": "Reach us."})["title"] == "Contact"


class TestSchemas:
    def test_home_section_keys_are_the_ones_the_template_reads(self):
        # This list is the contract with index.astro; a key it does not read is
        # dead copy. Pinned so a rename on one side fails loudly.
        assert cp.HOME_SECTION_KEYS == (
            "heroEyebrow", "heroTitle", "heroLede", "ctaLabel",
            "servicesTitle", "locationsTitle", "latestTitle",
        )

    def test_the_schemas_never_ask_for_a_business_fact(self):
        # The guarantee is structural: no phone/address/price field exists to
        # fill, so the model cannot return one.
        banned = {"phone", "address", "price", "rating", "reviews", "hours", "email"}
        for schema in (cp._HOME_SCHEMA, cp._ABOUT_SCHEMA, cp._CONTACT_SCHEMA):
            props = set(schema["properties"])
            for section in schema["properties"].values():
                props |= set((section.get("properties") or {}).keys())
            assert not (props & banned)


class TestGenerate:
    @pytest.mark.asyncio
    async def test_privacy_is_not_a_generated_kind(self):
        # Guards the caller's contract: privacy must never reach this writer.
        assert "privacy" not in cp.GENERATED_KINDS
        with pytest.raises(cp.CorePageError, match="core_page_kind_not_generated:privacy"):
            await cp.generate_core_page(page_kind="privacy", client=CLIENT, website=WEBSITE)

    @pytest.mark.asyncio
    async def test_home_generation_wires_the_forced_tool_and_facts(self):
        captured = {}

        async def fake_tool(**kwargs):
            captured.update(kwargs)
            return {"title": "Acme Roofing", "description": "Fast, local roof repair.",
                    "sections": {"heroTitle": "Roofs done right"}}

        with patch.object(cp.report_llm, "run_forced_tool", new=fake_tool), patch(
            "services.voice_card_service.source_texts", return_value=("Plain and direct.", "Homeowners.")
        ):
            content = await cp.generate_core_page(
                page_kind="home", client=CLIENT, website=WEBSITE, pages=PAGES
            )

        # The real services reached the prompt; the brand voice was injected.
        assert "Roof Repair" in captured["user"]
        assert "Plain and direct." in captured["user"]
        assert content["frontmatter"]["sections"] == {"heroTitle": "Roofs done right"}


class TestPublishRoundTrip:
    def test_home_sections_survive_into_the_committed_frontmatter(self):
        # The whole point: `sections` has to reach the .md file, or the template
        # renders the house defaults. It was NOT in the frontmatter key order
        # until this feature added it.
        content = cp._home_content(
            {"title": "Acme Roofing", "description": "Fast repair.",
             "sections": {"heroTitle": "Roofs done right", "heroLede": "We fix roofs fast."}}
        )
        files = website_content.files_for_pages(
            [{
                "route": "/",
                "page_type": "home",
                "title": content["title"],
                "description": content["description"],
                "body": content["body"],
                "extra": content["frontmatter"],
            }]
        )
        [(path, data)] = files.items()
        text = data.decode("utf-8")
        assert path == "src/content/pages/home.md"
        assert "sections:" in text
        assert "Roofs done right" in text
        assert "We fix roofs fast." in text
        # Core pages are addressed by entry id, so they carry no path/pageType.
        assert "pageType:" not in text

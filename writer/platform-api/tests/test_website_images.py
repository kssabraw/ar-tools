"""Unit tests for the hero-image writer.

The load-bearing property is that imagery is *additive*: every failure path —
off, unsupported page type, no key, a render or upload error — returns None and
leaves the page heroless, which the template renders as a finished page. Nothing
here may raise into the generator.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import website_images as wi
from services import website_content


CLIENT = {"id": "c1", "name": "Acme Roofing", "brand_voice": {"tone": "warm, trustworthy"}}
WEBSITE = {"id": "w1", "config": {"business": {"name": "Acme Roofing", "city": "Anaheim"}}}


class TestHeroEligibility:
    def test_service_and_location_pages_get_a_hero(self):
        assert wi.wants_hero("service")
        assert wi.wants_hero("location")
        assert wi.wants_hero("home")
        assert wi.wants_hero("post")

    def test_about_and_contact_do_not(self):
        # About leads with prose, contact with the NAP block; a stock hero on
        # either reads as filler.
        assert not wi.wants_hero("about")
        assert not wi.wants_hero("contact")
        assert not wi.wants_hero("privacy")


class TestPrompt:
    def test_a_local_page_prompt_names_the_subject_and_city(self):
        prompt = wi.build_prompt(
            {"title": "Roof Repair", "page_type": "service"},
            business="Acme Roofing", city="Anaheim", style="STYLE",
        )
        assert "Roof Repair" in prompt
        assert "Anaheim" in prompt
        assert prompt.endswith("STYLE")

    def test_a_post_prompt_carries_no_city(self):
        # A blog post is not geo-targeted, so bolting a city onto its art is
        # wrong — the geo pages own place.
        prompt = wi.build_prompt(
            {"title": "How roofs fail", "page_type": "post"},
            business="Acme", city="Anaheim", style="S",
        )
        assert "Anaheim" not in prompt

    def test_the_style_forbids_text_and_logos(self):
        # A render inventing a fake sign or garbled brand mark is the classic
        # failure; the style tail rules it out.
        style = wi.brand_style_suffix(CLIENT)
        assert "no text" in style and "no logos" in style
        # The client's tone rides along so a site's heroes read as one set.
        assert "warm, trustworthy" in style

    def test_alt_text_describes_the_page(self):
        alt = wi.alt_text({"title": "Roof Repair", "page_type": "service"}, city="Anaheim")
        assert alt == "Roof Repair in Anaheim"


class TestGating:
    @pytest.mark.asyncio
    async def test_disabled_yields_no_image_without_calling_the_renderer(self):
        render = AsyncMock()
        with patch.object(wi.settings, "website_images_enabled", False), patch(
            "services.illustration._generate_image", new=render
        ):
            out = await wi.generate_hero(
                page={"id": "p1", "page_type": "service", "title": "Roof Repair"},
                client=CLIENT, website=WEBSITE, business="Acme", city="Anaheim",
            )
        assert out is None
        render.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_api_key_disables_it_even_when_flagged_on(self):
        with patch.object(wi.settings, "website_images_enabled", True), patch.object(
            wi.settings, "openai_api_key", ""
        ):
            assert wi._enabled() is False

    @pytest.mark.asyncio
    async def test_an_ineligible_page_type_is_skipped(self):
        render = AsyncMock()
        with patch.object(wi.settings, "website_images_enabled", True), patch.object(
            wi.settings, "openai_api_key", "sk-x"
        ), patch("services.illustration._generate_image", new=render):
            out = await wi.generate_hero(
                page={"id": "p1", "page_type": "about", "title": "About"},
                client=CLIENT, website=WEBSITE, business="Acme", city="Anaheim",
            )
        assert out is None
        render.assert_not_called()


class TestGeneration:
    @pytest.mark.asyncio
    async def test_a_successful_render_returns_frontmatter(self, monkeypatch):
        storage = MagicMock()
        storage.storage.from_.return_value.get_public_url.return_value = "https://cdn/x.png"
        monkeypatch.setattr(wi, "get_supabase_storage", lambda w: storage)

        with patch.object(wi.settings, "website_images_enabled", True), patch.object(
            wi.settings, "openai_api_key", "sk-x"
        ), patch("services.illustration._generate_image", new=AsyncMock(return_value=b"png")):
            out = await wi.generate_hero(
                page={"id": "p1", "page_type": "service", "title": "Roof Repair"},
                client=CLIENT, website=WEBSITE, business="Acme", city="Anaheim",
            )
        assert out == {"heroImage": "https://cdn/x.png", "heroImageAlt": "Roof Repair in Anaheim"}
        # Uploaded once, under the per-page key so a regenerate overwrites.
        storage.storage.from_.return_value.upload.assert_called_once()
        assert wi.storage_key("w1", "p1") in storage.storage.from_.return_value.upload.call_args[0]

    @pytest.mark.asyncio
    async def test_a_render_returning_nothing_is_not_an_error(self):
        with patch.object(wi.settings, "website_images_enabled", True), patch.object(
            wi.settings, "openai_api_key", "sk-x"
        ), patch("services.illustration._generate_image", new=AsyncMock(return_value=None)):
            out = await wi.generate_hero(
                page={"id": "p1", "page_type": "service", "title": "Roof Repair"},
                client=CLIENT, website=WEBSITE, business="Acme", city="Anaheim",
            )
        assert out is None

    @pytest.mark.asyncio
    async def test_a_renderer_exception_never_escapes(self):
        with patch.object(wi.settings, "website_images_enabled", True), patch.object(
            wi.settings, "openai_api_key", "sk-x"
        ), patch("services.illustration._generate_image",
                 new=AsyncMock(side_effect=RuntimeError("api down"))):
            out = await wi.generate_hero(
                page={"id": "p1", "page_type": "service", "title": "Roof Repair"},
                client=CLIENT, website=WEBSITE, business="Acme", city="Anaheim",
            )
        assert out is None


class TestPublishRoundTrip:
    def test_a_hero_url_reaches_the_committed_frontmatter(self):
        # The image ships by being in the page's frontmatter, which build_files
        # already commits — so no publish change was needed.
        files = website_content.files_for_pages(
            [{
                "route": "/anaheim/roof-repair/",
                "page_type": "local_landing",
                "title": "Roof Repair in Anaheim",
                "description": "Fast repair.",
                "body": "Body.",
                "extra": {"heroImage": "https://cdn/x.png", "heroImageAlt": "Roof Repair in Anaheim"},
            }]
        )
        [(_path, data)] = files.items()
        text = data.decode("utf-8")
        assert 'heroImage: "https://cdn/x.png"' in text
        assert 'heroImageAlt: "Roof Repair in Anaheim"' in text

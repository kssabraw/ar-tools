"""Unit tests for the hero-image writer.

The load-bearing property is that imagery is *additive*: every failure path —
off, unsupported page type, no key, a render or upload error — returns None and
leaves the page heroless, which the template renders as a finished page. Nothing
here may raise into the generator.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from services import website_images as wi
from services import website_content


# The realistic blob shape — the structured voice is nested under current_voice,
# not flat. A flat fixture is what let a top-level-only tone lookup look correct.
CLIENT = {"id": "c1", "name": "Acme Roofing",
          "brand_voice": {"current_voice": {"tone": "warm, trustworthy"}}}
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

    def test_the_tone_is_read_from_where_the_blob_actually_keeps_it(self):
        # brand_voice nests the structured voice under current_voice. Reading
        # brand_voice["tone"] off the top level found nothing for every real
        # client, so the tone never reached the prompt.
        nested = {"brand_voice": {"current_voice": {"tone": "warm, plain-spoken"},
                                  "raw_text": "..."}}
        assert wi.brand_tone(nested) == "warm, plain-spoken"
        assert "warm, plain-spoken" in wi.brand_style_suffix(nested)

    def test_a_recommended_voice_is_used_when_there_is_no_current_one(self):
        assert wi.brand_tone({"brand_voice": {"recommended_voice": {"tone": "bold"}}}) == "bold"

    def test_a_guide_with_no_structured_tone_degrades_quietly(self):
        # A typed freeform guide has raw_text and no tone; that is not an error.
        assert wi.brand_tone({"brand_voice": {"raw_text": "Plain and direct."}}) == ""
        assert wi.brand_tone({}) == ""

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


class TestPhotoRejection:
    """The pure validator — a real web image, not a tracking pixel or a RAW dump."""

    def test_accepts_a_reasonable_jpeg(self):
        assert wi.photo_rejection_reason("image/jpeg", 800, 600, 200_000) is None

    def test_rejects_an_unsupported_type(self):
        assert wi.photo_rejection_reason("image/gif", 800, 600, 200_000) == "unsupported_image_type"

    def test_rejects_empty(self):
        assert wi.photo_rejection_reason("image/png", 800, 600, 0) == "empty_image"

    def test_rejects_oversized(self):
        assert wi.photo_rejection_reason("image/png", 800, 600, wi.PHOTO_MAX_BYTES + 1) == "image_too_large"

    def test_rejects_tiny_dimensions(self):
        assert wi.photo_rejection_reason("image/jpeg", 100, 100, 50_000) == "image_dimensions_too_small"

    def test_webp_is_supported(self):
        assert wi.photo_rejection_reason("image/webp", 400, 400, 50_000) is None


def _storage_mock(url: str = "https://cdn/website-projects/w1/x.jpg"):
    storage = MagicMock()
    storage.storage.from_.return_value.get_public_url.return_value = url
    return storage


class TestUploadProjectPhoto:
    def test_a_valid_upload_is_hosted_under_the_site_prefix(self):
        storage = _storage_mock("https://cdn/website-projects/w1/x.jpg?")
        with patch.object(wi, "_decode_image", return_value=("image/jpeg", 800, 600)), \
             patch("db.supabase_client.get_supabase", return_value=storage):
            url = wi.upload_project_photo("w1", b"realbytes", "image/jpeg")
        # The trailing '?' get_public_url can return is stripped.
        assert url == "https://cdn/website-projects/w1/x.jpg"
        path = storage.storage.from_.return_value.upload.call_args[0][0]
        assert path.startswith("website-projects/w1/") and path.endswith(".jpg")

    def test_the_real_format_is_sniffed_not_the_declared_type(self):
        # A file mislabeled image/png that is really a jpeg is stored as .jpg.
        storage = _storage_mock()
        with patch.object(wi, "_decode_image", return_value=("image/jpeg", 800, 600)), \
             patch("db.supabase_client.get_supabase", return_value=storage):
            wi.upload_project_photo("w1", b"bytes", "image/png")
        assert storage.storage.from_.return_value.upload.call_args[0][0].endswith(".jpg")

    def test_empty_upload_is_rejected(self):
        with pytest.raises(HTTPException) as e:
            wi.upload_project_photo("w1", b"", "image/jpeg")
        assert e.value.detail == "empty_image"

    def test_oversized_is_rejected_413(self):
        with patch.object(wi, "_decode_image", return_value=("image/png", 800, 600)):
            with pytest.raises(HTTPException) as e:
                wi.upload_project_photo("w1", b"x" * (wi.PHOTO_MAX_BYTES + 1), "image/png")
        assert e.value.status_code == 413 and e.value.detail == "image_too_large"

    def test_tiny_dimensions_rejected(self):
        with patch.object(wi, "_decode_image", return_value=("image/jpeg", 50, 50)):
            with pytest.raises(HTTPException) as e:
                wi.upload_project_photo("w1", b"bytes", "image/jpeg")
        assert e.value.detail == "image_dimensions_too_small"


@pytest.mark.asyncio
class TestImportProjectPhotoFromUrl:
    async def test_a_non_http_url_is_rejected_without_fetching(self):
        with pytest.raises(HTTPException) as e:
            await wi.import_project_photo_from_url("w1", "ftp://x/y.jpg")
        assert e.value.detail == "invalid_image_url"

    async def test_a_public_url_is_fetched_and_rehosted(self):
        resp = MagicMock(status_code=200, content=b"imgbytes", headers={"content-type": "image/jpeg"})
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=resp)))
        client.__aexit__ = AsyncMock(return_value=False)
        storage = _storage_mock("https://cdn/website-projects/w1/y.jpg")
        with patch("httpx.AsyncClient", return_value=client), \
             patch.object(wi, "_decode_image", return_value=("image/jpeg", 800, 600)), \
             patch("db.supabase_client.get_supabase", return_value=storage):
            url = await wi.import_project_photo_from_url("w1", "https://ex.com/y.jpg")
        assert url == "https://cdn/website-projects/w1/y.jpg"

    async def test_a_failed_fetch_raises_502(self):
        resp = MagicMock(status_code=404, content=b"")
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=MagicMock(get=AsyncMock(return_value=resp)))
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=client):
            with pytest.raises(HTTPException) as e:
                await wi.import_project_photo_from_url("w1", "https://ex.com/missing.jpg")
        assert e.value.status_code == 502 and e.value.detail == "image_fetch_failed"

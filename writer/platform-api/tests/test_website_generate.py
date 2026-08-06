"""Unit tests for per-page generation.

The interesting behaviour is what happens for page types the suite cannot write.
The catalog has ~25 of them and the engines cover a subset (PRD §4.7); a plan
that quietly skips the rest promises pages nothing can produce, so every
non-generable outcome has to name itself on the row.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import website_generate as wg


class TestBrandContextGate:
    def test_a_typed_brand_guide_satisfies_the_gate(self):
        assert wg.has_brand_context({"brand_voice": {"raw_text": "Plain, direct, no fluff."}})

    def test_no_guide_blocks(self):
        # Stronger than the suite's stance for a single article, deliberately:
        # the same failure on a website writes every page with zero context.
        assert not wg.has_brand_context({})
        assert not wg.has_brand_context({"brand_voice": None})

    def test_an_icp_alone_does_not_satisfy_a_voice_gate(self):
        assert not wg.has_brand_context({"detected_icp": {"summary": "Homeowners, 35-60"}})


def _supabase(page, website, client=None):
    tables = {}

    def table(name):
        if name not in tables:
            mock = MagicMock()
            for method in ("select", "eq", "limit", "in_", "order", "update", "insert"):
                getattr(mock, method).return_value = mock
            data = {
                "website_pages": [page],
                "websites": [website],
                "clients": [client] if client else [],
                "async_jobs": [{"id": "job-1"}],
            }[name]
            mock.execute.return_value = MagicMock(data=data)
            tables[name] = mock
        return tables[name]

    sb = MagicMock()
    sb.table.side_effect = table
    return sb, tables


SITE = {"id": "w1", "client_id": "c1", "name": "Acme"}
CLIENT = {"id": "c1", "brand_voice": {"raw_text": "Plain and direct."}}


@pytest.mark.asyncio
class TestGeneratePage:
    async def test_an_nlp_page_calls_the_existing_engine_unchanged(self):
        page = {
            "id": "p1",
            "website_id": "w1",
            "page_type": "local_landing",
            "title": "Roof Repair in Anaheim",
            "plan": {"engine": "nlp", "keyword": "Roof Repair Anaheim", "location": "Anaheim"},
        }
        sb, tables = _supabase(page, SITE, CLIENT)
        generated = AsyncMock(return_value={"id": "lsp-1", "page_title": "Roof Repair in Anaheim"})
        with patch.object(wg, "get_supabase", return_value=sb), patch(
            "services.local_seo_service.generate_page", new=generated
        ):
            result = await wg.generate_page(page_id="p1", user_id="u1")

        assert result == {"page_id": "p1", "generated": True, "source_id": "lsp-1"}
        assert generated.call_args.kwargs["keyword"] == "Roof Repair Anaheim"
        assert generated.call_args.kwargs["location"] == "Anaheim"
        # The page points at the local_seo_pages row rather than copying it, so
        # reoptimizing and republishing stays one action.
        written = tables["website_pages"].update.call_args[0][0]
        assert written["content_source"] == "local_seo_page"
        assert written["source_id"] == "lsp-1"
        # A new body invalidates the last committed bytes.
        assert written["content_hash"] is None

    async def test_a_template_rendered_page_is_recorded_not_generated(self):
        page = {"id": "p1", "website_id": "w1", "page_type": "sitemap",
                "plan": {"engine": "template"}}
        sb, tables = _supabase(page, SITE, CLIENT)
        with patch.object(wg, "get_supabase", return_value=sb), patch(
            "services.local_seo_service.generate_page", new=AsyncMock()
        ) as engine:
            result = await wg.generate_page(page_id="p1", user_id="u1")

        assert result["reason"] == "template_rendered"
        engine.assert_not_called()

    async def test_a_page_type_with_no_engine_says_so_on_the_row(self):
        page = {"id": "p1", "website_id": "w1", "page_type": "cost", "plan": {"engine": None}}
        sb, tables = _supabase(page, SITE, CLIENT)
        with patch.object(wg, "get_supabase", return_value=sb):
            result = await wg.generate_page(page_id="p1", user_id="u1")

        assert result["reason"] == "engine_unavailable:cost"
        assert tables["website_pages"].update.call_args[0][0]["error"] == "engine_unavailable:cost"

    async def test_a_specified_but_unbuilt_engine_is_distinguishable(self):
        # "This engine isn't built yet" and "nothing will ever write this" are
        # different problems with different fixes. No engine name is unbuilt
        # today, so this pins the *distinction* on a hypothetical one.
        page = {"id": "p1", "website_id": "w1", "page_type": "cost",
                "plan": {"engine": "some_future_engine"}}
        sb, _ = _supabase(page, SITE, CLIENT)
        with patch.object(wg, "get_supabase", return_value=sb):
            result = await wg.generate_page(page_id="p1", user_id="u1")

        assert result["reason"] == "engine_not_built:some_future_engine"

    async def test_a_home_page_is_written_by_the_core_pages_writer(self):
        page = {"id": "p1", "website_id": "w1", "page_type": "home", "title": "Home",
                "plan": {"engine": "core_pages"}}
        sb, tables = _supabase(page, SITE, CLIENT)
        content = {"title": "Acme Roofing", "description": "Fast roof repair.",
                   "body": "", "frontmatter": {"sections": {"heroTitle": "Roofs done right"}}}
        gen = AsyncMock(return_value=content)
        with patch.object(wg, "get_supabase", return_value=sb), patch(
            "services.website_core_pages.generate_core_page", new=gen
        ):
            result = await wg.generate_page(page_id="p1", user_id="u1")

        assert result == {"page_id": "p1", "generated": True, "page_kind": "home"}
        assert gen.call_args.kwargs["page_kind"] == "home"
        written = tables["website_pages"].update.call_args[0][0]
        # A core page IS its own source — stored on the row, no upstream record.
        assert written["content_source"] == "composed"
        assert written["source_id"] is None
        assert written["content"] == content
        assert written["content_hash"] is None

    async def test_privacy_is_deterministic_and_never_hits_the_writer(self):
        # The template renders the policy from a legal template + business facts;
        # sending it to an LLM would only invent a policy nobody asked for.
        page = {"id": "p1", "website_id": "w1", "page_type": "privacy",
                "plan": {"engine": "core_pages"}}
        sb, _ = _supabase(page, SITE, CLIENT)
        gen = AsyncMock()
        with patch.object(wg, "get_supabase", return_value=sb), patch(
            "services.website_core_pages.generate_core_page", new=gen
        ):
            result = await wg.generate_page(page_id="p1", user_id="u1")

        assert result["reason"] == "template_rendered"
        gen.assert_not_called()

    async def test_a_core_page_is_refused_without_brand_context(self):
        # A home page written with zero brand context is every visitor's first
        # impression of the client in a generic voice — the same bar as a service
        # page.
        page = {"id": "p1", "website_id": "w1", "page_type": "home",
                "plan": {"engine": "core_pages"}}
        sb, _ = _supabase(page, SITE, {"id": "c1"})
        gen = AsyncMock()
        with patch.object(wg, "get_supabase", return_value=sb), patch(
            "services.website_core_pages.generate_core_page", new=gen
        ):
            with pytest.raises(wg.GenerateError, match="content_no_brand_context"):
                await wg.generate_page(page_id="p1", user_id="u1")
        gen.assert_not_called()

    async def test_generation_is_refused_without_brand_context(self):
        page = {"id": "p1", "website_id": "w1", "page_type": "service",
                "plan": {"engine": "nlp", "keyword": "Roof Repair"}}
        sb, _ = _supabase(page, SITE, {"id": "c1"})
        with patch.object(wg, "get_supabase", return_value=sb), patch(
            "services.local_seo_service.generate_page", new=AsyncMock()
        ) as engine:
            with pytest.raises(wg.GenerateError, match="content_no_brand_context"):
                await wg.generate_page(page_id="p1", user_id="u1")
        engine.assert_not_called()

    async def test_a_plan_row_with_no_keyword_fails_loudly(self):
        page = {"id": "p1", "website_id": "w1", "page_type": "service",
                "plan": {"engine": "nlp", "keyword": ""}}
        sb, _ = _supabase(page, SITE, CLIENT)
        with patch.object(wg, "get_supabase", return_value=sb):
            with pytest.raises(wg.GenerateError, match="plan_row_has_no_keyword"):
                await wg.generate_page(page_id="p1", user_id="u1")


class TestEnqueue:
    def test_jobs_are_staggered_so_a_batch_runs_at_background_priority(self):
        sb = MagicMock()
        chain = sb.table.return_value
        chain.insert.return_value = chain
        chain.execute.return_value = MagicMock(data=[{"id": "j1"}, {"id": "j2"}])
        with patch.object(wg, "get_supabase", return_value=sb), patch.object(
            wg.settings, "website_publish_job_spacing_seconds", 20
        ):
            wg.enqueue_generation(
                website_id="w1", client_id="c1", page_ids=["p1", "p2"], user_id="u1"
            )
        rows = chain.insert.call_args[0][0]
        assert [r["job_type"] for r in rows] == ["website_page_generate"] * 2
        assert rows[0]["scheduled_at"] < rows[1]["scheduled_at"]
        # entity_id is the site so the freeze gate and the batch poll both
        # resolve; client_id rides the payload for job_client_id.
        assert rows[0]["entity_id"] == "w1"
        assert rows[0]["payload"]["client_id"] == "c1"

    def test_an_empty_selection_enqueues_nothing(self):
        with patch.object(wg, "get_supabase") as sb:
            assert wg.enqueue_generation(
                website_id="w1", client_id="c1", page_ids=[], user_id="u1"
            ) == []
        sb.assert_not_called()

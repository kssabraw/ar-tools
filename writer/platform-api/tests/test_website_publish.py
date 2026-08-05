"""Unit tests for the Website Builder's publish path.

Weighted toward the three things that are expensive to get wrong: the gate
deciding what ships, the idempotency rule deciding whether a commit happens at
all, and the JSON-LD parse that can fail a whole site build if it lets the wrong
shape through.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import website_publish as wp


class TestParseJsonld:
    def test_plain_object_passes_through(self):
        assert wp.parse_jsonld('{"@type": "Service"}') == {"@type": "Service"}

    def test_script_wrapper_is_stripped(self):
        raw = '<script type="application/ld+json">{"@type": "LocalBusiness"}</script>'
        assert wp.parse_jsonld(raw) == {"@type": "LocalBusiness"}

    def test_graph_array_takes_the_first_object(self):
        # The template injects one object verbatim; guessing at a merge would be
        # inventing schema the generator did not emit.
        assert wp.parse_jsonld('[{"@type": "A"}, {"@type": "B"}]') == {"@type": "A"}

    @pytest.mark.parametrize("raw", ["", None, "not json", "<script></script>", "[]", "{}", 7])
    def test_anything_unusable_is_dropped_not_smuggled(self, raw):
        # A page shipping without JSON-LD is a small loss. A page failing the
        # site build because a string reached a z.record() field is not.
        assert wp.parse_jsonld(raw) is None

    def test_dict_input_is_returned_as_is(self):
        assert wp.parse_jsonld({"@type": "FAQPage"}) == {"@type": "FAQPage"}


class TestContentHash:
    def test_same_files_hash_the_same_regardless_of_order(self):
        a = wp.content_hash({"a.md": b"one", "b.md": b"two"})
        b = wp.content_hash({"b.md": b"two", "a.md": b"one"})
        assert a == b

    def test_changed_body_changes_the_hash(self):
        assert wp.content_hash({"a.md": b"one"}) != wp.content_hash({"a.md": b"two"})

    def test_path_is_part_of_the_identity(self):
        assert wp.content_hash({"a.md": b"x"}) != wp.content_hash({"b.md": b"x"})

    def test_boundaries_prevent_a_concatenation_collision(self):
        # Without separators, {"ab": b"c"} and {"a": b"bc"} would hash alike.
        assert wp.content_hash({"ab": b"c"}) != wp.content_hash({"a": b"bc"})


class TestIdempotency:
    def test_unchanged_content_with_a_commit_is_a_no_op(self):
        page = {"commit_sha": "abc", "content_hash": "h"}
        assert wp.is_unchanged(page, "h") is True

    def test_changed_content_republishes(self):
        # The whole point: a reoptimized page has to be able to ship again.
        page = {"commit_sha": "abc", "content_hash": "old"}
        assert wp.is_unchanged(page, "new") is False

    def test_matching_hash_without_a_commit_still_publishes(self):
        # A previous attempt rendered and then failed; that page has never
        # shipped, and treating it as published would strand it.
        page = {"commit_sha": None, "content_hash": "h"}
        assert wp.is_unchanged(page, "h") is False


class TestSourceResolution:
    def test_local_seo_row_carries_body_and_both_gate_inputs(self):
        source = wp.source_from_local_seo(
            {
                "content_html": "<h2>Roof repair</h2><p>Fast work.</p>",
                "page_title": "Roof Repair in Anaheim",
                "schema_json": '{"@type": "Service"}',
                "composite_score": 81.5,
                "voice_violations": {"score": 90, "violations": []},
            }
        )
        assert "Roof repair" in source.body
        assert source.title == "Roof Repair in Anaheim"
        assert source.composite == 81.5
        assert source.voice == {"score": 90, "violations": []}
        assert source.jsonld == {"@type": "Service"}

    def test_a_client_with_no_guide_yields_no_voice_verdict(self):
        # None means "nothing to enforce" — not a score of zero.
        source = wp.source_from_local_seo({"content_html": "<p>x</p>", "voice_violations": None})
        assert source.voice is None

    def test_composed_page_defaults_to_facts_consistent(self):
        assert wp.source_from_content({"body": "hi", "title": "Hi"}).facts_consistent is True

    def test_composed_page_can_declare_a_facts_failure(self):
        assert wp.source_from_content({"facts_consistent": False}).facts_consistent is False


class TestBuildFiles:
    def _page(self, **over):
        page = {
            "route": "/anaheim/roof-repair/",
            "page_type": "local_landing",
            "title": "Roof Repair in Anaheim",
            "plan": {
                "frontmatter": {
                    "citySlug": "anaheim",
                    "serviceSlug": "roof-repair",
                    "locationName": "Anaheim",
                    "serviceName": "Roof Repair",
                }
            },
        }
        page.update(over)
        return page

    def test_plan_frontmatter_reaches_the_file(self):
        files = wp.build_files(self._page(), wp.SourceContent(body="Body", title="T"))
        content = files["src/content/local-landing/anaheim-roof-repair.md"].decode()
        assert 'citySlug: "anaheim"' in content
        assert 'pageType: "local_landing"' in content
        assert content.endswith("Body\n")

    def test_source_id_is_recorded_so_a_file_traces_back(self):
        files = wp.build_files(
            self._page(source_id="page-1"), wp.SourceContent(body="B", title="T")
        )
        assert 'sourceId: "page-1"' in next(iter(files.values())).decode()

    def test_stored_frontmatter_overrides_the_plan(self):
        # A human edit on the row must beat a value the planner derived.
        page = self._page(content={"frontmatter": {"locationName": "Anaheim Hills"}})
        files = wp.build_files(page, wp.SourceContent(body="B", title="T"))
        assert 'locationName: "Anaheim Hills"' in next(iter(files.values())).decode()


class TestHeldNotification:
    def test_dedupe_key_is_per_site_per_day(self):
        # One notification per batch, not one per page — and the uniqueness is
        # the table's, so concurrent publish jobs cannot race a duplicate.
        when = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
        later = datetime(2026, 8, 5, 23, 0, tzinfo=timezone.utc)
        assert wp.held_dedupe_key("site-1", when) == wp.held_dedupe_key("site-1", later)
        assert wp.held_dedupe_key("site-1", when) != wp.held_dedupe_key("site-2", when)


def _supabase_for(page: dict, website: dict, superseded: list[dict] | None = None):
    """A stub whose table() calls answer the publish path's reads."""
    tables: dict[str, MagicMock] = {}

    def table(name):
        if name not in tables:
            mock = MagicMock()
            mock.update.return_value = mock
            mock.insert.return_value = mock
            mock.select.return_value = mock
            mock.eq.return_value = mock
            mock.in_.return_value = mock
            mock.limit.return_value = mock
            mock.order.return_value = mock
            mock.not_.is_.return_value = mock
            if name == "website_pages":
                mock.execute.return_value = MagicMock(data=(superseded or [page]))
            elif name == "websites":
                mock.execute.return_value = MagicMock(data=[website])
            else:
                mock.execute.return_value = MagicMock(data=[{"id": "row-1"}])
            tables[name] = mock
        return tables[name]

    client = MagicMock()
    client.table.side_effect = table
    return client, tables


@pytest.mark.asyncio
class TestPublishPage:
    PAGE = {
        "id": "p1",
        "website_id": "w1",
        "route": "/anaheim/roof-repair/",
        "page_type": "local_landing",
        "title": "Roof Repair in Anaheim",
        "content_source": "composed",
        "plan": {"frontmatter": {"citySlug": "anaheim", "serviceSlug": "roof-repair",
                                 "locationName": "Anaheim", "serviceName": "Roof Repair"}},
        "content": {"body": "Body copy.", "title": "Roof Repair in Anaheim"},
        "commit_sha": None,
        "content_hash": None,
    }
    SITE = {"id": "w1", "client_id": "c1", "name": "Acme", "github_repo": "kssabraw/site-acme"}

    async def test_a_failed_gate_holds_the_page_and_commits_nothing(self):
        page = {**self.PAGE, "content": {"body": "B", "facts_consistent": False}}
        client, tables = _supabase_for(page, self.SITE)
        with patch.object(wp, "get_supabase", return_value=client), patch.object(
            wp, "commit_files_to_github", new=AsyncMock()
        ) as commit, patch("services.notifications.emit") as emit:
            result = await wp.publish_page(page_id="p1")

        assert result == {"page_id": "p1", "published": False, "reason": "facts_consistency_failed"}
        commit.assert_not_called()
        emit.assert_called_once()
        assert tables["website_pages"].update.call_args[0][0]["status"] == "draft"

    async def test_force_cannot_pass_a_non_overridable_gate(self):
        # Facts consistency is a liability question, not a quality preference.
        page = {**self.PAGE, "content": {"body": "B", "facts_consistent": False}}
        client, _ = _supabase_for(page, self.SITE)
        with patch.object(wp, "get_supabase", return_value=client), patch.object(
            wp, "commit_files_to_github", new=AsyncMock()
        ) as commit, patch("services.notifications.emit"):
            result = await wp.publish_page(page_id="p1", force=True)

        assert result["published"] is False
        commit.assert_not_called()

    async def test_a_clean_page_commits_and_records_its_deploy(self):
        client, tables = _supabase_for(self.PAGE, self.SITE)
        commit = AsyncMock(return_value={"commit_sha": "sha123", "tree_sha": "t"})
        with patch.object(wp, "get_supabase", return_value=client), patch.object(
            wp, "commit_files_to_github", new=commit
        ), patch.object(wp.website_deploy, "record_deploy") as record:
            result = await wp.publish_page(page_id="p1", user_id="u1")

        assert result["commit_sha"] == "sha123"
        files = commit.call_args.kwargs["files"]
        assert "src/content/local-landing/anaheim-roof-repair.md" in files
        record.assert_called_once()
        assert record.call_args.kwargs["trigger"] == "publish"
        assert record.call_args.kwargs["meta"]["overrides"] == []
        patch_written = tables["website_pages"].update.call_args[0][0]
        assert patch_written["status"] == "published"
        assert patch_written["content_hash"]

    async def test_an_override_is_recorded_on_the_deploy(self):
        # PRD §5.7 — an override invisible after the fact is indistinguishable
        # from a bug.
        page = {
            **self.PAGE,
            "content": {
                "body": "B",
                "voice": {"violations": [{"severity": "critical", "term": "we"}]},
            },
            "page_type": "service",
        }
        client, _ = _supabase_for(page, self.SITE)
        with patch.object(wp, "get_supabase", return_value=client), patch.object(
            wp, "commit_files_to_github", new=AsyncMock(return_value={"commit_sha": "s"})
        ), patch.object(wp.website_deploy, "record_deploy") as record:
            result = await wp.publish_page(page_id="p1", user_id="kyle", force=True)

        assert result["forced"] is True
        override = record.call_args.kwargs["meta"]["overrides"][0]
        assert override == {"page_id": "p1", "gate": "voice_violation", "forced_by": "kyle"}

    async def test_republishing_unchanged_content_makes_no_commit(self):
        rendered = wp.build_files(self.PAGE, wp.source_from_content(self.PAGE["content"]))
        page = {**self.PAGE, "commit_sha": "old", "content_hash": wp.content_hash(rendered)}
        client, _ = _supabase_for(page, self.SITE)
        with patch.object(wp, "get_supabase", return_value=client), patch.object(
            wp, "commit_files_to_github", new=AsyncMock()
        ) as commit:
            result = await wp.publish_page(page_id="p1")

        assert result == {"page_id": "p1", "published": True, "commit_sha": "old", "unchanged": True}
        commit.assert_not_called()

    async def test_a_template_only_page_publishes_without_a_file(self):
        # The template renders these from the published set; leaving them at
        # draft forever would be a queue nobody can clear.
        page = {**self.PAGE, "page_type": "sitemap", "route": "/sitemap/"}
        client, _ = _supabase_for(page, self.SITE)
        with patch.object(wp, "get_supabase", return_value=client), patch.object(
            wp, "commit_files_to_github", new=AsyncMock()
        ) as commit:
            result = await wp.publish_page(page_id="p1")

        assert result["template_only"] is True
        commit.assert_not_called()

    async def test_an_ungenerated_page_is_held_rather_than_shipped_empty(self):
        # Committing an empty file ships a real URL with nothing on it, which is
        # worse than a page that is visibly still a draft. This is also what
        # catches a page type with no engine at all (Areas We Serve).
        page = {**self.PAGE, "content": {"body": "   ", "title": "T"}}
        client, tables = _supabase_for(page, self.SITE)
        with patch.object(wp, "get_supabase", return_value=client), patch.object(
            wp, "commit_files_to_github", new=AsyncMock()
        ) as commit, patch("services.notifications.emit"):
            result = await wp.publish_page(page_id="p1")

        assert result["reason"] == "body_not_generated"
        commit.assert_not_called()

    async def test_an_unprovisioned_site_cannot_publish(self):
        client, _ = _supabase_for(self.PAGE, {**self.SITE, "github_repo": None})
        with patch.object(wp, "get_supabase", return_value=client):
            with pytest.raises(wp.PublishError, match="website_not_provisioned"):
                await wp.publish_page(page_id="p1")

    async def test_a_rename_redirect_rides_the_same_commit(self):
        superseded = [{"route": "/old-roof/", "redirect_to": "/roof-repair/"}]
        client, tables = _supabase_for(self.PAGE, self.SITE)
        # website_pages is read twice: the page itself, then the superseded set.
        tables_pages = client.table("website_pages")
        tables_pages.execute.side_effect = [
            MagicMock(data=[self.PAGE]),
            MagicMock(data=superseded),
            MagicMock(data=[]),
        ]
        commit = AsyncMock(return_value={"commit_sha": "s"})
        with patch.object(wp, "get_supabase", return_value=client), patch.object(
            wp, "commit_files_to_github", new=commit
        ), patch.object(wp.website_deploy, "record_deploy"):
            await wp.publish_page(page_id="p1")

        files = commit.call_args.kwargs["files"]
        assert files["public/_redirects"] == b"/old-roof/ /roof-repair/ 301\n"

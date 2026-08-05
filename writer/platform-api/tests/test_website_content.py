"""Unit tests for the Website Builder's content → repo-file conversion.

The frontmatter contract is the interface between the suite's writers and the
template's zod schema, so a mismatch here fails a whole site's build. The gate
tests cover §5.2–§5.4, weighted toward the auto-publish path where nobody reads
the page before the public does.
"""

from __future__ import annotations

from datetime import date

import pytest

from services import website_content as wc


class TestRepoLayout:
    @pytest.mark.parametrize(
        "page_type,expected",
        [
            ("service", "services"),
            ("sub_service", "services"),
            ("location", "locations"),
            ("neighborhood", "locations"),
            ("local_landing", "local-landing"),
            ("post", "posts"),
            ("about", "pages"),
        ],
    )
    def test_collection_is_a_shape_not_a_page_type(self, page_type, expected):
        assert wc.collection_of(page_type) == expected

    def test_unknown_page_type_is_a_clear_error(self):
        with pytest.raises(wc.ContentError, match="no_collection_for_page_type"):
            wc.collection_of("poi")

    def test_matrix_entry_ids_do_not_collide_across_cities(self):
        # The whole point: the last segment repeats across the matrix, so an id
        # built from it would have one city silently overwrite another.
        a = wc.entry_id("/anaheim/ac-repair/", "local_landing")
        b = wc.entry_id("/brea/ac-repair/", "local_landing")
        assert a != b
        assert a == "anaheim-ac-repair"

    def test_core_pages_use_their_fixed_entry_id(self):
        # The template looks these up by name, not by path.
        assert wc.entry_id("/about-us/", "about") == "about-us"
        assert wc.entry_id("/", "home") == "home"

    def test_repo_path_is_full(self):
        assert (
            wc.repo_path("/overland-park/roof-repair/", "local_landing")
            == "src/content/local-landing/overland-park-roof-repair.md"
        )


class TestFrontmatter:
    def test_routed_entries_declare_path_and_page_type(self):
        fm = wc.frontmatter_for(path="/anaheim/ac-repair/", page_type="local_landing", title="AC Repair")
        assert fm["path"] == "/anaheim/ac-repair/"
        assert fm["pageType"] == "local_landing"

    def test_core_pages_omit_path_and_page_type(self):
        fm = wc.frontmatter_for(path="/about-us/", page_type="about", title="About Us")
        assert "path" not in fm and "pageType" not in fm

    def test_path_must_carry_both_slashes(self):
        # The template's zod schema rejects anything else, so catching it here
        # turns a whole-site build failure into one page's error.
        with pytest.raises(wc.ContentError):
            wc.frontmatter_for(path="/anaheim/ac-repair", page_type="local_landing", title="x")

    def test_titles_with_colons_are_quoted(self):
        # The classic way hand-built frontmatter breaks.
        out = wc.render_frontmatter({"title": "Roof Repair: Fast"})
        assert 'title: "Roof Repair: Fast"' in out

    def test_quotes_and_newlines_are_escaped(self):
        out = wc.render_frontmatter({"title": 'He said "hi"', "description": "one\ntwo"})
        assert 'title: "He said \\"hi\\""' in out
        assert 'description: "one two"' in out

    def test_empty_values_are_dropped_not_emitted_blank(self):
        out = wc.render_frontmatter({"title": "T", "teaser": "", "order": 0, "draft": False})
        assert "teaser:" not in out
        # 0 and False are meaningful, not empty — but 0 == "" is False in Python
        # and False == 0 is True, so this is exactly where a naive falsy check
        # would silently drop a real value.
        assert "draft: false" in out

    def test_key_order_is_fixed_so_output_is_byte_stable(self):
        a = wc.render_frontmatter({"pageType": "service", "title": "T", "path": "/t/"})
        b = wc.render_frontmatter({"title": "T", "path": "/t/", "pageType": "service"})
        assert a == b

    def test_dates_serialize_iso(self):
        out = wc.render_frontmatter({"title": "T", "publishDate": date(2026, 7, 2)})
        assert "publishDate: 2026-07-02" in out

    def test_build_markdown_shape(self):
        md = wc.build_markdown(fields={"title": "T"}, body="Body text.")
        assert md.startswith("---\n") and "\n---\n\n" in md and md.endswith("\n")
        assert "Body text." in md


class TestPublishGates:
    def test_local_page_below_composite_is_held_but_overridable(self):
        v = wc.publish_verdict(page_type="service", composite=71.0)
        assert not v.allowed and v.overridable
        assert "seo_composite_below_threshold" in v.reason

    def test_local_page_at_threshold_publishes(self):
        assert wc.publish_verdict(page_type="service", composite=75.0).allowed

    def test_critical_voice_finding_holds_a_local_page(self):
        v = wc.publish_verdict(
            page_type="local_landing",
            composite=90.0,
            voice={"violations": [{"severity": "critical"}]},
        )
        assert not v.allowed and v.overridable

    def test_voice_warnings_stay_advisory(self):
        v = wc.publish_verdict(
            page_type="service", composite=90.0, voice={"violations": [{"severity": "warning"}]}
        )
        assert v.allowed

    def test_facts_inconsistency_blocks_everyone_everywhere(self):
        for page_type in ("service", "post", "about"):
            v = wc.publish_verdict(page_type=page_type, composite=99.0, facts_consistent=False)
            assert not v.allowed
            assert not v.overridable, "a facts failure must not be forceable at any role"


class TestAutoPublishGate:
    """§5.4 — stricter, because nobody reads these before the public does."""

    def _post(self, **over):
        fm = {"title": "T", "description": "D", "format": "informational_cluster"}
        fm.update(over.pop("frontmatter", {}))
        return wc.publish_verdict(page_type="post", frontmatter=fm, **over)

    def test_clean_post_auto_publishes(self):
        assert self._post().allowed

    def test_degraded_writer_run_is_never_published(self):
        v = self._post(writer_schema_version="1.9-degraded")
        assert not v.allowed and not v.overridable
        assert v.reason == "writer_run_degraded"

    def test_non_degraded_version_is_fine(self):
        assert self._post(writer_schema_version="1.9").allowed

    def test_missing_declared_format_holds_the_post(self):
        v = self._post(frontmatter={"format": ""})
        assert not v.allowed and "format" in v.reason

    def test_news_post_without_a_review_date_is_held(self):
        # Non-evergreen + auto-publish + no expiry ranks on stale info forever.
        v = self._post(frontmatter={"format": "news"})
        assert not v.allowed and v.reason == "news_post_missing_review_date"

    def test_news_post_with_a_review_date_publishes(self):
        assert self._post(frontmatter={"format": "news", "reviewBy": date(2026, 12, 1)}).allowed

    def test_critical_voice_on_a_post_is_not_overridable(self):
        # Unlike a local page, which a human has already reviewed.
        v = self._post(voice={"violations": [{"severity": "critical"}]})
        assert not v.allowed and not v.overridable


class TestBatchFiles:
    def test_builds_one_file_per_page(self):
        files = wc.files_for_pages(
            [
                {"route": "/roof-repair/", "page_type": "service", "title": "Roof Repair", "body": "x"},
                {"route": "/anaheim/", "page_type": "location", "title": "Anaheim", "body": "y"},
            ]
        )
        assert set(files) == {
            "src/content/services/roof-repair.md",
            "src/content/locations/anaheim.md",
        }

    def test_template_only_page_types_produce_no_file(self):
        # The blog archive and sitemap are rendered from data; there is nothing
        # to write and nothing to gate.
        files = wc.files_for_pages([{"route": "/blog/", "page_type": "blog_archive", "title": "Blog"}])
        assert files == {}

    def test_two_pages_resolving_to_one_file_is_an_error(self):
        with pytest.raises(wc.ContentError, match="duplicate_repo_path"):
            wc.files_for_pages(
                [
                    {"route": "/roof-repair/", "page_type": "service", "title": "A", "body": ""},
                    {"route": "/roof-repair/", "page_type": "service", "title": "B", "body": ""},
                ]
            )


class TestRedirects:
    def test_emits_301_per_superseded_route(self):
        out = wc.redirects_file([{"route": "/old-name/", "redirect_to": "/new-name/"}])
        assert out.strip() == "/old-name/ /new-name/ 301"

    def test_ignores_incomplete_or_self_referential_rows(self):
        out = wc.redirects_file(
            [
                {"route": "/a/", "redirect_to": ""},
                {"route": "", "redirect_to": "/b/"},
                {"route": "/same/", "redirect_to": "/same/"},
            ]
        )
        assert out == ""

    def test_output_is_deduped_and_sorted_for_stable_diffs(self):
        rows = [
            {"route": "/b/", "redirect_to": "/x/"},
            {"route": "/a/", "redirect_to": "/x/"},
            {"route": "/b/", "redirect_to": "/x/"},
        ]
        assert wc.redirects_file(rows) == "/a/ /x/ 301\n/b/ /x/ 301\n"

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

    def test_a_post_id_is_its_slug_because_the_route_supplies_the_prefix(self):
        # /blog/[...slug] uses the entry id AS the slug, so a full-path id would
        # publish /blog/blog-my-post/. Caught by building the template, not by
        # reading the schema.
        assert wc.entry_id("/blog/how-to-spot-a-failing-roof/", "post") == (
            "how-to-spot-a-failing-roof"
        )
        assert (
            wc.repo_path("/blog/how-to-spot-a-failing-roof/", "post")
            == "src/content/posts/how-to-spot-a-failing-roof.md"
        )

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


class TestPillarContent:
    def test_pillar_has_its_own_collection(self):
        assert wc.collection_of("pillar") == "pillars"

    def test_pillar_entry_id_is_its_top_level_slug(self):
        assert wc.entry_id("/roof-maintenance/", "pillar") == "roof-maintenance"

    def test_pillar_repo_path(self):
        assert wc.repo_path("/roof-maintenance/", "pillar") == (
            "src/content/pillars/roof-maintenance.md"
        )

    def test_clean_pillar_auto_publishes(self):
        v = wc.publish_verdict(
            page_type="pillar", frontmatter={"title": "T", "description": "D"}
        )
        assert v.allowed

    def test_pillar_missing_description_is_held(self):
        v = wc.publish_verdict(page_type="pillar", frontmatter={"title": "T"})
        assert not v.allowed
        assert "description" in v.reason

    def test_critical_voice_blocks_a_pillar_non_overridably(self):
        v = wc.publish_verdict(
            page_type="pillar",
            frontmatter={"title": "T", "description": "D"},
            voice={"violations": [{"severity": "critical"}]},
        )
        assert not v.allowed and not v.overridable

    def test_degraded_run_never_publishes_a_pillar(self):
        v = wc.publish_verdict(
            page_type="pillar",
            frontmatter={"title": "T", "description": "D"},
            writer_schema_version="1.9-degraded",
        )
        assert not v.allowed and not v.overridable


class TestExtensionContentLayer:
    """Where the ⭐ extension types + Writer-#6 hubs live in the repo, how they're
    addressed, and how the publish gate judges them."""

    def test_collections(self):
        assert wc.collection_of("cost") == "services"
        assert wc.collection_of("comparison") == "comparisons"
        assert wc.collection_of("faq") == "pages"
        assert wc.collection_of("services_index") == "pages"
        assert wc.collection_of("areas_we_serve") == "pages"

    def test_id_addressed_entries_use_stable_ids(self):
        assert wc.entry_id("/faq/", "faq") == "faq"
        assert wc.entry_id("/services/", "services_index") == "services"
        assert wc.entry_id("/areas-we-serve/", "areas_we_serve") == "areas-we-serve"

    def test_id_addressed_entries_omit_path_and_page_type(self):
        # A `pages`-collection entry has neither field in its schema.
        for pt in ("faq", "services_index", "areas_we_serve"):
            fm = wc.frontmatter_for(path="/faq/", page_type=pt, title="X")
            assert "path" not in fm and "pageType" not in fm

    def test_a_cost_page_is_a_routed_entry_with_path_and_type(self):
        fm = wc.frontmatter_for(path="/tree-removal/cost/", page_type="cost", title="Cost")
        assert fm["path"] == "/tree-removal/cost/"
        assert fm["pageType"] == "cost"

    def test_a_comparison_is_a_routed_entry(self):
        fm = wc.frontmatter_for(path="/compare/a-vs-b/", page_type="comparison", title="A vs B")
        assert fm["pageType"] == "comparison"

    def test_a_cost_page_is_serp_scored_like_a_service(self):
        assert wc.publish_verdict(page_type="cost", composite=None).reason == "seo_composite_missing"
        assert not wc.publish_verdict(page_type="cost", composite=71.0).allowed
        assert wc.publish_verdict(page_type="cost", composite=80.0).allowed

    def test_a_comparison_gates_like_a_pillar(self):
        assert wc.publish_verdict(
            page_type="comparison", frontmatter={"title": "A vs B", "description": "d"}
        ).allowed
        # A degraded run and a critical voice finding are both non-overridable.
        assert wc.publish_verdict(
            page_type="comparison", writer_schema_version="1.9-degraded",
            frontmatter={"title": "t", "description": "d"},
        ).reason == "writer_run_degraded"
        v = wc.publish_verdict(
            page_type="comparison",
            voice={"violations": [{"severity": "critical"}]},
            frontmatter={"title": "t", "description": "d"},
        )
        assert v.reason == "voice_violation" and not v.overridable
        assert not wc.publish_verdict(page_type="comparison", frontmatter={"title": "t"}).allowed

    def test_hubs_left_template_only_and_joined_the_section_set(self):
        assert "services_index" not in wc.TEMPLATE_ONLY_PAGE_TYPES
        assert "areas_we_serve" not in wc.TEMPLATE_ONLY_PAGE_TYPES
        assert wc.HUB_PAGE_TYPES == {"services_index", "areas_we_serve"}
        for pt in ("home", "faq", "services_index", "areas_we_serve"):
            assert pt in wc.SECTION_CONTENT_PAGE_TYPES

    def test_a_hub_with_a_body_now_produces_a_file(self):
        # Writer #6: the hubs are no longer skipped by files_for_pages.
        files = wc.files_for_pages(
            [{"route": "/services/", "page_type": "services_index", "title": "Services",
              "body": "", "extra": {"sections": {"lede": "All we do."}}}]
        )
        [(path, data)] = files.items()
        assert path == "src/content/pages/services.md"
        assert "All we do." in data.decode("utf-8")


class TestProjectContentLayer:
    def test_project_collection_and_routing(self):
        assert wc.collection_of("project") == "projects"
        assert "project" in wc.SECTION_CONTENT_PAGE_TYPES

    def test_a_project_is_a_routed_entry(self):
        fm = wc.frontmatter_for(path="/projects/oak-removal/", page_type="project", title="Oak")
        assert fm["path"] == "/projects/oak-removal/"
        assert fm["pageType"] == "project"

    def test_a_project_gate_is_advisory_not_serp_scored(self):
        # Not in the geo composite set — a project ships without a score; a
        # critical voice finding is overridable (like a core page).
        assert wc.publish_verdict(page_type="project").allowed
        v = wc.publish_verdict(page_type="project", voice={"violations": [{"severity": "critical"}]})
        assert v.reason == "voice_violation" and v.overridable is True
        # Facts inconsistency is never overridable, anywhere.
        assert not wc.publish_verdict(page_type="project", facts_consistent=False).overridable

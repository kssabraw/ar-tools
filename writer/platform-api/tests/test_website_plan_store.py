"""Unit tests for persisting and approving a site plan.

Two things carry the weight: a rebuild must not damage work that already
happened (published files, generated bodies), and approval must refuse every
blocking planning error — a published slug is immutable, so approving a wrong
URL costs a permanent redirect rather than an edit.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services import website_plan as wpl
from services import website_plan_store as store

CATALOG = [
    {"name": "Roof Repair", "order": 1},
    {"name": "Roof Replacement", "order": 2},
    {"name": "Gutter Cleaning", "order": 3, "include_in_matrix": False},
]
CITIES = [
    {"name": "Anaheim", "neighborhoods": [{"name": "Anaheim Hills"}]},
    {"name": "Brea"},
]


class TestParsing:
    def test_slugs_are_derived_when_absent(self):
        [svc] = store.parse_catalog([{"name": "Roof Repair"}])
        assert svc.slug == "roof-repair"

    def test_an_explicit_slug_wins(self):
        # A slug is immutable after first publish, so a stored value must never
        # be quietly re-derived from a renamed service.
        [svc] = store.parse_catalog([{"name": "Roof Repair & Restoration", "slug": "roofing"}])
        assert svc.slug == "roofing"

    def test_nameless_entries_are_dropped(self):
        assert store.parse_catalog([{"name": "  "}, {}]) == []

    def test_neighborhoods_accept_both_shapes(self):
        [city] = store.parse_cities([{"name": "Anaheim", "neighborhoods": ["Anaheim Hills"]}])
        assert city.neighborhoods == (("Anaheim Hills", "anaheim-hills"),)

    def test_matrix_exclusion_survives_parsing(self):
        catalog = store.parse_catalog(CATALOG)
        assert [s.slug for s in catalog if s.include_in_matrix] == [
            "roof-repair",
            "roof-replacement",
        ]

    def test_legacy_brands_parse_as_brand_variations(self):
        # The pre-generalization `brands` field still round-trips (an existing
        # site's stored catalog keeps working until its next save migrates it).
        [svc] = store.parse_catalog(
            [{"name": "AC Repair", "brands": ["Carrier", "  Trane  ", "", 5]}]
        )
        assert svc.brands == ("Carrier", "Trane")
        assert all(v.kind == "brand" for v in svc.variations)

    def test_variations_parse_with_kind_and_default_to_type(self):
        [svc] = store.parse_catalog(
            [
                {
                    "name": "Tree Removal",
                    "variations": [
                        {"label": "Oak Trees", "kind": "type"},
                        {"label": "Certified Arborist", "kind": "brand"},
                        {"label": "Palm Trees"},  # kind omitted -> type
                        "Maple Trees",  # bare string -> type
                        {"label": "Bad", "kind": "nonsense"},  # unknown kind -> type
                    ],
                }
            ]
        )
        by_label = {v.label: v.kind for v in svc.variations}
        assert by_label["Oak Trees"] == "type"
        assert by_label["Certified Arborist"] == "brand"
        assert by_label["Palm Trees"] == "type"
        assert by_label["Maple Trees"] == "type"
        assert by_label["Bad"] == "type"

    def test_variations_default_to_empty(self):
        [svc] = store.parse_catalog([{"name": "AC Repair"}])
        assert svc.variations == ()
        assert svc.brands == ()

    def test_present_variations_win_over_legacy_brands(self):
        # If both fields are present, `variations` is authoritative and legacy
        # `brands` are ignored — mirroring the frontend, which drops `brands` the
        # moment it writes `variations`. Honouring both would double them up.
        [svc] = store.parse_catalog(
            [{"name": "AC Repair", "brands": ["Carrier"], "variations": [{"label": "Emergency", "kind": "type"}]}]
        )
        assert svc.variations == (wpl.ServiceVariation(label="Emergency", kind="type"),)
        assert svc.brands == ()

    def test_an_empty_variations_list_still_drops_legacy_brands(self):
        # Presence of the key (even empty) means the catalog has been migrated,
        # so stale `brands` are not resurrected.
        [svc] = store.parse_catalog(
            [{"name": "AC Repair", "brands": ["Carrier"], "variations": []}]
        )
        assert svc.variations == ()


class TestHeadTerms:
    def test_defaults_to_the_first_service_in_nav_order(self):
        catalog = store.parse_catalog(CATALOG)
        cities = store.parse_cities(CITIES)
        assert store.head_terms({}, catalog, cities) == ("Roof Repair", "Anaheim")

    def test_explicit_config_wins(self):
        catalog = store.parse_catalog(CATALOG)
        cities = store.parse_cities(CITIES)
        config = {"business": {"primaryService": "Roofer", "city": "Fullerton"}}
        assert store.head_terms(config, catalog, cities) == ("Roofer", "Fullerton")

    def test_an_empty_catalog_yields_nothing_rather_than_a_guess(self):
        assert store.head_terms({}, [], []) == (None, None)


class TestPlanRows:
    def _rows(self):
        catalog = store.parse_catalog(CATALOG)
        cities = store.parse_cities(CITIES)
        plan = wpl.build_plan(site_type="local_business", catalog=catalog, cities=cities)
        return {
            r["route"]: r
            for r in store.plan_rows(
                "w1", plan, catalog=catalog, cities=cities,
                primary_service="Roof Repair", primary_city="Anaheim",
            )
        }

    def test_every_row_records_why_it_was_planned(self):
        # Reference §2 rule 3 — a reviewer must see why a page was proposed.
        assert all(r["trigger"] for r in self._rows().values())

    def test_a_matrix_row_carries_both_axes_for_the_template(self):
        row = self._rows()["/anaheim/roof-repair/"]
        assert row["plan"]["frontmatter"]["citySlug"] == "anaheim"
        assert row["plan"]["frontmatter"]["serviceName"] == "Roof Repair"
        assert row["plan"]["keyword"] == "Roof Repair Anaheim"

    def test_a_location_page_targets_the_geo_head_term(self):
        row = self._rows()["/anaheim/"]
        assert row["plan"]["keyword"] == "Roof Repair Anaheim"
        assert row["plan"]["frontmatter"]["locationName"] == "Anaheim"

    def test_a_service_page_is_never_geo_targeted(self):
        row = self._rows()["/roof-repair/"]
        assert row["plan"]["keyword"] == "Roof Repair"

    def test_a_matrix_excluded_service_gets_a_page_but_no_cells(self):
        rows = self._rows()
        assert "/gutter-cleaning/" in rows
        assert "/anaheim/gutter-cleaning/" not in rows

    def test_template_only_pages_are_marked_static(self):
        assert self._rows()["/sitemap/"]["content_source"] == "static"

    def test_a_neighborhood_declares_its_parent_city(self):
        row = self._rows()["/anaheim/anaheim-hills/"]
        assert row["plan"]["frontmatter"]["parentCity"] == "anaheim"
        assert row["page_type"] == "neighborhood"


class TestMergeRow:
    PLANNED = {
        "page_type": "service",
        "title": "Roof Repair",
        "trigger": "CORE",
        "tier": 1,
        "plan": {"engine": "nlp", "keyword": "Roof Repair"},
        "content_source": "composed",
    }

    def test_an_unchanged_row_produces_no_write(self):
        assert store.merge_row({**self.PLANNED}, self.PLANNED) == {}

    def test_a_retitled_page_updates(self):
        patch_ = store.merge_row({**self.PLANNED, "title": "Old"}, self.PLANNED)
        assert patch_ == {"title": "Roof Repair"}

    def test_a_generated_page_keeps_its_source(self):
        # Flipping a written page back to 'composed' would orphan the
        # local_seo_pages row that holds its text.
        existing = {**self.PLANNED, "content_source": "local_seo_page", "source_id": "p9"}
        assert "content_source" not in store.merge_row(existing, self.PLANNED)

    def test_publish_state_is_never_the_planner_s_business(self):
        existing = {**self.PLANNED, "status": "published", "commit_sha": "abc"}
        assert set(store.merge_row(existing, self.PLANNED)) <= set(store._PLANNER_FIELDS) | {
            "content_source"
        }


class TestApprovalGate:
    def test_a_reserved_slug_blocks(self):
        plan = wpl.build_plan(
            site_type="local_business",
            catalog=store.parse_catalog([{"name": "Reviews"}]),
            cities=store.parse_cities([{"name": "Anaheim"}]),
        )
        blocking = [i for i in plan.issues if i.blocking]
        assert blocking and blocking[0].kind == "reserved_slug"

    def test_the_link_budget_blocks_at_the_ratified_25(self):
        catalog = store.parse_catalog([{"name": f"Service {i}", "order": i} for i in range(30)])
        plan = wpl.build_plan(
            site_type="local_business", catalog=catalog,
            cities=store.parse_cities([{"name": "Anaheim"}, {"name": "Brea"}]),
        )
        issues = [i for i in plan.issues if i.kind == "link_budget"]
        assert issues and all(i.blocking for i in issues)

    def test_a_scale_gate_clears_with_a_named_sign_off(self):
        website = {"id": "w1", "site_type": "local_business", "config": {
            "catalog": [{"name": f"Service {i}", "order": i} for i in range(30)],
            "cities": [{"name": "Anaheim"}, {"name": "Brea"}],
        }}
        with patch.object(store, "get_supabase"):
            assert store.approval_blockers(website)
            assert store.approval_blockers(website, acknowledged=["link_budget"]) == []

    def test_a_planning_error_cannot_be_acknowledged_away(self):
        # A reserved-slug collision is wrong, not large. Waving it through ships
        # a URL that is immutable once published.
        website = {"id": "w1", "site_type": "local_business", "config": {
            "catalog": [{"name": "Reviews"}],
            "cities": [{"name": "Anaheim"}],
        }}
        with patch.object(store, "get_supabase"):
            blockers = store.approval_blockers(website, acknowledged=["reserved_slug"])
        assert [b["kind"] for b in blockers] == ["reserved_slug"]

    def test_approval_records_what_was_signed_off(self):
        # A sign-off nobody can find afterwards is indistinguishable from a gate
        # that never fired.
        supabase = MagicMock()
        chain = supabase.table.return_value
        chain.update.return_value = chain
        chain.eq.return_value = chain
        with patch.object(store, "get_supabase", return_value=supabase):
            approval = store.approve(
                {"id": "w1", "config": {}}, actor="kyle", acknowledged=["matrix_signoff"]
            )
        assert approval["approved_by"] == "kyle"
        assert approval["acknowledged"] == ["matrix_signoff"]

    def test_is_approved_reads_the_stamp(self):
        assert store.is_approved({"config": {"plan": {"approved_at": "2026-08-05T00:00:00Z"}}})
        assert not store.is_approved({"config": {}})
        assert not store.is_approved({})


class TestSelection:
    def test_only_this_site_s_pages_can_be_selected(self):
        pages = [{"id": "a"}, {"id": "b"}]
        assert store.coerce_ids(pages, ["b", "elsewhere"]) == ["b"]

    def test_an_empty_selection_never_becomes_everything(self):
        # Both generation and publishing cost something; "all" must be an
        # explicit act, not a default.
        assert store.coerce_ids([{"id": "a"}], []) == []
        assert store.coerce_ids([{"id": "a"}], None) == []


class TestConflictIssues:
    def _site(self, site_type="lead_gen"):
        return {"id": "w1", "site_type": site_type, "client_id": "c1"}

    def _supabase(self, others, kinds, routes):
        client = MagicMock()

        def table(name):
            chain = MagicMock()
            for method in ("select", "eq", "neq", "in_", "order", "limit"):
                getattr(chain, method).return_value = chain
            chain.is_.return_value = chain
            data = {
                "website_pages": routes,
                "websites": others,
                "clients": kinds,
            }[name]
            chain.execute.return_value = MagicMock(data=data)
            return chain

        client.table.side_effect = table
        return client

    def test_a_client_site_is_never_conflict_checked(self):
        with patch.object(store, "get_supabase") as sb:
            assert store.conflict_issues(self._site("local_business")) == []
        sb.assert_not_called()

    def test_overlap_with_a_client_site_blocks(self):
        # Competing with a client for their own keywords on the agency's own
        # infrastructure is a relationship failure, not an SEO one.
        client = self._supabase(
            others=[{"id": "w2", "name": "Acme Roofing", "client_id": "c2"}],
            kinds=[{"id": "c2", "kind": "client"}],
            routes=[{"website_id": "w1", "route": "/anaheim/roof-repair/"},
                    {"website_id": "w2", "route": "/anaheim/roof-repair/"}],
        )
        with patch.object(store, "get_supabase", return_value=client), patch.object(
            store, "stored", return_value=[{"route": "/anaheim/roof-repair/"}]
        ):
            issues = store.conflict_issues(self._site())
        assert len(issues) == 1
        assert issues[0].blocking is True
        assert "Acme Roofing" in issues[0].detail

    def test_overlap_with_another_property_only_warns(self):
        client = self._supabase(
            others=[{"id": "w2", "name": "Roofers Near Me", "client_id": "c2"}],
            kinds=[{"id": "c2", "kind": "owned_property"}],
            routes=[{"website_id": "w2", "route": "/anaheim/roof-repair/"}],
        )
        with patch.object(store, "get_supabase", return_value=client), patch.object(
            store, "stored", return_value=[{"route": "/anaheim/roof-repair/"}]
        ):
            issues = store.conflict_issues(self._site())
        assert issues[0].blocking is False


class TestPortfolioConflicts:
    def test_non_matrix_routes_are_not_cells(self):
        # A shared /about-us/ is not a conflict; only service × city cells are.
        assert wpl.portfolio_conflicts(
            ["/about-us/", "/"], [{"name": "Other", "kind": "client", "routes": ["/about-us/"]}]
        ) == []

    def test_the_overlap_is_named_not_just_counted(self):
        [issue] = wpl.portfolio_conflicts(
            ["/anaheim/roof-repair/"],
            [{"name": "Acme", "kind": "client", "routes": ["/anaheim/roof-repair/"]}],
        )
        assert "/anaheim/roof-repair/" in issue.detail

    def test_a_long_overlap_is_truncated_with_a_count(self):
        cells = [f"/city{i}/roof-repair/" for i in range(9)]
        [issue] = wpl.portfolio_conflicts(
            cells, [{"name": "Acme", "kind": "owned_property", "routes": cells}]
        )
        assert "+4 more" in issue.detail


class TestSingleServiceGate:
    def test_one_service_across_several_cities_warns(self):
        # /{city}/ and /{city}/{service}/ chase the same query; the reference
        # has a single-city exception but no single-service mirror.
        issues = wpl.single_service_gate(
            store.parse_catalog([{"name": "Roof Repair"}]), multi_city=True
        )
        assert len(issues) == 1
        assert issues[0].kind == "single_service_matrix"
        assert issues[0].blocking is False

    def test_a_single_city_business_has_no_matrix_to_warn_about(self):
        assert wpl.single_service_gate(
            store.parse_catalog([{"name": "Roof Repair"}]), multi_city=False
        ) == []

    def test_two_services_are_fine(self):
        assert wpl.single_service_gate(store.parse_catalog(CATALOG), multi_city=True) == []


class TestTemplateCoverage:
    def test_no_page_type_the_template_cannot_render_is_planned_today(self):
        # The two hubs that used to trip this now have routes in the template,
        # so a normal multi-city plan is fully renderable.
        plan = wpl.build_plan(
            site_type="local_business",
            catalog=store.parse_catalog(CATALOG),
            cities=store.parse_cities(CITIES),
        )
        assert [i for i in plan.issues if i.kind == "missing_template"] == []

    def test_an_unrenderable_type_blocks_but_can_be_signed_off(self):
        # The check is kept for the extension page types, which have ratified
        # URLs and no templates. Blocking per PRD §4.4, acknowledgeable because
        # none of §4.4's three recoveries exists until the theme compiler does.
        pages = [wpl.PlannedPage("/roof-repair/cost/", "cost", "Roof repair cost", "trigger")]
        with patch.object(wpl, "UNRENDERABLE_PAGE_TYPES", frozenset({"cost"})):
            [issue] = wpl.template_coverage_gate(pages)
        assert issue.blocking is True
        assert issue.acknowledgeable is True
        assert "cost" in issue.detail

    def test_a_renderable_plan_produces_no_coverage_issue(self):
        pages = [wpl.PlannedPage("/roof-repair/", "service", "Roof Repair", "CORE")]
        with patch.object(wpl, "UNRENDERABLE_PAGE_TYPES", frozenset({"cost"})):
            assert wpl.template_coverage_gate(pages) == []

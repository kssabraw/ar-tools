"""Unit tests for the Website Builder's site-plan inventory.

The rules under test come from the Page Type Reference v3.6 and the module PRD,
and the ones most likely to break silently are the exceptions: the single-city
no-matrix rule, neighborhoods not multiplying the matrix, and the reserved-slug
precedence that lets a CORE utility page occupy a reserved slug while a service
claiming the same one is an error.
"""

from __future__ import annotations

import pytest

from services import website_plan as wp
from services.website_plan import CityEntry, ServiceEntry, ServiceVariation


def svc(name: str, *, brands=(), types=(), **kw) -> ServiceEntry:
    """Build a ServiceEntry; `brands`/`types` are sugar for equipment-brand and
    narrower-type variations, so tests read as intent rather than dataclass."""
    variations = tuple(
        [ServiceVariation(label=b, kind="brand") for b in brands]
        + [ServiceVariation(label=t, kind="type") for t in types]
    )
    if variations:
        kw["variations"] = variations
    return ServiceEntry(name=name, slug=wp.slugify(name), **kw)


def city(name: str, neighborhoods=()) -> CityEntry:
    return CityEntry(
        name=name,
        slug=wp.slugify(name),
        neighborhoods=tuple((n, wp.slugify(n)) for n in neighborhoods),
    )


CATALOG = [svc("Roof Repair", order=10), svc("Gutter Cleaning", order=20)]
CITIES = [city("Overland Park"), city("Lees Summit")]


class TestUrlStructure:
    def test_services_sit_at_root_not_under_a_prefix(self):
        paths = {p.path for p in wp.service_pages(CATALOG)}
        assert "/roof-repair/" in paths
        assert not any(p.startswith("/services/") for p in paths)

    def test_sub_service_nests_under_its_parent(self):
        catalog = CATALOG + [svc("Tile Replacement", parent_slug="roof-repair")]
        pages = {p.path: p.page_type for p in wp.service_pages(catalog)}
        assert pages["/roof-repair/tile-replacement/"] == "sub_service"

    def test_cities_sit_at_root(self):
        paths = {p.path for p in wp.location_pages(CITIES, multi_city=True)}
        assert "/overland-park/" in paths
        assert not any(p.startswith("/locations/") for p in paths)

    def test_matrix_is_location_first(self):
        pages = wp.matrix_pages(CATALOG, CITIES, multi_city=True)
        paths = {p.path for p in pages}
        # Reference §1.1 R1 — the v3.0 order was reversed and is corrected.
        assert "/overland-park/roof-repair/" in paths
        assert "/roof-repair/overland-park/" not in paths

    def test_every_path_has_a_trailing_slash(self):
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=CITIES)
        assert all(p.path.endswith("/") for p in plan.pages)


class TestSingleCityException:
    """The explicit exception in reference §1.2 — easy to lose, expensive to miss."""

    def test_single_city_gets_no_location_pages(self):
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=[city("Anaheim")])
        assert not [p for p in plan.pages if p.page_type == "location"]

    def test_single_city_gets_no_matrix(self):
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=[city("Anaheim")])
        assert plan.matrix_count == 0
        assert not [p for p in plan.pages if p.page_type == "local_landing"]

    def test_single_city_still_gets_service_pages(self):
        # Its service pages geo-target the one city instead.
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=[city("Anaheim")])
        assert len([p for p in plan.pages if p.page_type == "service"]) == 2

    def test_multi_city_gets_the_matrix(self):
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=CITIES)
        assert plan.matrix_count == 4  # 2 services × 2 cities


class TestMatrixScope:
    def test_neighborhoods_do_not_multiply_the_matrix(self):
        # PRD §4.12.3: without this rule 15 cities × 4 neighborhoods × 10
        # services is 600 pages instead of 150.
        cities = [city("Overland Park", ["Deer Creek", "Nall Hills"]), city("Lees Summit")]
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=cities)
        assert plan.matrix_count == 4
        assert len([p for p in plan.pages if p.page_type == "neighborhood"]) == 2

    def test_service_excluded_from_matrix_keeps_its_own_page(self):
        catalog = [svc("Roof Repair", order=10), svc("Chimney Sweep", order=20, include_in_matrix=False)]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        paths = {p.path for p in plan.pages}
        assert "/chimney-sweep/" in paths
        assert "/overland-park/chimney-sweep/" not in paths
        assert plan.matrix_count == 2

    def test_sub_services_are_not_crossed_with_cities(self):
        catalog = CATALOG + [svc("Tile Replacement", parent_slug="roof-repair")]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        assert "/overland-park/tile-replacement/" not in {p.path for p in plan.pages}


class TestSiteTypes:
    def test_lead_gen_gets_the_same_geo_inventory_as_local_business(self):
        # Owner ruling 2026-08-04: lead_gen shares the geo silo and matrix; it
        # differs on identity, schema and facts, not on page structure.
        local = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=CITIES)
        lead = wp.build_plan(site_type="lead_gen", catalog=CATALOG, cities=CITIES)
        assert {p.path for p in local.pages} == {p.path for p in lead.pages}

    def test_informational_gets_no_service_or_location_pages(self):
        plan = wp.build_plan(site_type="informational", catalog=CATALOG, cities=CITIES)
        types = {p.page_type for p in plan.pages}
        assert not types & {"service", "location", "local_landing"}
        assert "blog_archive" in types

    def test_core_pages_use_the_reserved_slugs(self):
        paths = {p.path for p in wp.core_pages("local_business")}
        assert {"/about-us/", "/contact-us/", "/privacy-policy/", "/sitemap/"} <= paths


class TestPlanningErrors:
    def test_service_claiming_a_reserved_root_slug_blocks(self):
        catalog = [svc("Reviews")]  # collides with the reserved /reviews/
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        assert plan.blocked
        assert any(i.kind == "reserved_slug" for i in plan.issues)

    def test_core_utility_page_may_occupy_its_own_reserved_slug(self):
        # Precedence is utilities > services > cities > pillars, so /about-us/
        # being reserved is exactly why the About page may have it.
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=CITIES)
        assert not [i for i in plan.issues if i.kind == "reserved_slug"]

    def test_two_entries_claiming_one_path_blocks(self):
        # A city named for a service produces a genuine collision.
        plan = wp.build_plan(
            site_type="local_business",
            catalog=[svc("Roof Repair")],
            cities=[city("Roof Repair"), city("Lees Summit")],
        )
        assert plan.blocked
        assert any(i.kind == "duplicate_path" for i in plan.issues)

    def test_cost_is_reserved_at_the_second_level(self):
        catalog = [svc("Roof Repair", order=10), svc("Cost", parent_slug="roof-repair")]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        assert any("cost" in i.detail for i in plan.issues if i.kind == "reserved_slug")

    def test_a_clean_plan_is_not_blocked(self):
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=CITIES)
        assert not plan.blocked


class TestScaleGates:
    def test_matrix_over_200_blocks_pending_signoff(self):
        catalog = [svc(f"Service {i}", order=i) for i in range(15)]
        cities = [city(f"City {i}") for i in range(15)]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=cities)
        assert plan.matrix_count == 225
        assert any(i.kind == "matrix_signoff" and i.blocking for i in plan.issues)

    def test_matrix_signoff_is_acknowledgeable_not_a_wall(self):
        # "Blocks until acknowledged" (§4.3, §8.D). Without the distinction, a
        # site with a legitimately large matrix could never be approved and the
        # only way out would be to lie to the planner.
        catalog = [svc(f"Service {i}", order=i) for i in range(15)]
        cities = [city(f"City {i}") for i in range(15)]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=cities)
        [issue] = [i for i in plan.issues if i.kind == "matrix_signoff"]
        assert issue.acknowledgeable is True

    def test_link_budget_blocks_now_that_25_is_ratified(self):
        # Ratified by the owner 2026-08-05, superseding the reference's >40.
        # While the figure was unratified this could only warn.
        catalog = [svc(f"Service {i}", order=i) for i in range(30)]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        issues = [i for i in plan.issues if i.kind == "link_budget"]
        assert issues, "expected a link-budget breach at 30 services per city"
        assert all(i.blocking and i.acknowledgeable for i in issues)

    def test_a_normal_site_is_nowhere_near_the_budget(self):
        # The bar has to sit above every legitimate page or people learn to
        # click through it. The PRD's own worked example — a 12-service city
        # page — must pass.
        catalog = [svc(f"Service {i}", order=i) for i in range(12)]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        assert [i for i in plan.issues if i.kind == "link_budget"] == []

    def test_global_nav_is_not_counted_toward_the_budget(self):
        # Counting the SOP-mandated nav would put every legitimate city page
        # over the bar. The exclusion is half of what the 25 figure ratifies.
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=CITIES)
        # Its two matrix cells only: a 2-city site is below the location-hub
        # threshold, so there is no Areas We Serve page to link to.
        assert plan.links_per_index["/overland-park/"] == 2


class TestLinkCounting:
    """§4.8b's table, which is not the same as 'pages nested under this path'."""

    def test_a_service_page_counts_the_cities_that_offer_it(self):
        # The links a path-prefix count misses entirely: on a 15-city site they
        # are the whole number, and they are what pushes an index over budget.
        cities = [city(f"City {i}") for i in range(15)]
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=cities)
        assert plan.links_per_index["/roof-repair/"] == 15

    def test_a_city_page_counts_services_neighborhoods_and_areas(self):
        cities = [city("Overland Park", neighborhoods=("Nall Hills", "Deer Creek"))]
        cities += [city(f"City {i}") for i in range(5)]  # 6 cities → the hub exists
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=cities)
        # 2 matrix cells + 2 neighborhoods + the Areas We Serve page.
        assert plan.links_per_index["/overland-park/"] == 5

    def test_a_service_excluded_from_the_matrix_links_to_no_cities(self):
        catalog = [svc("Roof Repair", order=10), svc("Gutter Cleaning", order=20,
                                                     include_in_matrix=False)]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        assert plan.links_per_index["/gutter-cleaning/"] == 0

    def test_areas_we_serve_counts_every_city(self):
        cities = [city(f"City {i}") for i in range(9)]
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=cities)
        assert plan.links_per_index["/areas-we-serve/"] == 9

    def test_a_services_index_counts_every_top_level_service(self):
        catalog = [svc(f"Service {i}", order=i) for i in range(10)]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        assert plan.links_per_index["/services/"] == 10

    def test_a_single_city_site_has_no_matrix_links_to_count(self):
        plan = wp.build_plan(
            site_type="local_business", catalog=CATALOG, cities=[city("Overland Park")]
        )
        assert plan.links_per_index["/roof-repair/"] == 0


class TestCoreConditionalHubs:
    """Reference v3.5 note R6 — infrastructure, not optional add-ons."""

    def test_areas_we_serve_auto_triggers_at_six_cities(self):
        # Ratified at 6 by the owner 2026-08-06, settling reference R6's open
        # threshold — and superseding the >= 2 the v3.6 capture adopted.
        cities = [city(f"City {i}") for i in range(6)]
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=cities)
        [page] = [p for p in plan.pages if p.page_type == "areas_we_serve"]
        assert page.is_core_conditional
        assert not page.is_core

    def test_five_cities_is_not_enough(self):
        # A 2-5 city site gets location pages and a matrix but no location hub;
        # those cities are reached from the homepage grid, the matrix pages'
        # structural links, and the HTML sitemap.
        cities = [city(f"City {i}") for i in range(5)]
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=cities)
        assert not [p for p in plan.pages if p.page_type == "areas_we_serve"]
        # The location silo itself is unaffected — only the hub moved.
        assert len([p for p in plan.pages if p.page_type == "location"]) == 5

    def test_a_single_city_site_gets_no_areas_page(self):
        plan = wp.build_plan(
            site_type="local_business", catalog=CATALOG, cities=[city("Anaheim")]
        )
        assert not [p for p in plan.pages if p.page_type == "areas_we_serve"]

    def test_services_index_auto_triggers_above_eight_services(self):
        catalog = [svc(f"Service {i}", order=i) for i in range(9)]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        [page] = [p for p in plan.pages if p.page_type == "services_index"]
        assert page.is_core_conditional

    def test_eight_services_is_not_enough(self):
        # Building it anyway adds an unnecessary hierarchy layer; the services
        # fit in the nav.
        catalog = [svc(f"Service {i}", order=i) for i in range(8)]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        assert not [p for p in plan.pages if p.page_type == "services_index"]

    def test_hubs_sit_at_tier_4_but_are_still_included(self):
        # Tier 4 is "hubs once children exist". Inclusion is by CORE-conditional
        # trigger and is NOT subject to Q12's "propose Tiers 1-3 by default" —
        # a future tier filter must not drop them.
        cities = [city(f"City {i}") for i in range(6)]
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=cities)
        [page] = [p for p in plan.pages if p.page_type == "areas_we_serve"]
        assert page.tier == 4

    def test_an_ordinary_triggered_page_is_neither_core_nor_core_conditional(self):
        plan = wp.build_plan(
            site_type="local_business",
            catalog=CATALOG,
            cities=[city("Overland Park", ["Deer Creek"]), city("Lees Summit")],
        )
        [hood] = [p for p in plan.pages if p.page_type == "neighborhood"]
        assert not hood.is_core and not hood.is_core_conditional


class TestTriggers:
    def test_every_page_records_why_it_was_proposed(self):
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=CITIES)
        assert all(p.trigger for p in plan.pages)

    def test_services_index_triggers_only_on_nav_overflow(self):
        small = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=CITIES)
        assert "/services/" not in {p.path for p in small.pages}

        catalog = [svc(f"Service {i}", order=i) for i in range(10)]
        big = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        index = [p for p in big.pages if p.page_type == "services_index"]
        # The trigger records the threshold it cleared, so a reviewer sees why.
        assert index and "> 8" in index[0].trigger

    def test_areas_we_serve_triggers_only_at_the_ratified_city_count(self):
        below = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=CITIES)
        at = wp.build_plan(
            site_type="local_business", catalog=CATALOG,
            cities=[city(f"City {i}") for i in range(wp.AREAS_WE_SERVE_TRIGGER)],
        )
        assert "/areas-we-serve/" not in {p.path for p in below.pages}
        assert "/areas-we-serve/" in {p.path for p in at.pages}

    def test_neighborhood_trigger_names_the_entity_test(self):
        cities = [city("Overland Park", ["Deer Creek"]), city("Lees Summit")]
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=cities)
        hood = next(p for p in plan.pages if p.page_type == "neighborhood")
        assert "entity test" in hood.trigger


class TestSiloDiscovery:
    def test_lifts_location_names_only(self):
        per_silo = [
            {"silo": "Neighborhoods", "pages": [
                {"keyword": "roof repair overland park", "location_name": "Overland Park"},
                {"keyword": "roof repair lees summit", "location_name": "Lees Summit"},
            ]},
            # A service silo carries no location_name and contributes no cities:
            # a keyword is not a page type.
            {"silo": "Emergency", "pages": [{"keyword": "emergency roof repair"}]},
        ]
        cities = wp.cities_from_silo_plan(per_silo)
        assert [c.name for c in cities] == ["Lees Summit", "Overland Park"]
        assert cities[0].slug == "lees-summit"

    def test_empty_input_is_safe(self):
        assert wp.cities_from_silo_plan([]) == []


# --------------------------------------------------------------------------
# Content & Authority family (reference §5.3) — informational sites
# --------------------------------------------------------------------------


def _content_plan(post_specs, *, pillar="Roof Care", slug="roof-care"):
    """post_specs: list of (title, format). Keyword defaults to the title."""
    return {
        "pillars": [
            {
                "title": pillar,
                "slug": slug,
                "posts": [
                    {"title": t, "format": f, "keyword": t.lower()} for t, f in post_specs
                ],
            }
        ]
    }


class TestInformationalPlan:
    def test_posts_route_into_the_flat_blog_silo(self):
        cp = _content_plan([("Roof coatings", "informational_cluster")])
        plan = wp.build_plan(site_type="informational", catalog=[], cities=[], content_plan=cp)
        posts = [p for p in plan.pages if p.page_type == "post"]
        assert [p.path for p in posts] == ["/blog/roof-coatings/"]

    def test_geo_pages_are_never_planned_for_an_informational_site(self):
        cp = _content_plan([("A", "informational_cluster")])
        plan = wp.build_plan(site_type="informational", catalog=CATALOG, cities=CITIES, content_plan=cp)
        assert not any(
            p.page_type in {"service", "location", "local_landing"} for p in plan.pages
        )

    def test_pillar_page_is_emitted_at_five_evergreen_posts(self):
        cp = _content_plan([(f"Post {i}", "informational_cluster") for i in range(5)])
        plan = wp.build_plan(site_type="informational", catalog=[], cities=[], content_plan=cp)
        pillars = [p for p in plan.pages if p.page_type == "pillar"]
        assert [p.path for p in pillars] == ["/roof-care/"]

    def test_pillar_is_not_emitted_below_the_threshold(self):
        cp = _content_plan([(f"Post {i}", "informational_cluster") for i in range(4)])
        plan = wp.build_plan(site_type="informational", catalog=[], cities=[], content_plan=cp)
        assert not any(p.page_type == "pillar" for p in plan.pages)

    def test_news_posts_do_not_count_toward_the_pillar_threshold(self):
        # Four evergreen + two news = six posts but only four evergreen, so no
        # pillar (reference §5.3: news is excluded from pillar-cluster math).
        specs = [(f"Ever {i}", "informational_cluster") for i in range(4)]
        specs += [("News A", "news"), ("News B", "news")]
        cp = _content_plan(specs)
        plan = wp.build_plan(site_type="informational", catalog=[], cities=[], content_plan=cp)
        assert len([p for p in plan.pages if p.page_type == "post"]) == 6
        assert not any(p.page_type == "pillar" for p in plan.pages)

    def test_unknown_format_falls_back_to_the_default(self):
        pillars = wp.content_plan_pillars(_content_plan([("X", "bogus")]))
        assert pillars[0].posts[0].format == wp.DEFAULT_POST_FORMAT

    def test_duplicate_post_slugs_are_dropped_first_wins(self):
        cp = {
            "pillars": [
                {"title": "P", "slug": "p", "posts": [
                    {"title": "Same Title", "format": "listicle"},
                    {"title": "Same Title", "format": "comparison"},
                ]},
            ]
        }
        pillars = wp.content_plan_pillars(cp)
        assert len(pillars[0].posts) == 1
        assert pillars[0].posts[0].format == "listicle"

    def test_post_generation_uses_the_run_engine_with_a_brief(self):
        cp = _content_plan([("Roof coatings", "listicle")])
        pillars = wp.content_plan_pillars(cp)
        posts = {wp._path("blog", p.slug): p for pillar in pillars for p in pillar.posts}
        page = next(p for p in wp.informational_pages(pillars) if p.page_type == "post")
        inputs = wp.generation_inputs(page, services={}, cities={}, posts=posts, pillars={})
        assert inputs["engine"] == "run"
        assert inputs["content_type"] == "blog_post"
        assert inputs["keyword"] == "roof coatings"
        assert "listicle" in inputs["notes"]

    def test_pillar_generation_uses_the_run_engine(self):
        cp = _content_plan([(f"Post {i}", "informational_cluster") for i in range(5)])
        pillars = wp.content_plan_pillars(cp)
        pillars_map = {wp._path(pl.slug): pl for pl in pillars}
        page = next(p for p in wp.informational_pages(pillars) if p.page_type == "pillar")
        inputs = wp.generation_inputs(page, services={}, cities={}, posts={}, pillars=pillars_map)
        assert inputs["engine"] == "run"
        assert "authoritative parent" in inputs["notes"].lower()

    def test_post_frontmatter_declares_format_and_silo(self):
        cp = _content_plan([("Roof coatings", "comparison")])
        pillars = wp.content_plan_pillars(cp)
        posts = {wp._path("blog", p.slug): p for pillar in pillars for p in pillar.posts}
        pillars_map = {wp._path(pl.slug): pl for pl in pillars}
        page = next(p for p in wp.informational_pages(pillars) if p.page_type == "post")
        fm = wp.frontmatter_extra(page, services={}, cities={}, posts=posts, pillars=pillars_map)
        assert fm["format"] == "comparison"
        assert fm["silo"] == "roof-care"
        assert fm["category"] == "Roof Care"

    def test_pillar_links_count_its_cluster_posts_for_the_link_budget(self):
        cp = _content_plan([(f"Post {i}", "informational_cluster") for i in range(5)])
        plan = wp.build_plan(site_type="informational", catalog=[], cities=[], content_plan=cp)
        assert plan.links_per_index["/roof-care/"] == 5

    def test_a_pillar_slug_colliding_with_a_reserved_root_is_a_planning_error(self):
        cp = _content_plan(
            [(f"P{i}", "informational_cluster") for i in range(5)], pillar="Blog", slug="blog"
        )
        plan = wp.build_plan(site_type="informational", catalog=[], cities=[], content_plan=cp)
        assert any(i.kind == "reserved_slug" and i.blocking for i in plan.issues)


class TestLocalSiteBlog:
    def test_a_local_site_with_a_content_plan_gets_both_geo_and_blog(self):
        # Reference §5.3: blog posts are cross-family, so a local business's blog
        # is planned from its content plan ON TOP of its service/location pages.
        cp = _content_plan([("Roof care tips", "listicle")], pillar="Roof Care", slug="roof-care")
        plan = wp.build_plan(
            site_type="local_business", catalog=CATALOG, cities=CITIES, content_plan=cp
        )
        types = {p.page_type for p in plan.pages}
        assert {"service", "location", "local_landing"} <= types  # geo half
        assert "post" in types                                     # blog half
        assert "/blog/roof-care-tips/" in {p.path for p in plan.pages}

    def test_a_local_site_without_a_content_plan_is_unchanged(self):
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=CITIES)
        assert not any(p.page_type in {"post", "pillar"} for p in plan.pages)

    def test_a_local_blog_cluster_of_five_earns_a_pillar(self):
        cp = _content_plan(
            [(f"Post {i}", "informational_cluster") for i in range(5)],
            pillar="Roofing Guide", slug="roofing-guide",
        )
        plan = wp.build_plan(
            site_type="local_business", catalog=CATALOG, cities=CITIES, content_plan=cp
        )
        assert "/roofing-guide/" in {p.path for p in plan.pages if p.page_type == "pillar"}

    def test_a_pillar_colliding_with_a_service_slug_is_a_planning_error(self):
        # The pillar's top-level slug shares the local root namespace with
        # services, so a clash is a duplicate_path the reviewer must resolve.
        cp = _content_plan(
            [(f"P{i}", "informational_cluster") for i in range(5)],
            pillar="Roof Repair", slug="roof-repair",
        )
        catalog = [svc("Roof Repair", order=10)]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES, content_plan=cp)
        assert any(i.kind == "duplicate_path" and i.blocking for i in plan.issues)


class TestBrandServiceEngine:
    """Brand × service pages: /{service}/{brand}/ generated by the nlp engine."""

    def test_emits_one_page_per_top_level_service_brand(self):
        catalog = [svc("AC Repair", order=10, brands=("Carrier", "Trane"))]
        pages = wp.brand_service_pages(catalog)
        assert {p.path for p in pages} == {"/ac-repair/carrier/", "/ac-repair/trane/"}
        assert all(p.page_type == "brand_service" for p in pages)
        carrier = next(p for p in pages if p.path == "/ac-repair/carrier/")
        assert carrier.title == "Carrier AC Repair"
        assert carrier.tier == 4
        assert "Carrier" in carrier.trigger

    def test_a_service_without_brands_emits_none(self):
        assert wp.brand_service_pages([svc("AC Repair")]) == []

    def test_sub_services_never_take_brands(self):
        catalog = [
            svc("AC Repair", order=10),
            svc("Coil Cleaning", parent_slug="ac-repair", brands=("Carrier",)),
        ]
        assert wp.brand_service_pages(catalog) == []

    def test_duplicate_brand_slugs_are_deduped(self):
        catalog = [svc("AC Repair", brands=("Carrier", "carrier", "  Carrier  "))]
        assert len(wp.brand_service_pages(catalog)) == 1

    def test_generation_targets_the_brand_service_keyword_not_geo(self):
        catalog = [svc("AC Repair", brands=("Carrier",))]
        page = wp.brand_service_pages(catalog)[0]
        services = {s.slug: s for s in catalog}
        inputs = wp.generation_inputs(
            page, services=services, cities={}, primary_city="Anaheim"
        )
        assert inputs["engine"] == "nlp"
        assert inputs["keyword"] == "Carrier AC Repair"
        # Geo-agnostic like a service page: the city only scopes the SERP.
        assert inputs["location"] == "Anaheim"

    def test_frontmatter_takes_the_service_from_the_first_segment(self):
        catalog = [svc("AC Repair", teaser="Fast fixes", order=10, brands=("Carrier",))]
        page = wp.brand_service_pages(catalog)[0]
        services = {s.slug: s for s in catalog}
        fm = wp.frontmatter_extra(page, services=services, cities={})
        # The service is segs[0] (the brand is segs[-1]); teaser/parent come from it.
        assert fm["parentService"] == "ac-repair"
        assert fm["teaser"] == "Fast fixes"
        assert fm["order"] == 10

    def test_geo_site_plan_includes_brand_pages(self):
        catalog = [svc("AC Repair", order=10, brands=("Carrier",))]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        assert "/ac-repair/carrier/" in {p.path for p in plan.pages}

    def test_informational_site_has_no_brand_pages(self):
        catalog = [svc("AC Repair", brands=("Carrier",))]
        plan = wp.build_plan(site_type="informational", catalog=catalog, cities=[])
        assert not any(p.page_type == "brand_service" for p in plan.pages)

    def test_over_200_variation_pages_blocks_pending_signoff(self):
        brands = tuple(f"Brand{i}" for i in range(201))
        catalog = [svc("AC Repair", brands=brands)]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        gate = next((i for i in plan.issues if i.kind == "variation_scale"), None)
        assert gate is not None and gate.blocking and gate.acknowledgeable

    def test_brand_service_is_a_generable_page_type(self):
        assert "brand_service" in wp.NLP_PAGE_TYPES


class TestServiceVariations:
    """The generalized variation matrix: a 'type' modifier becomes a sub-service
    (Oak Tree Removal), a 'brand' modifier a brand × service page."""

    def test_type_variation_becomes_a_sub_service_with_a_clean_title(self):
        catalog = [svc("Tree Removal", types=("Oak Trees",))]
        pages = wp.service_variation_pages(catalog)
        assert len(pages) == 1
        page = pages[0]
        assert page.path == "/tree-removal/oak-trees/"
        assert page.page_type == "sub_service"
        # The label stands alone — no "Oak Trees Tree Removal" doubling.
        assert page.title == "Oak Trees"
        assert page.tier == 2

    def test_brand_and_type_variations_coexist_on_one_service(self):
        catalog = [svc("AC Repair", brands=("Carrier",), types=("Ductless Mini Split",))]
        pages = wp.service_variation_pages(catalog)
        kinds = {p.path: p.page_type for p in pages}
        assert kinds["/ac-repair/carrier/"] == "brand_service"
        assert kinds["/ac-repair/ductless-mini-split/"] == "sub_service"

    def test_a_fully_named_type_label_is_not_doubled(self):
        # The label already carries the service name, so the keyword stays clean.
        catalog = [svc("Tree Removal", types=("Oak Tree Removal",))]
        page = wp.service_variation_pages(catalog)[0]
        inputs = wp.generation_inputs(page, services={"tree-removal": catalog[0]}, cities={}, primary_city="Dallas")
        assert inputs["engine"] == "nlp"
        assert inputs["keyword"] == "Oak Tree Removal"
        assert inputs["location"] == "Dallas"

    def test_a_bare_type_label_is_scoped_by_the_parent_service(self):
        # A bare label ("Emergency") is thin and collision-prone on its own, so
        # the keyword is scoped by the parent service — while the title stays bare.
        catalog = [svc("AC Repair", types=("Emergency",))]
        page = wp.service_variation_pages(catalog)[0]
        assert page.title == "Emergency"
        inputs = wp.generation_inputs(page, services={"ac-repair": catalog[0]}, cities={}, primary_city="Dallas")
        assert inputs["keyword"] == "Emergency AC Repair"

    def test_same_bare_label_on_two_services_yields_distinct_keywords(self):
        # The regression this guards: two "Emergency" variations must not both
        # generate keyword "Emergency" + the same city (near-identical pages).
        catalog = [svc("AC Repair", types=("Emergency",)), svc("Heating Repair", types=("Emergency",))]
        by_slug = {s.slug: s for s in catalog}
        pages = wp.service_variation_pages(catalog)
        keywords = {
            wp.generation_inputs(p, services=by_slug, cities={}, primary_city="Dallas")["keyword"]
            for p in pages
        }
        assert keywords == {"Emergency AC Repair", "Emergency Heating Repair"}

    def test_a_real_catalog_sub_service_keeps_its_own_name(self):
        # The disambiguation only touches synthetic variations; a hand-added
        # sub-service (a catalog entry) still keys on its own name, unscoped.
        catalog = [svc("AC Repair", order=10), svc("Coil Cleaning", parent_slug="ac-repair")]
        by_slug = {s.slug: s for s in catalog}
        sub = wp.PlannedPage("/ac-repair/coil-cleaning/", "sub_service", "Coil Cleaning", "sub-service", tier=2)
        inputs = wp.generation_inputs(sub, services=by_slug, cities={}, primary_city="Dallas")
        assert inputs["keyword"] == "Coil Cleaning"

    def test_type_variation_frontmatter_nests_under_the_service(self):
        catalog = [svc("Tree Removal", types=("Oak Trees",))]
        page = wp.service_variation_pages(catalog)[0]
        fm = wp.frontmatter_extra(page, services={"tree-removal": catalog[0]}, cities={})
        assert fm["parentService"] == "tree-removal"

    def test_brands_property_reads_only_brand_variations(self):
        s = svc("AC Repair", brands=("Carrier",), types=("Mini Split",))
        assert s.brands == ("Carrier",)

    def test_geo_plan_includes_type_variation_pages(self):
        catalog = [svc("Tree Removal", order=10, types=("Oak Trees", "Palm Trees"))]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        paths = {p.path for p in plan.pages}
        assert "/tree-removal/oak-trees/" in paths
        assert "/tree-removal/palm-trees/" in paths


class TestHyperLocalEngine:
    """Hyper-specific local landing: /{city}/{service}/{subservice}/, nlp engine."""

    def test_generation_targets_the_page_need_in_the_city(self):
        page = wp.PlannedPage(
            "/anaheim/ac-repair/emergency-ac/",
            "hyper_local",
            "Emergency AC Repair Anaheim",
            "escalation",
        )
        cities = {"anaheim": city("Anaheim")}
        inputs = wp.generation_inputs(page, services={}, cities=cities)
        assert inputs["engine"] == "nlp"
        assert inputs["keyword"] == "Emergency AC Repair Anaheim"
        assert inputs["location"] == "Anaheim"

    def test_frontmatter_carries_the_local_landing_axes(self):
        page = wp.PlannedPage(
            "/anaheim/ac-repair/emergency-ac/",
            "hyper_local",
            "Emergency AC Repair Anaheim",
            "escalation",
        )
        catalog = {"ac-repair": svc("AC Repair")}
        cities = {"anaheim": city("Anaheim")}
        fm = wp.frontmatter_extra(page, services=catalog, cities=cities)
        assert fm["citySlug"] == "anaheim"
        assert fm["serviceSlug"] == "ac-repair"
        assert fm["locationName"] == "Anaheim"
        assert fm["serviceName"] == "AC Repair"

    def test_hyper_local_is_a_generable_page_type(self):
        assert "hyper_local" in wp.NLP_PAGE_TYPES

    def test_hyper_local_is_not_auto_emitted_by_the_planner(self):
        # Escalation-only (SOP: "never bulk-generate"); the engine exists but the
        # planner proposes none on its own.
        catalog = [svc("AC Repair", brands=("Carrier",))]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        assert not any(p.page_type == "hyper_local" for p in plan.pages)

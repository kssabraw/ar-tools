"""Unit tests for the Website Builder's site-plan inventory.

The rules under test come from the Page Type Reference v3.4 and the module PRD,
and the ones most likely to break silently are the exceptions: the single-city
no-matrix rule, neighborhoods not multiplying the matrix, and the reserved-slug
precedence that lets a CORE utility page occupy a reserved slug while a service
claiming the same one is an error.
"""

from __future__ import annotations

import pytest

from services import website_plan as wp
from services.website_plan import CityEntry, ServiceEntry


def svc(name: str, **kw) -> ServiceEntry:
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

    def test_links_advisory_never_blocks(self):
        # The figure is unratified and was ruled too high; a number that blocks
        # work needs ratifying first, so this warns and approval proceeds.
        catalog = [svc(f"Service {i}", order=i) for i in range(30)]
        plan = wp.build_plan(site_type="local_business", catalog=catalog, cities=CITIES)
        advisories = [i for i in plan.issues if i.kind == "links_advisory"]
        assert advisories, "expected an advisory at 30 services per city"
        assert all(not i.blocking for i in advisories)

    def test_global_nav_is_not_counted_toward_the_advisory(self):
        # Counting the SOP-mandated nav would put every legitimate city page
        # over the bar and train people to ignore the warning.
        plan = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=CITIES)
        assert plan.links_per_index["/overland-park/"] == 2  # its two matrix cells only


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
        assert index and "nav overflow" in index[0].trigger

    def test_areas_we_serve_triggers_on_multi_city_only(self):
        single = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=[city("Anaheim")])
        multi = wp.build_plan(site_type="local_business", catalog=CATALOG, cities=CITIES)
        assert "/areas-we-serve/" not in {p.path for p in single.pages}
        assert "/areas-we-serve/" in {p.path for p in multi.pages}

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

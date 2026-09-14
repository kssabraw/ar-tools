"""Unit tests for the Coverage Audit service layer (Phase 1) — mocked externals.

Covers the impure-but-decision-heavy helpers: service-axis derivation (planner
merge + provenance + fallbacks), the location-axis geocoding-unavailable degrade,
the demand-fetch reservation/idempotency, and the gap-keyword collector. Network,
LLM and Supabase calls are all monkeypatched.
"""

import asyncio

import pytest

from services import coverage_audit_service as svc


# --- _derive_service_axis (planner merge + provenance) ------------------------
def test_derive_service_axis_merges_planner_and_site(monkeypatch):
    monkeypatch.setattr(
        svc, "_plan_service_axis", lambda site, gbp, name: (["Roof Restoration", "Roof Repair"], None)
    )
    client = {"name": "Acme", "gbp": {"gbp_category": "Roofing Contractor"}}
    classified = {
        "service_only": [{"url": "https://x.com/roof-restoration/"}],
        "service_location": [{"url": "https://x.com/gutter-cleaning-melbourne/"}],
    }
    axis, prov = svc._derive_service_axis(client, classified, ["Melbourne"])
    labels = [a["label"] for a in axis]
    # Planner order first, then any site service the planner didn't emit.
    assert labels == ["Roof Restoration", "Roof Repair", "Gutter Cleaning"]
    by_label = {a["label"]: a["sources"] for a in axis}
    assert "planner" in by_label["Roof Restoration"]
    assert "site" in by_label["Roof Restoration"]      # also observed on the site
    assert by_label["Roof Repair"] == ["planner"]      # planner-only
    assert by_label["Gutter Cleaning"] == ["site"]     # site-only (planner missed it)
    assert prov["confirmed"] is False
    assert prov["planner_used"] is True


def test_derive_service_axis_falls_back_to_site_when_planner_unavailable(monkeypatch):
    monkeypatch.setattr(
        svc, "_plan_service_axis", lambda site, gbp, name: ([], "planner off")
    )
    client = {"name": "Acme", "gbp": {}}
    classified = {"service_only": [{"url": "https://x.com/roof-restoration/"}]}
    axis, prov = svc._derive_service_axis(client, classified, [])
    assert [a["label"] for a in axis] == ["Roof Restoration"]
    assert "planner off" in prov["notes"]


def test_derive_service_axis_last_resort_raw_gbp_categories(monkeypatch):
    monkeypatch.setattr(svc, "_plan_service_axis", lambda site, gbp, name: ([], "planner off"))
    client = {"name": "Acme", "gbp": {"gbp_category": "Roofing Contractor", "gbp_categories": ["Gutter service"]}}
    axis, prov = svc._derive_service_axis(client, {}, [])
    # No site pages + no planner → raw GBP categories offered for editing.
    assert [a["label"] for a in axis] == ["Roofing Contractor", "Gutter service"]
    assert any("raw GBP categories" in n for n in prov["notes"])


def test_gbp_categories_dedupes_primary_and_list():
    client = {"gbp": {"gbp_category": "Roofing Contractor", "gbp_categories": ["Roofing Contractor", "Gutter Service"]}}
    assert svc._gbp_categories(client) == ["Roofing Contractor", "Gutter Service"]


# --- _resolve_location_axis (geocoding-unavailable degrade) --------------------
def test_location_axis_degrades_visibly_without_maps_key(monkeypatch):
    monkeypatch.setattr(svc.settings, "google_maps_api_key", "", raising=False)
    client = {"business_location": "Melbourne,Victoria,Australia"}
    axis, prov = asyncio.run(svc._resolve_location_axis(client, "Melbourne,Victoria,Australia", 2036))
    assert [r["name"] for r in axis] == ["Melbourne"]
    assert axis[0]["source"] == "seed"
    assert any("Geocoding unavailable" in n for n in prov["notes"])


def test_location_axis_no_seed_city_notes(monkeypatch):
    monkeypatch.setattr(svc.settings, "google_maps_api_key", "", raising=False)
    axis, prov = asyncio.run(svc._resolve_location_axis({}, "", None))
    assert axis == []
    assert any("No business location" in n for n in prov["notes"])


def test_location_axis_merges_target_cities(monkeypatch):
    monkeypatch.setattr(svc.settings, "google_maps_api_key", "key", raising=False)
    monkeypatch.setattr(svc, "get_supabase", lambda: object())

    async def _fake_resolve(client, seed_location, code, sb):
        return ([{"name": "Geelong", "source": "nearby"}, {"name": "Ballarat", "source": "manual"}], ["Nearby note"])

    monkeypatch.setattr(svc.target_cities, "resolve_target_cities", _fake_resolve)
    axis, prov = asyncio.run(
        svc._resolve_location_axis(
            {"business_location": "Melbourne,Victoria,Australia"}, "Melbourne,Victoria,Australia", 2036
        )
    )
    assert [r["name"] for r in axis] == ["Melbourne", "Geelong", "Ballarat"]
    assert "Nearby note" in prov["notes"]


# --- _collect_keywords --------------------------------------------------------
def test_collect_keywords_dedupes_across_sections():
    diff = {
        "missing_services": [{"keyword": "Roofing"}],
        "missing_locations": [{"keyword": "Roofing Geelong"}],
        "missing_cells": [{"keyword": "Roofing Geelong"}, {"keyword": "Gutters Geelong"}, {"keyword": ""}],
    }
    kws = svc._collect_keywords(diff)
    assert kws == ["Roofing", "Roofing Geelong", "Gutters Geelong"]


# --- _fetch_demand (reserve before spend; cache-idempotent) --------------------
def test_fetch_demand_reserves_then_refreshes(monkeypatch):
    monkeypatch.setattr(svc, "get_supabase", lambda: object())
    monkeypatch.setattr(svc.keyword_market, "market_eligible", lambda k: True)

    calls = {"reserved": None, "refreshed": []}

    def _reserve(n):
        calls["reserved"] = n

    # First cache read is cold; the refresh warms it so the post-refresh read hits.
    state = {"warm": False}

    async def _refresh(sb, kws, code):
        calls["refreshed"] = kws
        state["warm"] = True
        return {"status": "ok", "fetched": len(kws)}

    def _cached(sb, kws, code):
        if state["warm"]:
            return {k.lower(): {"search_volume": 100, "cpc": 2.0, "competition": "LOW"} for k in kws}
        return {}

    monkeypatch.setattr(svc, "reserve_budget", _reserve)
    monkeypatch.setattr(svc.keyword_market, "refresh_keywords", _refresh)
    monkeypatch.setattr(svc.keyword_market, "fetch_cached_market", _cached)
    monkeypatch.setattr(svc.keyword_market, "stale_keywords", lambda kws, cached, cutoff: [k for k in kws if k.lower() not in cached])

    market, available, notes = asyncio.run(
        svc._fetch_demand(["Roofing Geelong", "Gutters Geelong"], 2036)
    )
    assert calls["reserved"] == 1  # ceil(2 / 1000)
    assert set(calls["refreshed"]) == {"Roofing Geelong", "Gutters Geelong"}
    assert available is True
    assert market["roofing geelong"]["search_volume"] == 100


def test_fetch_demand_idempotent_when_cache_warm(monkeypatch):
    """A reaper requeue finds every keyword already cached → nothing is re-billed."""
    monkeypatch.setattr(svc, "get_supabase", lambda: object())
    monkeypatch.setattr(svc.keyword_market, "market_eligible", lambda k: True)
    reserved = {"n": 0}
    monkeypatch.setattr(svc, "reserve_budget", lambda n: reserved.__setitem__("n", reserved["n"] + n))

    async def _refresh(sb, kws, code):  # should never be called
        raise AssertionError("refresh must not run when cache is warm")

    monkeypatch.setattr(svc.keyword_market, "refresh_keywords", _refresh)
    monkeypatch.setattr(
        svc.keyword_market, "fetch_cached_market",
        lambda sb, kws, code: {k.lower(): {"search_volume": 50, "cpc": 1.0, "competition": "LOW"} for k in kws},
    )
    monkeypatch.setattr(svc.keyword_market, "stale_keywords", lambda kws, cached, cutoff: [])

    market, available, notes = asyncio.run(svc._fetch_demand(["Roofing Geelong"], 2036))
    assert reserved["n"] == 0
    assert available is True
    assert market["roofing geelong"]["search_volume"] == 50


def test_fetch_demand_no_location_code_unavailable():
    market, available, notes = asyncio.run(svc._fetch_demand(["Roofing"], None))
    assert market == {}
    assert available is False
    assert any("demand data unavailable" in n.lower() for n in notes)


def test_fetch_demand_budget_exhausted_uses_cache(monkeypatch):
    monkeypatch.setattr(svc, "get_supabase", lambda: object())
    monkeypatch.setattr(svc.keyword_market, "market_eligible", lambda k: True)

    def _reserve(n):
        raise svc.BudgetExceeded("cap reached")

    monkeypatch.setattr(svc, "reserve_budget", _reserve)
    monkeypatch.setattr(
        svc.keyword_market, "fetch_cached_market",
        lambda sb, kws, code: {"roofing geelong": {"search_volume": 10, "cpc": 1.0, "competition": "LOW"}},
    )
    monkeypatch.setattr(svc.keyword_market, "stale_keywords", lambda kws, cached, cutoff: list(kws))

    market, available, notes = asyncio.run(svc._fetch_demand(["Roofing Geelong"], 2036))
    assert available is True  # cached row still usable
    assert any("budget exhausted" in n.lower() for n in notes)


# --- _derive_subservice_axis (Tier 2 — planner expansion + city-strip merge) ---
def _fake_llm():
    """A truthy sentinel standing in for the Sonnet client (never called directly —
    _generate_service_pages is monkeypatched)."""
    return object()


def test_derive_subservice_axis_expands_and_strips_city(monkeypatch):
    monkeypatch.setattr(svc.local_seo_silo, "_service_llm", _fake_llm)
    monkeypatch.setattr(svc.icp_service, "resolve_icp_text", lambda client: "")

    # The planner emits PER-CITY pages ("<modifier> <service> <city>"); the reused
    # service_labels_from_pages strips the representative city. Return realistic silos.
    def _gen(service, city, llm, icp_block=""):
        assert city == "Melbourne"  # representative city threaded through
        return [
            {
                "silo": "Core",
                "pages": [
                    {"keyword": f"{service} {city}", "supporting_keywords": []},
                    {"keyword": f"Emergency {service} {city}", "supporting_keywords": []},
                ],
            }
        ]

    monkeypatch.setattr(svc.local_seo_silo, "_generate_service_pages", _gen)

    main_axis = [{"label": "Roof Restoration"}, {"label": "Gutter Cleaning"}]
    axis, prov = asyncio.run(svc._derive_subservice_axis({}, main_axis, "Melbourne"))
    labels = [e["label"] for e in axis]
    # City stripped from every page; merged across both main services, deduped.
    assert labels == [
        "Roof Restoration",
        "Emergency Roof Restoration",
        "Gutter Cleaning",
        "Emergency Gutter Cleaning",
    ]
    assert prov["kind"] == "subservice"
    assert prov["planned_services"] == ["Roof Restoration", "Gutter Cleaning"]
    assert prov["failed_services"] == []
    # Each subservice is tagged with its parent main service (for the review screen).
    assert {e["label"]: e["service"] for e in axis}["Emergency Gutter Cleaning"] == "Gutter Cleaning"


def test_derive_subservice_axis_no_llm_degrades(monkeypatch):
    monkeypatch.setattr(svc.local_seo_silo, "_service_llm", lambda: None)
    axis, prov = asyncio.run(svc._derive_subservice_axis({}, [{"label": "Roofing"}], "Melbourne"))
    assert axis == []
    assert any("planner skipped" in n.lower() for n in prov["notes"])


def test_derive_subservice_axis_no_main_services_degrades():
    axis, prov = asyncio.run(svc._derive_subservice_axis({}, [], "Melbourne"))
    assert axis == []
    assert any("no main services" in n.lower() for n in prov["notes"])


def test_derive_subservice_axis_one_service_failing_is_skipped(monkeypatch):
    monkeypatch.setattr(svc.local_seo_silo, "_service_llm", _fake_llm)
    monkeypatch.setattr(svc.icp_service, "resolve_icp_text", lambda client: "")

    def _gen(service, city, llm, icp_block=""):
        if service == "Broken Service":
            raise RuntimeError("planner blew up")
        return [{"silo": "Core", "pages": [{"keyword": f"{service} {city}", "supporting_keywords": []}]}]

    monkeypatch.setattr(svc.local_seo_silo, "_generate_service_pages", _gen)

    main_axis = [{"label": "Roofing"}, {"label": "Broken Service"}]
    axis, prov = asyncio.run(svc._derive_subservice_axis({}, main_axis, "Melbourne"))
    # The good service still produces subservices; the failing one is recorded.
    assert [e["label"] for e in axis] == ["Roofing"]
    assert prov["planned_services"] == ["Roofing"]
    assert prov["failed_services"] == ["Broken Service"]
    assert any("could not expand" in n.lower() for n in prov["notes"])


def test_derive_subservice_axis_icp_failure_is_non_fatal(monkeypatch):
    monkeypatch.setattr(svc.local_seo_silo, "_service_llm", _fake_llm)

    def _boom(client):
        raise RuntimeError("icp read failed")

    monkeypatch.setattr(svc.icp_service, "resolve_icp_text", _boom)
    monkeypatch.setattr(
        svc.local_seo_silo,
        "_generate_service_pages",
        lambda service, city, llm, icp_block="": [
            {"silo": "Core", "pages": [{"keyword": f"{service} {city}", "supporting_keywords": []}]}
        ],
    )
    axis, prov = asyncio.run(svc._derive_subservice_axis({}, [{"label": "Roofing"}], "Melbourne"))
    assert [e["label"] for e in axis] == ["Roofing"]  # ICP failure degraded silently


def test_tier_2_is_supported():
    assert 2 in svc.SUPPORTED_TIERS


def test_tier_3_is_supported():
    assert 3 in svc.SUPPORTED_TIERS


def test_tier_4_is_supported():
    assert 4 in svc.SUPPORTED_TIERS


# --- run_coverage_audit_tier (Tier 3 — CDP location axis wiring) ----------------
class _FakeQuery:
    """Minimal chainable Supabase query stub that records the coverage_audits update."""

    def __init__(self, store, table):
        self._store = store
        self._table = table
        self._payload = None

    def update(self, row):
        self._payload = row
        return self

    def insert(self, row):
        self._payload = row
        return self

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._table == "coverage_audits" and self._payload is not None:
            self._store["audit_update"] = self._payload

        class _R:
            data = []

        return _R()


class _FakeSupabase:
    def __init__(self, store):
        self._store = store

    def table(self, name):
        return _FakeQuery(self._store, name)


def test_run_tier_3_uses_cdp_location_axis_and_keeps_location_rows(monkeypatch):
    """Tier 3 swaps the location axis to the census CDP list, uses the MAIN-service
    axis (Tier-1 path), keeps the location-hub rows, and threads cities into the
    place vocabulary. Everything external is mocked."""
    store: dict = {}
    monkeypatch.setattr(svc, "get_supabase", lambda: _FakeSupabase(store))
    monkeypatch.setattr(
        svc.local_seo_silo, "_get_client",
        lambda cid: {"name": "Acme Roofing", "business_location": "Metropolis,New York,United States",
                     "gbp": {"website": "https://acme.example"}},
    )
    monkeypatch.setattr(svc, "location_code_for", lambda client: 2840)

    # CDP location axis + city place-vocab (census_cdp is mocked wholesale here).
    async def _fake_cdp(client, seed_location, code, sb):
        return (
            [{"name": "Harrison", "source": "census_cdp"}, {"name": "Kearny", "source": "census_cdp"}],
            {"kind": "cdp", "seed_city": "Metropolis", "notes": ["CDP note"], "states": ["34"]},
            ["Metropolis", "Newark"],
        )

    monkeypatch.setattr(svc.census_cdp, "resolve_cdp_axis", _fake_cdp)

    # Site scan → one existing service page; service-axis derivation → main services.
    async def _fake_scan(website, code, use_paid_fallback=True):
        return (["https://acme.example/roof-restoration/"], "sitemap")

    monkeypatch.setattr(svc.site_page_index, "discover_site_urls", _fake_scan)
    monkeypatch.setattr(
        svc, "_derive_service_axis",
        lambda client, classified, place_vocab: (
            [{"label": "Roof Restoration", "sources": ["site"]}, {"label": "Gutter Cleaning", "sources": ["planner"]}],
            {"confirmed": False, "kind": "main_service", "notes": []},
        ),
    )
    monkeypatch.setattr(svc, "_in_tool_index", lambda cid: {"token_index": {}, "location_index": {}})

    # No demand data (keeps the test offline; floor disabled, gaps shown).
    async def _fake_demand(keywords, code):
        return {}, False, []

    monkeypatch.setattr(svc, "_fetch_demand", _fake_demand)

    result = asyncio.run(svc.run_coverage_audit_tier("audit-1", "client-1", 3))
    assert result["status"] == "complete"

    row = store["audit_update"]
    assert row["tier"] == 3
    # Location axis is the CDP list, not cities.
    assert [l["name"] for l in row["location_axis"]] == ["Harrison", "Kearny"]
    assert all(l["source"] == "census_cdp" for l in row["location_axis"])
    # Main-service axis (Tier-1 path), not subservices.
    assert [s["label"] for s in row["service_axis"]] == ["Roof Restoration", "Gutter Cleaning"]
    # Tier 3 KEEPS the location-hub rows (a CDP hub is a main-service concept).
    assert row["provenance"]["location_rows_shown"] is True
    # Location-hub keyword uses the primary main service + the CDP.
    hub_keywords = {g["keyword"] for g in row["gaps"]["missing_locations"]}
    assert "Roof Restoration Harrison" in hub_keywords
    assert "Roof Restoration Kearny" in hub_keywords
    # The CDP note is surfaced in the degraded-notes banner.
    assert "CDP note" in row["provenance"]["degraded_notes"]


# --- run_coverage_audit_tier (Tier 4 — CDP axis × subservice axis wiring) -------
def test_run_tier_4_uses_cdp_axis_and_subservice_axis_and_drops_location_rows(monkeypatch):
    """Tier 4 crosses the two existing axes: the census CDP location axis (like Tier
    3) AND the subservice service axis (like Tier 2). Like Tier 2, it DROPS the
    location-hub rows (a location-hub gap is a main-service concern), so
    `location_rows_shown` is False and `missing_locations` is empty. The seed city
    from the CDP provenance is threaded as the subservice planner's representative
    city, and the footprint cities are the classifier place vocabulary. Everything
    external is mocked."""
    store: dict = {}
    monkeypatch.setattr(svc, "get_supabase", lambda: _FakeSupabase(store))
    monkeypatch.setattr(
        svc.local_seo_silo, "_get_client",
        lambda cid: {"name": "Acme Roofing", "business_location": "Metropolis,New York,United States",
                     "gbp": {"website": "https://acme.example"}},
    )
    monkeypatch.setattr(svc, "location_code_for", lambda client: 2840)

    # CDP location axis + city place-vocab (census_cdp mocked wholesale, like Tier 3).
    async def _fake_cdp(client, seed_location, code, sb):
        return (
            [{"name": "Harrison", "source": "census_cdp"}, {"name": "Kearny", "source": "census_cdp"}],
            {"kind": "cdp", "seed_city": "Metropolis", "notes": ["CDP note"], "states": ["34"]},
            ["Metropolis", "Newark"],
        )

    monkeypatch.setattr(svc.census_cdp, "resolve_cdp_axis", _fake_cdp)

    async def _fake_scan(website, code, use_paid_fallback=True):
        return (["https://acme.example/roof-restoration/"], "sitemap")

    monkeypatch.setattr(svc.site_page_index, "discover_site_urls", _fake_scan)

    # Main-service derivation (feeds the subservice planner). Capture the place vocab
    # to prove the footprint cities + CDP names are threaded in.
    captured: dict = {}

    def _fake_main(client, classified, place_vocab):
        captured["place_vocab"] = list(place_vocab)
        return (
            [{"label": "Roof Restoration", "sources": ["site"]}],
            {"confirmed": False, "kind": "main_service", "notes": []},
        )

    monkeypatch.setattr(svc, "_derive_service_axis", _fake_main)

    # Subservice expansion (like Tier 2). Capture the representative city.
    async def _fake_sub(client, main_axis, representative_city):
        captured["representative_city"] = representative_city
        return (
            [{"label": "Leak Repair", "sources": ["planner"]}, {"label": "Tile Replacement", "sources": ["planner"]}],
            {"kind": "subservice", "main_services": ["Roof Restoration"], "planned_services": ["Roof Restoration"],
             "failed_services": [], "notes": []},
        )

    monkeypatch.setattr(svc, "_derive_subservice_axis", _fake_sub)
    monkeypatch.setattr(svc, "_in_tool_index", lambda cid: {"token_index": {}, "location_index": {}})

    async def _fake_demand(keywords, code):
        return {}, False, []

    monkeypatch.setattr(svc, "_fetch_demand", _fake_demand)

    result = asyncio.run(svc.run_coverage_audit_tier("audit-1", "client-1", 4))
    assert result["status"] == "complete"

    row = store["audit_update"]
    assert row["tier"] == 4
    # Location axis is the CDP list (like Tier 3), not cities.
    assert [l["name"] for l in row["location_axis"]] == ["Harrison", "Kearny"]
    assert all(l["source"] == "census_cdp" for l in row["location_axis"])
    # Service axis is the SUBSERVICE expansion (like Tier 2), not main services.
    assert [s["label"] for s in row["service_axis"]] == ["Leak Repair", "Tile Replacement"]
    assert row["provenance"]["service_axis"]["kind"] == "subservice"
    # Location-hub rows are DROPPED (like Tier 2 — a subservice audit).
    assert row["provenance"]["location_rows_shown"] is False
    assert row["gaps"]["missing_locations"] == []
    # The subservice × CDP cells are still built + seeded (2 subservices × 2 CDPs).
    assert row["gaps"]["counts"]["cells_total"] == 4
    # The CDP seed city is the subservice planner's representative city.
    assert captured["representative_city"] == "Metropolis"
    # Footprint cities + CDP names are the classifier place vocabulary.
    assert "Metropolis" in captured["place_vocab"]
    assert "Newark" in captured["place_vocab"]
    assert "Harrison" in captured["place_vocab"]
    # The CDP note is surfaced in the degraded-notes banner.
    assert "CDP note" in row["provenance"]["degraded_notes"]


def test_run_tier_4_override_axis_is_confirmed_subservice(monkeypatch):
    """An edited (override) service axis is used verbatim for Tier 4 and tagged as a
    confirmed SUBSERVICE axis (not main_service), mirroring Tier 2."""
    store: dict = {}
    monkeypatch.setattr(svc, "get_supabase", lambda: _FakeSupabase(store))
    monkeypatch.setattr(
        svc.local_seo_silo, "_get_client",
        lambda cid: {"name": "Acme Roofing", "business_location": "Metropolis,New York,United States",
                     "gbp": {"website": "https://acme.example"}},
    )
    monkeypatch.setattr(svc, "location_code_for", lambda client: 2840)

    async def _fake_cdp(client, seed_location, code, sb):
        return ([{"name": "Harrison", "source": "census_cdp"}], {"kind": "cdp", "seed_city": "Metropolis", "notes": []}, ["Metropolis"])

    monkeypatch.setattr(svc.census_cdp, "resolve_cdp_axis", _fake_cdp)

    async def _fake_scan(website, code, use_paid_fallback=True):
        return (["https://acme.example/leak-repair-metropolis/"], "sitemap")

    monkeypatch.setattr(svc.site_page_index, "discover_site_urls", _fake_scan)
    monkeypatch.setattr(svc, "_in_tool_index", lambda cid: {"token_index": {}, "location_index": {}})

    async def _fake_demand(keywords, code):
        return {}, False, []

    monkeypatch.setattr(svc, "_fetch_demand", _fake_demand)

    result = asyncio.run(
        svc.run_coverage_audit_tier("audit-1", "client-1", 4, service_axis_override=["Leak Repair", "Tile Replacement"])
    )
    assert result["status"] == "complete"
    row = store["audit_update"]
    assert [s["label"] for s in row["service_axis"]] == ["Leak Repair", "Tile Replacement"]
    assert row["provenance"]["service_axis"]["kind"] == "subservice"
    assert row["provenance"]["service_axis"]["confirmed"] is True
    # Override tier 4 still drops the location-hub rows.
    assert row["provenance"]["location_rows_shown"] is False
    assert row["gaps"]["missing_locations"] == []


# --- run_coverage_audit_tier (Tier 1 — planner offloaded off the event loop) ---
def test_run_tier_1_offloads_service_axis_planner_off_the_loop(monkeypatch):
    """The blocking service-axis planner must run in a worker thread (via
    asyncio.to_thread), never on the shared event loop the API + job lanes run on.
    We record the thread `_derive_service_axis` executes on and assert it is NOT
    the event-loop's main thread."""
    import threading

    store: dict = {}
    monkeypatch.setattr(svc, "get_supabase", lambda: _FakeSupabase(store))
    monkeypatch.setattr(
        svc.local_seo_silo, "_get_client",
        lambda cid: {"name": "Acme", "business_location": "Melbourne,Victoria,Australia",
                     "gbp": {"website": "https://acme.example"}},
    )
    monkeypatch.setattr(svc, "location_code_for", lambda client: 2036)

    async def _fake_loc(client, seed_location, code):
        return [{"name": "Melbourne", "source": "seed"}], {"seed_city": "Melbourne", "notes": []}

    monkeypatch.setattr(svc, "_resolve_location_axis", _fake_loc)

    async def _fake_scan(website, code, use_paid_fallback=True):
        return (["https://acme.example/roof-restoration/"], "sitemap")

    monkeypatch.setattr(svc.site_page_index, "discover_site_urls", _fake_scan)
    monkeypatch.setattr(svc, "_in_tool_index", lambda cid: {"token_index": {}, "location_index": {}})

    async def _fake_demand(keywords, code):
        return {}, False, []

    monkeypatch.setattr(svc, "_fetch_demand", _fake_demand)

    ran_on: dict = {}
    main_ident = threading.get_ident()

    def _derive(client, classified, place_vocab):
        ran_on["ident"] = threading.get_ident()
        return [{"label": "Roof Restoration", "sources": ["site"]}], {"confirmed": False, "notes": []}

    monkeypatch.setattr(svc, "_derive_service_axis", _derive)

    result = asyncio.run(svc.run_coverage_audit_tier("audit-1", "client-1", 1))
    assert result["status"] == "complete"
    # The planner ran, and on a DIFFERENT thread than the event loop → not blocking it.
    assert "ident" in ran_on
    assert ran_on["ident"] != main_ident


# --- enqueue_coverage_audit (in-flight dedup) ---------------------------------
class _EnqueueFake:
    """A Supabase stub for enqueue_coverage_audit: returns a controlled in-flight
    async_jobs list for the dedup read, and records/answers the two inserts."""

    def __init__(self, inflight):
        self._inflight = inflight
        self.audit_inserts = 0
        self.job_inserts = 0

    def table(self, name):
        return _EnqueueQuery(self, name)


class _EnqueueQuery:
    def __init__(self, fake, table):
        self._fake = fake
        self._table = table
        self._mode = "select"

    def select(self, *a, **k):
        self._mode = "select"
        return self

    def insert(self, row):
        self._mode = "insert"
        if self._table == "coverage_audits":
            self._fake.audit_inserts += 1
        elif self._table == "async_jobs":
            self._fake.job_inserts += 1
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def execute(self):
        class _R:
            pass

        r = _R()
        if self._mode == "insert" and self._table == "coverage_audits":
            r.data = [{"id": "new-audit"}]
        elif self._mode == "insert" and self._table == "async_jobs":
            r.data = [{"id": "new-job"}]
        else:  # the dedup select on async_jobs
            r.data = self._fake._inflight
        return r


def test_enqueue_dedups_inflight_auto_run(monkeypatch):
    """A fresh auto-run (service_axis=None) reuses an in-flight coverage_audit job
    for the same (client, tier) with no edited axis — no second row/job is created."""
    fake = _EnqueueFake(
        inflight=[{"id": "job-A", "payload": {"tier": 1, "audit_id": "audit-A", "service_axis": None}}]
    )
    monkeypatch.setattr(svc, "get_supabase", lambda: fake)
    audit_id, job_id = svc.enqueue_coverage_audit("client-1", 1, "user-1")
    assert (audit_id, job_id) == ("audit-A", "job-A")
    assert fake.audit_inserts == 0 and fake.job_inserts == 0


def test_enqueue_dedup_ignores_other_tier_and_override(monkeypatch):
    """The in-flight job is a different tier AND an edited-axis run — neither
    matches, so a fresh run is created."""
    fake = _EnqueueFake(
        inflight=[
            {"id": "job-T2", "payload": {"tier": 2, "audit_id": "audit-T2", "service_axis": None}},
            {"id": "job-edit", "payload": {"tier": 1, "audit_id": "audit-edit", "service_axis": ["Roofing"]}},
        ]
    )
    monkeypatch.setattr(svc, "get_supabase", lambda: fake)
    audit_id, job_id = svc.enqueue_coverage_audit("client-1", 1, "user-1")
    assert (audit_id, job_id) == ("new-audit", "new-job")
    assert fake.audit_inserts == 1 and fake.job_inserts == 1


def test_enqueue_override_always_fresh(monkeypatch):
    """An edited-axis re-run never dedups against an in-flight auto-run — the team
    asked for a new axis, so a fresh run is always created."""
    fake = _EnqueueFake(
        inflight=[{"id": "job-A", "payload": {"tier": 1, "audit_id": "audit-A", "service_axis": None}}]
    )
    monkeypatch.setattr(svc, "get_supabase", lambda: fake)
    audit_id, job_id = svc.enqueue_coverage_audit("client-1", 1, "user-1", service_axis=["Roofing"])
    assert (audit_id, job_id) == ("new-audit", "new-job")
    assert fake.audit_inserts == 1 and fake.job_inserts == 1


def test_enqueue_no_inflight_creates_new(monkeypatch):
    fake = _EnqueueFake(inflight=[])
    monkeypatch.setattr(svc, "get_supabase", lambda: fake)
    audit_id, job_id = svc.enqueue_coverage_audit("client-1", 1, "user-1")
    assert (audit_id, job_id) == ("new-audit", "new-job")
    assert fake.audit_inserts == 1 and fake.job_inserts == 1


def test_enqueue_unsupported_tier_rejected(monkeypatch):
    monkeypatch.setattr(svc, "get_supabase", lambda: _EnqueueFake([]))
    import pytest as _pytest
    from fastapi import HTTPException

    with _pytest.raises(HTTPException) as ei:
        svc.enqueue_coverage_audit("client-1", 9, "user-1")
    assert ei.value.status_code == 400


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

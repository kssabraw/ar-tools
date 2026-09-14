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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

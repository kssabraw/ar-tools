"""Unit tests for the service-page planner (Fanout completeness discovery).

Pure logic only — seed derivation + found/missing marking. The Fanout pipeline
(`_run_pipeline`) bills DataForSEO/LLM and is not exercised here.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services import service_page_plan as spp


# ── derive_seed ───────────────────────────────────────────────────────────────

def test_derive_seed_prefers_gbp_category():
    client = {
        "gbp": {"gbp_category": "Plumber"},
        "website_analysis": {"services": ["Drain Cleaning", "Water Heater Repair"]},
        "name": "Acme Plumbing",
    }
    seed, seed_terms, notes = spp.derive_seed(client)
    assert seed == "Plumber"
    assert seed_terms == ["Drain Cleaning", "Water Heater Repair"]  # scraped → anchors
    assert notes == []


def test_derive_seed_falls_back_to_scraped_services():
    client = {
        "gbp": {},
        "website_analysis": {"services": ["HVAC Installation", "AC Repair", "Furnace Tune-Up"]},
        "name": "Acme HVAC",
    }
    seed, seed_terms, notes = spp.derive_seed(client)
    assert seed == "HVAC Installation"  # first service is the seed
    assert seed_terms == ["AC Repair", "Furnace Tune-Up"]  # the rest are anchors
    assert any("site's services" in n for n in notes)


def test_derive_seed_falls_back_to_business_name():
    client = {"gbp": {}, "website_analysis": {"services": []}, "name": "Acme Roofing"}
    seed, seed_terms, notes = spp.derive_seed(client)
    assert seed == "Acme Roofing services"
    assert seed_terms == []
    assert any("business name" in n for n in notes)


def test_derive_seed_empty_when_nothing_available():
    seed, seed_terms, notes = spp.derive_seed({"gbp": {}, "website_analysis": {}, "name": ""})
    assert seed == ""
    assert seed_terms == []


def test_derive_seed_dedupes_scraped_services_case_insensitively():
    client = {
        "gbp": {"gbp_category": "Plumber"},
        "website_analysis": {"services": ["Drain Cleaning", "drain cleaning", "  ", "Pipe Repair"]},
    }
    seed, seed_terms, _ = spp.derive_seed(client)
    assert seed == "Plumber"
    assert seed_terms == ["Drain Cleaning", "Pipe Repair"]  # dupe + blank dropped


# ── _to_items (found vs missing vs service_page runs) ─────────────────────────

def _fake_supabase_with_runs(rows: list[dict]) -> MagicMock:
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value.eq.return_value
    chain.execute.return_value.data = rows
    return sb


def test_to_items_marks_found_by_keyword_or_service():
    rows = [
        {"keyword": "drain cleaning", "service": None},
        {"keyword": "x", "service": "Water Heater Repair"},  # matched via service
    ]
    per_silo = [
        {"silo": "Drains", "pages": ["Drain Cleaning", "Hydro Jetting"]},
        {"silo": "Water Heaters", "pages": ["Water Heater Repair"]},
    ]
    with patch.object(spp, "get_supabase", return_value=_fake_supabase_with_runs(rows)):
        items = spp._to_items(per_silo, "client-1")

    by_kw = {i["keyword"]: i for i in items}
    assert by_kw["Drain Cleaning"]["status"] == "found"        # keyword match (case-insensitive)
    assert by_kw["Water Heater Repair"]["status"] == "found"   # service match
    assert by_kw["Hydro Jetting"]["status"] == "missing"
    assert by_kw["Drain Cleaning"]["group"] == "Drains"
    assert all(i["url"] is None for i in items)


def test_to_items_all_missing_when_no_runs():
    per_silo = [{"silo": "Drains", "pages": ["Drain Cleaning", "Hydro Jetting"]}]
    with patch.object(spp, "get_supabase", return_value=_fake_supabase_with_runs([])):
        items = spp._to_items(per_silo, "client-1")
    assert [i["status"] for i in items] == ["missing", "missing"]


def test_to_items_degrades_on_lookup_error():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("db down")
    per_silo = [{"silo": "Drains", "pages": ["Drain Cleaning"]}]
    with patch.object(spp, "get_supabase", return_value=sb):
        items = spp._to_items(per_silo, "client-1")
    # Lookup failure → everything reported missing rather than raising.
    assert items[0]["status"] == "missing"

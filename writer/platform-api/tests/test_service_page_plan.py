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


# ── filter_existing_on_site (sitemap duplicate removal) ───────────────────────

def _items(*keywords: str) -> list[dict]:
    return [{"keyword": k, "group": "Drains", "status": "missing", "url": None} for k in keywords]


def test_match_existing_url_exact_slug_equality():
    index = spp._build_url_index(["https://acme.com/services/drain-cleaning/"])
    # Slug equals the service (parent "/services/" dir ignored) → match.
    assert spp._match_existing_url("Drain Cleaning", index) == "https://acme.com/services/drain-cleaning/"
    # Page is more specific than the candidate → no match (qualifiers stay honest).
    assert spp._match_existing_url("Emergency Drain Cleaning", index) is None
    # Unrelated service → no match.
    assert spp._match_existing_url("Water Heater Repair", index) is None


def test_match_existing_url_ignores_query_and_case():
    index = spp._build_url_index(["https://acme.com/Hydro-Jetting?ref=nav"])
    assert spp._match_existing_url("hydro jetting", index) == "https://acme.com/Hydro-Jetting?ref=nav"


def test_match_existing_url_stopwords_in_slug_still_match():
    # "/drain-cleaning-services/" → slug tokens minus the "services" stopword.
    index = spp._build_url_index(["https://acme.com/drain-cleaning-services/"])
    assert spp._match_existing_url("drain cleaning", index) == "https://acme.com/drain-cleaning-services/"


def test_match_ignores_non_service_pages():
    # A blog post / taxonomy page mentioning the service must NOT suppress the
    # candidate — these are excluded by their non-service path segment (#1).
    index = spp._build_url_index([
        "https://acme.com/blog/signs-you-need-drain-cleaning/",
        "https://acme.com/category/drain-cleaning/",
        "https://acme.com/tag/drain-cleaning/",
    ])
    assert index == []  # all excluded
    assert spp._match_existing_url("Drain Cleaning", index) is None


def test_match_generic_token_not_removed_by_narrower_variant():
    # "plumbing" must not be removed just because "/commercial-plumbing/" exists (#2).
    index = spp._build_url_index(["https://acme.com/commercial-plumbing/"])
    assert spp._match_existing_url("plumbing", index) is None
    # The narrower candidate that actually matches the page is still removed.
    assert spp._match_existing_url("commercial plumbing", index) == "https://acme.com/commercial-plumbing/"


def test_filter_existing_on_site_removes_published_pages():
    items = _items("Drain Cleaning", "Hydro Jetting", "Sewer Repair")
    site_urls = [
        "https://acme.com/",
        "https://acme.com/services/drain-cleaning/",
        "https://acme.com/services/hydro-jetting/",
    ]
    kept, removed = spp.filter_existing_on_site(items, site_urls)
    assert {i["keyword"] for i in kept} == {"Sewer Repair"}
    assert {i["keyword"] for i in removed} == {"Drain Cleaning", "Hydro Jetting"}
    # Removed items carry the matched live URL for observability.
    assert all(i["url"] for i in removed)


def test_filter_existing_on_site_no_sitemap_keeps_everything():
    items = _items("Drain Cleaning", "Hydro Jetting")
    kept, on_site = spp.filter_existing_on_site(items, [])
    assert len(kept) == 2
    assert on_site == []


# ── classify_on_site (rank → reoptimize vs drop) ──────────────────────────────

def test_classify_on_site_buckets_by_rank():
    on_site = [
        {"keyword": "drain cleaning", "group": "Drains", "status": "missing", "url": "u1"},   # rank 3
        {"keyword": "hydro jetting", "group": "Drains", "status": "missing", "url": "u2"},     # rank 12
        {"keyword": "sewer repair", "group": "Sewers", "status": "found", "url": "u3"},        # None
        {"keyword": "pipe relining", "group": "Pipes", "status": "missing", "url": "u4"},      # unknown
    ]
    ranks = [3, 12, None, spp._RANK_UNKNOWN]
    reopt, removed_top, unchecked = spp.classify_on_site(on_site, ranks, top_n=5)

    assert removed_top == 1            # drain cleaning (rank 3) dropped
    assert unchecked == 1             # pipe relining couldn't be checked → dropped
    by_kw = {i["keyword"]: i for i in reopt}
    assert set(by_kw) == {"hydro jetting", "sewer repair"}
    assert by_kw["hydro jetting"]["status"] == "reoptimize"
    assert by_kw["hydro jetting"]["rank"] == 12
    assert by_kw["sewer repair"]["rank"] is None      # ranks somewhere past the SERP depth
    assert by_kw["hydro jetting"]["url"] == "u2"      # live URL preserved


def test_classify_on_site_boundary_top_n_inclusive():
    on_site = [{"keyword": "x", "group": "g", "status": "missing", "url": "u"}]
    # rank == top_n is "ranking well" → dropped, not offered.
    reopt, removed_top, unchecked = spp.classify_on_site(on_site, [5], top_n=5)
    assert reopt == [] and removed_top == 1 and unchecked == 0


# ── start_service_plan (reuse / insert / race) ────────────────────────────────

async def test_start_service_plan_reuses_existing_active_job():
    with patch.object(spp, "_get_client", return_value={"id": "c1"}), \
         patch.object(spp, "get_supabase", return_value=MagicMock()), \
         patch.object(spp, "_active_plan_id", return_value="existing-job"):
        assert await spp.start_service_plan("c1", "u1") == "existing-job"


async def test_start_service_plan_inserts_when_none_active():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "new-job"}]
    with patch.object(spp, "_get_client", return_value={"id": "c1"}), \
         patch.object(spp, "get_supabase", return_value=sb), \
         patch.object(spp, "_active_plan_id", return_value=None):
        assert await spp.start_service_plan("c1", "u1") == "new-job"


async def test_start_service_plan_returns_winner_on_insert_conflict():
    # Concurrent insert loses the partial-unique-index race → return the winner.
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError("duplicate key")
    with patch.object(spp, "_get_client", return_value={"id": "c1"}), \
         patch.object(spp, "get_supabase", return_value=sb), \
         patch.object(spp, "_active_plan_id", side_effect=[None, "winner-job"]):
        assert await spp.start_service_plan("c1", "u1") == "winner-job"


async def test_start_service_plan_reraises_when_conflict_has_no_winner():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError("real db error")
    with patch.object(spp, "_get_client", return_value={"id": "c1"}), \
         patch.object(spp, "get_supabase", return_value=sb), \
         patch.object(spp, "_active_plan_id", side_effect=[None, None]):
        try:
            await spp.start_service_plan("c1", "u1")
            assert False, "expected the original error to propagate"
        except RuntimeError as exc:
            assert "real db error" in str(exc)


# ── run_service_plan_job guard ────────────────────────────────────────────────

async def test_run_job_fails_cleanly_without_client_id():
    sb = MagicMock()
    # _get_client must never be reached when client_id is missing.
    with patch.object(spp, "get_supabase", return_value=sb), \
         patch.object(spp, "_get_client", side_effect=AssertionError("must not be called")):
        await spp.run_service_plan_job({"id": "job-1", "payload": {}})
    update_arg = sb.table.return_value.update.call_args[0][0]
    assert update_arg["status"] == "failed"
    assert "client_id" in update_arg["error"]

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import local_seo_service  # noqa: E402


def _client_row(**overrides):
    row = {
        "id": "client-1",
        "name": "Joe's Plumbing",
        "website_url": "https://joesplumbing.com",
        "business_location": "Anaheim, CA",
        "gbp": {
            "business_name": "Joe's Plumbing Co",
            "gbp_category": "Plumber",
            "address": "123 Main St, Anaheim, CA",
            "phone": "+1-714-555-0100",
            "website": "https://joesplumbing.com",
            "hours": {"mon": "9-5"},
            "description": "Family plumber",
            "reviews": [{"text": "Great"}],
        },
    }
    row.update(overrides)
    return row


def _supabase_for_client(client_row, insert_row=None):
    """A chainable supabase mock. `execute` returns the client row first, then
    the inserted row (for the persist path). Any further calls (e.g. the
    best-effort score-history insert) get a permissive default so the mock never
    runs out."""
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for method in ("select", "eq", "single", "insert", "order", "limit", "delete"):
        getattr(table, method).return_value = table
    results = [MagicMock(data=client_row)]
    if insert_row is not None:
        results.append(MagicMock(data=[insert_row]))
    it = iter(results)
    default = MagicMock(data=[insert_row] if insert_row is not None else None)
    table.execute.side_effect = lambda *a, **k: next(it, default)
    return supabase


def test_gbp_to_generate_payload_maps_fields():
    payload = local_seo_service._gbp_to_generate_payload(_client_row(), "emergency plumber", "Anaheim, CA")
    assert payload["keyword"] == "emergency plumber"
    assert payload["business_name"] == "Joe's Plumbing Co"
    assert payload["gbp_category"] == "Plumber"
    assert payload["run_analysis"] is True
    # hours are JSON-encoded; reviews passed through
    assert payload["hours"] == '{"mon": "9-5"}'
    assert payload["reviews"] == [{"text": "Great"}]


def test_business_fields_falls_back_to_client_row():
    fields = local_seo_service._business_fields(_client_row(gbp={}))
    assert fields["business_name"] == "Joe's Plumbing"          # falls back to client name
    assert fields["address"] == "Anaheim, CA"                   # falls back to business_location
    assert fields["website"] == "https://joesplumbing.com"      # falls back to website_url


@pytest.mark.asyncio
async def test_generate_page_persists_row():
    inserted = {"id": "page-1", "client_id": "client-1", "keyword": "emergency plumber"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    nlp_result = {
        "content_html": "<article>x</article>",
        "schema_json": "{}",
        "page_title": "Emergency Plumber Anaheim",
        "composite_score": 88.0,
        "content_gaps": [],
    }
    cached_analysis = {"serp_urls": ["https://a.com"], "google_entities": []}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.analysis_cache, "get", return_value=cached_analysis) as cache_get, \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=nlp_result)) as stream:
        # location_code supplied → resolve_location short-circuits (no network).
        page = await local_seo_service.generate_page(
            "client-1", "emergency plumber", "Anaheim,California,United States", 1013962, "user-9"
        )

    assert page == inserted
    stream.assert_awaited_once()
    assert stream.await_args[0][0] == "/generate-page"
    # the resolved location_code is forwarded to the nlp generate payload
    assert stream.await_args[0][1]["location_code"] == 1013962
    # analysis always runs → the cached analysis is fetched and passed to nlp
    cache_get.assert_called_once()
    assert stream.await_args[0][1]["serp_analysis"] == cached_analysis
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["mode"] == "generate"
    assert persisted["composite_score"] == 88.0
    assert persisted["created_by"] == "user-9"
    assert persisted["run_analysis"] is True


def test_gbp_to_rankability_payload_sources_gbp_fields():
    client = _client_row(
        gbp_place_id="ChIJ-place",
        gbp={
            "business_name": "Joe's Plumbing Co",
            "gbp_category": "Plumber",
            "address": "123 Main St, Anaheim, CA",
            "website": "https://joesplumbing.com",
            "gbp_review_count": 42,
            "latitude": 33.8,
            "longitude": -117.9,
        },
    )
    payload = local_seo_service._gbp_to_rankability_payload(
        client, "emergency plumber", "Anaheim, CA", 1013962, "  Anaheim  "
    )
    assert payload["gbp_category"] == "Plumber"
    assert payload["business_address"] == "123 Main St, Anaheim, CA"
    assert payload["business_review_count"] == 42
    assert payload["business_lat"] == 33.8
    assert payload["business_lng"] == -117.9
    assert payload["gbp_place_id"] == "ChIJ-place"
    assert payload["location_code"] == 1013962
    assert payload["sab_city"] == "Anaheim"  # trimmed


def test_gbp_to_rankability_payload_blank_sab_city_becomes_none():
    payload = local_seo_service._gbp_to_rankability_payload(
        _client_row(), "plumber", "Anaheim, CA", None, "   "
    )
    assert payload["sab_city"] is None


@pytest.mark.asyncio
async def test_check_rankability_proxies_and_returns_report():
    supabase = _supabase_for_client(_client_row(gbp_place_id="ChIJ-x"))
    report = {"score": 72, "verdict": "strong", "score_breakdown": {}, "has_map_pack": True,
              "competitors": [], "ranking_categories": [], "category_match": "exact"}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.locations_service, "resolve_location",
                      new=AsyncMock(return_value=("Anaheim,California,United States", 1013962))), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock(return_value=report)) as post:
        out = await local_seo_service.check_rankability(
            "client-1", "emergency plumber", "Anaheim, CA", 1013962, None, user_id="user-7"
        )
    assert out == report
    path, payload = post.await_args[0]
    assert path == "/check-rankability"
    assert payload["keyword"] == "emergency plumber"
    assert payload["gbp_category"] == "Plumber"
    # the resolved location/code is forwarded
    assert payload["location_code"] == 1013962
    # user_id is forwarded for per-user rate limiting
    assert post.await_args.kwargs["user_id"] == "user-7"


@pytest.mark.asyncio
async def test_check_rankability_requires_gbp_category():
    supabase = _supabase_for_client(_client_row(gbp={}, business_location=None))
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock()) as post:
        with pytest.raises(HTTPException) as exc:
            await local_seo_service.check_rankability(
                "client-1", "plumber", "Anaheim, CA", None, None
            )
    assert exc.value.detail == "client_has_no_gbp_category"
    post.assert_not_awaited()  # short-circuits before any nlp call


@pytest.mark.asyncio
async def test_find_page_requires_website():
    supabase = _supabase_for_client(_client_row(website_url=None, gbp={}))
    with patch.object(local_seo_service, "get_supabase", return_value=supabase):
        with pytest.raises(HTTPException) as exc:
            await local_seo_service.find_page("client-1", "plumber", "Anaheim, CA")
    assert exc.value.detail == "client_has_no_website"


@pytest.mark.asyncio
async def test_score_page_requires_a_source():
    supabase = _supabase_for_client(_client_row())
    with patch.object(local_seo_service, "get_supabase", return_value=supabase):
        with pytest.raises(HTTPException) as exc:
            await local_seo_service.score_page("client-1", "plumber", "Anaheim, CA", None, None, None, None)
    assert exc.value.detail == "page_url_or_content_required"


@pytest.mark.asyncio
async def test_reoptimize_uses_surfaced_score_and_skips_rescore():
    inserted = {"id": "page-2", "client_id": "client-1", "keyword": "plumber"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    reopt_result = {
        "content_html": "<article/>", "schema_json": "{}",
        "composite_score": 91.0, "composite_status": "excellent",
    }
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=reopt_result)), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock()) as post:
        await local_seo_service.reoptimize_page(
            "client-1", "plumber", "Anaheim, CA", "<article/>", None, [], {"serp": 1}, "user-1",
        )

    post.assert_not_awaited()  # surfaced score → no redundant /score-page call
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["mode"] == "reoptimize"
    assert persisted["composite_score"] == 91.0


@pytest.mark.asyncio
async def test_reoptimize_falls_back_to_rescore_when_score_absent():
    inserted = {"id": "page-3", "client_id": "client-1", "keyword": "plumber"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    reopt_result = {"content_html": "<article/>", "schema_json": "{}"}  # older nlp: no score
    score = {"composite_score": 84.0, "composite_status": "good"}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=reopt_result)), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock(return_value=score)) as post:
        await local_seo_service.reoptimize_page(
            "client-1", "plumber", "Anaheim, CA", "<article/>", None, [], None, "user-1",
        )

    post.assert_awaited_once()
    assert post.await_args[0][0] == "/score-page"
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["composite_score"] == 84.0


# ── reoptimize-by-URL (the Reoptimization tab: score-gate at threshold) ──────

@pytest.mark.asyncio
async def test_reoptimize_url_skips_page_at_or_above_threshold():
    # A page already scoring >= the threshold is left untouched (no rewrite).
    supabase = _supabase_for_client(_client_row())
    score = {"composite_score": 82.0, "composite_status": "good", "deficiencies": []}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.locations_service, "resolve_location",
                      new=AsyncMock(return_value=("Anaheim,California,United States", 1013962))), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value={"serp": 1})), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock(return_value=score)) as post, \
         patch.object(local_seo_service, "reoptimize_page", new=AsyncMock()) as reopt:
        out = await local_seo_service.reoptimize_url(
            "client-1", "https://x.com/p", "plumber", "Anaheim, CA", 1013962, "user-1",
            score_threshold=75.0,
        )
    assert out["status"] == "skipped"
    assert out["score"] == 82.0
    assert "82" in out["reason"]
    assert post.await_args[0][0] == "/score-page"      # scored once
    reopt.assert_not_awaited()                          # but not rewritten


@pytest.mark.asyncio
async def test_reoptimize_url_skips_at_exact_threshold():
    # Boundary: composite == threshold is "at or above" → skipped (gate is >=).
    supabase = _supabase_for_client(_client_row())
    score = {"composite_score": 75.0, "composite_status": "needs_improvement", "deficiencies": []}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.locations_service, "resolve_location",
                      new=AsyncMock(return_value=("Anaheim,California,United States", 1013962))), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value=None)), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock(return_value=score)), \
         patch.object(local_seo_service, "reoptimize_page", new=AsyncMock()) as reopt:
        out = await local_seo_service.reoptimize_url(
            "client-1", "https://x.com/p", "plumber", "Anaheim, CA", 1013962, "user-1",
            score_threshold=75.0,
        )
    assert out["status"] == "skipped"
    reopt.assert_not_awaited()


@pytest.mark.asyncio
async def test_reoptimize_url_rewrites_when_unscoreable():
    # Score endpoint returns no composite_score (e.g. page couldn't be fetched/scored)
    # → gate is False → proceed to reoptimize, with prev_score None.
    supabase = _supabase_for_client(_client_row())
    score = {"deficiencies": []}  # no composite_score key
    page = {"id": "page-u", "page_title": "T", "composite_score": 79.0,
            "composite_status": "needs_improvement", "published_doc_url": None}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.locations_service, "resolve_location",
                      new=AsyncMock(return_value=("Anaheim,California,United States", 1013962))), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value=None)), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock(return_value=score)), \
         patch.object(local_seo_service, "reoptimize_page", new=AsyncMock(return_value=page)) as reopt:
        out = await local_seo_service.reoptimize_url(
            "client-1", "https://x.com/p", "plumber", "Anaheim, CA", 1013962, "user-1",
        )
    assert out["status"] == "reoptimized"
    assert out["prev_score"] is None
    assert out["new_score"] == 79.0
    reopt.assert_awaited_once()


@pytest.mark.asyncio
async def test_reoptimize_url_rewrites_page_below_threshold():
    supabase = _supabase_for_client(_client_row())
    score = {"composite_score": 54.0, "composite_status": "poor", "deficiencies": [{"engine_key": "organic_ranking"}]}
    page = {"id": "page-9", "page_title": "T", "composite_score": 81.0,
            "composite_status": "good", "published_doc_url": None}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.locations_service, "resolve_location",
                      new=AsyncMock(return_value=("Anaheim,California,United States", 1013962))), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value={"serp": 1})), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock(return_value=score)), \
         patch.object(local_seo_service, "reoptimize_page", new=AsyncMock(return_value=page)) as reopt:
        out = await local_seo_service.reoptimize_url(
            "client-1", "https://x.com/p", "plumber", "Anaheim, CA", 1013962, "user-1",
        )
    assert out["status"] == "reoptimized"
    assert out["prev_score"] == 54.0
    assert out["new_score"] == 81.0
    assert out["page"]["id"] == "page-9"
    reopt.assert_awaited_once()
    # the scored deficiencies + shared serp analysis are forwarded to the rewrite
    assert reopt.await_args.kwargs["deficiencies"] == [{"engine_key": "organic_ranking"}]
    assert reopt.await_args.kwargs["serp_analysis"] == {"serp": 1}
    assert reopt.await_args.kwargs["existing_page_url"] == "https://x.com/p"


@pytest.mark.asyncio
async def test_reoptimize_url_publishes_when_requested():
    supabase = _supabase_for_client(_client_row())
    score = {"composite_score": 40.0, "deficiencies": []}
    page = {"id": "page-9", "page_title": "T", "composite_score": 80.0,
            "composite_status": "good", "published_doc_url": None}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.locations_service, "resolve_location",
                      new=AsyncMock(return_value=("loc", 1))), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value=None)), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock(return_value=score)), \
         patch.object(local_seo_service, "reoptimize_page", new=AsyncMock(return_value=page)), \
         patch.object(local_seo_service, "publish_page",
                      new=AsyncMock(return_value={"doc_url": "https://d/1", "doc_id": "1"})) as pub:
        out = await local_seo_service.reoptimize_url(
            "client-1", "https://x.com/p", "plumber", "Anaheim, CA", 1, "user-1",
            publish_to_doc=True,
        )
    pub.assert_awaited_once_with("page-9", "user-1")
    assert out["published"]["doc_url"] == "https://d/1"
    assert out["page"]["published_doc_url"] == "https://d/1"


@pytest.mark.asyncio
async def test_reoptimize_url_publish_failure_is_non_fatal():
    # The rewrite is already saved in-app, so a publish failure is surfaced per
    # row rather than losing the work.
    supabase = _supabase_for_client(_client_row())
    score = {"composite_score": 40.0, "deficiencies": []}
    page = {"id": "page-9", "page_title": "T", "composite_score": 80.0,
            "composite_status": "good", "published_doc_url": None}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.locations_service, "resolve_location",
                      new=AsyncMock(return_value=("loc", 1))), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value=None)), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock(return_value=score)), \
         patch.object(local_seo_service, "reoptimize_page", new=AsyncMock(return_value=page)), \
         patch.object(local_seo_service, "publish_page",
                      new=AsyncMock(side_effect=HTTPException(status_code=422, detail="missing_google_drive_folder_id"))):
        out = await local_seo_service.reoptimize_url(
            "client-1", "https://x.com/p", "plumber", "Anaheim, CA", 1, "user-1",
            publish_to_doc=True,
        )
    assert out["status"] == "reoptimized"          # rewrite still returned
    assert out["publish_error"] == "missing_google_drive_folder_id"


@pytest.mark.asyncio
async def test_related_pages_proxies_business_fields():
    supabase = _supabase_for_client(_client_row())
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock(return_value={"items": [], "token_usage": {}})) as post:
        result = await local_seo_service.related_pages("client-1", "plumber", "Anaheim, CA")

    assert result == {"items": [], "token_usage": {}}
    path, payload = post.await_args[0]
    assert path == "/related-pages"
    assert payload["business_name"] == "Joe's Plumbing Co"
    assert payload["website"] == "https://joesplumbing.com"


@pytest.mark.asyncio
async def test_analyze_returns_cache_hit_without_calling_nlp():
    supabase = _supabase_for_client(_client_row())
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.analysis_cache, "get", return_value={"cached": True}) as cache_get, \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock()) as post:
        out = await local_seo_service.analyze(
            "client-1", "roof restoration", "Melbourne,Victoria,Australia", 1000567
        )
    assert out == {"cached": True}
    cache_get.assert_called_once()
    post.assert_not_awaited()  # cache hit → no nlp scrape


@pytest.mark.asyncio
async def test_analyze_miss_calls_nlp_and_stores():
    supabase = _supabase_for_client(_client_row())
    fresh = {"serp_urls": [], "google_entities": []}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.analysis_cache, "get", return_value=None), \
         patch.object(local_seo_service.analysis_cache, "store") as store, \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock(return_value=fresh)) as post:
        out = await local_seo_service.analyze(
            "client-1", "roof restoration", "Melbourne,Victoria,Australia", 1000567
        )
    assert out == fresh
    post.assert_awaited_once()
    assert post.await_args[0][0] == "/analyze"
    store.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_force_refresh_bypasses_cache():
    supabase = _supabase_for_client(_client_row())
    fresh = {"serp_urls": []}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.analysis_cache, "get") as cache_get, \
         patch.object(local_seo_service.analysis_cache, "store"), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock(return_value=fresh)) as post:
        out = await local_seo_service.analyze(
            "client-1", "roof restoration", "Melbourne,Victoria,Australia", 1000567, force_refresh=True
        )
    assert out == fresh
    cache_get.assert_not_called()  # force_refresh skips the cache read
    post.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_degrades_when_analysis_unavailable():
    # analysis can't be computed (thin SERP / provider outage) → generate should
    # still produce a page, with run_analysis flipped off so nlp doesn't re-scrape.
    inserted = {"id": "page-x", "client_id": "client-1", "keyword": "k"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    nlp_result = {"content_html": "<a/>", "schema_json": "{}", "content_gaps": []}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value=None)), \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=nlp_result)) as stream:
        await local_seo_service.generate_page(
            "client-1", "k", "Melbourne,Victoria,Australia", 1000567, "user-1"
        )
    payload = stream.await_args[0][1]
    assert payload["run_analysis"] is False     # degraded → nlp won't re-attempt the scrape
    assert "serp_analysis" not in payload
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["run_analysis"] is True    # provenance: analysis always runs first


@pytest.mark.asyncio
async def test_score_degrades_when_analysis_unavailable():
    # Score-My-Page contract: serp_analysis is optional. If it can't be computed,
    # scoring proceeds (nlp's deterministic engine falls back to neutral).
    supabase = _supabase_for_client(_client_row())
    score = {"composite_score": 70.0, "composite_status": "ok"}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value=None)), \
         patch.object(local_seo_service, "_post_nlp", new=AsyncMock(return_value=score)) as post:
        out = await local_seo_service.score_page(
            "client-1", "k", "Melbourne,Victoria,Australia", 1000567,
            "https://x.com/p", None, None, user_id="user-1",
        )
    assert out == score
    path, payload = post.await_args[0]
    assert path == "/score-page"
    assert payload["serp_analysis"] is None


@pytest.mark.asyncio
async def test_analyze_propagates_provider_failure():
    # analyze() requires the analysis (it's the deliverable) → provider error propagates.
    supabase = _supabase_for_client(_client_row())
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.analysis_cache, "get", return_value=None), \
         patch.object(local_seo_service.analysis_cache, "store"), \
         patch.object(local_seo_service, "_post_nlp",
                      new=AsyncMock(side_effect=HTTPException(status_code=502, detail="local_seo_provider_error"))):
        with pytest.raises(HTTPException) as exc:
            await local_seo_service.analyze("client-1", "k", "Melbourne,Victoria,Australia", 1000567)
    assert exc.value.status_code == 502


def _nlp_response(status_code, *, json_body=None, text=""):
    """A fake httpx response for _post_nlp: minimal .status_code/.text/.json()."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_body is None:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = json_body
    return resp


def _patch_nlp_post(resp):
    """Patch httpx.AsyncClient so _post_nlp's client.post returns `resp`."""
    client = AsyncMock()
    client.post.return_value = resp
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return patch.object(local_seo_service.httpx, "AsyncClient", return_value=ctx)


@pytest.mark.asyncio
async def test_post_nlp_propagates_actionable_4xx_message():
    # nlp's friendly 422 (e.g. unreachable website) must reach the user instead
    # of being flattened to the opaque local_seo_provider_error.
    msg = "Your website returned a 404 error. Check that the URL is correct and the site is live."
    resp = _nlp_response(422, json_body={"detail": msg})
    with _patch_nlp_post(resp):
        with pytest.raises(HTTPException) as exc:
            await local_seo_service._post_nlp("/analyze-brand-voice", {})
    assert exc.value.status_code == 422
    assert exc.value.detail == msg


@pytest.mark.asyncio
async def test_post_nlp_4xx_without_detail_falls_back_to_provider_error():
    resp = _nlp_response(400, text="Bad Request")
    with _patch_nlp_post(resp):
        with pytest.raises(HTTPException) as exc:
            await local_seo_service._post_nlp("/analyze-brand-voice", {})
    assert exc.value.status_code == 400
    assert exc.value.detail == "local_seo_provider_error"


@pytest.mark.asyncio
async def test_post_nlp_5xx_stays_generic_provider_error():
    resp = _nlp_response(500, json_body={"detail": "boom"})
    with _patch_nlp_post(resp):
        with pytest.raises(HTTPException) as exc:
            await local_seo_service._post_nlp("/analyze-brand-voice", {})
    assert exc.value.status_code == 502
    assert exc.value.detail == "local_seo_provider_error"


@pytest.mark.asyncio
async def test_get_or_compute_single_flight_collapses_concurrent_misses():
    # 5 concurrent misses for the same key → exactly ONE nlp compute (single-flight).
    cache: dict = {}

    def fake_get(kw, code, loc):
        return cache.get(local_seo_service.analysis_cache.cache_key(kw, code, loc))

    def fake_store(kw, code, loc, analysis):
        cache[local_seo_service.analysis_cache.cache_key(kw, code, loc)] = analysis

    async def slow_analyze(path, payload, **kwargs):
        await asyncio.sleep(0.05)
        return {"serp_urls": []}

    with patch.object(local_seo_service, "_post_nlp", new=AsyncMock(side_effect=slow_analyze)) as post, \
         patch.object(local_seo_service.analysis_cache, "get", side_effect=fake_get), \
         patch.object(local_seo_service.analysis_cache, "store", side_effect=fake_store):
        results = await asyncio.gather(*[
            local_seo_service._get_or_compute_analysis("kw", "loc-x", 7, False) for _ in range(5)
        ])

    assert all(r == {"serp_urls": []} for r in results)
    post.assert_awaited_once()


_GEN_NLP_RESULT = {"content_html": "<a/>", "schema_json": "{}", "content_gaps": []}


@pytest.mark.asyncio
async def test_generate_uses_per_page_template_over_client_default():
    supabase = _supabase_for_client(
        _client_row(local_seo_page_template_url="https://default.example/x"),
        insert_row={"id": "p", "client_id": "client-1", "keyword": "k"},
    )
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.analysis_cache, "get", return_value={"serp_urls": []}), \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=_GEN_NLP_RESULT)) as stream:
        await local_seo_service.generate_page(
            "client-1", "k", "Melbourne,Victoria,Australia", 1000567, "user-1",
            page_template_url="https://override.example/y",
        )
    assert stream.await_args[0][1]["page_template_url"] == "https://override.example/y"


@pytest.mark.asyncio
async def test_generate_falls_back_to_client_template_default():
    supabase = _supabase_for_client(
        _client_row(local_seo_page_template_url="https://default.example/x"),
        insert_row={"id": "p", "client_id": "client-1", "keyword": "k"},
    )
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.analysis_cache, "get", return_value={"serp_urls": []}), \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=_GEN_NLP_RESULT)) as stream:
        await local_seo_service.generate_page(
            "client-1", "k", "Melbourne,Victoria,Australia", 1000567, "user-1",
        )
    assert stream.await_args[0][1]["page_template_url"] == "https://default.example/x"


def test_set_page_template_default_trims_and_updates():
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for m in ("update", "eq"):
        getattr(table, m).return_value = table
    table.execute.return_value = MagicMock(data=[{"id": "client-1"}])
    with patch.object(local_seo_service, "get_supabase", return_value=supabase):
        out = local_seo_service.set_page_template_default("client-1", "  https://x.example/p  ")
    assert out == {"local_seo_page_template_url": "https://x.example/p"}
    assert table.update.call_args[0][0]["local_seo_page_template_url"] == "https://x.example/p"


def test_set_page_template_default_clears_with_blank():
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for m in ("update", "eq"):
        getattr(table, m).return_value = table
    table.execute.return_value = MagicMock(data=[{"id": "client-1"}])
    with patch.object(local_seo_service, "get_supabase", return_value=supabase):
        out = local_seo_service.set_page_template_default("client-1", "   ")
    assert out == {"local_seo_page_template_url": None}
    assert table.update.call_args[0][0]["local_seo_page_template_url"] is None


# ── score-run history ────────────────────────────────────────────────────────

def _score_result(**overrides):
    result = {
        "composite_score": 47.4,
        "composite_status": "fail",
        "engine_scores": {"organic_ranking": {"score": 52, "issues": [], "recommendations": []}},
        "deficiencies": [{"engine_key": "organic_ranking", "score": 52}],
        "token_usage": {"model": "claude-sonnet-4-6", "cost_usd": 0.067},
    }
    result.update(overrides)
    return result


def test_score_run_row_maps_full_verdict():
    row = local_seo_service._score_run_row(
        "client-1", "roof restoration", "Melbourne,Victoria,Australia", "score",
        _score_result(), page_id=None, page_url="https://x.example/", user_id="u-1",
    )
    assert row["client_id"] == "client-1"
    assert row["mode"] == "score"
    assert row["page_id"] is None
    assert row["page_url"] == "https://x.example/"
    assert row["composite_score"] == 47.4
    assert row["engine_scores"]["organic_ranking"]["score"] == 52
    assert row["deficiencies"][0]["engine_key"] == "organic_ranking"
    assert row["created_by"] == "u-1"


def test_score_run_row_falls_back_to_content_gaps_for_deficiencies():
    # generate results carry the engine failures under content_gaps, not deficiencies.
    result = _score_result(deficiencies=None, content_gaps=[{"engine_key": "aeo_llm_retrieval"}])
    row = local_seo_service._score_run_row(
        "c", "kw", "loc", "generate", result, page_id="p-1", page_url=None, user_id=None,
    )
    assert row["deficiencies"] == [{"engine_key": "aeo_llm_retrieval"}]
    assert row["page_id"] == "p-1"


def test_record_score_run_skips_when_no_verdict():
    # No engine_scores and no composite → nothing written (and no supabase call).
    with patch.object(local_seo_service, "get_supabase") as gs:
        local_seo_service._record_score_run(
            "c", "kw", "loc", "score", {"content_html": "<p>x</p>"},
        )
    gs.assert_not_called()


def test_record_score_run_swallows_db_errors():
    # A history-write failure must never propagate out of the run.
    supabase = MagicMock()
    supabase.table.side_effect = RuntimeError("db down")
    with patch.object(local_seo_service, "get_supabase", return_value=supabase):
        # Should not raise.
        local_seo_service._record_score_run(
            "c", "kw", "loc", "score", _score_result(), page_url="https://x.example/",
        )


# ── publish to Google Doc ────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _FakeAsyncClient:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        return self._resp


def _publish_supabase(page_row, client_row):
    """execute() returns: page (get_page) → client → update."""
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for m in ("select", "eq", "single", "update"):
        getattr(table, m).return_value = table
    table.execute.side_effect = [
        MagicMock(data=page_row),
        MagicMock(data=client_row),
        MagicMock(data=[{"id": "page-1"}]),
    ]
    return supabase


@pytest.mark.asyncio
async def test_publish_page_success_persists_doc():
    page = {"id": "page-1", "client_id": "client-1", "keyword": "plumber",
            "page_title": "Plumber Anaheim", "content_html": "<h1>Plumber</h1><p>Call us.</p>"}
    supabase = _publish_supabase(page, {"name": "Joe", "google_drive_folder_id": "folder-9"})
    resp = _FakeResp({"success": True, "doc_id": "doc-1", "doc_url": "https://docs/doc-1"})
    capture: dict = {}

    class _CapClient(_FakeAsyncClient):
        async def post(self, url, json=None):
            capture["json"] = json
            return self._resp

    with patch.object(local_seo_service.settings, "google_apps_script_url", "https://script"), \
         patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.httpx, "AsyncClient", lambda *a, **k: _CapClient(resp)):
        out = await local_seo_service.publish_page("page-1", "user-1")
    assert out == {"success": True, "doc_id": "doc-1", "doc_url": "https://docs/doc-1"}
    # The page's HTML is sent as-is with format="html" (not degraded to markdown),
    # so the resulting Doc copy-pastes cleanly into WordPress.
    assert capture["json"]["format"] == "html"
    assert capture["json"]["content"] == "<h1>Plumber</h1><p>Call us.</p>"
    update_arg = supabase.table.return_value.update.call_args[0][0]
    assert update_arg["published_doc_url"] == "https://docs/doc-1"
    assert update_arg["published_doc_id"] == "doc-1"


@pytest.mark.asyncio
async def test_publish_page_requires_drive_folder():
    page = {"id": "page-1", "client_id": "client-1", "keyword": "plumber",
            "content_html": "<p>x</p>", "page_title": "t"}
    supabase = _publish_supabase(page, {"name": "Joe", "google_drive_folder_id": None})
    with patch.object(local_seo_service.settings, "google_apps_script_url", "https://script"), \
         patch.object(local_seo_service, "get_supabase", return_value=supabase):
        with pytest.raises(HTTPException) as exc:
            await local_seo_service.publish_page("page-1", "user-1")
    assert exc.value.status_code == 422
    assert exc.value.detail == "missing_google_drive_folder_id"


@pytest.mark.asyncio
async def test_publish_page_not_configured():
    with patch.object(local_seo_service.settings, "google_apps_script_url", ""):
        with pytest.raises(HTTPException) as exc:
            await local_seo_service.publish_page("page-1", "user-1")
    assert exc.value.status_code == 503


# ── interactive actions as background jobs ───────────────────────────────────

def _action_job_supabase():
    """A supabase mock for the single update the action-job handler performs
    (async_jobs → update → eq → execute)."""
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    table.update.return_value = table
    table.eq.return_value = table
    table.insert.return_value = table
    table.execute.return_value = MagicMock(data=[{"id": "job-1"}])
    return supabase


@pytest.mark.asyncio
async def test_enqueue_action_inserts_local_seo_action_job():
    supabase = _action_job_supabase()
    supabase.table.return_value.execute.return_value = MagicMock(data=[{"id": "job-xyz"}])
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_get_client", return_value=_client_row()):
        job_id = await local_seo_service.enqueue_action(
            "client-1", "analyze", {"keyword": "plumber", "location": "Anaheim, CA"}, "user-1",
        )
    assert job_id == "job-xyz"
    insert_arg = supabase.table.return_value.insert.call_args[0][0]
    assert insert_arg["job_type"] == "local_seo_action"
    assert insert_arg["entity_id"] == "client-1"
    assert insert_arg["payload"]["action"] == "analyze"
    assert insert_arg["payload"]["args"]["keyword"] == "plumber"
    assert insert_arg["payload"]["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_run_action_job_stores_result_on_complete():
    job = {"id": "job-1", "payload": {
        "action": "find_page", "client_id": "client-1",
        "args": {"keyword": "plumber", "location": "Anaheim, CA"}, "user_id": "user-1",
    }}
    supabase = _action_job_supabase()
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "find_page", new=AsyncMock(return_value={"match": None})):
        await local_seo_service.run_local_seo_action_job(job)
    update_arg = supabase.table.return_value.update.call_args[0][0]
    assert update_arg["status"] == "complete"
    assert update_arg["result"] == {"match": None}


@pytest.mark.asyncio
async def test_run_action_job_records_failure():
    job = {"id": "job-1", "payload": {
        "action": "find_page", "client_id": "client-1",
        "args": {"keyword": "x", "location": "y"}, "user_id": "u",
    }}
    supabase = _action_job_supabase()
    err = HTTPException(status_code=400, detail="client_has_no_website")
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "find_page", new=AsyncMock(side_effect=err)):
        await local_seo_service.run_local_seo_action_job(job)
    update_arg = supabase.table.return_value.update.call_args[0][0]
    assert update_arg["status"] == "failed"
    assert "client_has_no_website" in update_arg["error"]


@pytest.mark.asyncio
async def test_run_action_job_unknown_action_fails():
    job = {"id": "job-1", "payload": {"action": "bogus", "client_id": "c", "args": {}, "user_id": "u"}}
    supabase = _action_job_supabase()
    with patch.object(local_seo_service, "get_supabase", return_value=supabase):
        await local_seo_service.run_local_seo_action_job(job)
    update_arg = supabase.table.return_value.update.call_args[0][0]
    assert update_arg["status"] == "failed"
    assert "unknown_local_seo_action" in update_arg["error"]

import asyncio
import json
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
    # analysis can't be computed (provider outage) even after one retry →
    # generate still produces a page, with run_analysis flipped off so nlp
    # doesn't re-scrape — but NOT silently: the page carries the market's
    # fallback length target, the degrade is notified, and the persisted row
    # records that no analysis informed it.
    inserted = {"id": "page-x", "client_id": "client-1", "keyword": "k"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    nlp_result = {"content_html": "<a/>", "schema_json": "{}", "content_gaps": []}
    analysis = AsyncMock(return_value=None)
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=analysis), \
         patch.object(local_seo_service, "_resolve_fallback_length_target", return_value=1234), \
         patch.object(local_seo_service, "_notify_analysis_degraded") as notify, \
         patch("services.local_seo_service.asyncio.sleep", new=AsyncMock()) as sleep, \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=nlp_result)) as stream:
        await local_seo_service.generate_page(
            "client-1", "k", "Melbourne,Victoria,Australia", 1000567, "user-1"
        )
    assert analysis.await_count == 2            # first attempt + one retry
    sleep.assert_awaited_once()
    payload = stream.await_args[0][1]
    assert payload["run_analysis"] is False     # degraded → nlp won't re-attempt the scrape
    assert "serp_analysis" not in payload
    assert payload["length_target"] == 1234     # length is still budgeted + graded
    notify.assert_called_once_with("client-1", "k", "Melbourne,Victoria,Australia", 1234)
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["run_analysis"] is False   # honest provenance: no analysis informed this page


@pytest.mark.asyncio
async def test_generate_retry_recovers_the_analysis():
    # The failure seen in production was a seconds-long nlp restart window: the
    # first analysis attempt fails, the retry succeeds → normal (non-degraded)
    # generation, no fallback target, no notification.
    inserted = {"id": "page-x", "client_id": "client-1", "keyword": "k"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    nlp_result = {"content_html": "<a/>", "schema_json": "{}", "content_gaps": []}
    serp = {"serp_word_target": 1500, "serp_avg_word_count": 1250}
    analysis = AsyncMock(side_effect=[None, serp])
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=analysis), \
         patch.object(local_seo_service, "_notify_analysis_degraded") as notify, \
         patch("services.local_seo_service.asyncio.sleep", new=AsyncMock()), \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=nlp_result)) as stream:
        await local_seo_service.generate_page(
            "client-1", "k", "Melbourne,Victoria,Australia", 1000567, "user-1"
        )
    assert analysis.await_count == 2
    payload = stream.await_args[0][1]
    assert payload["serp_analysis"] == serp
    assert "run_analysis" not in payload or payload["run_analysis"] is True
    assert "length_target" not in payload
    notify.assert_not_called()
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["run_analysis"] is True


@pytest.mark.asyncio
async def test_generate_uses_fallback_target_when_serp_has_no_length():
    # The analysis ran but measured no usable competitor length (thin SERP):
    # still budget the page on the market's standing target — but that is not
    # a degrade, so no notification and run_analysis stays True.
    inserted = {"id": "page-x", "client_id": "client-1", "keyword": "k"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    nlp_result = {"content_html": "<a/>", "schema_json": "{}", "content_gaps": []}
    serp = {"serp_urls": ["https://a.com"], "serp_word_target": None}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value=serp)), \
         patch.object(local_seo_service, "_resolve_fallback_length_target", return_value=1200), \
         patch.object(local_seo_service, "_notify_analysis_degraded") as notify, \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=nlp_result)) as stream:
        await local_seo_service.generate_page(
            "client-1", "k", "Melbourne,Victoria,Australia", 1000567, "user-1"
        )
    payload = stream.await_args[0][1]
    assert payload["serp_analysis"] == serp
    assert payload["length_target"] == 1200
    notify.assert_not_called()
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["run_analysis"] is True


@pytest.mark.asyncio
async def test_generate_threads_the_page_spec_and_records_the_length_verdict():
    # The kept page spec rides on the nlp payload, its target drives the
    # reference scaling, and the persisted row records spec id/version + the
    # deterministic target-vs-actual verdict.
    from services import page_spec as ps
    inserted = {"id": "page-x", "client_id": "client-1", "keyword": "k"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    serp = {"serp_word_target": 1058, "serp_avg_word_count": 882, "serp_urls": ["a"] * 15}
    spec = ps.build_spec(client_id="client-1", keyword="k", location="L", location_code=1000567,
                         serp_analysis=serp, reference_entry=None, reference_page_type=None,
                         fallback_target=1200)
    spec["id"], spec["version"] = "spec-1", 1
    html = "<article>" + "".join(
        f'<section id="{s["key"]}"><h2>{s["key"]}</h2><p>' + " ".join(["w"] * s["min_words"]) + "</p></section>"
        for s in spec["sections"]
    ) + "</article>"
    nlp_result = {"content_html": html, "schema_json": "{}", "content_gaps": []}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value=serp)), \
         patch.object(local_seo_service, "_resolve_page_spec", return_value=spec) as resolve, \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=nlp_result)) as stream:
        page = await local_seo_service.generate_page(
            "client-1", "k", "Melbourne,Victoria,Australia", 1000567, "user-1"
        )
    resolve.assert_called_once()
    payload = stream.await_args[0][1]
    assert payload["page_spec"]["id"] == "spec-1"
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["page_spec_id"] == "spec-1" and persisted["spec_version"] == 1
    assert persisted["target_words"] == 1058
    assert persisted["actual_words"] == sum(s["min_words"] for s in spec["sections"])
    assert persisted["length_status"] == "in_band"
    assert page["length_verdict"]["status"] == "in_band"


@pytest.mark.asyncio
async def test_generate_survives_a_spec_failure():
    # A spec that can't be built must never fail the page: the payload simply
    # carries no spec and the row's spec columns stay null.
    inserted = {"id": "page-x", "client_id": "client-1", "keyword": "k"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    nlp_result = {"content_html": "<a/>", "schema_json": "{}", "content_gaps": []}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value={"serp_word_target": 1000})), \
         patch.object(local_seo_service.page_spec_store, "resolve_spec", side_effect=RuntimeError("db down")), \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=nlp_result)) as stream:
        await local_seo_service.generate_page(
            "client-1", "k", "Melbourne,Victoria,Australia", 1000567, "user-1"
        )
    payload = stream.await_args[0][1]
    assert "page_spec" not in payload
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["page_spec_id"] is None and persisted["length_status"] is None


@pytest.mark.asyncio
async def test_generate_over_ceiling_is_saved_honestly_and_notified():
    # Plan §5.5: a page still over the spec ceiling is saved with
    # length_status=over_length AND surfaced through the notifications service.
    from services import page_spec as ps
    inserted = {"id": "page-x", "client_id": "client-1", "keyword": "k"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    serp = {"serp_word_target": 1058, "serp_avg_word_count": 882, "serp_urls": ["a"] * 15}
    spec = ps.build_spec(client_id="client-1", keyword="k", location="L", location_code=1000567,
                         serp_analysis=serp, reference_entry=None, reference_page_type=None,
                         fallback_target=1200)
    spec["id"], spec["version"] = "spec-1", 1
    html = '<article><section id="services"><h2>s</h2><p>' + " ".join(["w"] * 3000) + "</p></section></article>"
    nlp_result = {"content_html": html, "schema_json": "{}", "content_gaps": []}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value=serp)), \
         patch.object(local_seo_service, "_resolve_page_spec", return_value=spec), \
         patch("services.notifications.emit") as emit, \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=nlp_result)):
        page = await local_seo_service.generate_page(
            "client-1", "k", "Melbourne,Victoria,Australia", 1000567, "user-1"
        )
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["length_status"] == "over_length" and persisted["actual_words"] == 3000
    assert page["length_verdict"]["over_ceiling"] is True
    over = [c for c in emit.call_args_list if c.kwargs["kind"] == "content_over_length"]
    assert len(over) == 1
    assert over[0].kwargs["dedupe_key"] == "content_over_length:page-x"


@pytest.mark.asyncio
async def test_generate_with_a_spec_skips_the_legacy_gate_and_records_structure_drift():
    # Phase 4: a spec-driven page is never run through the old reference
    # structure gate (nlp enforces structure against the spec section by
    # section); a page still off its spec is saved structure_status=drift with
    # its issue list (incl. nlp's per-section sentiment audit) AND notified.
    from services import page_spec as ps
    inserted = {"id": "page-s", "client_id": "client-1", "keyword": "k"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    serp = {"serp_word_target": 1058, "serp_avg_word_count": 882, "serp_urls": ["a"] * 15}
    spec = ps.build_spec(client_id="client-1", keyword="k", location="L", location_code=1000567,
                         serp_analysis=serp, reference_entry=None, reference_page_type=None,
                         fallback_target=1200)
    spec["id"], spec["version"] = "spec-4", 4
    # every section present at its min band … but cta-primary is missing and
    # nlp's audit read the usp as negative
    html = "<article>" + "".join(
        f'<section id="{s["key"]}"><h2>{s["key"]}</h2><p>' + " ".join(["w"] * s["min_words"]) + "</p></section>"
        for s in spec["sections"] if s["key"] != "cta-primary"
    ) + "</article>"
    nlp_result = {"content_html": html, "schema_json": "{}", "content_gaps": [],
                  "structure_verdict": {"status": "drift", "issues": [],
                                        "audit": {"usp": {"intent_ok": True, "sentiment": "negative", "note": "gloomy"}}}}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value=serp)), \
         patch.object(local_seo_service, "_resolve_page_spec", return_value=spec), \
         patch.object(local_seo_service, "_apply_structure_gate", new=AsyncMock(side_effect=AssertionError("legacy gate must not run"))), \
         patch("services.notifications.emit") as emit, \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=nlp_result)):
        page = await local_seo_service.generate_page(
            "client-1", "k", "Melbourne,Victoria,Australia", 1000567, "user-1"
        )
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["structure_status"] == "drift"
    codes = {(i.get("key"), i["code"]) for i in persisted["structure_issues"]}
    assert ("cta-primary", "missing_required") in codes and ("usp", "sentiment") in codes
    assert page["structure_verdict"]["audit"]["usp"]["sentiment"] == "negative"
    kinds = [c.kwargs["kind"] for c in emit.call_args_list]
    assert "content_structure_drift" in kinds
    drift = next(c for c in emit.call_args_list if c.kwargs["kind"] == "content_structure_drift")
    assert drift.kwargs["dedupe_key"] == "content_structure_drift:page-s"
    assert "structure issue(s)" in drift.kwargs["summary"]
    assert any(i["code"] == "sentiment" for i in drift.kwargs["payload"]["issues"])


@pytest.mark.asyncio
async def test_generate_without_a_spec_still_runs_the_legacy_gate():
    inserted = {"id": "page-l", "client_id": "client-1", "keyword": "k"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    nlp_result = {"content_html": "<a/>", "schema_json": "{}", "content_gaps": []}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_get_or_compute_analysis", new=AsyncMock(return_value={"serp_word_target": 1000})), \
         patch.object(local_seo_service, "_resolve_page_spec", return_value=None), \
         patch.object(local_seo_service, "_apply_structure_gate", new=AsyncMock(side_effect=lambda r, p, a: r)) as gate, \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=nlp_result)):
        await local_seo_service.generate_page("client-1", "k", "Melbourne,Victoria,Australia", 1000567, "user-1")
    gate.assert_awaited_once()
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["structure_status"] is None and persisted["structure_issues"] is None


@pytest.mark.asyncio
async def test_reoptimize_threads_the_spec_and_records_the_verdict():
    from services import page_spec as ps
    inserted = {"id": "page-r", "client_id": "client-1", "keyword": "k"}
    supabase = _supabase_for_client(_client_row(), insert_row=inserted)
    serp = {"serp_word_target": 1058, "serp_avg_word_count": 882, "serp_urls": ["a"] * 15}
    spec = ps.build_spec(client_id="client-1", keyword="k", location="L", location_code=1000567,
                         serp_analysis=serp, reference_entry=None, reference_page_type=None,
                         fallback_target=1200)
    spec["id"], spec["version"] = "spec-2", 2
    html = "<article>" + "".join(
        f'<section id="{s["key"]}"><h2>{s["key"]}</h2><p>' + " ".join(["w"] * s["min_words"]) + "</p></section>"
        for s in spec["sections"]
    ) + "</article>"
    nlp_result = {"content_html": html, "schema_json": "{}", "composite_score": 88.0, "composite_status": "good"}
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service.locations_service, "resolve_location",
                      new=AsyncMock(return_value=("Melbourne,Victoria,Australia", 1000567))), \
         patch.object(local_seo_service, "_resolve_fallback_length_target", return_value=1200), \
         patch.object(local_seo_service, "_resolve_page_spec", return_value=spec) as resolve, \
         patch.object(local_seo_service.voice_card_service if hasattr(local_seo_service, "voice_card_service") else local_seo_service, "get_voice_card", new=AsyncMock(return_value={}), create=True), \
         patch("services.voice_card_service.get_voice_card", new=AsyncMock(return_value={})), \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=nlp_result)) as stream:
        page = await local_seo_service.reoptimize_page(
            "client-1", "k", "Melbourne,Victoria,Australia", "<p>old</p>", None, [], serp, "user-1"
        )
    resolve.assert_called_once()
    assert resolve.call_args[0][3] == 1000567  # keyed on the resolved DataForSEO code, like generate
    payload = stream.await_args[0][1]
    assert payload["page_spec"]["id"] == "spec-2"
    persisted = supabase.table.return_value.insert.call_args_list[0][0][0]
    assert persisted["page_spec_id"] == "spec-2" and persisted["spec_version"] == 2
    assert persisted["length_status"] == "in_band" and persisted["mode"] == "reoptimize"


def test_fallback_word_target_is_the_median_of_recent_targets_else_default():
    # median is robust to one unusually long SERP in the market
    assert local_seo_service.fallback_word_target([1232, 1627, 1326, 1321, 1240], 1200) == 1321
    assert local_seo_service.fallback_word_target([1300, 1500], 1200) == 1400
    # junk / empty → the config default
    assert local_seo_service.fallback_word_target([], 1200) == 1200
    assert local_seo_service.fallback_word_target([0, -5, None], 1200) == 1200
    assert local_seo_service.fallback_word_target([], 0) == 1
    # an implausible target (a bloated or thin SERP) never defines the market —
    # least of all when it is the only cached analysis at the location
    assert local_seo_service.fallback_word_target([2782], 1200) == 1200
    assert local_seo_service.fallback_word_target([2782, 1321, 1240, 600], 1200) == 1280


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


def _publish_supabase(page_row, client_row, compliance_mode=None):
    """execute() returns: page (get_page) → content-compliance mode → client → update.

    The compliance-mode fetch is the content_compliance guardrail's per-client
    lookup that runs before any destination write; it defaults to an unregulated
    client (mode None → 'off'), so the guardrail is a no-op in these tests.
    """
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for m in ("select", "eq", "single", "update"):
        getattr(table, m).return_value = table
    table.execute.side_effect = [
        MagicMock(data=page_row),
        MagicMock(data={"content_compliance_mode": compliance_mode}),
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


# ── _stream_nlp error propagation ───────────────────────────────────────────
# 65 local_seo_generate jobs failed with the bare string
# "local_seo_generation_failed". The nlp worker sends its reason in the SSE
# error event; it was logged and dropped, so once Railway logs rolled off those
# failures became permanently undiagnosable. The detail is what reaches
# async_jobs.error, so the reason has to travel in it.
class _FakeStreamResponse:
    def __init__(self, status_code=200, lines=(), body=b""):
        self.status_code = status_code
        self._lines = list(lines)
        self._body = body

    async def aread(self):
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _patch_nlp_stream(resp):
    """Patch httpx.AsyncClient so _stream_nlp's client.stream() yields `resp`."""
    stream_ctx = MagicMock()
    stream_ctx.__aenter__ = AsyncMock(return_value=resp)
    stream_ctx.__aexit__ = AsyncMock(return_value=False)
    client = MagicMock()
    client.stream = MagicMock(return_value=stream_ctx)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return patch.object(local_seo_service.httpx, "AsyncClient", return_value=ctx)


@pytest.mark.asyncio
async def test_stream_nlp_carries_the_worker_reason_into_the_detail():
    reason = "Anthropic overloaded_error: the model is temporarily unavailable"
    resp = _FakeStreamResponse(
        lines=[f'data: {json.dumps({"step": "error", "message": reason})}']
    )
    with _patch_nlp_stream(resp):
        with pytest.raises(HTTPException) as exc:
            await local_seo_service._stream_nlp("/generate-page", {})
    # Code kept as a prefix so existing matching still works...
    assert exc.value.detail.startswith("local_seo_generation_failed")
    # ...and the reason now survives into async_jobs.error.
    assert reason in exc.value.detail


@pytest.mark.asyncio
async def test_stream_nlp_falls_back_to_the_bare_code_without_a_message():
    resp = _FakeStreamResponse(lines=[f'data: {json.dumps({"step": "error"})}'])
    with _patch_nlp_stream(resp):
        with pytest.raises(HTTPException) as exc:
            await local_seo_service._stream_nlp("/generate-page", {})
    assert exc.value.detail == "local_seo_generation_failed"


@pytest.mark.asyncio
async def test_stream_nlp_names_the_upstream_status_on_a_non_200():
    resp = _FakeStreamResponse(status_code=503, body=b"upstream down")
    with _patch_nlp_stream(resp):
        with pytest.raises(HTTPException) as exc:
            await local_seo_service._stream_nlp("/generate-page", {})
    assert exc.value.detail.startswith("local_seo_provider_error")
    assert "503" in exc.value.detail


@pytest.mark.asyncio
async def test_stream_nlp_skips_a_non_object_sse_payload():
    """`data: null` is valid JSON but not an object. Before the isinstance guard
    it reached event.get() and raised "'NoneType' object has no attribute 'get'"
    — the same crash that killed 6 page_structure_scrape jobs."""
    resp = _FakeStreamResponse(lines=[
        "data: null",
        "data: [1, 2]",
        f'data: {json.dumps({"step": "done", "result": {"id": "page-1"}})}',
    ])
    with _patch_nlp_stream(resp):
        result = await local_seo_service._stream_nlp("/generate-page", {})
    # The junk lines are skipped, not fatal, and the real event still lands.
    assert result == {"id": "page-1"}


# ── Trust & Proof (docs/modules/local-landing-page-structure.md) ─────────────

def test_trust_signal_fields_maps_jsonb():
    row = _client_row(trust_signals={
        "certifications": [{"name": "BBB", "logo_url": "b.png"}],
        "affiliations": [{"name": "MPA"}],
        "financing_partners": [{"name": "Wisetack", "logo_url": "w.png"}],
        "license_number": "CCC123",
        "years_founded": "1998",   # string coerces to int
        "founding_date": "1998",
    })
    out = local_seo_service._trust_signal_fields(row)
    assert out["certifications"] == [{"name": "BBB", "logo_url": "b.png"}]
    assert out["affiliations"] == [{"name": "MPA"}]
    assert out["financing_partners"][0]["name"] == "Wisetack"
    assert out["license_number"] == "CCC123"
    assert out["years_founded"] == 1998
    assert out["founding_date"] == "1998"


def test_trust_signal_fields_defaults_when_absent_or_malformed():
    # No trust_signals at all → empty lists / None, never a crash.
    out = local_seo_service._trust_signal_fields(_client_row())
    assert out["certifications"] == []
    assert out["affiliations"] == []
    assert out["financing_partners"] == []
    assert out["license_number"] is None
    assert out["years_founded"] is None
    # Malformed types degrade gracefully.
    bad = local_seo_service._trust_signal_fields(
        _client_row(trust_signals={"certifications": "nope", "years_founded": "n/a"})
    )
    assert bad["certifications"] == []
    assert bad["years_founded"] is None
    # trust_signals present but not a dict.
    assert local_seo_service._trust_signal_fields(_client_row(trust_signals=[]))["certifications"] == []


def test_generate_payload_includes_trust_fields_and_gbp_rating():
    row = _client_row(trust_signals={"license_number": "L-9"})
    row["gbp"]["gbp_rating"] = 4.8
    row["gbp"]["gbp_review_count"] = 57
    payload = local_seo_service._gbp_to_generate_payload(row, "plumber", "Anaheim, CA")
    assert payload["license_number"] == "L-9"
    assert payload["gbp_rating"] == 4.8
    assert payload["gbp_review_count"] == 57
    assert payload["certifications"] == []  # absent field → empty, still present as a key


def test_client_assets_reads_and_shapes_rows():
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for method in ("select", "eq", "order"):
        getattr(table, method).return_value = table
    table.execute.return_value = MagicMock(data=[
        {"kind": "team_photo", "url": "t.jpg", "caption": "Crew", "sort_order": 0},
        {"kind": "video_embed", "url": "", "caption": "", "sort_order": 1},  # no url → dropped
        {"kind": "vehicle", "url": "v.jpg", "caption": None, "sort_order": 2},
    ])
    with patch.object(local_seo_service, "get_supabase", return_value=supabase):
        assets = local_seo_service._client_assets("client-1")
    assert assets == [
        {"kind": "team_photo", "url": "t.jpg", "caption": "Crew"},
        {"kind": "vehicle", "url": "v.jpg", "caption": ""},
    ]


def test_client_assets_degrades_on_read_error():
    supabase = MagicMock()
    supabase.table.side_effect = RuntimeError("boom")
    with patch.object(local_seo_service, "get_supabase", return_value=supabase):
        assert local_seo_service._client_assets("client-1") == []

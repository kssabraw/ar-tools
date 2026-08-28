"""Unit tests for the Ecommerce Writer — pure payload/persistence + discovery helpers.

No network: the nlp calls, Supabase writes, and site discovery are mocked. Only
the pure mapping/classification logic is exercised here (the orchestration
functions hit Supabase + nlp and are covered by integration testing).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import ecommerce_service as e  # noqa: E402
from services import ecommerce_discovery as d  # noqa: E402


def _client_row(**overrides):
    row = {
        "id": "client-1",
        "name": "Acme Gear",
        "website_url": "https://acmegear.com",
        "brand_voice": {"tone": "playful"},
        "detected_icp": {"segments": ["hikers"]},
        "differentiators": [{"claim": "lifetime warranty", "mechanism": "in-house repair"}],
        "gbp": {
            "business_name": "Acme Gear Co",
            "gbp_category": "Outdoor equipment store",
            "website": "https://acmegear.com",
        },
    }
    row.update(overrides)
    return row


# ── page-type normalization ──────────────────────────────────────────────────

def test_norm_page_type():
    assert e._norm_page_type("collection") == "collection"
    assert e._norm_page_type("Collection") == "collection"
    assert e._norm_page_type("product") == "product"
    assert e._norm_page_type(None) == "product"
    assert e._norm_page_type("garbage") == "product"


# ── business identity fallbacks ──────────────────────────────────────────────

def test_business_name_prefers_gbp_then_client():
    assert e._business_name(_client_row()) == "Acme Gear Co"
    row = _client_row(gbp={})
    assert e._business_name(row) == "Acme Gear"


def test_brand_context_includes_name_and_category():
    ctx = e._brand_context(_client_row())
    assert "Acme Gear Co" in ctx
    assert "Outdoor equipment store" in ctx


# ── generate payload mapping ─────────────────────────────────────────────────

def test_generate_payload_maps_and_passes_assets():
    payload = e._generate_payload(
        _client_row(), "trail running shoes", "collection",
        source_url="  https://supplier.com/x  ", product_input="  specs here  ",
    )
    assert payload["keyword"] == "trail running shoes"
    assert payload["page_type"] == "collection"
    assert payload["business_name"] == "Acme Gear Co"
    assert payload["website"] == "https://acmegear.com"
    # Whitespace is trimmed; empty → None.
    assert payload["source_url"] == "https://supplier.com/x"
    assert payload["product_input"] == "specs here"
    # Client assets pass through so the writer targets voice + customers.
    assert payload["brand_voice"] == {"tone": "playful"}
    assert payload["detected_icp"] == {"segments": ["hikers"]}
    assert payload["differentiators"][0]["claim"] == "lifetime warranty"
    assert payload["run_analysis"] is True


def test_generate_payload_blank_facts_become_none():
    payload = e._generate_payload(_client_row(), "kw", "product", source_url="   ", product_input="")
    assert payload["source_url"] is None
    assert payload["product_input"] is None


# ── house PDP template resolution ────────────────────────────────────────────

def _capture_generate_payload(client_row, page_type, page_template_url=None):
    """Drive generate_page with the network/DB mocked, returning the payload sent
    to nlp so we can assert house-template resolution."""
    sent = {}

    async def _fake_stream(path, payload, on_progress=None):
        sent.update(payload)
        return {"content_html": "<article></article>", "composite_score": 90}

    with patch.object(e, "_get_client", return_value=client_row), \
         patch.object(e, "_stream_nlp", new=AsyncMock(side_effect=_fake_stream)), \
         patch.object(e, "_persist_page", return_value={"id": "p1"}):
        _run(e.generate_page("c1", "kw", page_type, None, None, "u1", page_template_url=page_template_url))
    return sent


def test_product_uses_client_default_house_template():
    row = _client_row(ecommerce_page_template_url="https://acmegear.com/best-pdp")
    sent = _capture_generate_payload(row, "product")
    assert sent["page_template_url"] == "https://acmegear.com/best-pdp"


def test_per_call_template_overrides_client_default():
    row = _client_row(ecommerce_page_template_url="https://acmegear.com/best-pdp")
    sent = _capture_generate_payload(row, "product", page_template_url="https://acmegear.com/other-pdp")
    assert sent["page_template_url"] == "https://acmegear.com/other-pdp"


def test_collection_ignores_house_template():
    row = _client_row(ecommerce_page_template_url="https://acmegear.com/best-pdp")
    sent = _capture_generate_payload(row, "collection")
    assert sent["page_template_url"] is None


def test_set_page_template_default_normalizes_blank_to_none():
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for m in ("update", "eq"):
        getattr(table, m).return_value = table
    table.execute.return_value = MagicMock(data=[{"id": "c1"}])
    with patch.object(e, "get_supabase", return_value=supabase):
        out = e.set_page_template_default("c1", "   ")
    assert out["ecommerce_page_template_url"] is None


# ── score-run history row ────────────────────────────────────────────────────

def test_score_run_row_shape():
    row = e._score_run_row(
        "c1", "kw", "product", "generate",
        {"composite_score": 82.0, "composite_status": "good", "engine_scores": {"organic_ranking": {"score": 80}}},
        page_id="p1", page_url=None, user_id="u1",
    )
    assert row["client_id"] == "c1"
    assert row["page_id"] == "p1"
    assert row["page_type"] == "product"
    assert row["mode"] == "generate"
    assert row["composite_score"] == 82.0


def test_score_run_row_deficiencies_fall_back_to_content_gaps():
    # generate results carry engine failures under content_gaps, not deficiencies.
    row = e._score_run_row(
        "c1", "kw", "product", "generate",
        {"composite_score": 70, "content_gaps": [{"engine": "structured_data"}]},
        page_id=None, page_url=None, user_id=None,
    )
    assert row["deficiencies"] == [{"engine": "structured_data"}]


# ── URL classification ───────────────────────────────────────────────────────

def test_classify_ecommerce_url():
    assert d.classify_ecommerce_url("https://x.com/products/blue-shoe") == "product"
    assert d.classify_ecommerce_url("https://x.com/product/blue-shoe") == "product"
    assert d.classify_ecommerce_url("https://x.com/p/12345") == "product"
    assert d.classify_ecommerce_url("https://x.com/collections/running") == "collection"
    assert d.classify_ecommerce_url("https://x.com/category/boots") == "collection"
    assert d.classify_ecommerce_url("https://x.com/shop/mens") == "collection"
    assert d.classify_ecommerce_url("https://x.com/blog/how-to-lace") is None
    assert d.classify_ecommerce_url("https://x.com/about") is None


def test_classify_prefers_collection_over_loose_product_hint():
    # A collection path must not be misread as a product page.
    assert d.classify_ecommerce_url("https://x.com/collections/products-sale") == "collection"


# ── discovery orchestration ──────────────────────────────────────────────────

def _run(coro):
    # A fresh loop per call: sibling tests use asyncio.run(), which sets the
    # thread's current loop to None on exit, so asyncio.get_event_loop() here
    # raises "no current event loop" depending on test order (surfaced once CI
    # ran the full suite). An owned loop is order-independent.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _supabase_with_client(client_row):
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for method in ("select", "eq", "single"):
        getattr(table, method).return_value = table
    table.execute.return_value = MagicMock(data=client_row)
    return supabase


def test_discover_pages_filters_dedups_and_classifies():
    urls = [
        "https://acmegear.com/products/tent",
        "https://acmegear.com/products/tent/",   # dup of the above (trailing slash)
        "https://acmegear.com/collections/tents",
        "https://acmegear.com/blog/camping-tips",
        "https://acmegear.com/about",
    ]
    with patch.object(d, "get_supabase", return_value=_supabase_with_client({"website_url": "https://acmegear.com", "gbp": {}})), \
         patch.object(d, "discover_site_urls", new=AsyncMock(return_value=(urls, "sitemap"))):
        res = _run(d.discover_pages("client-1"))
    got = {(i["url"], i["page_type"]) for i in res["items"]}
    assert ("https://acmegear.com/products/tent", "product") in got
    assert ("https://acmegear.com/collections/tents", "collection") in got
    assert res["count"] == 2  # blog/about excluded, trailing-slash dup collapsed
    assert res["source"] == "sitemap"


def test_discover_pages_page_type_filter():
    urls = ["https://acmegear.com/products/tent", "https://acmegear.com/collections/tents"]
    with patch.object(d, "get_supabase", return_value=_supabase_with_client({"website_url": "https://acmegear.com", "gbp": {}})), \
         patch.object(d, "discover_site_urls", new=AsyncMock(return_value=(urls, "sitemap"))):
        res = _run(d.discover_pages("client-1", page_type="collection"))
    assert res["count"] == 1
    assert res["items"][0]["page_type"] == "collection"


def test_discover_pages_no_website_is_degraded_not_error():
    with patch.object(d, "get_supabase", return_value=_supabase_with_client({"website_url": None, "gbp": {}})):
        res = _run(d.discover_pages("client-1"))
    assert res["items"] == []
    assert res["source"] == "none"
    assert "no website" in res["note"].lower()


# ── _stream_nlp error propagation (mirrors local_seo) ───────────────────────
# The nlp worker's reason must reach async_jobs.error, not just the logs.
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
    stream_ctx = MagicMock()
    stream_ctx.__aenter__ = AsyncMock(return_value=resp)
    stream_ctx.__aexit__ = AsyncMock(return_value=False)
    client = MagicMock()
    client.stream = MagicMock(return_value=stream_ctx)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return patch.object(e.httpx, "AsyncClient", return_value=ctx)


def test_ecommerce_stream_carries_the_worker_reason():
    from fastapi import HTTPException

    reason = "scrape failed: source_url returned 403"
    resp = _FakeStreamResponse(
        lines=[f'data: {json.dumps({"step": "error", "message": reason})}']
    )
    with _patch_nlp_stream(resp):
        try:
            asyncio.run(e._stream_nlp("/generate-ecommerce-page", {}))
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.detail.startswith("ecommerce_generation_failed")
            assert reason in exc.detail


def test_ecommerce_stream_names_upstream_status_on_non_200():
    from fastapi import HTTPException

    resp = _FakeStreamResponse(status_code=502, body=b"bad gateway")
    with _patch_nlp_stream(resp):
        try:
            asyncio.run(e._stream_nlp("/generate-ecommerce-page", {}))
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.detail.startswith("ecommerce_provider_error")
            assert "502" in exc.detail


# ── public-spec fact cache: normalization ────────────────────────────────────
# The cache is keyed globally on a normalized compound name, so the whole
# question is "do two keywords name the same molecule?". Over-normalizing is the
# dangerous direction — it would serve one compound's CAS number for another.

from services import ecommerce_facts_cache as fc  # noqa: E402


def test_normalize_strips_commercial_modifiers_and_dosage():
    # The four spellings of the same product this client actually uses.
    key = fc.normalize_entity_key("L-Carnitine")
    assert key == "l carnitine"
    assert fc.normalize_entity_key("Buy L Carnitine") == key
    assert fc.normalize_entity_key("L-Carnitine 1200mg 10ml") == key
    assert fc.normalize_entity_key("  BEST  l carnitine  ONLINE ") == key


def test_normalize_handles_spaced_dose_units():
    assert fc.normalize_entity_key("Semaglutide 5 mg vial") == "semaglutide"


def test_normalize_keeps_compound_identity_numbers():
    # BPC-157's number IS its identity — it must survive where "1200mg" does not.
    assert fc.normalize_entity_key("BPC-157") == "bpc 157"
    assert fc.normalize_entity_key("Buy BPC-157 5mg") == "bpc 157"


def test_normalize_keeps_blends_distinct_from_their_components():
    # The single most important property: a blend is NOT the same molecule.
    assert fc.normalize_entity_key("BPC-157 TB-500") != fc.normalize_entity_key("BPC-157")


def test_normalize_returns_empty_when_nothing_identifying_survives():
    for junk in ["", None, "buy online", "10ml", "1200 10", "   "]:
        assert fc.normalize_entity_key(junk) == ""


# ── public-spec fact cache: freshness ────────────────────────────────────────

def test_is_fresh_within_ttl():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    assert fc.is_fresh((now - timedelta(days=30)).isoformat(), 180, now) is True
    assert fc.is_fresh((now - timedelta(days=200)).isoformat(), 180, now) is False


def test_is_fresh_treats_unusable_input_as_stale():
    # Safe direction: re-research (one pass) beats serving an entry of unknown age.
    assert fc.is_fresh(None, 180) is False
    assert fc.is_fresh("not-a-date", 180) is False


def test_is_fresh_ttl_zero_disables_the_cache():
    from datetime import datetime, timezone

    assert fc.is_fresh(datetime.now(timezone.utc).isoformat(), 0) is False


def test_cache_row_shape():
    facts = [{"field": "CAS number", "value": "541-15-1"}]
    row = fc.cache_row("l carnitine", " L-Carnitine ", "product", facts, source_page_id="page-1")
    assert row["entity_key"] == "l carnitine"
    assert row["entity"] == "L-Carnitine"
    assert row["facts"] == facts
    assert row["source_page_id"] == "page-1"
    assert row["fetched_at"] == "now()"


# ── restart resilience: pre-rewrite score checkpoint / resume ────────────────

def _reoptimize_url_mocks(reopt_calls):
    """Patch reoptimize_url's collaborators. `reopt_calls` collects the kwargs the
    rewrite (reoptimize_from) was called with, so a test can assert the resumed
    deficiencies/serp_analysis were threaded through. reoptimize_verdict says
    'rewrite' so the flow always reaches the rewrite."""
    from services import voice_card_service

    async def _fake_reopt_from(**kwargs):
        reopt_calls.append(kwargs)
        return {"id": "p1", "composite_score": 88, "composite_status": "good", "page_title": "T"}

    return [
        patch.object(e, "reoptimize_from", new=AsyncMock(side_effect=_fake_reopt_from)),
        patch.object(e, "_record_score_run", new=MagicMock()),
        patch.object(voice_card_service, "reoptimize_verdict", return_value=(True, "below_threshold")),
    ]


def test_reoptimize_url_fresh_scores_and_checkpoints():
    """A fresh run scores the page, checkpoints that score, and rewrites."""
    reopt_calls = []
    saved = []
    score = {"composite_score": 60, "voice_compliance": None,
             "deficiencies": [{"engine": "x"}], "serp_analysis": {"top": []}}

    async def _on_checkpoint(sc):
        saved.append(sc)

    mocks = _reoptimize_url_mocks(reopt_calls)
    with patch.object(e, "score_page", new=AsyncMock(return_value=score)) as score_page, \
         mocks[0], mocks[1], mocks[2]:
        out = _run(e.reoptimize_url(
            "c1", "https://acme.com/p", "kw", "product", "u1",
            on_checkpoint=_on_checkpoint,
        ))
    assert score_page.await_count == 1              # scored fresh
    assert saved == [score]                          # checkpoint persisted
    assert out["status"] == "reoptimized"
    # The score's deficiencies + serp analysis were threaded into the rewrite.
    assert reopt_calls[0]["deficiencies"] == [{"engine": "x"}]
    assert reopt_calls[0]["serp_analysis"] == {"top": []}


def test_reoptimize_url_resume_skips_scoring():
    """A requeued run with a saved checkpoint reuses it — no re-score, no
    re-checkpoint — and threads the resumed score into the rewrite."""
    reopt_calls = []
    saved = []
    resume = {"composite_score": 60, "voice_compliance": None,
              "deficiencies": [{"engine": "y"}], "serp_analysis": {"cached": True}}

    async def _on_checkpoint(sc):
        saved.append(sc)

    mocks = _reoptimize_url_mocks(reopt_calls)
    with patch.object(e, "score_page", new=AsyncMock()) as score_page, \
         mocks[0], mocks[1], mocks[2]:
        out = _run(e.reoptimize_url(
            "c1", "https://acme.com/p", "kw", "product", "u1",
            resume_score=resume, on_checkpoint=_on_checkpoint,
        ))
    assert score_page.await_count == 0              # NOT re-scored
    assert saved == []                               # NOT re-checkpointed
    assert out["status"] == "reoptimized"
    assert reopt_calls[0]["deficiencies"] == [{"engine": "y"}]
    assert reopt_calls[0]["serp_analysis"] == {"cached": True}


def test_reoptimize_url_ignores_checkpoint_without_serp():
    """A malformed/partial checkpoint (no serp_analysis) is not trusted — the run
    falls back to a fresh score rather than rewriting on an empty SERP."""
    reopt_calls = []
    score = {"composite_score": 60, "voice_compliance": None,
             "deficiencies": [], "serp_analysis": {"top": []}}
    mocks = _reoptimize_url_mocks(reopt_calls)
    with patch.object(e, "score_page", new=AsyncMock(return_value=score)) as score_page, \
         mocks[0], mocks[1], mocks[2]:
        _run(e.reoptimize_url(
            "c1", "https://acme.com/p", "kw", "product", "u1",
            resume_score={"composite_score": 60},  # no serp_analysis
        ))
    assert score_page.await_count == 1


def test_checkpoint_writer_persists_score_under_running_guard():
    """_job_checkpoint_writer merges the score into payload._checkpoint and writes
    it guarded on status='running'."""
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for m in ("update", "eq"):
        getattr(table, m).return_value = table
    with patch.object(e, "get_supabase", return_value=supabase):
        writer = e._job_checkpoint_writer("job-1", {"client_id": "c1", "page_url": "u"})
        _run(writer({"composite_score": 70, "serp_analysis": {}}))
    payload_written = table.update.call_args[0][0]["payload"]
    assert payload_written["client_id"] == "c1"
    assert payload_written["_checkpoint"] == {"composite_score": 70, "serp_analysis": {}}
    # Guarded so a job that settled between read and write is never stomped.
    table.eq.assert_any_call("status", "running")


def test_checkpoint_writer_is_none_without_job_id():
    assert e._job_checkpoint_writer(None, {"a": 1}) is None

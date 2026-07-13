"""Unit tests for the Ecommerce Writer — pure payload/persistence + discovery helpers.

No network: the nlp calls, Supabase writes, and site discovery are mocked. Only
the pure mapping/classification logic is exercised here (the orchestration
functions hit Supabase + nlp and are covered by integration testing).
"""

from __future__ import annotations

import asyncio
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

    async def _fake_stream(path, payload):
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
    return asyncio.get_event_loop().run_until_complete(coro)


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

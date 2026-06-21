import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import icp_service  # noqa: E402


def _client_row(**overrides):
    row = {
        "id": "client-1",
        "name": "Joe's Plumbing",
        "website_url": "https://joesplumbing.com",
        "gbp": {"business_name": "Joe's Plumbing Co", "gbp_category": "Plumber",
                "gbp_categories": ["Plumber", "Drainage service"],
                "website": "https://joesplumbing.com"},
        "detected_icp": None,
        "differentiators": None,
        "icp_text": "",
    }
    row.update(overrides)
    return row


def _supabase():
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for method in ("select", "eq", "single", "update", "insert"):
        getattr(table, method).return_value = table
    table.execute.return_value = MagicMock(data=[{"id": "client-1"}])
    return supabase


# ── scan ─────────────────────────────────────────────────────────────────────

def test_scan_persists_app_icp_and_differentiators():
    nlp = {
        "detected_icp": {"segments": [{"label": "Emergency Homeowner", "primary": True}],
                         "reasoning": "because"},
        "differentiators": [{"claim": "24/7", "mechanism": "on-call crews", "type": "availability"}],
        "pages_crawled": 9, "analysis_status": "complete",
    }
    supabase = _supabase()
    with patch.object(icp_service, "_get_client", return_value=_client_row()), \
         patch.object(icp_service, "_post_nlp", new=AsyncMock(return_value=nlp)), \
         patch.object(icp_service, "get_supabase", return_value=supabase):
        result = asyncio.run(icp_service.scan("client-1", force=False, user_id="u1"))

    assert result["detected_icp"]["source"] == "app"
    assert result["detected_icp"]["segments"][0]["label"] == "Emergency Homeowner"
    assert result["differentiators"][0]["type"] == "availability"
    assert result["analysis_status"] == "complete"
    persisted = supabase.table.return_value.update.call_args[0][0]
    assert persisted["detected_icp"]["source"] == "app"
    assert "differentiators" in persisted


def test_scan_payload_includes_categories_and_falls_back_without_gbp():
    captured = {}

    async def _fake_post(path, payload, user_id=None):
        captured["path"] = path
        captured["payload"] = payload
        return {"detected_icp": {}, "differentiators": [], "pages_crawled": 0, "analysis_status": "partial"}

    row = _client_row(gbp=None)
    with patch.object(icp_service, "_get_client", return_value=row), \
         patch.object(icp_service, "_post_nlp", new=_fake_post), \
         patch.object(icp_service, "get_supabase", return_value=_supabase()):
        asyncio.run(icp_service.scan("client-1", force=False, user_id="u1"))

    assert captured["path"] == "/analyze-business"
    assert captured["payload"]["business_name"] == "Joe's Plumbing"
    assert captured["payload"]["website_url"] == "https://joesplumbing.com"
    assert captured["payload"]["gbp_categories"] == []


def test_scan_refuses_to_overwrite_user_structured_icp():
    row = _client_row(detected_icp={"source": "user", "segments": [{"label": "X"}]})
    with patch.object(icp_service, "_get_client", return_value=row), \
         patch.object(icp_service, "_post_nlp", new=AsyncMock()) as post, \
         patch.object(icp_service, "get_supabase", return_value=_supabase()):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(icp_service.scan("client-1", force=False, user_id="u1"))
    assert exc.value.status_code == 409
    assert exc.value.detail == "icp_user_authored"
    post.assert_not_called()


def test_scan_allows_raw_text_only_icp_and_preserves_it():
    row = _client_row(detected_icp={"source": "user", "raw_text": "We serve panicked homeowners."})
    with patch.object(icp_service, "_get_client", return_value=row), \
         patch.object(icp_service, "_post_nlp",
                      new=AsyncMock(return_value={"detected_icp": {"segments": [{"label": "Y"}]},
                                                  "differentiators": [], "pages_crawled": 1,
                                                  "analysis_status": "complete"})), \
         patch.object(icp_service, "get_supabase", return_value=_supabase()):
        result = asyncio.run(icp_service.scan("client-1", force=False, user_id="u1"))
    assert result["detected_icp"]["raw_text"] == "We serve panicked homeowners."  # preserved
    assert result["detected_icp"]["segments"][0]["label"] == "Y"                   # enriched


def test_scan_forwards_user_id():
    captured = {}

    async def _fake_post(path, payload, user_id=None):
        captured["user_id"] = user_id
        return {"detected_icp": {}, "differentiators": [], "pages_crawled": 0, "analysis_status": "partial"}

    with patch.object(icp_service, "_get_client", return_value=_client_row()), \
         patch.object(icp_service, "_post_nlp", new=_fake_post), \
         patch.object(icp_service, "get_supabase", return_value=_supabase()):
        asyncio.run(icp_service.scan("client-1", force=False, user_id="user-7"))
    assert captured["user_id"] == "user-7"


# ── update / guard / merge ───────────────────────────────────────────────────

def test_update_sets_source_user_and_replaces_differentiators():
    row = _client_row(detected_icp={"source": "app", "segments": [{"label": "old"}]},
                      differentiators=[{"claim": "old"}])
    with patch.object(icp_service, "_get_client", return_value=row), \
         patch.object(icp_service, "get_supabase", return_value=_supabase()):
        result = icp_service.update(
            "client-1", raw_text=None, segments=[{"label": "new"}], reasoning="r",
            differentiators=[{"claim": "fast"}], user_id="u1",
        )
    assert result["detected_icp"]["source"] == "user"
    assert result["detected_icp"]["segments"][0]["label"] == "new"
    assert result["differentiators"][0]["claim"] == "fast"


def test_ensure_scannable_blocks_structured_allows_raw_only():
    structured = _client_row(detected_icp={"source": "user", "segments": [{"label": "X"}]})
    with patch.object(icp_service, "_get_client", return_value=structured):
        with pytest.raises(HTTPException) as exc:
            icp_service.ensure_scannable("client-1", force=False)
    assert exc.value.status_code == 409
    raw_only = _client_row(detected_icp={"source": "user", "raw_text": "hi"})
    with patch.object(icp_service, "_get_client", return_value=raw_only):
        icp_service.ensure_scannable("client-1", force=False)  # no raise


def test_merge_raw_text_seeds_and_collapses():
    blob = icp_service.merge_raw_text(None, "we serve homeowners")
    assert blob["source"] == "user"
    assert blob["raw_text"] == "we serve homeowners"
    assert icp_service.merge_raw_text(None, "  ") is None


# ── snapshot rendering (Blog Writer convergence, differentiators folded in) ──

def test_resolve_icp_text_prefers_raw_then_folds_differentiators():
    client = {
        "detected_icp": {"raw_text": "Panicked homeowners with a flooding basement."},
        "differentiators": [{"claim": "1-hour response", "mechanism": "local crews"}],
    }
    out = icp_service.resolve_icp_text(client)
    assert out.startswith("Panicked homeowners")
    assert "DIFFERENTIATORS" in out and "1-hour response (mechanism: local crews)" in out


def test_resolve_icp_text_structured_then_legacy_fallback():
    structured = icp_service.resolve_icp_text({
        "detected_icp": {"segments": [{"label": "Homeowner", "primary": True,
                                       "psychographics": {"fears": ["cost"]}}]},
        "differentiators": [],
    })
    assert "TARGET CUSTOMER PROFILES" in structured and "Homeowner — PRIMARY" in structured
    # detected_icp unset → legacy column
    assert icp_service.resolve_icp_text({"detected_icp": None, "icp_text": "legacy"}) == "legacy"
    assert icp_service.resolve_icp_text({}) == ""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import brand_voice_service  # noqa: E402


def _client_row(**overrides):
    row = {
        "id": "client-1",
        "name": "Joe's Plumbing",
        "website_url": "https://joesplumbing.com",
        "gbp": {"business_name": "Joe's Plumbing Co", "gbp_category": "Plumber",
                "website": "https://joesplumbing.com"},
        "brand_voice": None,
    }
    row.update(overrides)
    return row


def _supabase(update_returns=None):
    """Chainable supabase mock. `execute` returns the update result row(s)."""
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for method in ("select", "eq", "single", "update", "insert"):
        getattr(table, method).return_value = table
    table.execute.return_value = MagicMock(data=update_returns or [{"id": "client-1"}])
    return supabase


# ── scan: app analysis persists with source 'app' ────────────────────────────

def test_scan_persists_app_voice():
    engine = {
        "current_voice": {"tone": "friendly"},
        "recommended_voice": {"tone": "bold"},
        "recommended_accepted": None,
        "writer_execution_guide": {"quick_cheat_sheet": ["be clear"]},
    }
    supabase = _supabase()
    with patch.object(brand_voice_service, "_get_client", return_value=_client_row()), \
         patch.object(brand_voice_service, "_post_nlp",
                      new=AsyncMock(return_value={"brand_voice": engine, "pages_sampled": 7})), \
         patch.object(brand_voice_service, "get_supabase", return_value=supabase):
        import asyncio
        result = asyncio.run(brand_voice_service.scan("client-1", force=False, user_id="u1"))

    blob = result["brand_voice"]
    assert blob["source"] == "app"
    assert blob["current_voice"] == {"tone": "friendly"}
    assert blob["recommended_voice"] == {"tone": "bold"}
    assert blob["generated_at"] is not None
    assert result["pages_sampled"] == 7
    # persisted blob written under the brand_voice column
    persisted = supabase.table.return_value.update.call_args[0][0]
    assert persisted["brand_voice"]["source"] == "app"


def test_scan_payload_falls_back_to_client_row_without_gbp():
    """GBP-independent: a client with no gbp still scans using name + website_url."""
    captured = {}

    async def _fake_post(path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {"brand_voice": {}, "pages_sampled": 0}

    row = _client_row(gbp=None)
    with patch.object(brand_voice_service, "_get_client", return_value=row), \
         patch.object(brand_voice_service, "_post_nlp", new=_fake_post), \
         patch.object(brand_voice_service, "get_supabase", return_value=_supabase()):
        import asyncio
        asyncio.run(brand_voice_service.scan("client-1", force=False, user_id="u1"))

    assert captured["path"] == "/analyze-brand-voice"
    assert captured["payload"]["business_name"] == "Joe's Plumbing"
    assert captured["payload"]["website_url"] == "https://joesplumbing.com"
    assert captured["payload"]["gbp_category"] == ""


# ── supersede guard: user-authored voice is not clobbered ────────────────────

def test_scan_refuses_to_overwrite_user_voice_without_force():
    row = _client_row(brand_voice={"source": "user", "raw_text": "we are bold"})
    with patch.object(brand_voice_service, "_get_client", return_value=row), \
         patch.object(brand_voice_service, "_post_nlp", new=AsyncMock()) as post, \
         patch.object(brand_voice_service, "get_supabase", return_value=_supabase()):
        import asyncio
        with pytest.raises(HTTPException) as exc:
            asyncio.run(brand_voice_service.scan("client-1", force=False, user_id="u1"))
    assert exc.value.status_code == 409
    assert exc.value.detail == "brand_voice_user_authored"
    post.assert_not_called()


def test_scan_force_overwrites_user_voice():
    row = _client_row(brand_voice={"source": "user", "raw_text": "we are bold"})
    with patch.object(brand_voice_service, "_get_client", return_value=row), \
         patch.object(brand_voice_service, "_post_nlp",
                      new=AsyncMock(return_value={"brand_voice": {"current_voice": {"tone": "x"}},
                                                  "pages_sampled": 1})), \
         patch.object(brand_voice_service, "get_supabase", return_value=_supabase()):
        import asyncio
        result = asyncio.run(brand_voice_service.scan("client-1", force=True, user_id="u1"))
    assert result["brand_voice"]["source"] == "app"


# ── manual update: marks source 'user' (supersede) ───────────────────────────

def test_update_sets_source_user_and_merges():
    row = _client_row(brand_voice={"source": "app", "current_voice": {"tone": "old"},
                                   "recommended_voice": {"tone": "rec"}})
    supabase = _supabase()
    with patch.object(brand_voice_service, "_get_client", return_value=row), \
         patch.object(brand_voice_service, "get_supabase", return_value=supabase):
        result = brand_voice_service.update(
            "client-1", raw_text="we fix it fast", current_voice=None,
            recommended_accepted=True, user_id="u1",
        )
    blob = result["brand_voice"]
    assert blob["source"] == "user"
    assert blob["raw_text"] == "we fix it fast"
    assert blob["recommended_accepted"] is True
    # untouched fields are preserved from the existing blob
    assert blob["recommended_voice"] == {"tone": "rec"}
    assert blob["edited_at"] is not None

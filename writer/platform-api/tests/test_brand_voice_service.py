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

    async def _fake_post(path, payload, user_id=None):
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

def test_scan_refuses_to_overwrite_user_structured_voice_without_force():
    # A user who filled the structured form (current_voice) is protected.
    row = _client_row(brand_voice={"source": "user", "current_voice": {"tone": "bold"}})
    with patch.object(brand_voice_service, "_get_client", return_value=row), \
         patch.object(brand_voice_service, "_post_nlp", new=AsyncMock()) as post, \
         patch.object(brand_voice_service, "get_supabase", return_value=_supabase()):
        import asyncio
        with pytest.raises(HTTPException) as exc:
            asyncio.run(brand_voice_service.scan("client-1", force=False, user_id="u1"))
    assert exc.value.status_code == 409
    assert exc.value.detail == "brand_voice_user_authored"
    post.assert_not_called()


def test_scan_allows_raw_text_only_voice_and_preserves_it():
    # A user with only a freeform guide (raw_text) is NOT blocked — the scan
    # enriches structured fields while preserving their raw_text.
    row = _client_row(brand_voice={"source": "user", "raw_text": "fast & friendly"})
    with patch.object(brand_voice_service, "_get_client", return_value=row), \
         patch.object(brand_voice_service, "_post_nlp",
                      new=AsyncMock(return_value={"brand_voice": {"current_voice": {"tone": "x"}},
                                                  "pages_sampled": 2})), \
         patch.object(brand_voice_service, "get_supabase", return_value=_supabase()):
        import asyncio
        result = asyncio.run(brand_voice_service.scan("client-1", force=False, user_id="u1"))
    blob = result["brand_voice"]
    assert blob["source"] == "app"
    assert blob["raw_text"] == "fast & friendly"   # preserved
    assert blob["current_voice"] == {"tone": "x"}  # enriched


def test_scan_force_overwrites_user_voice_but_keeps_raw_text():
    row = _client_row(brand_voice={"source": "user", "current_voice": {"tone": "b"},
                                   "raw_text": "we are bold"})
    with patch.object(brand_voice_service, "_get_client", return_value=row), \
         patch.object(brand_voice_service, "_post_nlp",
                      new=AsyncMock(return_value={"brand_voice": {"current_voice": {"tone": "x"}},
                                                  "pages_sampled": 1})), \
         patch.object(brand_voice_service, "get_supabase", return_value=_supabase()):
        import asyncio
        result = asyncio.run(brand_voice_service.scan("client-1", force=True, user_id="u1"))
    assert result["brand_voice"]["source"] == "app"
    assert result["brand_voice"]["raw_text"] == "we are bold"


def test_scan_forwards_user_id_for_rate_limiting():
    captured = {}

    async def _fake_post(path, payload, user_id=None):
        captured["user_id"] = user_id
        return {"brand_voice": {}, "pages_sampled": 0}

    with patch.object(brand_voice_service, "_get_client", return_value=_client_row()), \
         patch.object(brand_voice_service, "_post_nlp", new=_fake_post), \
         patch.object(brand_voice_service, "get_supabase", return_value=_supabase()):
        import asyncio
        asyncio.run(brand_voice_service.scan("client-1", force=False, user_id="user-42"))
    assert captured["user_id"] == "user-42"


# ── ensure_scannable (router pre-flight → real HTTP 409) ─────────────────────

def test_ensure_scannable_blocks_user_structured_voice():
    row = _client_row(brand_voice={"source": "user", "current_voice": {"tone": "b"}})
    with patch.object(brand_voice_service, "_get_client", return_value=row):
        with pytest.raises(HTTPException) as exc:
            brand_voice_service.ensure_scannable("client-1", force=False)
    assert exc.value.status_code == 409


def test_ensure_scannable_allows_raw_text_only_and_force():
    row = _client_row(brand_voice={"source": "user", "raw_text": "hi"})
    with patch.object(brand_voice_service, "_get_client", return_value=row):
        brand_voice_service.ensure_scannable("client-1", force=False)  # no raise
    structured = _client_row(brand_voice={"source": "user", "current_voice": {"tone": "b"}})
    with patch.object(brand_voice_service, "_get_client", return_value=structured):
        brand_voice_service.ensure_scannable("client-1", force=True)  # force overrides


# ── merge_raw_text (clients-router convergence helper) ───────────────────────

def test_merge_raw_text_seeds_user_voice():
    blob = brand_voice_service.merge_raw_text(None, "we fix pipes fast")
    assert blob["source"] == "user"
    assert blob["raw_text"] == "we fix pipes fast"
    assert blob["current_voice"] is None
    assert blob["edited_at"] is not None


# ── render_brand_voice_text / resolve_brand_guide_text (Slice 2 bridge) ──────

def test_render_returns_raw_text_unwrapped():
    # Free-text clients must get byte-identical text to the legacy column.
    bv = {"source": "user", "raw_text": "We fix pipes fast and clean up after."}
    assert brand_voice_service.render_brand_voice_text(bv) == "We fix pipes fast and clean up after."


def test_render_structured_block_when_no_raw_text():
    bv = {
        "source": "app",
        "current_voice": {"tone": "Warm and direct", "personality": ["honest", "local"]},
        "writer_execution_guide": {"quick_cheat_sheet": ["Lead with the answer"]},
    }
    out = brand_voice_service.render_brand_voice_text(bv)
    assert out.startswith("BRAND VOICE (match this exactly):")
    assert "Tone: Warm and direct" in out
    assert "Quick cheat sheet:" in out and "- Lead with the answer" in out


def test_render_recommended_only_used_when_accepted():
    bv = {"current_voice": {"tone": "old"}, "recommended_voice": {"tone": "new"}}
    assert "old" in brand_voice_service.render_brand_voice_text(bv)
    bv["recommended_accepted"] = True
    assert "new" in brand_voice_service.render_brand_voice_text(bv)


def test_render_empty_for_none_or_blank():
    assert brand_voice_service.render_brand_voice_text(None) == ""
    assert brand_voice_service.render_brand_voice_text({"source": "app"}) == ""


def test_resolve_prefers_brand_voice_then_falls_back():
    # brand_voice present → wins
    client = {"brand_voice": {"raw_text": "voice wins"}, "brand_guide_text": "legacy"}
    assert brand_voice_service.resolve_brand_guide_text(client) == "voice wins"
    # brand_voice unset → legacy column
    assert brand_voice_service.resolve_brand_guide_text(
        {"brand_voice": None, "brand_guide_text": "legacy"}
    ) == "legacy"
    # neither → empty string (never None, matches snapshot contract)
    assert brand_voice_service.resolve_brand_guide_text({}) == ""


def test_merge_raw_text_preserves_structured_and_collapses_empty():
    existing = {"source": "app", "current_voice": {"tone": "x"}}
    blob = brand_voice_service.merge_raw_text(existing, "")
    assert blob["current_voice"] == {"tone": "x"}  # structured kept
    assert blob["raw_text"] is None
    assert blob["source"] == "app"                 # not flipped on empty text
    # nothing meaningful → collapses to NULL
    assert brand_voice_service.merge_raw_text(None, "   ") is None


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

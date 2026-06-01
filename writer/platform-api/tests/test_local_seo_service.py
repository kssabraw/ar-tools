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
    the inserted row (for the persist path)."""
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for method in ("select", "eq", "single", "insert", "order", "delete"):
        getattr(table, method).return_value = table
    results = [MagicMock(data=client_row)]
    if insert_row is not None:
        results.append(MagicMock(data=[insert_row]))
    table.execute.side_effect = results
    return supabase


def test_gbp_to_generate_payload_maps_fields():
    payload = local_seo_service._gbp_to_generate_payload(_client_row(), "emergency plumber", "Anaheim, CA", True)
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
    with patch.object(local_seo_service, "get_supabase", return_value=supabase), \
         patch.object(local_seo_service, "_stream_nlp", new=AsyncMock(return_value=nlp_result)) as stream:
        page = await local_seo_service.generate_page("client-1", "emergency plumber", "Anaheim, CA", True, "user-9")

    assert page == inserted
    stream.assert_awaited_once()
    assert stream.await_args[0][0] == "/generate-page"
    persisted = supabase.table.return_value.insert.call_args[0][0]
    assert persisted["mode"] == "generate"
    assert persisted["composite_score"] == 88.0
    assert persisted["created_by"] == "user-9"
    assert persisted["run_analysis"] is True


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

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import clients  # noqa: E402
from models.clients import ClientCreateRequest  # noqa: E402


def _supabase():
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    table.insert.return_value = table
    table.execute.return_value = MagicMock(data=[{}])
    return supabase


def test_auto_assets_enqueues_two_jobs_for_client_with_website():
    supabase = _supabase()
    client = {"id": "c1", "website_url": "https://x.com", "gbp": None}
    with patch.object(clients.settings, "auto_generate_brand_voice_icp", True), \
         patch.object(clients, "get_supabase", return_value=supabase):
        clients._enqueue_auto_brand_voice_icp(client, "u1")
    rows = supabase.table.return_value.insert.call_args[0][0]
    assert [r["job_type"] for r in rows] == ["brand_voice_scan", "icp_scan"]
    assert all(r["payload"] == {"client_id": "c1", "user_id": "u1"} for r in rows)
    assert all(r["entity_id"] == "c1" for r in rows)


def test_auto_assets_enqueues_for_gbp_only_client():
    supabase = _supabase()
    client = {"id": "c1", "website_url": None, "gbp": {"business_name": "X"}}
    with patch.object(clients.settings, "auto_generate_brand_voice_icp", True), \
         patch.object(clients, "get_supabase", return_value=supabase):
        clients._enqueue_auto_brand_voice_icp(client, "u1")
    assert supabase.table.return_value.insert.called


def test_auto_assets_skipped_when_disabled():
    supabase = _supabase()
    client = {"id": "c1", "website_url": "https://x.com", "gbp": None}
    with patch.object(clients.settings, "auto_generate_brand_voice_icp", False), \
         patch.object(clients, "get_supabase", return_value=supabase):
        clients._enqueue_auto_brand_voice_icp(client, "u1")
    supabase.table.return_value.insert.assert_not_called()


def test_auto_assets_skipped_without_website_or_gbp():
    supabase = _supabase()
    client = {"id": "c1", "website_url": None, "gbp": None}
    with patch.object(clients.settings, "auto_generate_brand_voice_icp", True), \
         patch.object(clients, "get_supabase", return_value=supabase):
        clients._enqueue_auto_brand_voice_icp(client, "u1")
    supabase.table.return_value.insert.assert_not_called()


# ── Prospect creation + conversion ──────────────────────────────────────────

def _full_row(**over) -> dict:
    """A clients row carrying every field ClientDetail requires (NOT NULL cols),
    so _to_client_detail() can build the response."""
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "Acme Plumbing",
        "website_url": "https://acme.test",
        "website_analysis_status": "pending",
        "brand_guide_source_type": "text",
        "brand_guide_text": "",
        "icp_source_type": "text",
        "icp_text": "",
        "archived": False,
        "created_at": "2026-09-15T00:00:00Z",
        "updated_at": "2026-09-15T00:00:00Z",
        "kind": "client",
        "gbp": None,
    }
    row.update(over)
    return row


def _create_supabase(inserted_row: dict):
    """Supabase mock where the name dup-check reads empty and insert returns the
    given row. The select chain uses table.execute (empty); insert uses its own
    chain so the two don't collide on one return value."""
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.single.return_value = table
    table.update.return_value = table
    table.execute.return_value = MagicMock(data=[])  # dup-check → not taken
    insert_chain = MagicMock()
    table.insert.return_value = insert_chain
    insert_chain.execute.return_value = MagicMock(data=[inserted_row])
    return supabase


def _base_create_body(**over) -> ClientCreateRequest:
    fields = dict(
        name="Acme Plumbing",
        website_url="https://acme.test",
        brand_guide_source_type="text",
        icp_source_type="text",
    )
    fields.update(over)
    return ClientCreateRequest(**fields)


def test_create_prospect_skips_full_provisioning():
    supabase = _create_supabase(_full_row(kind="prospect"))
    body = _base_create_body(kind="prospect")
    with patch.object(clients, "get_supabase", return_value=supabase), \
         patch.object(clients, "_provision_full_client") as prov, \
         patch.object(clients.brand_voice_service, "merge_raw_text", return_value=None), \
         patch.object(clients.icp_service, "merge_raw_text", return_value=None), \
         patch.object(clients.rank_location, "enqueue_location_derive") as rank_derive:
        result = asyncio.run(clients.create_client(body, auth={"user_id": "u1"}))
    # A prospect stays lightweight: no full provisioning, and (no GBP) no rank derive.
    prov.assert_not_called()
    rank_derive.assert_not_called()
    # The inserted row carried kind='prospect'.
    assert supabase.table.return_value.insert.call_args[0][0]["kind"] == "prospect"
    assert result.kind == "prospect"


def test_create_client_runs_full_provisioning():
    supabase = _create_supabase(_full_row(kind="client"))
    body = _base_create_body(kind="client")
    with patch.object(clients, "get_supabase", return_value=supabase), \
         patch.object(clients, "_provision_full_client") as prov, \
         patch.object(clients.brand_voice_service, "merge_raw_text", return_value=None), \
         patch.object(clients.icp_service, "merge_raw_text", return_value=None):
        asyncio.run(clients.create_client(body, auth={"user_id": "u1"}))
    prov.assert_called_once()
    assert supabase.table.return_value.insert.call_args[0][0]["kind"] == "client"


def test_provision_full_client_enqueues_expected_steps():
    supabase = _create_supabase({})
    client = {
        "id": "c1", "website_url": "https://acme.test",
        "github_repo": "org/repo", "gsc_property": "sc-domain:acme.test",
        "gbp": {"business_name": "Acme"},
    }
    with patch.object(clients, "get_supabase", return_value=supabase), \
         patch.object(clients, "_enqueue_website_scrape") as scrape, \
         patch.object(clients.github_infer, "enqueue_github_infer") as gh, \
         patch.object(clients, "_ensure_gsc_property_registered") as gsc, \
         patch.object(clients, "_enqueue_auto_brand_voice_icp") as auto, \
         patch.object(clients.rank_location, "enqueue_location_derive") as rank_derive:
        clients._provision_full_client(client, "u1")
    scrape.assert_called_once_with("c1", "https://acme.test")
    gh.assert_called_once_with("c1")
    gsc.assert_called_once()
    auto.assert_called_once()
    rank_derive.assert_called_once_with("c1")


def test_convert_prospect_flips_kind_and_provisions():
    row = _full_row(kind="prospect")
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.single.return_value = table
    table.update.return_value = table
    # First execute = fetch existing prospect; second = the update returning the row.
    table.execute.side_effect = [
        MagicMock(data=row),  # .single().execute() existing
        MagicMock(data=[{**row, "kind": "client"}]),  # update().execute()
    ]
    with patch.object(clients, "get_supabase", return_value=supabase), \
         patch.object(clients, "_provision_full_client") as prov:
        result = asyncio.run(clients.convert_prospect("p1", auth={"user_id": "u1"}))
    prov.assert_called_once()
    assert result.kind == "client"

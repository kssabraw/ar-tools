import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import clients  # noqa: E402


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

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import analysis_cache  # noqa: E402


def test_cache_key_prefers_code_and_normalizes():
    # location_code wins over the name; keyword whitespace/case normalized
    assert analysis_cache.cache_key("  Roof  Restoration ", 1000567, "anything") == "roof restoration::1000567"
    # no code → normalized location name
    assert analysis_cache.cache_key("Plumber", None, " Anaheim, CA ") == "plumber::anaheim, ca"


def _supabase_returning(rows):
    supabase = MagicMock()
    table = MagicMock()
    supabase.table.return_value = table
    for m in ("select", "eq", "limit", "upsert"):
        getattr(table, m).return_value = table
    table.execute.return_value = MagicMock(data=rows)
    return supabase


def test_get_returns_fresh_entry_marked_from_cache():
    fresh = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    supabase = _supabase_returning([
        {"analysis": {"keyword": "x", "analysis_cost": {"subtotal": 0.07}}, "created_at": fresh},
    ])
    with patch.object(analysis_cache, "get_supabase", return_value=supabase):
        with patch.object(analysis_cache.settings, "analysis_cache_ttl_days", 14):
            out = analysis_cache.get("roof restoration", 1000567, "Melbourne")
    assert out["keyword"] == "x"
    # served from cache → flagged + cost zeroed so it isn't double-counted
    assert out["from_cache"] is True
    assert out["analysis_cost"] == {"cached": True, "subtotal": 0.0}


def test_get_treats_stale_entry_as_miss():
    stale = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    supabase = _supabase_returning([{"analysis": {"keyword": "x"}, "created_at": stale}])
    with patch.object(analysis_cache, "get_supabase", return_value=supabase):
        with patch.object(analysis_cache.settings, "analysis_cache_ttl_days", 14):
            assert analysis_cache.get("roof restoration", 1000567, "Melbourne") is None


def test_get_miss_returns_none():
    supabase = _supabase_returning([])
    with patch.object(analysis_cache, "get_supabase", return_value=supabase):
        with patch.object(analysis_cache.settings, "analysis_cache_ttl_days", 14):
            assert analysis_cache.get("k", None, "loc") is None


def test_ttl_zero_disables_cache():
    with patch.object(analysis_cache.settings, "analysis_cache_ttl_days", 0):
        # get short-circuits before any supabase access
        assert analysis_cache.get("k", 1, "loc") is None
        analysis_cache.store("k", 1, "loc", {"a": 1})  # no-op, must not raise


def test_store_upserts_on_cache_key():
    supabase = _supabase_returning([])
    with patch.object(analysis_cache, "get_supabase", return_value=supabase):
        with patch.object(analysis_cache.settings, "analysis_cache_ttl_days", 14):
            analysis_cache.store("Roof Restoration", 1000567, "Melbourne", {"keyword": "x"})
    args, kwargs = supabase.table.return_value.upsert.call_args
    assert kwargs.get("on_conflict") == "cache_key"
    assert args[0]["cache_key"] == "roof restoration::1000567"
    assert args[0]["analysis"] == {"keyword": "x"}

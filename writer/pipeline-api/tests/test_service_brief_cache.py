"""Tests for the Service Page Brief research cache (mirrors test_brief_cache)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from modules.service_brief.cache import _normalize_keyword, get_cached, write_cache


def _make_supabase_mock(rows: list[dict]):
    table = MagicMock()
    table.select.return_value = table
    table.eq.return_value = table
    table.gte.return_value = table
    table.order.return_value = table
    table.limit.return_value = table
    table.execute.return_value = MagicMock(data=rows)
    table.insert.return_value = table

    client = MagicMock()
    client.table.return_value = table
    return client, table


def test_normalize_keyword():
    assert _normalize_keyword("  Emergency DRAIN cleaning ") == "emergency drain cleaning"


async def test_get_cached_hit():
    payload = {"mode": "local_service", "serp_profile": {}}
    rows = [{"output_payload": payload, "created_at": "2026-06-24T10:00:00Z"}]
    client, table = _make_supabase_mock(rows)
    with patch("modules.service_brief.cache.get_supabase", return_value=client):
        result = await get_cached("Emergency Drain Cleaning", 2840)
    assert result == payload
    table.eq.assert_any_call("keyword", "emergency drain cleaning")
    table.eq.assert_any_call("location_code", 2840)


async def test_get_cached_miss_returns_none():
    client, _ = _make_supabase_mock(rows=[])
    with patch("modules.service_brief.cache.get_supabase", return_value=client):
        assert await get_cached("x", 2840) is None


async def test_get_cached_swallows_db_errors():
    client = MagicMock()
    client.table.side_effect = RuntimeError("network down")
    with patch("modules.service_brief.cache.get_supabase", return_value=client):
        assert await get_cached("x", 2840) is None


async def test_write_cache_inserts_normalized_row():
    client, table = _make_supabase_mock(rows=[])
    with patch("modules.service_brief.cache.get_supabase", return_value=client):
        await write_cache(
            keyword="Emergency Drain Cleaning",
            location_code=2840,
            schema_version="1.0",
            output_payload={"mode": "local_service"},
            duration_ms=999,
        )
    inserted = table.insert.call_args[0][0]
    assert inserted["keyword"] == "emergency drain cleaning"
    assert inserted["schema_version"] == "1.0"
    assert inserted["output_payload"] == {"mode": "local_service"}
    assert inserted["duration_ms"] == 999


async def test_write_cache_omits_none_optionals():
    client, table = _make_supabase_mock(rows=[])
    with patch("modules.service_brief.cache.get_supabase", return_value=client):
        await write_cache(
            keyword="x", location_code=2840, schema_version="1.0", output_payload={},
        )
    inserted = table.insert.call_args[0][0]
    assert "cost_usd" not in inserted
    assert "duration_ms" not in inserted


async def test_write_cache_swallows_errors():
    client = MagicMock()
    client.table.side_effect = RuntimeError("DB down")
    with patch("modules.service_brief.cache.get_supabase", return_value=client):
        await write_cache(keyword="x", location_code=2840, schema_version="1.0", output_payload={})

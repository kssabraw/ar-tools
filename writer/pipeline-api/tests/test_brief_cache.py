"""Tests for the Brief Generator 7-day Supabase cache (Stage 10)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from modules.brief.cache import (
    _normalize_keyword,
    get_cached,
    write_cache,
)


def _make_supabase_mock(rows: list[dict]):
    """Build a mock supabase client whose query chain returns `rows`."""
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


# ----------------------------------------------------------------------
# _normalize_keyword
# ----------------------------------------------------------------------

def test_normalize_keyword_strips_and_lowercases():
    assert _normalize_keyword("  TIKTok shop  ") == "tiktok shop"


# ----------------------------------------------------------------------
# get_cached
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_cached_returns_payload_on_hit():
    payload = {"schema_version": "2.2", "keyword": "what is tiktok shop"}
    rows = [{"output_payload": payload, "created_at": "2026-04-30T10:00:00Z"}]
    client, table = _make_supabase_mock(rows)

    with patch("modules.brief.cache.get_supabase", return_value=client):
        result = await get_cached("What is TikTok Shop", 2840)

    assert result == payload
    # Verify the query was scoped correctly
    table.eq.assert_any_call("keyword", "what is tiktok shop")
    table.eq.assert_any_call("location_code", 2840)
    table.order.assert_called_once_with("created_at", desc=True)


@pytest.mark.asyncio
async def test_get_cached_returns_none_on_miss():
    client, _ = _make_supabase_mock(rows=[])
    with patch("modules.brief.cache.get_supabase", return_value=client):
        result = await get_cached("anything", 2840)
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_returns_none_when_payload_not_dict():
    """Defensive: a row with non-dict payload should not be returned."""
    rows = [{"output_payload": "not a dict", "created_at": "x"}]
    client, _ = _make_supabase_mock(rows)
    with patch("modules.brief.cache.get_supabase", return_value=client):
        result = await get_cached("x", 2840)
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_swallows_db_errors():
    """Lookup failures degrade silently — pipeline regenerates."""
    client = MagicMock()
    client.table.side_effect = RuntimeError("network down")
    with patch("modules.brief.cache.get_supabase", return_value=client):
        result = await get_cached("x", 2840)
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_logs_hit(caplog):
    rows = [{"output_payload": {"k": "v"}, "created_at": "now"}]
    client, _ = _make_supabase_mock(rows)
    with patch("modules.brief.cache.get_supabase", return_value=client):
        with caplog.at_level("INFO", logger="modules.brief.cache"):
            await get_cached("x", 2840)
    assert any(r.message == "brief.cache.hit" for r in caplog.records)


@pytest.mark.asyncio
async def test_get_cached_logs_miss(caplog):
    client, _ = _make_supabase_mock(rows=[])
    with patch("modules.brief.cache.get_supabase", return_value=client):
        with caplog.at_level("INFO", logger="modules.brief.cache"):
            await get_cached("x", 2840)
    assert any(r.message == "brief.cache.miss" for r in caplog.records)


@pytest.mark.asyncio
async def test_get_cached_uses_ttl_window():
    """Sanity: query uses the configured TTL window for the freshness gate."""
    from config import settings
    rows = []
    client, table = _make_supabase_mock(rows)
    before_call = datetime.now(timezone.utc)
    with patch("modules.brief.cache.get_supabase", return_value=client):
        await get_cached("x", 2840)
    # gte() was called once with the threshold timestamp
    threshold_str = table.gte.call_args[0][1]
    threshold = datetime.fromisoformat(threshold_str.replace("Z", "+00:00"))
    expected = before_call - timedelta(days=settings.brief_cache_ttl_days)
    # Allow 5-second slack for timing
    assert abs((threshold - expected).total_seconds()) < 5.0


# ----------------------------------------------------------------------
# write_cache
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_cache_inserts_row_with_normalized_keyword():
    client, table = _make_supabase_mock(rows=[])
    with patch("modules.brief.cache.get_supabase", return_value=client):
        await write_cache(
            keyword="What is TikTok Shop",
            location_code=2840,
            schema_version="2.2",
            output_payload={"k": "v"},
            triggered_by_client_id="client-uuid",
            duration_ms=12345,
        )

    table.insert.assert_called_once()
    inserted = table.insert.call_args[0][0]
    assert inserted["keyword"] == "what is tiktok shop"
    assert inserted["location_code"] == 2840
    assert inserted["schema_version"] == "2.2"
    assert inserted["output_payload"] == {"k": "v"}
    assert inserted["triggered_by_client_id"] == "client-uuid"
    assert inserted["duration_ms"] == 12345


@pytest.mark.asyncio
async def test_write_cache_omits_optional_fields_when_none():
    client, table = _make_supabase_mock(rows=[])
    with patch("modules.brief.cache.get_supabase", return_value=client):
        await write_cache(
            keyword="x",
            location_code=2840,
            schema_version="2.2",
            output_payload={},
        )

    inserted = table.insert.call_args[0][0]
    # Optional fields with None values are NOT inserted
    assert "triggered_by_client_id" not in inserted
    assert "cost_usd" not in inserted
    assert "duration_ms" not in inserted


@pytest.mark.asyncio
async def test_write_cache_swallows_errors():
    """Cache write failures must never bubble up."""
    client = MagicMock()
    client.table.side_effect = RuntimeError("DB down")
    with patch("modules.brief.cache.get_supabase", return_value=client):
        # Must not raise
        await write_cache(
            keyword="x",
            location_code=2840,
            schema_version="2.2",
            output_payload={},
        )


@pytest.mark.asyncio
async def test_write_cache_logs_failure(caplog):
    client = MagicMock()
    client.table.side_effect = RuntimeError("boom")
    with patch("modules.brief.cache.get_supabase", return_value=client):
        with caplog.at_level("WARNING", logger="modules.brief.cache"):
            await write_cache(
                keyword="x",
                location_code=2840,
                schema_version="2.2",
                output_payload={},
            )
    assert any(r.message == "brief.cache.write_failed" for r in caplog.records)

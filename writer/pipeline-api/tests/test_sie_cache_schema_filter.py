"""SIE cache schema-version validation tests.

After v1.4 we validate the cached payload's schema_version IN PYTHON
rather than via a SQL filter, so the cache works whether or not the DB
has a `schema_version` column. These tests verify:
  - A matching payload schema is returned.
  - A mismatched payload schema is rejected (treated as miss).
  - The query never adds an `.eq("schema_version", ...)` filter (which
    would 400 on DBs missing that column).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from modules.sie.cache import get_cached, write_cache


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


@pytest.mark.asyncio
async def test_get_cached_returns_payload_when_schema_matches():
    rows = [{
        "output_payload": {"schema_version": "1.4", "keyword": "kw"},
        "created_at": "2026-05-01T00:00:00Z",
    }]
    client, table = _make_supabase_mock(rows)
    with patch("modules.sie.cache.get_supabase", return_value=client):
        result = await get_cached("kw", 2840, "safe", schema_version="1.4")
    assert result is not None
    assert result["schema_version"] == "1.4"


@pytest.mark.asyncio
async def test_get_cached_treats_schema_mismatch_as_miss():
    """A 1.3 payload returned from the DB must be rejected when the
    caller expects 1.4 — otherwise SIEResponse.model_validate would
    raise on the Literal mismatch."""
    rows = [{
        "output_payload": {"schema_version": "1.3", "keyword": "kw"},
        "created_at": "2026-05-01T00:00:00Z",
    }]
    client, _ = _make_supabase_mock(rows)
    with patch("modules.sie.cache.get_supabase", return_value=client):
        result = await get_cached("kw", 2840, "safe", schema_version="1.4")
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_does_not_filter_by_schema_version_column():
    """Defensive against DB drift: the query must NEVER add
    .eq('schema_version', ...) — that would 400 on a sie_cache table
    without that column."""
    rows: list[dict] = []
    client, table = _make_supabase_mock(rows)
    with patch("modules.sie.cache.get_supabase", return_value=client):
        await get_cached("kw", 2840, "safe", schema_version="1.4")
    schema_version_calls = [
        c for c in table.eq.call_args_list
        if c.args and c.args[0] == "schema_version"
    ]
    assert schema_version_calls == []


@pytest.mark.asyncio
async def test_get_cached_works_without_schema_version_arg():
    """Backward compat: schema_version is optional; when omitted, the
    payload is returned regardless of its schema (legacy callers)."""
    rows = [{
        "output_payload": {"schema_version": "anything"},
        "created_at": "2026-05-01T00:00:00Z",
    }]
    client, _ = _make_supabase_mock(rows)
    with patch("modules.sie.cache.get_supabase", return_value=client):
        result = await get_cached("kw", 2840, "safe")
    assert result is not None


@pytest.mark.asyncio
async def test_write_cache_omits_optional_columns():
    """write_cache must NOT pass schema_version / cost_usd / duration_ms
    columns in the INSERT — they may not exist on every deploy's
    sie_cache table. The schema_version is preserved inside
    output_payload."""
    client, table = _make_supabase_mock(rows=[])
    with patch("modules.sie.cache.get_supabase", return_value=client):
        await write_cache(
            "kw", 2840, "safe",
            schema_version="1.4",
            output_payload={"schema_version": "1.4"},
            cost_usd=0.123,
            duration_ms=4567,
        )
    table.insert.assert_called_once()
    inserted_row = table.insert.call_args.args[0]
    assert "schema_version" not in inserted_row
    assert "cost_usd" not in inserted_row
    assert "duration_ms" not in inserted_row
    # And the essentials ARE present.
    assert inserted_row["keyword"] == "kw"
    assert inserted_row["location_code"] == 2840
    assert inserted_row["outlier_mode"] == "safe"
    assert inserted_row["output_payload"] == {"schema_version": "1.4"}

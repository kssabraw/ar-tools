"""SIE cache schema-version filter tests.

When SIE bumps its schema (e.g. 1.3 → 1.4), cached payloads from the
previous shape must be treated as misses — otherwise a Pydantic
Literal mismatch on schema_version aborts every SIE call until the
7-day TTL expires.

These tests verify `get_cached` plumbs schema_version into the
Supabase query as an `.eq("schema_version", ...)` filter.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from modules.sie.cache import get_cached


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
async def test_get_cached_filters_by_schema_version_when_provided():
    """Passing schema_version="1.4" must add an .eq filter so old-shape
    rows aren't returned."""
    rows = [{
        "output_payload": {"schema_version": "1.4", "keyword": "kw"},
        "created_at": "2026-05-01T00:00:00Z",
        "schema_version": "1.4",
    }]
    client, table = _make_supabase_mock(rows)
    with patch("modules.sie.cache.get_supabase", return_value=client):
        result = await get_cached(
            "kw", 2840, "safe", schema_version="1.4",
        )
    assert result is not None
    table.eq.assert_any_call("schema_version", "1.4")


@pytest.mark.asyncio
async def test_get_cached_omits_schema_version_filter_when_none():
    """Backward compat: when schema_version is None (legacy callers),
    no filter is added — same query as before this fix."""
    rows: list[dict] = []
    client, table = _make_supabase_mock(rows)
    with patch("modules.sie.cache.get_supabase", return_value=client):
        await get_cached("kw", 2840, "safe")
    schema_version_calls = [
        c for c in table.eq.call_args_list
        if c.args and c.args[0] == "schema_version"
    ]
    assert schema_version_calls == []


@pytest.mark.asyncio
async def test_get_cached_returns_none_when_schema_filter_excludes_all():
    """An old 1.3 row sitting in the cache must be invisible when we
    filter for 1.4 — the mock returns no rows under that filter."""
    client, _ = _make_supabase_mock(rows=[])
    with patch("modules.sie.cache.get_supabase", return_value=client):
        result = await get_cached(
            "kw", 2840, "safe", schema_version="1.4",
        )
    assert result is None

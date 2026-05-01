"""Tests for services.silo_dedup (Platform PRD v1.4 §8.5)."""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


def _vec(*comps, dim: int = 1536) -> list[float]:
    """Helper to build a unit vector with the leading axes specified."""
    out = [0.0] * dim
    for i, val in enumerate(comps):
        out[i] = val
    return _normalize(out)


# ----------------------------------------------------------------------
# _unit_normalize
# ----------------------------------------------------------------------

def test_unit_normalize_returns_unit_vector():
    from services.silo_dedup import _unit_normalize
    v = _unit_normalize([3.0, 4.0])
    assert v[0] == pytest.approx(0.6)
    assert v[1] == pytest.approx(0.8)


def test_unit_normalize_handles_zero_vector():
    from services.silo_dedup import _unit_normalize
    v = _unit_normalize([0.0, 0.0])
    assert v == [0.0, 0.0]


# ----------------------------------------------------------------------
# enqueue_silo_dedup
# ----------------------------------------------------------------------

def test_enqueue_inserts_async_jobs_row():
    from services import silo_dedup

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.insert.return_value = mock_table
    mock_table.execute.return_value = MagicMock(data=[{"id": "job-1"}])

    with patch.object(silo_dedup, "get_supabase", return_value=mock_supabase):
        silo_dedup.enqueue_silo_dedup(
            module_output_id="mo-1",
            run_id="run-1",
            client_id="client-1",
        )

    mock_supabase.table.assert_called_once_with("async_jobs")
    inserted = mock_table.insert.call_args[0][0]
    assert inserted["job_type"] == "silo_dedup"
    assert inserted["entity_id"] == "mo-1"
    assert inserted["payload"]["module_output_id"] == "mo-1"
    assert inserted["payload"]["run_id"] == "run-1"
    assert inserted["payload"]["client_id"] == "client-1"


def test_enqueue_swallows_errors():
    from services import silo_dedup
    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = RuntimeError("DB down")

    with patch.object(silo_dedup, "get_supabase", return_value=mock_supabase):
        # Must not raise — best-effort enqueue
        silo_dedup.enqueue_silo_dedup(
            module_output_id="mo",
            run_id="run",
            client_id="client",
        )


# ----------------------------------------------------------------------
# _find_match
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_match_returns_best_above_threshold():
    from services import silo_dedup

    target = _vec(1.0)
    close_existing = _vec(0.95, 0.31)
    far_existing = _vec(0.0, 1.0)

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.neq.return_value = mock_table
    mock_table.execute.return_value = MagicMock(
        data=[
            {
                "id": "row-close",
                "suggested_keyword": "close one",
                "suggested_keyword_embedding": close_existing,
                "status": "proposed",
                "source_run_ids": [],
                "occurrence_count": 1,
            },
            {
                "id": "row-far",
                "suggested_keyword": "far one",
                "suggested_keyword_embedding": far_existing,
                "status": "proposed",
                "source_run_ids": [],
                "occurrence_count": 1,
            },
        ]
    )

    with patch.object(silo_dedup, "get_supabase", return_value=mock_supabase):
        match = await silo_dedup._find_match("client-1", target)

    assert match is not None
    assert match["id"] == "row-close"
    assert match["_similarity"] >= 0.85


@pytest.mark.asyncio
async def test_find_match_returns_none_when_all_below_threshold():
    from services import silo_dedup

    target = _vec(1.0)
    too_far = _vec(0.0, 1.0)  # cosine 0

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.neq.return_value = mock_table
    mock_table.execute.return_value = MagicMock(
        data=[
            {
                "id": "row",
                "suggested_keyword_embedding": too_far,
                "status": "proposed",
                "source_run_ids": [],
                "occurrence_count": 1,
            }
        ]
    )

    with patch.object(silo_dedup, "get_supabase", return_value=mock_supabase):
        match = await silo_dedup._find_match("client-1", target)
    assert match is None


@pytest.mark.asyncio
async def test_find_match_handles_empty_pool():
    from services import silo_dedup

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.neq.return_value = mock_table
    mock_table.execute.return_value = MagicMock(data=[])

    with patch.object(silo_dedup, "get_supabase", return_value=mock_supabase):
        match = await silo_dedup._find_match("client-1", _vec(1.0))
    assert match is None


@pytest.mark.asyncio
async def test_find_match_parses_string_vector_format():
    """Supabase-py returns pgvector columns as strings like '[0.1,0.2,...]'."""
    from services import silo_dedup

    target = _vec(1.0, dim=4)
    # Build a near-identical 4D vector as a STRING (mimics supabase-py output)
    close_existing_str = "[" + ",".join(str(x) for x in _vec(0.95, 0.31, dim=4)) + "]"

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.neq.return_value = mock_table
    mock_table.execute.return_value = MagicMock(
        data=[
            {
                "id": "row-x",
                "suggested_keyword_embedding": close_existing_str,
                "status": "proposed",
                "source_run_ids": [],
                "occurrence_count": 1,
            }
        ]
    )

    with patch.object(silo_dedup, "get_supabase", return_value=mock_supabase):
        match = await silo_dedup._find_match("client-1", target)
    # Cosine of [1,0,0,0] vs [0.95, 0.31, 0, 0] is ~0.95 → above 0.85
    assert match is not None
    assert match["id"] == "row-x"


# ----------------------------------------------------------------------
# _process_one_candidate
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_skips_non_viable():
    from services import silo_dedup
    cand = {
        "suggested_keyword": "Some keyword",
        "viable_as_standalone_article": False,
    }
    result = await silo_dedup._process_one_candidate(
        cand, run_id="run-1", client_id="client-1",
    )
    assert result == "skipped_non_viable"


@pytest.mark.asyncio
async def test_process_skips_empty_keyword():
    from services import silo_dedup
    result = await silo_dedup._process_one_candidate(
        {"suggested_keyword": "  ", "viable_as_standalone_article": True},
        run_id="run", client_id="client",
    )
    assert result == "skipped_non_viable"


@pytest.mark.asyncio
async def test_process_inserts_new_when_no_match():
    from services import silo_dedup

    cand = {
        "suggested_keyword": "How TikTok Shop works",
        "viable_as_standalone_article": True,
        "search_demand_score": 0.55,
        "estimated_intent": "how-to",
        "routed_from": "scope_verification",
    }

    async def fake_embed(text):
        return _vec(1.0)

    async def fake_no_match(client_id, embedding):
        return None

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.insert.return_value = mock_table
    mock_table.execute.return_value = MagicMock(data=[{"id": "new-row"}])

    with (
        patch.object(silo_dedup, "_embed_keyword", fake_embed),
        patch.object(silo_dedup, "_find_match", fake_no_match),
        patch.object(silo_dedup, "get_supabase", return_value=mock_supabase),
    ):
        result = await silo_dedup._process_one_candidate(
            cand, run_id="run-1", client_id="client-1",
        )

    assert result == "new_insert"
    inserted = mock_table.insert.call_args[0][0]
    assert inserted["client_id"] == "client-1"
    assert inserted["status"] == "proposed"
    assert inserted["occurrence_count"] == 1
    assert inserted["source_run_ids"] == ["run-1"]
    assert inserted["estimated_intent"] == "how-to"


@pytest.mark.asyncio
async def test_process_increments_on_match():
    from services import silo_dedup

    cand = {
        "suggested_keyword": "TikTok algorithm tactics",
        "viable_as_standalone_article": True,
        "source_headings": [{"text": "new heading"}],
    }

    async def fake_embed(text):
        return _vec(1.0)

    async def fake_match(client_id, embedding):
        return {
            "id": "existing-row",
            "occurrence_count": 2,
            "source_run_ids": ["run-old"],
            "_similarity": 0.92,
        }

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.update.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.execute.return_value = MagicMock(data=[{}])

    with (
        patch.object(silo_dedup, "_embed_keyword", fake_embed),
        patch.object(silo_dedup, "_find_match", fake_match),
        patch.object(silo_dedup, "get_supabase", return_value=mock_supabase),
    ):
        result = await silo_dedup._process_one_candidate(
            cand, run_id="run-new", client_id="client-1",
        )

    assert result == "dedup_hit"
    update_payload = mock_table.update.call_args[0][0]
    assert update_payload["occurrence_count"] == 3
    assert update_payload["last_seen_run_id"] == "run-new"
    assert "run-old" in update_payload["source_run_ids"]
    assert "run-new" in update_payload["source_run_ids"]


@pytest.mark.asyncio
async def test_process_does_not_double_append_run_id():
    """If the same run_id is already in source_run_ids, it shouldn't be added again."""
    from services import silo_dedup

    cand = {"suggested_keyword": "x", "viable_as_standalone_article": True}

    async def fake_embed(text):
        return _vec(1.0)

    async def fake_match(client_id, embedding):
        return {
            "id": "row",
            "occurrence_count": 5,
            "source_run_ids": ["run-1"],
            "_similarity": 0.99,
        }

    mock_supabase = MagicMock()
    mock_table = MagicMock()
    mock_supabase.table.return_value = mock_table
    mock_table.update.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.execute.return_value = MagicMock(data=[{}])

    with (
        patch.object(silo_dedup, "_embed_keyword", fake_embed),
        patch.object(silo_dedup, "_find_match", fake_match),
        patch.object(silo_dedup, "get_supabase", return_value=mock_supabase),
    ):
        await silo_dedup._process_one_candidate(
            cand, run_id="run-1", client_id="client-1",
        )

    update_payload = mock_table.update.call_args[0][0]
    # source_run_ids should still contain "run-1" exactly once
    assert update_payload["source_run_ids"].count("run-1") == 1

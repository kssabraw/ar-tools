"""Unit tests for services.director.providers — the pure target-key helper,
plus the two providers directly load-bearing for E1 (prov_producers) and the
qa_idle predicate's data source (prov_qa)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from services.director import providers as P

TODAY = date(2026, 8, 28)


def test_target_key_prefers_keyword_over_page_url():
    assert P._target_key({"keyword": "Roof Repair", "page_url": "https://x.com/a"}) == "kw:roof repair"


def test_target_key_falls_back_to_page_url():
    assert P._target_key({"page_url": "HTTPS://X.com/A"}) == "url:https://x.com/a"


def test_target_key_none_when_empty():
    assert P._target_key({}) is None
    assert P._target_key(None) is None


def _table_mock(rows: list[dict]):
    mock = MagicMock()
    mock.select.return_value = mock
    mock.eq.return_value = mock
    mock.is_.return_value = mock
    mock.in_.return_value = mock
    mock.gte.return_value = mock
    mock.order.return_value = mock
    mock.limit.return_value = mock
    mock.not_.is_.return_value = mock
    mock.execute.return_value = MagicMock(data=rows)
    return mock


def test_prov_producers_flags_unknown_source_never_dropped():
    tasks = [
        {"id": "t1", "client_id": "c1", "source": "rank_drop"},
        {"id": "t2", "client_id": "c1", "source": "totally_new_producer"},
        {"id": "t3", "client_id": "c1", "source": "totally_new_producer"},
    ]
    sb = MagicMock()
    sb.table.return_value = _table_mock(tasks)

    result = P.prov_producers(sb, ["c1"], TODAY)

    assert result["open_by_source"] == {"rank_drop": 1, "totally_new_producer": 2}
    assert result["unwatched_seam"] == {"totally_new_producer": 2}


def test_prov_producers_no_unwatched_when_all_known():
    tasks = [{"id": "t1", "client_id": "c1", "source": "rank_drop"}]
    sb = MagicMock()
    sb.table.return_value = _table_mock(tasks)

    result = P.prov_producers(sb, ["c1"], TODAY)
    assert result["unwatched_seam"] is None


def test_prov_producers_empty_returns_none():
    sb = MagicMock()
    sb.table.return_value = _table_mock([])
    assert P.prov_producers(sb, ["c1"], TODAY) is None


def test_prov_producers_read_failure_returns_none():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("db down")
    assert P.prov_producers(sb, ["c1"], TODAY) is None


def test_prov_qa_reports_idle_when_nothing_entered():
    def table(name):
        if name == "task_activity":
            return _table_mock([])  # nothing entered QA
        if name == "qa_reviews":
            return _table_mock([{"verdict": "pass", "created_at": "2026-08-01"}])
        return _table_mock([])

    sb = MagicMock()
    sb.table.side_effect = table

    result = P.prov_qa(sb, TODAY)
    assert result["entered_in_qa_count"] == 0
    assert result["last_entered_at"] is None
    assert result["verdict_mix"] == {"pass": 1}


def test_prov_qa_counts_entries_by_trigger_status(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "qa_trigger_status", "in_qa")
    activity = [
        {"task_id": "t1", "detail": {"field": "status_key", "to": "in_qa"}, "created_at": "2026-08-27"},
        {"task_id": "t2", "detail": {"field": "status_key", "to": "in_progress"}, "created_at": "2026-08-26"},
    ]

    def table(name):
        if name == "task_activity":
            return _table_mock(activity)
        return _table_mock([])

    sb = MagicMock()
    sb.table.side_effect = table

    result = P.prov_qa(sb, TODAY)
    assert result["entered_in_qa_count"] == 1
    assert result["last_entered_at"] == "2026-08-27"


def test_prov_qa_both_empty_returns_none():
    sb = MagicMock()
    sb.table.return_value = _table_mock([])
    assert P.prov_qa(sb, TODAY) is None

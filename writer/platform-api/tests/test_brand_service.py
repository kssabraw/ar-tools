"""Unit tests for services.brand_service.compute_trends — pure rollup logic."""

from __future__ import annotations

from services import brand_service as bsvc


def _row(batch, engine, found, created_at, status="completed", competitor=False):
    return {
        "scan_batch_id": batch, "engine": engine, "mention_found": found,
        "created_at": created_at, "status": status, "is_competitor_scan": competitor,
    }


def test_compute_trends_empty():
    assert bsvc.compute_trends([]) == []


def test_compute_trends_rolls_up_per_engine_and_overall():
    rows = [
        _row("b1", "chatgpt", True, "2026-06-01T10:00:00Z"),
        _row("b1", "claude", False, "2026-06-01T10:00:05Z"),
        _row("b1", "gemini", True, "2026-06-01T10:00:10Z"),
    ]
    trends = bsvc.compute_trends(rows)
    assert len(trends) == 1
    b = trends[0]
    assert b["scan_batch_id"] == "b1"
    assert b["total"] == 3 and b["found"] == 2
    assert b["visibility_pct"] == 66.7
    assert b["engines"]["chatgpt"]["visibility_pct"] == 100.0
    assert b["engines"]["claude"]["visibility_pct"] == 0.0
    # The batch's timestamp is the earliest row in it.
    assert b["created_at"] == "2026-06-01T10:00:00Z"


def test_compute_trends_orders_batches_by_time_and_skips_incomplete():
    rows = [
        _row("late", "chatgpt", True, "2026-06-10T10:00:00Z"),
        _row("early", "chatgpt", True, "2026-06-01T10:00:00Z"),
        _row("early", "claude", None, "2026-06-01T10:00:00Z", status="failed"),  # skipped
    ]
    trends = bsvc.compute_trends(rows)
    assert [t["scan_batch_id"] for t in trends] == ["early", "late"]
    # The failed row is excluded from the early batch's totals.
    assert trends[0]["total"] == 1

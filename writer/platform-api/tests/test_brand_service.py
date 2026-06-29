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


# ── aggregate_response_analysis (batch-wide insights rollup) ──────────────────
def test_aggregate_response_analysis_rolls_up_batch():
    rows = [
        {"status": "completed", "engine": "chatgpt", "response_analysis": {
            "discovered_competitors": [{"name": "New Co", "attributes": ["fast"]}],
            "competitor_attributes": [{"name": "Rival", "attributes": ["24/7"]}],
            "aio": {"mention_kind": "citation_only"},
            "sources": {"by_type": {"directory": 2, "editorial": 1}},
        }},
        {"status": "completed", "engine": "google_ai_overview", "response_analysis": {
            "discovered_competitors": [{"name": "New Co", "attributes": ["licensed"]}],
            "competitor_attributes": [{"name": "Rival", "attributes": ["family-owned"]}],
            "aio": {"mention_kind": "in_content_link"},
            "sources": {"by_type": {"directory": 1}},
        }},
    ]
    out = bsvc.aggregate_response_analysis(rows)
    # Discovered competitor seen across both engines, attributes merged.
    disc = out["discovered_competitors"][0]
    assert disc["name"] == "New Co" and disc["count"] == 2
    assert set(disc["attributes"]) == {"fast", "licensed"}
    # AIO mention-kind + source-type tallies.
    assert out["aio_mention_kinds"] == {"citation_only": 1, "in_content_link": 1}
    assert out["source_types"] == {"directory": 3, "editorial": 1}
    # Cross-engine consensus surfaces Rival across both engines (Rival appears
    # in competitor_attributes; New Co in discovered_competitors — both count 2).
    rival = next(b for b in out["consensus"]["businesses"] if b["name"] == "Rival")
    assert rival["count"] == 2
    assert set(rival["attributes"]) == {"24/7", "family-owned"}

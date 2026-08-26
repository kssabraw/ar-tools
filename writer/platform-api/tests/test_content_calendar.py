"""Unit tests for the content calendar — pure range/row-normalization helpers.

No network: only the pure functions are exercised (the DB assembly hits Supabase
+ the fanout schema and is covered by integration testing).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import content_calendar as cc  # noqa: E402


# ── resolve_range ────────────────────────────────────────────────────────────


def test_resolve_range_pads_by_one_day_each_side():
    lo, hi = cc.resolve_range("2026-08-01", "2026-08-31", now=datetime(2026, 8, 15, tzinfo=timezone.utc))
    # start padded a day earlier, midnight; end padded a day later, end-of-day.
    assert lo.startswith("2026-07-31T00:00:00")
    assert hi.startswith("2026-09-01T23:59:59")


def test_resolve_range_defaults_to_current_month_when_absent():
    lo, hi = cc.resolve_range(None, None, now=datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc))
    # default start = first of the current month, padded a day back -> Jul 31.
    assert lo.startswith("2026-07-31T00:00:00")
    # default end = ~62 days out, padded a day forward.
    assert hi > lo


def test_resolve_range_swapped_bounds_are_clamped_not_negative():
    lo, hi = cc.resolve_range("2026-08-31", "2026-08-01", now=datetime(2026, 8, 15, tzinfo=timezone.utc))
    # end < start collapses to start; the padded window is still ordered.
    assert hi > lo
    assert lo.startswith("2026-08-30T00:00:00")


def test_resolve_range_ignores_garbage_dates():
    lo, hi = cc.resolve_range("not-a-date", "", now=datetime(2026, 8, 15, tzinfo=timezone.utc))
    assert lo.startswith("2026-07-31T00:00:00")  # fell back to current-month default
    assert hi > lo


# ── suite_row ────────────────────────────────────────────────────────────────


def _item(**over):
    row = {
        "id": "item-1", "batch_id": "batch-1", "client_id": "client-1",
        "keyword": "roof repair sydney", "location": "Sydney",
        "status": "scheduled", "scheduled_at": "2026-08-12T09:00:00+00:00",
    }
    row.update(over)
    return row


def test_suite_row_maps_batch_and_client():
    row = cc.suite_row(_item(), {"content_type": "service_page", "mode": "drip"}, "Acme Roofing")
    assert row == {
        "source": "content_scheduler",
        "parent_id": "batch-1",
        "item_id": "item-1",
        "client_id": "client-1",
        "client_name": "Acme Roofing",
        "content_type": "service_page",
        "mode": "drip",
        "label": "roof repair sydney",
        "location": "Sydney",
        "scheduled_at": "2026-08-12T09:00:00+00:00",
        "status": "scheduled",
    }


def test_suite_row_defaults_missing_batch_and_blank_keyword():
    row = cc.suite_row(_item(keyword="   "), None, None)
    assert row["content_type"] == "blog_post"   # default when batch is missing
    assert row["mode"] is None
    assert row["label"] == "Untitled page"      # blank keyword -> placeholder


# ── fanout_row ───────────────────────────────────────────────────────────────


def _run(**over):
    row = {
        "id": "run-1", "content_schedule_id": "sch-1", "session_id": "sess-1",
        "cluster_id": "cl-1", "status": "queued",
        "scheduled_at": "2026-08-13T09:00:00+00:00",
    }
    row.update(over)
    return row


def test_fanout_row_maps_schedule_and_label():
    row = cc.fanout_row(
        _run(), {"content_type": "local_seo_page", "mode": "weekly", "location": "Bondi"},
        "Best plumber in Bondi", "client-9", "Bondi Plumbing",
    )
    assert row == {
        "source": "fanout",
        "parent_id": "sch-1",
        "item_id": "run-1",
        "client_id": "client-9",
        "client_name": "Bondi Plumbing",
        "content_type": "local_seo_page",
        "mode": "weekly",
        "label": "Best plumber in Bondi",
        "location": "Bondi",
        "scheduled_at": "2026-08-13T09:00:00+00:00",
        "status": "queued",
    }


def test_fanout_row_falls_back_when_label_and_schedule_missing():
    row = cc.fanout_row(_run(), None, None, "client-9", None)
    assert row["content_type"] == "blog_post"
    assert row["label"] == "Untitled article"
    assert row["location"] is None


# ── sort ─────────────────────────────────────────────────────────────────────


def test_sort_rows_orders_by_scheduled_at_then_label():
    rows = [
        {"scheduled_at": "2026-08-13T09:00:00+00:00", "label": "b"},
        {"scheduled_at": "2026-08-12T09:00:00+00:00", "label": "z"},
        {"scheduled_at": "2026-08-13T09:00:00+00:00", "label": "a"},
        {"scheduled_at": None, "label": "no-date"},
    ]
    out = cc._sort_rows(list(rows))
    assert [r["label"] for r in out] == ["no-date", "z", "a", "b"]

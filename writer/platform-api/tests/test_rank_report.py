"""Unit tests for the scheduled-report due-logic (Organic Rank Tracker)."""

from __future__ import annotations

from datetime import date

from services.rank_report import is_report_due, render_report_markdown


def test_as_needed_never_due():
    assert is_report_due({"mode": "as_needed"}, date(2026, 6, 22)) is False


def test_weekly_due_on_matching_weekday():
    # 2026-06-22 is a Monday (weekday 0).
    assert is_report_due({"mode": "weekly", "day_of_week": 0}, date(2026, 6, 22)) is True
    assert is_report_due({"mode": "weekly", "day_of_week": 2}, date(2026, 6, 22)) is False


def test_not_generated_twice_same_day():
    cfg = {"mode": "weekly", "day_of_week": 0, "last_generated_at": "2026-06-22T08:00:00+00:00"}
    assert is_report_due(cfg, date(2026, 6, 22)) is False


def test_monthly_due_on_day_of_month():
    assert is_report_due({"mode": "monthly", "day_of_month": 22}, date(2026, 6, 22)) is True
    assert is_report_due({"mode": "monthly", "day_of_month": 10}, date(2026, 6, 22)) is False


def test_monthly_clamps_to_month_end():
    # February 2026 has 28 days; day_of_month 31 → fires on the 28th.
    assert is_report_due({"mode": "monthly", "day_of_month": 31}, date(2026, 2, 28)) is True


def test_interval_first_run_and_elapsed():
    assert is_report_due({"mode": "interval", "interval_days": 7}, date(2026, 6, 22)) is True  # no last
    cfg = {"mode": "interval", "interval_days": 14, "last_generated_at": "2026-06-08T00:00:00+00:00"}
    assert is_report_due(cfg, date(2026, 6, 22)) is True   # 14 days elapsed
    assert is_report_due(cfg, date(2026, 6, 21)) is False  # only 13 days


def _snapshot():
    return {
        "generated_at": "2026-06-22T10:00:00+00:00",
        "client": {"name": "Acme HVAC", "logo_url": None},
        "location": "Phoenix, Arizona",
        "gsc_connected": True,
        "overview": {"keyword_count": 2, "at_risk": 1, "avg_position_30d": 8.4,
                     "clicks_30d": 120, "impressions_30d": 3000,
                     "status_counts": {"climbing": 1, "deindex_risk": 1}},
        "keywords": [
            {"keyword": "ac repair", "status": "climbing", "primary_source": "gsc",
             "today_rank": None, "avg_30": 5.0, "avg_90": 9.0, "clicks_30d": 100,
             "direction": "up", "cpc": 12.0, "search_volume": 2400, "est_monthly_value": 800.0},
            {"keyword": "furnace install", "status": "deindex_risk", "primary_source": "gsc",
             "today_rank": None, "avg_30": None, "avg_90": 14.0, "clicks_30d": 20,
             "direction": "down", "cpc": None, "search_volume": None, "est_monthly_value": None},
        ],
    }


def test_render_markdown_has_sections_and_totals():
    md = render_report_markdown(_snapshot())
    assert "# Organic Rankings Report — Acme HVAC" in md
    assert "Phoenix, Arizona" in md
    assert "**Estimated monthly value:** $800" in md
    assert "Climbing 1" in md and "At risk 1" in md
    assert "## Top opportunities by estimated value" in md
    assert "ac repair" in md and "furnace install" in md
    # GSC mode → the full table has the GSC columns
    assert "| Keyword | Status | Today | 30d | 90d | Clicks |" in md


def test_render_markdown_dataforseo_mode_drops_gsc_columns():
    snap = _snapshot()
    snap["gsc_connected"] = False
    md = render_report_markdown(snap)
    assert "| Keyword | Status | Today |" in md
    assert "Clicks (30d)" not in md

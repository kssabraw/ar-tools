"""Unit tests for the scheduled-report due-logic (Organic Rank Tracker)."""

from __future__ import annotations

from datetime import date

from services.rank_report import is_report_due


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

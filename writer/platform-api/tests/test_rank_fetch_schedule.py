"""Unit tests for the per-client rank-fetch due-logic (Organic Rank Tracker)."""

from __future__ import annotations

from datetime import date

from services.dataforseo_rank import is_fetch_due

# 2026-06-22 is a Monday (weekday 0); default global weekday is Monday.
_MON = date(2026, 6, 22)
_DEFAULT_WEEKDAY = 0


def test_no_config_defaults_to_legacy_weekly_weekday():
    # A client with no schedule row keeps the legacy cadence: weekly on the
    # global default weekday (Monday here), and nothing on other days.
    assert is_fetch_due({}, _MON, _DEFAULT_WEEKDAY) is True
    assert is_fetch_due({}, date(2026, 6, 23), _DEFAULT_WEEKDAY) is False  # Tuesday


def test_off_never_due():
    assert is_fetch_due({"mode": "off"}, _MON, _DEFAULT_WEEKDAY) is False


def test_weekly_due_on_matching_weekday():
    assert is_fetch_due({"mode": "weekly", "day_of_week": 0}, _MON, _DEFAULT_WEEKDAY) is True
    assert is_fetch_due({"mode": "weekly", "day_of_week": 2}, _MON, _DEFAULT_WEEKDAY) is False


def test_weekly_null_day_falls_back_to_default_weekday():
    # A weekly row without an explicit day uses the global default weekday.
    assert is_fetch_due({"mode": "weekly"}, _MON, 0) is True
    assert is_fetch_due({"mode": "weekly"}, _MON, 3) is False


def test_not_fetched_twice_same_day():
    cfg = {"mode": "weekly", "day_of_week": 0, "last_fetched_at": "2026-06-22T08:00:00+00:00"}
    assert is_fetch_due(cfg, _MON, _DEFAULT_WEEKDAY) is False


def test_monthly_due_on_day_of_month():
    assert is_fetch_due({"mode": "monthly", "day_of_month": 22}, _MON, _DEFAULT_WEEKDAY) is True
    assert is_fetch_due({"mode": "monthly", "day_of_month": 10}, _MON, _DEFAULT_WEEKDAY) is False


def test_monthly_clamps_to_month_end():
    # February 2026 has 28 days; day_of_month 31 → fires on the 28th.
    assert is_fetch_due({"mode": "monthly", "day_of_month": 31}, date(2026, 2, 28), _DEFAULT_WEEKDAY) is True


def test_interval_first_run_and_elapsed():
    assert is_fetch_due({"mode": "interval", "interval_days": 7}, _MON, _DEFAULT_WEEKDAY) is True  # no last
    cfg = {"mode": "interval", "interval_days": 14, "last_fetched_at": "2026-06-08T00:00:00+00:00"}
    assert is_fetch_due(cfg, _MON, _DEFAULT_WEEKDAY) is True   # 14 days elapsed
    assert is_fetch_due(cfg, date(2026, 6, 21), _DEFAULT_WEEKDAY) is False  # only 13 days

"""Unit tests for services.brand_schedule.compute_next_run_at — pure clock math."""

from __future__ import annotations

from datetime import datetime, timezone

from services import brand_schedule as bsch


def _utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_disabled_has_no_next_run():
    assert bsch.compute_next_run_at(_utc(2026, 6, 27, 12), "disabled", None, None, 9) is None


def test_weekly_picks_the_right_weekday_and_hour():
    now = _utc(2026, 6, 24, 12)  # a Wednesday at 12:00
    nxt = bsch.compute_next_run_at(now, "weekly", 4, None, 9)  # Friday @ 09:00 UTC
    assert nxt is not None
    assert nxt.weekday() == 4
    assert nxt.hour == 9
    assert nxt > now
    assert (nxt - now).days < 7


def test_weekly_same_day_after_hour_rolls_to_next_week():
    now = _utc(2026, 6, 24, 12)  # Wednesday 12:00
    nxt = bsch.compute_next_run_at(now, "weekly", now.weekday(), None, 9)  # today @ 09:00 already passed
    assert nxt.weekday() == now.weekday()
    assert nxt.hour == 9
    assert nxt.date() > now.date()


def test_monthly_past_day_rolls_to_next_month():
    nxt = bsch.compute_next_run_at(_utc(2026, 6, 27, 12), "monthly", None, 15, 9)
    assert (nxt.year, nxt.month, nxt.day, nxt.hour) == (2026, 7, 15, 9)


def test_monthly_future_day_stays_this_month():
    nxt = bsch.compute_next_run_at(_utc(2026, 6, 10, 12), "monthly", None, 15, 9)
    assert (nxt.month, nxt.day) == (6, 15)


def test_monthly_december_rolls_over_year():
    nxt = bsch.compute_next_run_at(_utc(2026, 12, 20, 12), "monthly", None, 5, 9)
    assert (nxt.year, nxt.month, nxt.day) == (2027, 1, 5)

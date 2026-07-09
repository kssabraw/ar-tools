"""Pure tests for the fanout schedule planner's cadences
(fanout.writer.schedule_planner.plan_runs).

Covers the recurring modes added on top of all_at_once / drip / fixed:
weekly (N per week on a weekday), monthly_date (N per month on a day-of-month),
and monthly_weekday (N per month on the Kth weekday, -1 = last). All finite:
articles fill per-period buckets of `per_day` and the schedule ends once the
batch is placed.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, time, timedelta

import pytest

from fanout.writer.schedule_planner import ScheduleError, plan_runs

_IDS = [f"c{i}" for i in range(5)]
_TOD = time(9, 0)


def _dates(runs):
    return sorted({r.scheduled_at.date() for r in runs})


def test_weekly_on_weekday_buckets_by_count():
    # 2/week on Wednesday (weekday=2); start Mon 2026-07-06 -> first Wed 07-08.
    runs = plan_runs(_IDS, mode="weekly", per_day=2, start_date=date(2026, 7, 6),
                     time_of_day=_TOD, tz_name="UTC", weekday=2)
    days = _dates(runs)
    assert days == [date(2026, 7, 8), date(2026, 7, 15), date(2026, 7, 22)]
    assert all(d.weekday() == 2 for d in days)
    counts = Counter(r.scheduled_at.date() for r in runs)
    assert counts[date(2026, 7, 8)] == 2 and counts[date(2026, 7, 22)] == 1


def test_weekly_requires_weekday():
    with pytest.raises(ScheduleError):
        plan_runs(_IDS, mode="weekly", per_day=2, start_date=date(2026, 7, 6),
                  time_of_day=_TOD)


def test_weekly_multiple_weekdays_each_a_slot():
    # One per selected weekday: Tue(1) + Thu(3), Mon 2026-07-06 start. Unsorted input.
    runs = plan_runs([f"c{i}" for i in range(6)], mode="weekly", per_day=1,
                     start_date=date(2026, 7, 6), time_of_day=_TOD, tz_name="UTC",
                     weekdays=[3, 1])
    assert _dates(runs) == [date(2026, 7, 7), date(2026, 7, 9), date(2026, 7, 14),
                            date(2026, 7, 16), date(2026, 7, 21), date(2026, 7, 23)]


def test_weekly_multiple_weekdays_per_slot_count():
    # per_day=2 with two weekdays => 4/week (2 on each selected day).
    runs = plan_runs([f"c{i}" for i in range(4)], mode="weekly", per_day=2,
                     start_date=date(2026, 7, 6), time_of_day=_TOD, tz_name="UTC",
                     weekdays=[1, 3])
    counts = Counter(r.scheduled_at.date() for r in runs)
    assert counts[date(2026, 7, 7)] == 2 and counts[date(2026, 7, 9)] == 2


def test_weekly_multiple_weekdays_skips_pre_start_days():
    # Wed start: Tue of that week is before start and skipped.
    runs = plan_runs([f"c{i}" for i in range(3)], mode="weekly", per_day=1,
                     start_date=date(2026, 7, 8), time_of_day=_TOD, tz_name="UTC",
                     weekdays=[1, 3])
    assert _dates(runs) == [date(2026, 7, 9), date(2026, 7, 14), date(2026, 7, 16)]


def test_weekly_empty_weekdays_rejected():
    with pytest.raises(ScheduleError):
        plan_runs(_IDS, mode="weekly", per_day=1, start_date=date(2026, 7, 6),
                  time_of_day=_TOD, weekdays=[])


def test_monthly_date_anchors_next_month_when_day_passed():
    # 2/month on the 15th; start 07-20 -> Jul 15 already gone, so first is Aug 15.
    runs = plan_runs(_IDS, mode="monthly_date", per_day=2, start_date=date(2026, 7, 20),
                     time_of_day=_TOD, tz_name="UTC", day_of_month=15)
    assert _dates(runs) == [date(2026, 8, 15), date(2026, 9, 15), date(2026, 10, 15)]


def test_monthly_date_clamps_to_month_length():
    runs = plan_runs(["a"], mode="monthly_date", per_day=1, start_date=date(2027, 2, 1),
                     time_of_day=_TOD, tz_name="UTC", day_of_month=31)
    assert runs[0].scheduled_at.date() == date(2027, 2, 28)


def test_monthly_weekday_first_monday():
    runs = plan_runs(_IDS, mode="monthly_weekday", per_day=2, start_date=date(2026, 7, 6),
                     time_of_day=_TOD, tz_name="UTC", weekday=0, week_of_month=1)
    days = _dates(runs)
    assert days == [date(2026, 7, 6), date(2026, 8, 3), date(2026, 9, 7)]
    assert all(d.weekday() == 0 for d in days)


def test_monthly_weekday_last_friday():
    runs = plan_runs(["a"], mode="monthly_weekday", per_day=1, start_date=date(2026, 7, 1),
                     time_of_day=_TOD, tz_name="UTC", weekday=4, week_of_month=-1)
    assert runs[0].scheduled_at.date() == date(2026, 7, 31)


def test_no_span_cap_allows_multi_year_drip():
    # 800 articles at 1/day spans > 2 years — no span cap (owner ruling 2026-07-09).
    ids = [f"c{i}" for i in range(800)]
    runs = plan_runs(ids, mode="drip", per_day=1, start_date=date(2026, 1, 1),
                     time_of_day=_TOD, tz_name="UTC")
    assert len(runs) == 800
    assert runs[-1].scheduled_at.date() == date(2026, 1, 1) + timedelta(days=799)


def test_existing_modes_unchanged():
    assert len(plan_runs(_IDS, mode="all_at_once")) == 5
    assert len(plan_runs(_IDS, mode="drip", per_day=2, start_date=date(2026, 7, 6),
                         time_of_day=_TOD)) == 5
    fixed = plan_runs(_IDS, mode="fixed", start_date=date(2026, 7, 6), time_of_day=_TOD)
    assert len({r.scheduled_at for r in fixed}) == 1

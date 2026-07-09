"""M15 slice 3 — schedule planner (pure, handoff.md §9.4).

`Schedule all` materializes one `content_schedules` + N `scheduled_article_runs`. This module
decides the deterministic ordering + each run's `scheduled_at`; persistence is the storage
layer's job.

- **Pillars-first ordering**: clusters are emitted silo-by-silo in architecture order (a
  pillar's supporting articles grouped together), so a supporting article never generates
  before its silo-mates — its up-link resolves. Stable + deterministic.
- **all_at_once**: every run is due `now`.
- **drip N/day**: run i is due `start_date + floor(i / per_day)` days at `time_of_day` in
  `timezone`, stored as UTC. Validated so the schedule never spans > 365 days.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

MAX_SCHEDULE_DAYS = 365

# Drip-like cadences: articles are placed in per-period buckets of `per_day` (the
# count-per-period, reused across all of these), one bucket per successive period.
_PERIODIC_MODES = ("drip", "weekly", "monthly_date", "monthly_weekday")


class ScheduleError(ValueError):
    """Invalid schedule parameters (the API maps this to a 400 with the hint)."""

    def __init__(self, message: str, *, min_per_day: int | None = None) -> None:
        super().__init__(message)
        self.min_per_day = min_per_day


@dataclass
class PlannedRun:
    cluster_id: str
    scheduled_at: datetime          # tz-aware UTC


def order_clusters(architecture: dict | None, all_cluster_ids: list[str]) -> list[str]:
    """Order clusters pillars-first: walk the architecture's pillars in order, emitting each
    pillar's supporting-article cluster ids (that still exist), then append any clusters not
    referenced by the architecture (stable input order). No architecture -> input order."""
    valid = list(dict.fromkeys(cid for cid in all_cluster_ids if cid))
    if not architecture:
        return valid
    valid_set = set(valid)
    ordered: list[str] = []
    seen: set[str] = set()
    for pillar in architecture.get("pillars", []):
        for cid in pillar.get("supporting_article_ids", []):
            if cid in valid_set and cid not in seen:
                ordered.append(cid)
                seen.add(cid)
    for cid in valid:                       # clusters the architecture doesn't reference
        if cid not in seen:
            ordered.append(cid)
            seen.add(cid)
    return ordered


def schedule_days(count: int, per_day: int) -> int:
    """Calendar days a drip of `count` at `per_day` spans (the last day may be partial)."""
    if per_day < 1:
        raise ScheduleError("per_day must be >= 1")
    return math.ceil(count / per_day)


def finish_date(start: date, count: int, per_day: int) -> date:
    """Date the last article is scheduled for (inclusive)."""
    return start + timedelta(days=schedule_days(count, per_day) - 1)


def _first_weekday_on_or_after(start: date, weekday: int) -> date:
    """The first date >= `start` whose weekday (0=Mon .. 6=Sun) is `weekday`."""
    return start + timedelta(days=(weekday - start.weekday()) % 7)


def _add_months(year: int, month: int, k: int) -> tuple[int, int]:
    """(year, month) advanced by `k` calendar months (month 1..12)."""
    idx = (month - 1) + k
    return year + idx // 12, idx % 12 + 1


def _nth_weekday_of_month(year: int, month: int, weekday: int, nth: int) -> date | None:
    """The `nth` occurrence of `weekday` in a month. nth=1..4 counts from the start,
    nth=-1 is the last occurrence. Returns None when an nth (1..4) doesn't exist that
    month (only possible for a 5th, which we don't offer)."""
    last_day = calendar.monthrange(year, month)[1]
    if nth == -1:
        d = date(year, month, last_day)
        return d - timedelta(days=(d.weekday() - weekday) % 7)
    first = date(year, month, 1)
    day = 1 + (weekday - first.weekday()) % 7 + (nth - 1) * 7
    return date(year, month, day) if day <= last_day else None


def _period_dates(
    mode: str, n_periods: int, *, start: date, weekday: int | None,
    weekdays: list[int] | None, day_of_month: int | None, week_of_month: int | None,
) -> list[date]:
    """The local start-date of each successive period (bucket slot) for a periodic
    cadence. Weekly supports MULTIPLE weekdays: each selected weekday is its own slot
    every week (e.g. {Tue, Thu} = two slots/week), emitted chronologically."""
    if mode == "drip":
        return [start + timedelta(days=k) for k in range(n_periods)]
    if mode == "weekly":
        days = sorted({d for d in (weekdays or ([weekday] if weekday is not None else []))
                       if d is not None and 0 <= d <= 6})
        if not days:
            raise ScheduleError("A weekly schedule requires at least one weekday (0=Mon .. 6=Sun).")
        base_monday = start - timedelta(days=start.weekday())   # Monday of start's week
        out: list[date] = []
        k = 0
        while len(out) < n_periods:
            for wd in days:                                     # ascending weekday -> chronological
                d = base_monday + timedelta(days=k * 7 + wd)
                if d >= start:
                    out.append(d)
                    if len(out) >= n_periods:
                        break
            k += 1
        return out
    if mode == "monthly_date":
        if not day_of_month or not (1 <= day_of_month <= 31):
            raise ScheduleError("A monthly schedule requires a day of month (1-31).")
        out: list[date] = []
        # Anchor on this month if its clamped day is still >= start, else next month.
        y, m = start.year, start.month
        first_day = min(day_of_month, calendar.monthrange(y, m)[1])
        if date(y, m, first_day) < start:
            y, m = _add_months(y, m, 1)
        for k in range(n_periods):
            yy, mm = _add_months(y, m, k)
            out.append(date(yy, mm, min(day_of_month, calendar.monthrange(yy, mm)[1])))
        return out
    if mode == "monthly_weekday":
        if weekday is None or week_of_month is None:
            raise ScheduleError(
                "A monthly-by-weekday schedule requires a weekday and which occurrence "
                "(1-4, or -1 for last)."
            )
        out2: list[date] = []
        y, m = start.year, start.month
        first = _nth_weekday_of_month(y, m, weekday, week_of_month)
        if first is None or first < start:
            y, m = _add_months(y, m, 1)
        k = 0
        while len(out2) < n_periods:
            yy, mm = _add_months(y, m, k)
            d = _nth_weekday_of_month(yy, mm, weekday, week_of_month)
            if d is not None:
                out2.append(d)
            k += 1
        return out2
    raise ScheduleError(f"Unknown mode: {mode}")


def plan_runs(
    ordered_cluster_ids: list[str], *, mode: str, per_day: int | None = None,
    start_date: date | None = None, time_of_day: time | None = None, tz_name: str = "UTC",
    weekday: int | None = None, weekdays: list[int] | None = None,
    day_of_month: int | None = None, week_of_month: int | None = None,
    now_utc: datetime | None = None,
) -> list[PlannedRun]:
    """Compute each run's `scheduled_at`. Raises ScheduleError on bad params (incl. a
    schedule that would span > 365 days, carrying the `min_per_day` hint).

    Periodic modes (drip/weekly/monthly_date/monthly_weekday) place articles in
    per-period buckets of `per_day` (the count per slot). For weekly, each selected
    weekday is its own slot every week — pass `weekdays` (a set) for multiple days
    (e.g. Tue+Thu = 2 slots/week); `weekday` is the single-day fallback.
    `day_of_month`/`week_of_month` anchor the monthly cadences."""
    now = now_utc or datetime.now(timezone.utc)
    ids = [c for c in ordered_cluster_ids if c]
    if not ids:
        raise ScheduleError("No clusters to schedule")

    if mode == "all_at_once":
        return [PlannedRun(cid, now) for cid in ids]
    if mode == "fixed":
        # All selected articles written on one chosen calendar day (e.g. "deliver July 4 ->
        # write July 3"). start_date is the target day; time_of_day/tz set the moment.
        if not start_date:
            raise ScheduleError("A specific-date schedule requires a target date")
        target = _local_to_utc(start_date, time_of_day or time(9, 0), tz_name)
        return [PlannedRun(cid, target) for cid in ids]
    if mode not in _PERIODIC_MODES:
        raise ScheduleError(f"Unknown mode: {mode}")

    if not per_day or per_day < 1:
        raise ScheduleError("This schedule requires a count per period >= 1", )
    start = start_date or now.date()
    tod = time_of_day or time(9, 0)
    n_periods = math.ceil(len(ids) / per_day)
    period_dates = _period_dates(
        mode, n_periods, start=start, weekday=weekday, weekdays=weekdays,
        day_of_month=day_of_month, week_of_month=week_of_month,
    )
    span = (period_dates[-1] - start).days + 1 if period_dates else 0
    if span > MAX_SCHEDULE_DAYS:
        raise ScheduleError(
            f"Schedule spans {span} days (> {MAX_SCHEDULE_DAYS}). Increase the count per period.",
            min_per_day=math.ceil(len(ids) / MAX_SCHEDULE_DAYS),
        )
    return [
        PlannedRun(cid, _local_to_utc(period_dates[i // per_day], tod, tz_name))
        for i, cid in enumerate(ids)
    ]


def _local_to_utc(d: date, tod: time, tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:  # noqa: BLE001 — unknown tz -> 400
        raise ScheduleError(f"Unknown timezone: {tz_name}") from exc
    return datetime.combine(d, tod, tzinfo=tz).astimezone(timezone.utc)

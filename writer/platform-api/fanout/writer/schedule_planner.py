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

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

MAX_SCHEDULE_DAYS = 365


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


def plan_runs(
    ordered_cluster_ids: list[str], *, mode: str, per_day: int | None = None,
    start_date: date | None = None, time_of_day: time | None = None, tz_name: str = "UTC",
    now_utc: datetime | None = None,
) -> list[PlannedRun]:
    """Compute each run's `scheduled_at`. Raises ScheduleError on bad params (incl. a drip
    that would span > 365 days, carrying the `min_per_day` hint)."""
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
    if mode != "drip":
        raise ScheduleError(f"Unknown mode: {mode}")

    if not per_day or per_day < 1:
        raise ScheduleError("Drip requires per_day >= 1")
    days = schedule_days(len(ids), per_day)
    if days > MAX_SCHEDULE_DAYS:
        raise ScheduleError(
            f"Schedule spans {days} days (> {MAX_SCHEDULE_DAYS}). Increase per_day.",
            min_per_day=math.ceil(len(ids) / MAX_SCHEDULE_DAYS),
        )
    start = start_date or now.date()
    tod = time_of_day or time(9, 0)
    runs: list[PlannedRun] = []
    for i, cid in enumerate(ids):
        runs.append(PlannedRun(cid, _local_to_utc(start + timedelta(days=i // per_day), tod, tz_name)))
    return runs


def _local_to_utc(d: date, tod: time, tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:  # noqa: BLE001 — unknown tz -> 400
        raise ScheduleError(f"Unknown timezone: {tz_name}") from exc
    return datetime.combine(d, tod, tzinfo=tz).astimezone(timezone.utc)

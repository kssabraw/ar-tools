"""AI Visibility (Brand Strength) — scheduled scans.

A per-client `brand_scan_schedules` row drives a recurring scan (weekly/monthly).
Scheduling reuses the suite's shared in-process scheduler (services/gsc_scheduler)
— no new cron infra (locked decision). Each schedule carries its own
`next_run_at`; the scheduler tick enqueues any that are due and advances the
clock. Day-of-week uses Python's convention: Monday=0 … Sunday=6.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from db.supabase_client import get_supabase
from services import brand_service
from services.brand_scan import ENGINE_ORDER, ENGINES, enqueue_brand_scan

logger = logging.getLogger("brand_schedule")

_VALID_CADENCES = {"weekly", "monthly", "disabled"}


def compute_next_run_at(
    now: datetime,
    cadence: str,
    day_of_week: Optional[int],
    day_of_month: Optional[int],
    hour_utc: int,
) -> Optional[datetime]:
    """Next fire time strictly after `now` (UTC). None when disabled. Pure."""
    if cadence == "disabled":
        return None
    if cadence == "weekly":
        dow = day_of_week if day_of_week is not None else 0
        days_ahead = (dow - now.weekday()) % 7
        candidate = (now + timedelta(days=days_ahead)).replace(
            hour=hour_utc, minute=0, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate
    if cadence == "monthly":
        dom = day_of_month if day_of_month is not None else 1
        candidate = now.replace(day=dom, hour=hour_utc, minute=0, second=0, microsecond=0)
        if candidate <= now:
            year = now.year + (1 if now.month == 12 else 0)
            month = 1 if now.month == 12 else now.month + 1
            candidate = candidate.replace(year=year, month=month)
        return candidate
    raise HTTPException(status_code=400, detail="invalid_cadence")


def _default_schedule() -> dict:
    return {
        "cadence": "disabled", "day_of_week": None, "day_of_month": None,
        "hour_utc": 9, "selected_engines": list(ENGINE_ORDER),
        "include_competitors": False, "is_active": False,
        "next_run_at": None, "last_run_at": None,
    }


def get_schedule(client_id: str) -> dict:
    res = (
        get_supabase().table("brand_scan_schedules")
        .select("cadence, day_of_week, day_of_month, hour_utc, selected_engines, "
                "include_competitors, is_active, next_run_at, last_run_at")
        .eq("client_id", client_id)
        .limit(1)
        .execute().data
    )
    return res[0] if res else _default_schedule()


def upsert_schedule(
    client_id: str,
    cadence: str,
    day_of_week: Optional[int],
    day_of_month: Optional[int],
    hour_utc: int,
    selected_engines: Optional[list[str]],
    include_competitors: bool,
    is_active: bool,
) -> dict:
    if cadence not in _VALID_CADENCES:
        raise HTTPException(status_code=400, detail="invalid_cadence")
    if not 0 <= hour_utc <= 23:
        raise HTTPException(status_code=400, detail="invalid_hour")
    engines = selected_engines if selected_engines is not None else list(ENGINE_ORDER)
    if any(e not in ENGINES for e in engines) or not engines:
        raise HTTPException(status_code=400, detail="invalid_engine")
    if cadence == "weekly" and day_of_week is None:
        day_of_week = 0
    if cadence == "monthly" and day_of_month is None:
        day_of_month = 1

    now = datetime.now(timezone.utc)
    next_run = compute_next_run_at(now, cadence, day_of_week, day_of_month, hour_utc)
    # A disabled or inactive schedule has no next run.
    next_run_iso = next_run.isoformat() if (next_run and is_active and cadence != "disabled") else None

    row = {
        "client_id": client_id, "cadence": cadence, "day_of_week": day_of_week,
        "day_of_month": day_of_month, "hour_utc": hour_utc, "selected_engines": engines,
        "include_competitors": include_competitors, "is_active": is_active,
        "next_run_at": next_run_iso, "updated_at": "now()",
    }
    (
        get_supabase().table("brand_scan_schedules")
        .upsert(row, on_conflict="client_id")
        .execute()
    )
    return get_schedule(client_id)


def _has_pending_scan(supabase, client_id: str) -> bool:
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "brand_scan").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    return bool(existing.data)


def enqueue_due_brand_scans() -> int:
    """Scheduler tick: enqueue a brand_scan for each active schedule whose
    next_run_at is due, then advance its clock. Returns the count enqueued."""
    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    due = (
        supabase.table("brand_scan_schedules")
        .select("client_id, cadence, day_of_week, day_of_month, hour_utc, "
                "selected_engines, include_competitors")
        .eq("is_active", True)
        .neq("cadence", "disabled")
        .lte("next_run_at", now.isoformat())
        .execute().data or []
    )
    enqueued = 0
    for sched in due:
        client_id = sched["client_id"]
        next_run = compute_next_run_at(
            now, sched["cadence"], sched.get("day_of_week"),
            sched.get("day_of_month"), sched["hour_utc"],
        )
        # Always advance the clock so a keywordless or in-flight client doesn't
        # re-fire every tick.
        supabase.table("brand_scan_schedules").update({
            "last_run_at": now.isoformat(),
            "next_run_at": next_run.isoformat() if next_run else None,
        }).eq("client_id", client_id).execute()

        if _has_pending_scan(supabase, client_id):
            continue
        active = [k["id"] for k in brand_service.list_keywords(client_id, include_inactive=False)]
        if not active:
            continue
        try:
            enqueue_brand_scan(
                client_id, active, sched["selected_engines"],
                bool(sched.get("include_competitors")), None,
            )
            enqueued += 1
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("brand_schedule.enqueue_failed", extra={"client_id": client_id, "error": str(exc)})
    if enqueued:
        logger.info("brand_schedule.enqueued", extra={"clients": enqueued})
    return enqueued

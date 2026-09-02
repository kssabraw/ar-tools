"""Worker-lane observability — an admin read of where async jobs are queueing.

Read-only. Reports each in-process worker lane's live queue depth (pending +
running under the lane's own claim filter) plus the bulk lane's per-client
running breakdown (so you can see whether one client's batch is dominating and
whether raising `bulk_lane_workers` is warranted). A few lightweight count
queries per call.

The lane shapes mirror the launcher in `main.py` (MAIN / INTERACTIVE / FANOUT /
BULK, priority-fenced per `services/job_priority.py`). Keep this list in sync
with that launcher.
"""

from __future__ import annotations

from typing import List, Optional

from config import settings
from db.supabase_client import get_supabase
from services import job_priority


def _count(supabase, status: str, job_types: Optional[List[str]] = None,
           exclude: Optional[List[str]] = None,
           priority_min: Optional[int] = None,
           priority_max: Optional[int] = None) -> int:
    try:
        q = supabase.table("async_jobs").select("id", count="exact").eq("status", status)
        if job_types:
            q = q.in_("job_type", job_types)
        if exclude:
            q = q.not_.in_("job_type", exclude)
        if priority_min is not None:
            q = q.gte("priority", priority_min)
        if priority_max is not None:
            q = q.lte("priority", priority_max)
        return int(q.execute().count or 0)
    except Exception:  # noqa: BLE001 — observability is advisory, never 500 on it
        return -1


def _running_by_client(supabase, exclude: Optional[List[str]],
                       priority_max: Optional[int]) -> dict[str, int]:
    try:
        q = supabase.table("async_jobs").select("entity_id").eq("status", "running")
        if exclude:
            q = q.not_.in_("job_type", exclude)
        if priority_max is not None:
            q = q.lte("priority", priority_max)
        rows = q.execute().data or []
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, int] = {}
    for r in rows:
        cid = r.get("entity_id")
        if cid:
            out[cid] = out.get(cid, 0) + 1
    return out


def lane_status() -> dict:
    """Per-lane queue depth for the in-process worker lanes. Each lane reports
    pending/running counts under its own claim filter; the bulk lane also reports
    a per-client running breakdown. MAIN overlaps the other lanes (it claims
    every non-fanout job at any priority), so its counts are the whole non-fanout
    backlog, not a disjoint bucket — noted on the row."""
    supabase = get_supabase()
    fanout = list(settings.fanout_job_types)
    interactive = list(settings.interactive_job_types)
    bg = job_priority.BACKGROUND

    def depth(**flt) -> dict:
        return {
            "pending": _count(supabase, "pending", **flt),
            "running": _count(supabase, "running", **flt),
        }

    main_row = {
        "name": "main", "workers": 1,
        "note": "catch-all + reaper; claims all non-fanout at any priority (overlaps other lanes)",
        **depth(exclude=fanout),
    }
    interactive_row = {
        "name": "interactive", "workers": 1,
        "note": f"short user-awaited jobs, priority >= {job_priority.INTERACTIVE}",
        **depth(job_types=interactive, priority_min=job_priority.INTERACTIVE),
    }
    fanout_row = {
        "name": "fanout",
        "workers": (max(1, settings.fanout_lane_workers) if fanout else 0),
        "note": "Fanout pipeline jobs",
        **depth(job_types=fanout),
    }
    bulk_row = {
        "name": "bulk", "workers": max(0, settings.bulk_lane_workers),
        "max_per_client": settings.bulk_lane_max_per_client,
        "note": f"background-priority batch items, priority <= {bg}",
        **depth(exclude=fanout, priority_max=bg),
        "per_client_running": _running_by_client(supabase, fanout, bg),
    }

    return {
        "poll_interval_s": settings.job_worker_poll_interval_seconds,
        "priorities": {"interactive": job_priority.INTERACTIVE, "background": bg},
        "lanes": [main_row, interactive_row, fanout_row, bulk_row],
    }

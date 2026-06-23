"""M15 slice 4 — content-schedule worker (handoff.md §9.6).

An in-process asyncio loop in the FastAPI backend (no new Railway service, no Postgres cron).
Every `scheduler_tick_seconds` it claims up to `cap - in_flight` due runs via the atomic
`claim_scheduled_runs` RPC (FOR UPDATE SKIP LOCKED), then generates each in a worker thread
(`generate_article_core`, the same path the Generate button uses) and records the result on
the run row. A startup sweep requeues rows stuck `running` (a restart mid-write).

Durable by construction: state lives in `scheduled_article_runs`, so a process restart just
resumes on the next tick. The heartbeat living in the web process is the accepted M5-style
trade-off; the sweep closes the stuck-row gap on this path.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fanout.config import get_settings
from fanout.cost_attribution import metered_run
from fanout.storage.supabase_client import get_service_client

logger = logging.getLogger(__name__)

_loop_task: asyncio.Task | None = None
_inflight: set[asyncio.Task] = set()
_executor: ThreadPoolExecutor | None = None


async def start() -> None:
    """Start the loop (called from the FastAPI lifespan). No-op if disabled or already running."""
    global _loop_task, _executor
    s = get_settings()
    if not s.scheduler_enabled or (_loop_task and not _loop_task.done()):
        return
    _executor = ThreadPoolExecutor(max_workers=s.scheduler_concurrency_cap,
                                   thread_name_prefix="sched-writer")
    try:
        _recover_stuck(s.scheduler_stuck_minutes)
    except Exception as exc:  # noqa: BLE001 — never block startup on the sweep
        logger.warning("scheduler_recover_failed", extra={"event": "scheduler_recover_failed",
                                                          "reason": repr(exc)})
    _loop_task = asyncio.create_task(_run_loop())
    logger.info("scheduler_started", extra={"event": "scheduler_started",
                                            "cap": s.scheduler_concurrency_cap,
                                            "tick_s": s.scheduler_tick_seconds})


async def stop() -> None:
    """Stop the loop + let in-flight writes finish, but bounded by `scheduler_shutdown_grace_s`
    so a minutes-long write can't hang shutdown past the platform's grace period — an abandoned
    `running` row is recovered by the next startup sweep."""
    global _loop_task
    if _loop_task:
        _loop_task.cancel()
        _loop_task = None
    if _inflight:
        grace = float(get_settings().scheduler_shutdown_grace_s)
        try:
            await asyncio.wait_for(asyncio.gather(*_inflight, return_exceptions=True), timeout=grace)
        except asyncio.TimeoutError:
            logger.warning("scheduler_shutdown_timeout",
                           extra={"event": "scheduler_shutdown_timeout", "in_flight": len(_inflight)})
    if _executor:
        _executor.shutdown(wait=False)


async def _run_loop() -> None:
    s = get_settings()
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a bad tick must not kill the loop
            logger.warning("scheduler_tick_failed",
                           extra={"event": "scheduler_tick_failed", "reason": repr(exc)})
        await asyncio.sleep(s.scheduler_tick_seconds)


async def _tick() -> None:
    s = get_settings()
    cap = s.scheduler_concurrency_cap - len(_inflight)
    if cap <= 0:
        return
    loop = asyncio.get_running_loop()
    # Claim on the default executor (a quick DB call), not `_executor` — so it never waits on a
    # cap-sized worker thread that an in-flight article write is holding.
    rows = await loop.run_in_executor(None, _claim_due, cap)
    for row in rows:
        task = asyncio.create_task(_dispatch(row))
        _inflight.add(task)
        task.add_done_callback(_inflight.discard)


async def _dispatch(row: dict) -> None:
    """Run one claimed row in a worker thread (the write is blocking, minutes long)."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _process_run, row)


# ----- sync helpers (run in the worker thread) ------------------------------


def _claim_due(cap: int) -> list[dict]:
    res = get_service_client().rpc("claim_scheduled_runs", {"cap": cap}).execute()
    return res.data or []


def _recover_stuck(stuck_minutes: int) -> None:
    """Requeue rows left `running` by a prior process (restart mid-write)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)).isoformat()
    res = (get_service_client().table("scheduled_article_runs")
           .update({"status": "queued", "started_at": None})
           .eq("status", "running").lt("started_at", cutoff).execute())
    if res.data:
        logger.info("scheduler_requeued_stuck",
                    extra={"event": "scheduler_requeued_stuck", "count": len(res.data)})


def _process_run(row: dict) -> None:
    """Generate the article for one claimed run, then record the outcome + advance the schedule."""
    from fanout import jobs
    from fanout.storage import silo as store

    run_id = row["id"]
    cluster_id = row["cluster_id"]
    session_id = row["session_id"]
    schedule_id = row.get("content_schedule_id")
    try:
        cluster = store.get_cluster(cluster_id)
        pkid = (cluster or {}).get("primary_keyword_id")
        keyword = store.get_keyword_texts([pkid]).get(pkid) if pkid else None
        session = store.get_session(session_id)
        if not keyword or not session:
            _finish_run(run_id, "failed", error="cluster has no primary keyword or session missing")
            return
        location_code = store.session_location_code(session)
        with metered_run(session_id, "article_generation"):
            ok = jobs.generate_article_core(
                session_id, cluster_id, keyword, location_code,
                scheduled_article_run_id=run_id)
        _finish_run(run_id, "complete" if ok else "failed",
                    error=None if ok else "article generation failed")
    except Exception as exc:  # noqa: BLE001 — one bad run must not stop the worker
        logger.error("scheduled_run_failed",
                     extra={"event": "scheduled_run_failed", "run_id": run_id,
                            "cluster_id": cluster_id, "reason": repr(exc)})
        _finish_run(run_id, "failed", error=repr(exc)[:500])
    finally:
        if schedule_id:
            _maybe_complete_schedule(schedule_id)


def _finish_run(run_id: str, status: str, *, error: str | None) -> None:
    get_service_client().table("scheduled_article_runs").update({
        "status": status, "completed_at": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }).eq("id", run_id).execute()


def _maybe_complete_schedule(schedule_id: str) -> None:
    """Flip an active schedule -> complete once none of its runs are queued/running. Leaves a
    paused/cancelled schedule untouched."""
    client = get_service_client()
    sched = (client.table("content_schedules").select("status")
             .eq("id", schedule_id).limit(1).execute().data or [])
    if not sched or sched[0]["status"] != "active":
        return
    pending = (client.table("scheduled_article_runs").select("id", count="exact")
               .eq("content_schedule_id", schedule_id)
               .in_("status", ["queued", "running"]).execute())
    if (pending.count or 0) == 0:
        client.table("content_schedules").update({"status": "complete"}).eq(
            "id", schedule_id).execute()

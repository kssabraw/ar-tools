"""Event-loop lag watchdog.

platform-api runs its GSC/scheduler + job-worker lanes on the **same** asyncio
event loop as the HTTP server (single process, single replica by design). Any
synchronous / blocking call that runs *on* the loop therefore stalls everything
at once — the 2026-09-16 outage was a blocking Google API call wedging the loop
so that even CORS preflights hung for 5 minutes and nothing loaded. Blocking work
is supposed to go through ``asyncio.to_thread`` / ``run_in_threadpool``; this
watchdog is the safety net that makes a regression *observable* instead of silent.

It periodically sleeps for a fixed interval and measures how late it wakes: on a
healthy loop the lateness ("lag") is ~0; when something blocks the loop for N
seconds, the sleep wakes ~N seconds late and we log a warning with the lag.

Honest limitation: a *total* wedge freezes this coroutine too (it lives on the
same loop), so a full stall is only reported once the loop frees again — one
large lag reading on recovery. Its real, everyday value is catching *partial*
blocking — a handler or job step that blocks the loop for a few seconds under
load — before it grows into a full outage, and giving a timestamped lag signal
to grep for after one.

Started from the app lifespan alongside the workers; best-effort and must never
crash the app.
"""

from __future__ import annotations

import asyncio
import logging

from config import settings

logger = logging.getLogger(__name__)


async def event_loop_watchdog() -> None:
    """Background task: log ``event_loop_lag_high`` whenever loop lag exceeds the
    configured threshold. Runs until cancelled at shutdown."""
    if not settings.event_loop_watchdog_enabled:
        return

    interval = max(0.1, float(settings.event_loop_watchdog_interval_seconds))
    threshold = max(0.0, float(settings.event_loop_watchdog_lag_threshold_seconds))
    loop = asyncio.get_running_loop()
    # Inline formatting (not extra=): platform-api's basicConfig formats only
    # %(message)s, so anything passed via extra never reaches the logs.
    logger.info(
        "event_loop_watchdog.started interval_s=%.1f threshold_s=%.1f",
        interval,
        threshold,
    )
    try:
        while True:
            start = loop.time()
            await asyncio.sleep(interval)
            # How much later than `interval` did we actually wake? That excess is
            # time the loop spent unable to service this timer — i.e. blocked.
            lag = loop.time() - start - interval
            if lag > threshold:
                logger.warning(
                    "event_loop_lag_high lag_s=%.3f interval_s=%.1f threshold_s=%.1f",
                    lag,
                    interval,
                    threshold,
                )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover - a watchdog must never crash the app
        logger.warning("event_loop_watchdog_error error=%s", str(exc))

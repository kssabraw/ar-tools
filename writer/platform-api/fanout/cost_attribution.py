"""Bind a cost meter to a run and flush it to the session (PRD §16.4).

`metered_run` is for the background pipeline jobs: it binds a `CostMeter` on the
job thread (so nested worker threads inherit it via `ContextThreadPoolExecutor`),
spawns a daemon that flushes the running total to `sessions.actual_cost_usd` +
`cost_breakdown` every `cost_flush_interval_s`, and does a final flush on exit —
including on failure, so a crashed/partial run still records the cost spent so far
(§16.4 "final flush on step completion or session terminal state").

`metered_sync` is for the short synchronous silo-discovery call in the request
path: bind + single final flush, no periodic thread.

Cost accumulates across a session's runs (expand → plan → architecture, plus any
re-plan/regate/fanout): each flush atomically *increments* `actual_cost_usd` +
`cost_breakdown` by the spend since the previous flush (`increment_session_cost`,
row-locked in SQL), so the persisted figure is the session's real cumulative cost
(matches §16.4 "the session's running cost"). The delta increment is correct even when
several writers touch the same session at once — the M15 scheduler drains up to `cap`
article writes of one session concurrently, which the old base+absolute write lost.
"""

import logging
import threading
from contextlib import contextmanager

from fanout.config import get_settings
from fanout.cost_meter import CostMeter, bind_meter, set_step
from fanout.storage import silo as store

logger = logging.getLogger(__name__)


def _breakdown_delta(curr: dict[str, float], last: dict[str, float]) -> dict[str, float]:
    """Per-step spend since the last flush (only the changed steps, rounded)."""
    out: dict[str, float] = {}
    for step, cost in curr.items():
        d = round(cost - last.get(step, 0.0), 6)
        if d:
            out[step] = d
    return out


def _make_flusher(session_id: str, meter: CostMeter):
    """A do_flush() closure that increments the session by the delta since its last successful
    flush. `last` only advances on success, so a transient flush failure is retried (its delta
    rolls into the next flush) rather than lost."""
    last = {"total": 0.0, "breakdown": {}}

    def do_flush() -> None:
        total, breakdown = meter.snapshot()
        d_total = round(total - last["total"], 6)
        d_breakdown = _breakdown_delta(breakdown, last["breakdown"])
        if d_total == 0.0 and not d_breakdown:
            return
        try:
            store.increment_session_cost(session_id, d_total, d_breakdown)
        except Exception as exc:  # noqa: BLE001 — a flush failure must not kill the run
            logger.warning("cost_flush_failed",
                           extra={"event": "cost_flush_failed", "reason": repr(exc)})
            return                                      # don't advance last -> retry the delta
        last["total"] = total
        last["breakdown"] = dict(breakdown)

    return do_flush


@contextmanager
def metered_run(session_id: str, step: str):
    """Background-job metering: periodic + final flush (PRD §16.4)."""
    meter = CostMeter()
    bind_meter(meter)
    set_step(step)
    interval = float(get_settings().cost_flush_interval_s)
    stop = threading.Event()
    # Serialize this run's own DB writes so its final flush is always its last write: once stop
    # is set the loop starts no new flush, so at most one periodic flush is in flight, and the
    # final flush blocks on the lock until it finishes. (Cross-run safety is the SQL row lock.)
    flush_lock = threading.Lock()
    flush = _make_flusher(session_id, meter)

    def do_flush() -> None:
        with flush_lock:
            flush()

    def loop() -> None:
        while not stop.wait(interval):
            do_flush()

    flusher = threading.Thread(target=loop, name=f"cost-flush-{step}", daemon=True)
    flusher.start()
    try:
        yield meter
    finally:
        stop.set()
        flusher.join(timeout=2.0)
        do_flush()
        bind_meter(None)


@contextmanager
def metered_sync(session_id: str, step: str):
    """Synchronous metering for the in-request silo-discovery call: a single
    final flush, no periodic thread (the call is quick)."""
    meter = CostMeter()
    bind_meter(meter)
    set_step(step)
    flush = _make_flusher(session_id, meter)
    try:
        yield meter
    finally:
        flush()
        bind_meter(None)

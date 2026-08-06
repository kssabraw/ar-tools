"""Recover pipeline runs orphaned by a process restart.

The pipeline jobs (expand / plan-articles / regate / recursive fanout /
architecture) run in an in-process `ThreadPoolExecutor`, and the session's
status *is* the claim: `try_claim_run` refuses to start a run whose session is
already `queued` or `running`. Each job owns its terminal status, setting
`error` + `last_error` from its own `except` block.

A SIGKILL never reaches that `except` block. So when the container is replaced —
routinely, on every deploy — an executing run dies with the session left at
`running`: no error, no worker, and no way to restart it, because the claim guard
correctly refuses to start a second run on a session that looks live. It shows in
the UI as a progress bar that never advances. That happened on 2026-08-05: a
deploy landed mid-write and killed an article-planning run one second after its
last batch insert, stranding a session that had already spent $7.18 on expansion.

`jobs.py` documented this as an accepted v1 caveat whose recovery was "a new
session". That is more expensive than it needs to be: when the orphaned run was
article planning, the expensive half (expansion + the gated keyword pool) is
already durable in the DB, so the session can go back to `awaiting_article_planning`
and re-plan for the cost of the planning step alone.

**Startup-only, deliberately.** The tempting design is an age cutoff, like the
content scheduler's `_recover_stuck`. It is wrong here: a recursive-fanout run is
5-8x a base run, so no cutoff separates "stranded" from "legitimately slow", and
reaping a live run would rewrite the status out from under a job that is still
spending money. At startup the question doesn't arise — the executor is
per-process, this process has just started and owns no jobs, so anything the DB
still calls live was orphaned by definition. That does assume a single replica
(Railway PLATFORM is `numReplicas: 1`); with two, a restarting replica would reap
the other's live runs, and this would need a real claim (owner id + heartbeat)
rather than a status flag.
"""

import logging

logger = logging.getLogger(__name__)

# Statuses that mean "a worker is on this" — the same set `try_claim_run` refuses
# to start a second run against.
LIVE_STATUSES = ("queued", "running")

_RESTART_NOTE = (
    "The server restarted while this run was in progress (usually a deploy), so "
    "the run was interrupted. Everything collected before that point was saved."
)


def orphan_recovery_target(session: dict) -> tuple[str, str]:
    """The status an orphaned session should be returned to, plus the note to
    record. Pure.

    Expansion is the expensive half and it lands in the DB as a complete unit
    (`insert_classified_keywords` + the clustering log, written together at the
    end of the job). If the clustering log is there, expansion finished and only
    the planning half was lost — so the session goes back to
    `awaiting_article_planning`, where the workspace offers "Plan articles" and a
    re-plan costs only the planning step. Any partial clusters the killed write
    left behind are cleared by `reset_article_planning` at the start of that run.

    Otherwise the run died during expansion itself, leaving a partial keyword
    pool. That is recorded as `error`: the UI can only resume a session from
    `awaiting_article_planning` or `complete` (see the frontend's `hasResults`),
    so returning it to an earlier status would look like a normal waiting state
    while offering no way forward. `error` says what happened and points at
    starting a new session, which is what `jobs.py` has always prescribed here.
    """
    log = session.get("statistical_clustering_log") or {}
    if log.get("topics"):
        return "awaiting_article_planning", (
            _RESTART_NOTE + " Expansion had already finished, so its keywords "
            "were kept — re-run article planning to continue."
        )
    return "error", (
        _RESTART_NOTE + " It was interrupted during expansion, so the keyword "
        "pool is incomplete — start a new session for this seed."
    )


def recover_orphaned_runs(store=None) -> int:
    """Return every session still marked live to a state a human can act on.

    Called once at startup. Best-effort per row: one row that fails to update
    must not stop the rest being recovered, and the sweep must never block
    startup. Returns the number of sessions recovered.

    `store` is injectable so this is testable without importing the pipeline's
    heavy dependency chain; production passes nothing and gets the real one.
    """
    if store is None:
        from fanout.storage import silo as store

    try:
        sessions = store.list_live_sessions()
    except Exception as exc:  # noqa: BLE001 — never block startup on the sweep
        logger.warning(
            "fanout_orphan_sweep_failed",
            extra={"event": "fanout_orphan_sweep_failed", "reason": repr(exc)},
        )
        return 0

    recovered = 0
    for session in sessions:
        status, note = orphan_recovery_target(session)
        try:
            store.recover_orphaned_session(session["id"], status, note)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "fanout_orphan_recover_row_failed",
                extra={"event": "fanout_orphan_recover_row_failed",
                       "session_id": session.get("id"), "reason": repr(exc)},
            )
            continue
        recovered += 1
        logger.info(
            "fanout_orphan_recovered",
            extra={"event": "fanout_orphan_recovered",
                   "session_id": session.get("id"),
                   "was": session.get("status"), "now": status},
        )
    if recovered:
        logger.info(
            "fanout_orphan_sweep_complete",
            extra={"event": "fanout_orphan_sweep_complete", "count": recovered},
        )
    return recovered

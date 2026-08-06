"""Recover pipeline runs orphaned when the process holding them goes away.

The pipeline jobs (expand / plan-articles / regate / recursive fanout /
architecture) run in an in-process `ThreadPoolExecutor`, and the session's
status *is* the claim: `try_claim_run` refuses to start a run whose session is
already `queued` or `running`. Each job owns its terminal status, setting
`error` + `last_error` from its own `except` block.

A SIGKILL never reaches that `except`. So when the container is replaced —
routinely, on every deploy — an executing run dies with the session left at
`running`: no error, no worker, and no way to restart it, because the claim guard
correctly refuses a second run on a session that looks live. It shows in the UI
as a progress bar that never advances. That happened on 2026-08-05: a deploy
landed mid-write and killed an article-planning run one second after its last
batch insert, stranding a session that had already spent $7.18 on expansion.

Recovery runs from the DYING side, not the starting side
--------------------------------------------------------
The obvious placement — sweep every live-looking session at startup — is wrong,
and dangerously so. Railway replaces containers with an overlap: in the incident
above the new container was live at 00:18:10 while the old one kept working until
00:18:23.9. A sweep in the new container's startup path would therefore reap a
run that is genuinely still executing. Flipping that session out of `running`
means the outgoing job can no longer record its result (`try_finalize_running` is
conditional-on-running), so a *completed* plan would be mislabelled and re-planned
at full cost — and worse, `try_claim_run` would then permit a second job to start
writing to the same session while the first still is.

So the primary path is `recover_owned_runs`, called on shutdown: the process
marks the sessions *it* owns, read from the cancellation registry. No race — it
can only touch its own work — and it covers deploys, which is the actual cause.
Every write is guarded on the session still being in a live status, so a job that
finished inside the shutdown grace is never clobbered.

`recover_orphaned_runs` remains as a fallback for kills too hard for a shutdown
hook (OOM, SIGKILL without SIGTERM). It runs `orphan_sweep_delay_s` after
startup rather than during it, so the handover window has closed before it looks.
That still assumes a single replica (Railway PLATFORM is `numReplicas: 1`); with
two, one replica's fallback sweep could reap another's live run, and this would
need a real claim — owner id plus heartbeat — rather than a status flag.
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
    """The status an interrupted session should be returned to, plus the note to
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


def _recover(sessions: list[dict], store) -> int:
    """Mark each still-live session. Best-effort per row: one row that fails to
    update must not stop the rest. Returns how many were recovered."""
    recovered = 0
    for session in sessions:
        status, note = orphan_recovery_target(session)
        try:
            # Guarded on the row still being live, so a job that finished between
            # the read and this write keeps its own terminal status.
            if not store.recover_orphaned_session(session["id"], status, note):
                continue
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "fanout_recover_row_failed",
                extra={"event": "fanout_recover_row_failed",
                       "session_id": session.get("id"), "reason": repr(exc)},
            )
            continue
        recovered += 1
        logger.info(
            "fanout_run_recovered",
            extra={"event": "fanout_run_recovered", "session_id": session.get("id"),
                   "was": session.get("status"), "now": status},
        )
    return recovered


def recover_owned_runs(store=None, owned_ids=None) -> int:
    """Shutdown path: mark this process's own in-flight runs as interrupted.

    The primary recovery. Reads the sessions this process holds registrations for
    rather than everything that looks live, so it cannot touch another container's
    work during a deploy handover. Never raises — it runs while the process is
    already on its way out.

    `store` / `owned_ids` are injectable for testing; production passes neither.
    """
    if owned_ids is None:
        from fanout import cancellation

        owned_ids = cancellation.owned_sessions()
    if not owned_ids:
        return 0
    if store is None:
        from fanout.storage import silo as store

    try:
        sessions = store.get_live_sessions(list(owned_ids))
    except Exception as exc:  # noqa: BLE001 — shutdown is best-effort
        logger.warning(
            "fanout_owned_recovery_failed",
            extra={"event": "fanout_owned_recovery_failed", "reason": repr(exc)},
        )
        return 0

    recovered = _recover(sessions, store)
    if recovered:
        logger.info(
            "fanout_owned_recovery_complete",
            extra={"event": "fanout_owned_recovery_complete", "count": recovered},
        )
    return recovered


def recover_orphaned_runs(store=None) -> int:
    """Fallback path: mark every session that still looks live.

    For kills too hard for the shutdown hook (OOM, SIGKILL). MUST NOT run during
    startup — see the module docstring; the caller delays it past the deploy
    handover window. Never raises.
    """
    if store is None:
        from fanout.storage import silo as store

    try:
        sessions = store.list_live_sessions()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "fanout_orphan_sweep_failed",
            extra={"event": "fanout_orphan_sweep_failed", "reason": repr(exc)},
        )
        return 0

    recovered = _recover(sessions, store)
    if recovered:
        logger.info(
            "fanout_orphan_sweep_complete",
            extra={"event": "fanout_orphan_sweep_complete", "count": recovered},
        )
    return recovered

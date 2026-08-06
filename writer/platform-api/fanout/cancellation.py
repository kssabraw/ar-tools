"""Cooperative cancellation for pipeline runs.

A `POST /sessions/{id}/cancel` flips the session to `cancelled` and signals the
background worker via a `threading.Event` registered here. The worker — and the
nested DataForSEO/OpenAI/Anthropic call sites it spawns — call
`raise_if_cancelled()` before each external request; finding the event set, they
raise `CancelledByUser`, which propagates out of the pipeline (through
`except Exception` handlers in pipeline code, because it's a BaseException —
same propagation rule as KeyboardInterrupt) and is caught at the top of each
`run_*_job` in `jobs.py`, which writes the terminal status.

In-flight HTTP requests are not aborted (sync httpx doesn't cancel cleanly
mid-flight), so worst-case wait after cancel ≈ one DataForSEO timeout (60s).
Saves cost on every subsequent call.
"""

import threading

from fanout.logging import get_session_id

_events: dict[str, threading.Event] = {}
_lock = threading.Lock()


class CancelledByUser(BaseException):
    """A pipeline run was cancelled via the /cancel endpoint. BaseException so it
    isn't swallowed by the per-stage `except Exception` blocks that degrade a
    failing source — cancellation must abort the whole run, not just one source."""


def _event_for(session_id: str) -> threading.Event:
    with _lock:
        evt = _events.get(session_id)
        if evt is None:
            evt = threading.Event()
            _events[session_id] = evt
        return evt


def register(session_id: str) -> threading.Event:
    """Called at the start of a job: ensure an event exists for this session
    (adopts a pre-set event if /cancel landed before the worker started)."""
    return _event_for(session_id)


def clear(session_id: str) -> None:
    """Called in the job's finally: drop the event so a future run starts fresh."""
    with _lock:
        _events.pop(session_id, None)


def owned_sessions() -> list[str]:
    """Session ids this process currently holds a registration for — used by the
    shutdown hook to mark its own in-flight runs as interrupted (run_recovery.py).

    `register` is called at the start of each job and `clear` in its `finally`,
    so this is the process's live set. It can also contain a session whose only
    registration came from `/cancel` (`set_cancelled` creates the event on
    demand); that session's status is already `cancelled`, and the recovery write
    only touches rows still in a live status, so it's a harmless inclusion."""
    with _lock:
        return list(_events)


def set_cancelled(session_id: str) -> None:
    """Called by the /cancel endpoint."""
    _event_for(session_id).set()


def is_cancelled(session_id: str) -> bool:
    with _lock:
        evt = _events.get(session_id)
    return bool(evt and evt.is_set())


def raise_if_cancelled() -> None:
    """Called from external client wrappers (and any pipeline hot loop that wants
    to bail early). Reads the current session_id from the logging contextvar
    (propagated into pipeline workers by ContextThreadPoolExecutor)."""
    sid = get_session_id()
    if sid and is_cancelled(sid):
        raise CancelledByUser(sid)

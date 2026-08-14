"""Bounded retry for the pipeline's terminal DB writes (pure — unit-tested).

Expansion / regate / recursive-fanout each end the same way: persist the full
classified keyword pool (thousands of rows, active ones carrying 1536-dim
embeddings — large POST bodies), then flip the session's status + clustering log.
supabase-py / httpx do **not** retry writes, so a single transient transport
drop (`RemoteProtocolError: Server disconnected`, a read/connect/pool timeout)
aborts the whole job. That is how session BPC-157 was stranded on 2026-08-14: the
pipeline had finished and the pool was fully written, but a Supabase disconnect
during the keyword insert raised before the clustering log could be persisted —
leaving status=`error` over a complete, resumable pool the UI then declared
"incomplete".

`call_with_transport_retry` turns that one-off into a non-event. The caller is
responsible for passing an **idempotent** `fn` (the pipeline jobs wrap
delete-then-insert-all as one unit, so a retry re-establishes the same final
state rather than duplicating rows — a bare insert retry could double a batch
that committed server-side before the connection dropped).

httpx is imported lazily inside the transient classifier so this module (and the
tests that import it) stay importable in the httpx-less unit-test environment,
mirroring the lazy-import convention in `fanout/sie/*_client.py`.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

# httpx transport-layer exception class names — matched by name so the classifier
# needs no httpx import to recognise them (the isinstance check below still runs
# when httpx is installed, which also catches provider subclasses we don't name).
_TRANSIENT_NAMES = frozenset(
    {
        "TransportError",
        "NetworkError",
        "ProtocolError",
        "LocalProtocolError",
        "RemoteProtocolError",
        "ConnectError",
        "ReadError",
        "WriteError",
        "CloseError",
        "TimeoutException",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
    }
)


def is_transient_transport_error(exc: BaseException) -> bool:
    """True for an httpx transport-layer failure (connection dropped mid-request,
    timeout, pool exhaustion) — the class of error a plain retry usually clears.
    Never true for CancelledByUser / KeyboardInterrupt (those are BaseExceptions
    the retry loop's `except Exception` never even catches) or for application
    errors (a PostgREST 4xx surfaces as an APIError, not a transport error)."""
    try:  # pragma: no cover - exercised only where httpx is installed
        import httpx

        if isinstance(exc, httpx.TransportError):
            return True
    except Exception:  # noqa: BLE001 — httpx may be absent (unit-test env)
        pass
    return type(exc).__name__ in _TRANSIENT_NAMES


def call_with_transport_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_sleep: float = 0.5,
    max_sleep: float = 4.0,
    is_transient: Callable[[BaseException], bool] = is_transient_transport_error,
    on_retry: Callable[[BaseException, int], None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> T:
    """Call `fn`, retrying only on transient transport errors with exponential
    backoff (`base_sleep * 2**(n-1)`, clamped to `max_sleep`). A non-transient
    error, or the final attempt, re-raises. `fn` MUST be idempotent — the caller
    owns that. `on_retry(exc, next_attempt)` is invoked before each backoff for
    observability. `sleeper` is injectable so tests don't actually sleep."""
    total = max(1, int(attempts))
    for attempt in range(1, total + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — re-raised unless transient + retriable
            if attempt >= total or not is_transient(exc):
                raise
            if on_retry is not None:
                on_retry(exc, attempt + 1)
            sleeper(min(base_sleep * (2 ** (attempt - 1)), max_sleep))
    # Unreachable: the loop either returns or raises on the final attempt.
    raise AssertionError("call_with_transport_retry exhausted without returning")

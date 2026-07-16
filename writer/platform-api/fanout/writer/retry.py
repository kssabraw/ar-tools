"""Bounded-retry policy for the content scheduler (pure — unit-tested).

The scheduler treats a generation failure that isn't a clear config error
(frozen client, missing cluster/keyword) as *transient* and requeues the run
with exponential backoff, up to a bounded number of attempts. This module holds
the two pure decisions — "should we retry again?" and "how long until the next
attempt?" — so they're testable without touching the DB or the asyncio loop.

Rationale: transient LLM overloads (429/529), research-stage timeouts, and
worker restarts mid-write are non-deterministic — the same run usually succeeds
on a later attempt (confirmed live: a run that failed on 2026-07-16 succeeded
on a plain requeue). Rather than classify every exception type, we retry any
non-terminal failure a bounded number of times and dead-letter the rest with a
notification so a human looks.
"""

from __future__ import annotations


def next_attempt_number(attempts: int | None) -> int:
    """The attempt counter after recording one more failure (0/None -> 1)."""
    return max(0, int(attempts or 0)) + 1


def should_retry(attempts: int, max_attempts: int) -> bool:
    """Whether a run that has now recorded `attempts` failures should be retried
    (True) rather than dead-lettered (False). `attempts` is the post-increment
    count — the value from `next_attempt_number`. With max_attempts=4 a run gets
    the original try plus 3 retries before dead-lettering."""
    return int(attempts) < max(1, int(max_attempts))


def retry_delay_seconds(attempt: int, base_seconds: int, cap_seconds: int) -> int:
    """Exponential backoff for the given attempt number (1-based): the delay
    before attempt N is ``base * 2**(N-1)``, clamped to ``[base, cap]``.

    attempt 1 -> base, 2 -> 2*base, 3 -> 4*base, … capped at `cap`. A non-positive
    attempt is treated as 1 (never a zero/negative delay)."""
    base = max(1, int(base_seconds))
    cap = max(base, int(cap_seconds))
    n = max(1, int(attempt))
    # Cap the exponent so 2**n can't overflow into a huge int for pathological
    # attempt counts before the min() clamps it anyway.
    shift = min(n - 1, 30)
    return min(cap, base * (2 ** shift))

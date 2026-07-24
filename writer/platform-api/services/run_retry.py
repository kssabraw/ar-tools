"""Run-level transient-failure auto-retry — pure classification + backoff.

The pipeline's module calls already retry transient upstream blips at the HTTP
layer (the Anthropic and DataForSEO clients each back off on 429/5xx/timeouts).
This layer sits one level up: it catches the *run* that still fails at a stage
because a transient upstream outage outlasted those in-call retries — e.g. a
multi-minute DataForSEO SERP outage — and lets the orchestrator re-dispatch it
after a backoff delay instead of leaving it terminally failed for a human to
notice and re-run.

Only the transient band is retried. The classifier is an **allowlist** by
design: we auto-retry infra/upstream transients only, never deterministic
failures (schema mismatch, content-validation aborts, a genuinely-empty SERP)
that would just burn paid module calls re-failing. These helpers are pure so the
policy is unit-testable without touching the DB or the event loop.
"""

from __future__ import annotations

# Stable markers, matched (case-insensitively) against the StageError cause
# string the orchestrator records. Codes come from two places:
#   - orchestrator._call_module transport classification: `module_timeout`
#     (read timeout / blown hard deadline), `module_unavailable` (connection
#     drop, e.g. a Railway redeploy rollover).
#   - the pipeline module's own error code, surfaced in the HTTP-error body and
#     prefixed into the router `detail` (e.g. `serp_failed` — a DataForSEO SERP
#     outage that survived the client-level retries in the brief/SIE module).
_TRANSIENT_MARKERS = (
    "module_timeout",
    "module_unavailable",
    "serp_failed",
)


def is_transient_stage_error(cause: str) -> bool:
    """True when a stage failure looks like a transient upstream/infra outage
    worth an automatic delayed retry. Pure."""
    text = (cause or "").lower()
    if any(marker in text for marker in _TRANSIENT_MARKERS):
        return True
    # A module_error carrying an HTTP 5xx from the pipeline module is an
    # unhandled upstream server error (e.g. the DataForSEO `internal_error` 500)
    # — transient. A 4xx (422 validation, `serp_no_results`) is permanent and is
    # NOT matched here (only the `serp_failed` marker above lifts a 422).
    if "module_error: http 5" in text:
        return True
    return False


def should_retry(retry_count: int, cause: str, max_retries: int) -> bool:
    """Whether a run that failed with `cause` (having already auto-retried
    `retry_count` times) gets another automatic attempt. Pure."""
    if max_retries <= 0:
        return False
    return retry_count < max_retries and is_transient_stage_error(cause)


def retry_delay_minutes(attempt: int, base_minutes: float, factor: float) -> float:
    """Backoff for the Nth attempt (1-indexed): base * factor**(attempt-1).
    At the defaults (base=5, factor=3) → 5, 15, 45 minutes. Pure."""
    n = max(1, attempt)
    return base_minutes * (factor ** (n - 1))

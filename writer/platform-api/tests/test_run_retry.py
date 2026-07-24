"""Unit tests for the run-level transient-failure auto-retry policy
(services/run_retry.py) — the allowlist classifier and the backoff schedule."""

from __future__ import annotations

import pytest

from services import run_retry


# ---- transient classification (allowlist) ----------------------------------

@pytest.mark.parametrize(
    "cause",
    [
        "module_timeout: HTTP read timeout",
        "module_unavailable: Server disconnected without sending a response.",
        # A DataForSEO SERP outage surfaced by brief/SIE as a 422 with the code
        # prefixed into the detail.
        'module_error: HTTP 422: {"detail":"serp_failed: DataForSEO SERP failed: '
        "/v3/serp/google/organic/live/advanced: task error Internal SE Server Error.\"}",
        # An unhandled upstream 500 from the pipeline module.
        'module_error: HTTP 500: {"detail":"internal_error"}',
        "module_error: HTTP 503: upstream unavailable",
    ],
)
def test_transient_causes_retry(cause):
    assert run_retry.is_transient_stage_error(cause) is True


@pytest.mark.parametrize(
    "cause",
    [
        # A genuinely-empty SERP is a real outcome, not a transient blip.
        'module_error: HTTP 422: {"detail":"serp_no_results: DataForSEO returned 0 organic results."}',
        # Deterministic content-validation / config failures re-fail on retry.
        'module_error: HTTP 422: {"detail":"title_generation_failed: ..."}',
        "schema version mismatch: expected 2.8, got 2.7",
        'module_error: HTTP 400: {"detail":"bad_request"}',
        "",
    ],
)
def test_permanent_causes_do_not_retry(cause):
    assert run_retry.is_transient_stage_error(cause) is False


def test_serp_no_results_not_confused_with_serp_failed():
    # The `serp_failed` marker must not accidentally match `serp_no_results`.
    assert run_retry.is_transient_stage_error("serp_no_results") is False
    assert run_retry.is_transient_stage_error("serp_failed") is True


# ---- should_retry: budget + transience gate --------------------------------

def test_should_retry_respects_budget():
    transient = "module_timeout"
    assert run_retry.should_retry(0, transient, max_retries=3) is True
    assert run_retry.should_retry(2, transient, max_retries=3) is True
    assert run_retry.should_retry(3, transient, max_retries=3) is False  # exhausted
    assert run_retry.should_retry(4, transient, max_retries=3) is False


def test_should_retry_permanent_never_retries_even_with_budget():
    assert run_retry.should_retry(0, "serp_no_results", max_retries=3) is False


def test_should_retry_disabled_when_max_zero():
    assert run_retry.should_retry(0, "module_timeout", max_retries=0) is False


# ---- backoff schedule ------------------------------------------------------

def test_retry_delay_schedule_defaults():
    # base=5, factor=3 → 5, 15, 45 minutes for attempts 1..3.
    assert run_retry.retry_delay_minutes(1, 5.0, 3.0) == 5.0
    assert run_retry.retry_delay_minutes(2, 5.0, 3.0) == 15.0
    assert run_retry.retry_delay_minutes(3, 5.0, 3.0) == 45.0


def test_retry_delay_floor_on_bad_attempt():
    # A 0/negative attempt is floored to the first-attempt delay, never negative.
    assert run_retry.retry_delay_minutes(0, 5.0, 3.0) == 5.0

"""Unit tests for run-failure plain-English explanations (services/run_failure.py)."""

from __future__ import annotations

from services import run_failure


def test_stage_label_known_and_unknown():
    assert run_failure.stage_label("sie") == "term & entity analysis (SIE)"
    assert run_failure.stage_label("writer") == "article writing"
    assert run_failure.stage_label(None) == "content pipeline"
    assert run_failure.stage_label("brand_new_stage") == "brand_new_stage"


def test_failure_reason_matches_markers():
    assert "internal server error" in run_failure.failure_reason(
        'module_error: HTTP 500: {"detail":"internal_error"}'
    )
    assert "timed out" in run_failure.failure_reason("module_timeout")
    assert "briefly unreachable" in run_failure.failure_reason("module_unavailable")
    assert "no usable competitor results" in run_failure.failure_reason("serp_no_results")
    assert "SERP" in run_failure.failure_reason("serp_failed")
    assert run_failure.failure_reason("something weird") == "of an unexpected error"


def test_explain_transient_500_after_retries_calls_out_persistence():
    # The exact production incident: an HTTP 500 (classified transient) that
    # exhausted its auto-retries — the explanation must flag it as persistent.
    msg = run_failure.explain_failure(
        "sie", 'module_error: HTTP 500: {"detail":"internal_error"}', retry_count=3
    )
    assert "term & entity analysis (SIE)" in msg
    assert "internal server error" in msg
    assert "3 times" in msg
    assert "persistent" in msg


def test_explain_transient_no_retries_suggests_rerun():
    msg = run_failure.explain_failure("brief", "module_timeout", retry_count=0)
    assert "content brief" in msg
    assert "Re-running often clears" in msg


def test_explain_permanent_says_rerun_wont_help():
    # A 4xx is NOT transient (run_retry allowlist) — re-running won't help.
    msg = run_failure.explain_failure("writer", "module_error: HTTP 422: bad", retry_count=0)
    assert "won't help" in msg


def test_explain_singular_retry_grammar():
    msg = run_failure.explain_failure("sie", "module_timeout", retry_count=1)
    assert "1 time and kept failing" in msg

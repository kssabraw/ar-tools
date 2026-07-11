"""Unit tests for services.freeze — pure helpers + the router/worker gates.

DB-touching functions (freeze_client / lift_freeze / the check job) are covered
by integration testing; here we pin the pure decision logic and the gate
behavior with `active_freeze` mocked.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from services import freeze


# ---------------------------------------------------------------------------
# should_warn_deindex — coverageState is the authority, not the coarse verdict.
# Detection is warn-only (nothing auto-freezes), and benign NEUTRAL states must
# never alarm — those were the source of the false-positive deindex warnings.
# ---------------------------------------------------------------------------
def test_warn_on_genuinely_not_indexed_neutral():
    assert freeze.should_warn_deindex("NEUTRAL", "Crawled - currently not indexed") is True
    assert freeze.should_warn_deindex("NEUTRAL", "Discovered - currently not indexed") is True
    assert freeze.should_warn_deindex("NEUTRAL", "URL is unknown to Google") is True


def test_no_warn_on_benign_neutral_states():
    # A homepage on Google under a different canonical (http/https, www, redirect,
    # duplicate, alternate) is NOT deindexed — this is the false-positive class.
    assert freeze.should_warn_deindex("NEUTRAL", "Page with redirect") is False
    assert freeze.should_warn_deindex("NEUTRAL", "Duplicate, Google chose different canonical than user") is False
    assert freeze.should_warn_deindex("NEUTRAL", "Alternate page with proper canonical tag") is False
    assert freeze.should_warn_deindex("NEUTRAL", "Excluded by 'noindex' tag") is False


def test_warn_on_fail_verdict():
    assert freeze.should_warn_deindex("FAIL", "Not found (404)") is True
    assert freeze.should_warn_deindex("FAIL", "Submitted URL seems to be a Soft 404") is True


def test_no_warn_on_pass_or_unknown():
    assert freeze.should_warn_deindex("PASS", "Submitted and indexed") is False
    # API hiccups / missing verdicts must never alarm
    assert freeze.should_warn_deindex(None, None) is False
    assert freeze.should_warn_deindex("NEUTRAL", None) is False  # NEUTRAL without a deindex coverage string
    assert freeze.should_warn_deindex("VERDICT_UNSPECIFIED", None) is False


# ---------------------------------------------------------------------------
# job_client_id
# ---------------------------------------------------------------------------
def test_job_client_id_prefers_payload():
    job = {"payload": {"client_id": "c-1"}, "entity_id": "e-1"}
    assert freeze.job_client_id(job) == "c-1"


def test_job_client_id_falls_back_to_entity():
    assert freeze.job_client_id({"payload": {}, "entity_id": "e-1"}) == "e-1"
    assert freeze.job_client_id({"payload": None, "entity_id": None}) is None


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------
def test_gated_job_types_are_content_or_link_output():
    # Monitoring/analysis jobs must keep running under a freeze — only output
    # jobs are gated (SOP pauses the work, not the observation).
    assert "local_seo_generate" in freeze.FREEZE_GATED_JOB_TYPES
    assert "syndication_item" in freeze.FREEZE_GATED_JOB_TYPES
    for observational in ("gsc_ingest", "maps_scan", "brand_scan", "reopt_plan", "freeze_check"):
        assert observational not in freeze.FREEZE_GATED_JOB_TYPES


def test_assert_not_frozen_raises_409_when_frozen():
    with patch.object(freeze, "active_freeze", return_value={"id": "f-1"}):
        with pytest.raises(HTTPException) as exc:
            freeze.assert_not_frozen("c-1")
        assert exc.value.status_code == 409
        assert exc.value.detail == "client_frozen"


def test_assert_not_frozen_passes_when_clear():
    with patch.object(freeze, "active_freeze", return_value=None):
        freeze.assert_not_frozen("c-1")  # no raise


def test_is_frozen_handles_missing_client_id():
    assert freeze.is_frozen(None) is False
    assert freeze.is_frozen("") is False

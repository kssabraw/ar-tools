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
# should_auto_freeze — only a hard not-indexed verdict freezes automatically
# ---------------------------------------------------------------------------
def test_auto_freeze_on_not_indexed():
    assert freeze.should_auto_freeze("not_indexed", "Page with redirect") is True
    assert freeze.should_auto_freeze("not_indexed", None) is True


def test_no_auto_freeze_on_indexed_or_unknown():
    assert freeze.should_auto_freeze("indexed", None) is False
    # API hiccups / missing verdicts must never freeze a client
    assert freeze.should_auto_freeze("unknown", None) is False


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

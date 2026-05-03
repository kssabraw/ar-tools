"""Tests for the brief cache-decision UX (PRD v2.6).

Covers the platform-api side:
  - RunCreateRequest accepts brief_force_refresh (default False)
  - Orchestrator's _build_brief_payload forwards the field as
    `force_refresh` into the BriefRequest
  - Briefs router's keyword normalization matches the pipeline-api
    cache key (lowercase + strip)
"""

from __future__ import annotations

import pytest
from uuid import uuid4

from models.runs import RunCreateRequest
from routers.briefs import _normalize_keyword
from services.orchestrator import _build_brief_payload


# ---------------------------------------------------------------------------
# RunCreateRequest schema
# ---------------------------------------------------------------------------


def test_run_create_request_default_brief_force_refresh_false():
    """Existing callers that don't supply the field still work — and
    they get the cache-using default behavior."""
    req = RunCreateRequest(client_id=uuid4(), keyword="some keyword")
    assert req.brief_force_refresh is False


def test_run_create_request_accepts_brief_force_refresh_true():
    req = RunCreateRequest(
        client_id=uuid4(),
        keyword="some keyword",
        brief_force_refresh=True,
    )
    assert req.brief_force_refresh is True


def test_run_create_request_brief_force_refresh_independent_of_sie():
    """sie_force_refresh and brief_force_refresh are independent toggles —
    the user might want fresh SERP signals (SIE) but still reuse the
    brief, or vice versa."""
    req = RunCreateRequest(
        client_id=uuid4(),
        keyword="kw",
        sie_force_refresh=True,
        brief_force_refresh=False,
    )
    assert req.sie_force_refresh is True
    assert req.brief_force_refresh is False


# ---------------------------------------------------------------------------
# Orchestrator payload builder
# ---------------------------------------------------------------------------


def test_build_brief_payload_forwards_force_refresh_true():
    """When the runs row has brief_force_refresh=True, the BriefRequest
    payload sent to pipeline-api carries `force_refresh=True` so the
    cache lookup is skipped."""
    run = {
        "id": "run-uuid",
        "keyword": "tiktok shop seller fees",
        "intent_override": None,
        "brief_force_refresh": True,
    }
    payload = _build_brief_payload(run)
    assert payload["force_refresh"] is True
    assert payload["keyword"] == "tiktok shop seller fees"


def test_build_brief_payload_forwards_force_refresh_false_default():
    """Missing column / None / False → force_refresh=False (default
    cache-using behavior)."""
    run_missing = {
        "id": "run-uuid",
        "keyword": "kw",
        "intent_override": None,
    }
    run_explicit = {
        "id": "run-uuid",
        "keyword": "kw",
        "intent_override": None,
        "brief_force_refresh": False,
    }
    assert _build_brief_payload(run_missing)["force_refresh"] is False
    assert _build_brief_payload(run_explicit)["force_refresh"] is False


def test_build_brief_payload_includes_existing_fields():
    """Regression: the new field must not displace the existing
    payload contract."""
    run = {
        "id": "run-uuid",
        "keyword": "kw",
        "intent_override": "how-to",
        "brief_force_refresh": True,
    }
    payload = _build_brief_payload(run)
    assert payload["run_id"] == "run-uuid"
    assert payload["attempt"] == 1
    assert payload["location_code"] == 2840
    assert payload["intent_override"] == "how-to"


# ---------------------------------------------------------------------------
# Keyword normalization (must match pipeline-api cache.py)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("input_kw,expected", [
    ("TikTok Shop ROI", "tiktok shop roi"),
    ("  spaced keyword  ", "spaced keyword"),
    ("MIXED case", "mixed case"),
    ("already lowercase", "already lowercase"),
])
def test_normalize_keyword_matches_pipeline_api(input_kw, expected):
    """Cache-status lookup MUST normalize the keyword identically to
    the pipeline-api's cache.py:_normalize_keyword. If they drift,
    dashboard lookups will miss valid cache rows."""
    assert _normalize_keyword(input_kw) == expected

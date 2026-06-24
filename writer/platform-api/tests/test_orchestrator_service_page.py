"""Tests for the service_page orchestration branch + payload builders."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import services.orchestrator as orch


# ----------------------------------------------------------------------
# Registries / schema-version extraction
# ----------------------------------------------------------------------

def test_registries_include_service_modules():
    for m in ("service_brief", "service_writer"):
        assert orch.EXPECTED_MODULE_VERSIONS[m] == "1.0"
        assert m in orch.MODULE_PATHS
        assert m in orch.MODULE_TIMEOUTS
    assert orch.MODULE_PATHS["service_brief"] == "/service-brief"
    assert orch.MODULE_PATHS["service_writer"] == "/service-write"


def test_extract_schema_version_service_modules():
    assert orch._extract_schema_version("service_brief", {"metadata": {"schema_version": "1.0"}}) == "1.0"
    assert orch._extract_schema_version("service_writer", {"metadata": {"schema_version": "1.0"}}) == "1.0"


# ----------------------------------------------------------------------
# Payload builders
# ----------------------------------------------------------------------

def test_build_service_brief_payload():
    run = {"id": "r1", "keyword": "emergency drain cleaning", "service": "Drain Cleaning",
           "location": "Austin, TX", "location_code": 1234}
    snap = {"brand_guide_text": "b", "icp_text": "i", "website_analysis": {"services": ["x"]}}
    p = orch._build_service_brief_payload(run, snap)
    assert p["service"] == "Drain Cleaning"
    assert p["primary_query"] == "emergency drain cleaning"
    assert p["location"] == "Austin, TX"
    assert p["location_code"] == 1234
    assert p["client_context"]["icp_text"] == "i"
    assert p["client_context"]["brand_voice_text"] == "b"


def test_build_service_brief_payload_defaults():
    p = orch._build_service_brief_payload({"id": "r1", "keyword": "kw"}, {})
    assert p["service"] == "kw"          # service defaults to keyword
    assert p["location_code"] == 2840    # US default


def test_build_service_writer_payload():
    snap = {"brand_guide_text": "b", "icp_text": "i", "website_analysis_unavailable": True}
    p = orch._build_service_writer_payload({"id": "r1"}, {"service": "S"}, snap)
    assert p["service_brief_output"] == {"service": "S"}
    assert p["client_context"]["brand_guide_text"] == "b"
    assert p["client_context"]["website_analysis_unavailable"] is True


# ----------------------------------------------------------------------
# orchestrate_run branching
# ----------------------------------------------------------------------

def _patches(run: dict, call_recorder):
    async def fake_call(module, run_id, payload, attempt=1):
        call_recorder.append(module)
        return {"metadata": {"schema_version": "1.0"}, "sie_cache_hit": False}

    return [
        patch.object(orch, "_get_run", AsyncMock(return_value=run)),
        patch.object(orch, "_get_snapshot", AsyncMock(return_value={"brand_guide_text": "b", "icp_text": "i"})),
        patch.object(orch, "_load_completed_outputs", AsyncMock(return_value={})),
        patch.object(orch, "_is_cancelled", AsyncMock(return_value=False)),
        patch.object(orch, "_set_run_status", AsyncMock()),
        patch.object(orch, "_update_total_cost", AsyncMock()),
        patch.object(orch, "_sb", MagicMock()),
        patch.object(orch, "_call_module", AsyncMock(side_effect=fake_call)),
    ]


async def test_service_page_runs_two_stages_in_order():
    run = {"id": "r1", "keyword": "drain cleaning", "client_id": "c1",
           "content_type": "service_page", "service": "Drain Cleaning"}
    calls: list[str] = []
    ps = _patches(run, calls)
    for p in ps:
        p.start()
    try:
        await orch.orchestrate_run("r1")
    finally:
        for p in ps:
            p.stop()
    assert calls == ["service_brief", "service_writer"]


async def test_blog_path_does_not_call_service_modules():
    run = {"id": "r1", "keyword": "kw", "client_id": "c1", "content_type": "blog_post"}
    calls: list[str] = []
    ps = _patches(run, calls)
    for p in ps:
        p.start()
    try:
        await orch.orchestrate_run("r1")
    finally:
        for p in ps:
            p.stop()
    assert "service_brief" not in calls and "service_writer" not in calls
    assert "brief" in calls and "writer" in calls

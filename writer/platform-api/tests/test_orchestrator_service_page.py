"""Tests for the service_page orchestration branch + payload builders."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import services.orchestrator as orch


# ----------------------------------------------------------------------
# Registries / schema-version extraction
# ----------------------------------------------------------------------

def test_registries_include_service_modules():
    assert orch.EXPECTED_MODULE_VERSIONS["service_brief"] == "1.2"
    assert orch.EXPECTED_MODULE_VERSIONS["service_writer"] == "1.0"
    for m in ("service_brief", "service_writer"):
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


# ----------------------------------------------------------------------
# _call_module transport-error retry (connection drops from redeploys)
# ----------------------------------------------------------------------

def _ok_response(schema_version: str = "1.4"):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"schema_version": schema_version, "cost_usd": 0.0}
    return resp


def _fake_async_client(post_mock):
    """A factory standing in for httpx.AsyncClient whose `.post` is post_mock
    (a shared AsyncMock, so its side_effect sequence spans retry attempts)."""
    def factory(*args, **kwargs):
        cm = MagicMock()
        client = MagicMock()
        client.post = post_mock
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm
    return factory


def _call_module_patches(post_mock, sleep_mock):
    return [
        patch.object(orch, "_create_module_output", AsyncMock(return_value="out1")),
        patch.object(orch, "_fail_module_output", AsyncMock()),
        patch.object(orch, "_save_module_output", AsyncMock()),
        patch.object(orch.asyncio, "sleep", sleep_mock),
        patch.object(orch.httpx, "AsyncClient", _fake_async_client(post_mock)),
    ]


async def test_call_module_retries_connection_drop_then_succeeds():
    # First attempt: the pipeline container was swapped mid-request (the exact
    # error the user hit). Second attempt: the new container answers.
    post = AsyncMock(side_effect=[
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
        _ok_response("1.4"),
    ])
    sleep = AsyncMock()
    ps = _call_module_patches(post, sleep)
    for p in ps:
        p.start()
    try:
        result = await orch._call_module("sie", "r1", {"k": "v"})
    finally:
        for p in ps:
            p.stop()
    assert result["schema_version"] == "1.4"
    assert post.await_count == 2      # retried exactly once
    sleep.assert_awaited_once()       # backed off before the retry


async def test_call_module_connection_drop_exhausts_retry_as_unavailable():
    # Both attempts drop — surface a StageError coded module_unavailable
    # (distinct from module_timeout / module_error).
    post = AsyncMock(side_effect=[
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
        httpx.ConnectError("connection refused"),
    ])
    ps = _call_module_patches(post, AsyncMock())
    for p in ps:
        p.start()
    try:
        with pytest.raises(orch.StageError) as ei:
            await orch._call_module("sie", "r1", {"k": "v"})
    finally:
        for p in ps:
            p.stop()
    assert ei.value.stage == "sie"
    assert "module_unavailable" in str(ei.value.cause)
    assert post.await_count == 2


async def test_call_module_hard_deadline_cuts_off_hung_module():
    # A pipeline module that hangs far past its budget (the ~17-min research
    # stall) must be cut off by the asyncio.wait_for hard ceiling even when
    # httpx's own transport timeout never fires, and surface as a retryable
    # module_timeout (one retry, then terminal).
    async def _hang(*a, **k):
        await asyncio.sleep(5)
        return _ok_response()

    post = AsyncMock(side_effect=_hang)
    ps = [
        patch.object(orch, "_create_module_output", AsyncMock(return_value="out1")),
        patch.object(orch, "_fail_module_output", AsyncMock()),
        patch.object(orch, "_save_module_output", AsyncMock()),
        # Tiny effective deadline so the test doesn't actually wait: 0 + 0.05.
        patch.dict(orch.MODULE_TIMEOUTS, {"sie": 0}),
        patch.object(orch, "HARD_DEADLINE_BUFFER_SECONDS", 0.05),
        patch.object(orch.httpx, "AsyncClient", _fake_async_client(post)),
    ]
    for p in ps:
        p.start()
    try:
        with pytest.raises(orch.StageError) as ei:
            await orch._call_module("sie", "r1", {"k": "v"})
    finally:
        for p in ps:
            p.stop()
    assert ei.value.stage == "sie"
    assert "module_timeout" in str(ei.value.cause)
    assert post.await_count == 2      # timed out, retried once, timed out again

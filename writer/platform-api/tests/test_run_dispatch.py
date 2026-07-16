"""Tests for the shared run-dispatch helper + the Fanout service_page job."""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

# `python-louvain` (imported as `community`) is a Fanout clustering dependency
# present in the deployed image but unbuildable in this test sandbox. Importing
# `fanout.jobs` pulls it transitively (via fanout/pipeline/clustering.py), which
# generate_service_page_core never touches — stub it so the import succeeds.
if "community" not in sys.modules:
    _community = types.ModuleType("community")
    _community.community_louvain = MagicMock()
    sys.modules["community"] = _community

import services.run_dispatch as rd


def _supabase_recording(inserts: dict):
    """A supabase mock that records insert payloads per table and returns a
    fixed run id for the runs insert."""
    def table(name):
        t = MagicMock()

        def insert(payload):
            inserts.setdefault(name, []).append(payload)
            ex = MagicMock()
            ex.execute.return_value = MagicMock(data=[{"id": "run-1"}])
            return ex

        t.insert.side_effect = insert
        return t

    client = MagicMock()
    client.table.side_effect = table
    return client


def test_create_run_and_snapshot_writes_run_and_snapshot():
    inserts: dict = {}
    client = _supabase_recording(inserts)
    with patch.object(rd, "get_supabase", return_value=client), \
         patch.object(rd.brand_voice_service, "resolve_brand_guide_text", return_value="BRAND"), \
         patch.object(rd.icp_service, "resolve_icp_text", return_value="ICP"), \
         patch.object(rd, "detect_format", return_value="text"):
        run_id = rd.create_run_and_snapshot(
            client={"id": "c1"},
            keyword="emergency drain cleaning",
            content_type="service_page",
            created_by="u1",
        )

    assert run_id == "run-1"
    run_row = inserts["runs"][0]
    assert run_row["content_type"] == "service_page"
    assert run_row["service"] == "emergency drain cleaning"  # defaults to keyword
    assert run_row["status"] == "queued"
    assert run_row["created_by"] == "u1"
    snap = inserts["client_context_snapshots"][0]
    assert snap["run_id"] == "run-1"
    assert snap["brand_guide_text"] == "BRAND"
    assert snap["icp_text"] == "ICP"


def test_create_run_and_snapshot_blog_service_is_none():
    inserts: dict = {}
    client = _supabase_recording(inserts)
    with patch.object(rd, "get_supabase", return_value=client), \
         patch.object(rd.brand_voice_service, "resolve_brand_guide_text", return_value=""), \
         patch.object(rd.icp_service, "resolve_icp_text", return_value=""), \
         patch.object(rd, "detect_format", return_value="text"):
        rd.create_run_and_snapshot(client={"id": "c1"}, keyword="kw", content_type="blog_post")
    assert inserts["runs"][0]["service"] is None


# ----------------------------------------------------------------------
# Fanout generate_service_page_core
# ----------------------------------------------------------------------

def _run_status_supabase(status: str):
    client = MagicMock()
    chain = client.table.return_value
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.single.return_value = chain
    chain.execute.return_value = MagicMock(data={"status": status})
    return client


def test_generate_service_page_core_success():
    from fanout import jobs

    with patch("services.local_seo_service._get_client", return_value={"id": "c1"}), \
         patch("services.run_dispatch.create_run_and_snapshot", return_value="run-1") as mk, \
         patch("services.orchestrator.orchestrate_run", AsyncMock()), \
         patch("db.supabase_client.get_supabase", return_value=_run_status_supabase("complete")):
        ok = jobs.generate_service_page_core(
            session={"client_id": "c1"}, keyword="drain cleaning", user_id="u1",
        )

    assert ok == "run-1"  # returns the suite run id (truthy) on success
    assert mk.call_args.kwargs["content_type"] == "service_page"
    assert mk.call_args.kwargs["keyword"] == "drain cleaning"


def test_generate_service_page_core_failed_run():
    from fanout import jobs

    errors: list[str] = []
    with patch("services.local_seo_service._get_client", return_value={"id": "c1"}), \
         patch("services.run_dispatch.create_run_and_snapshot", return_value="run-1"), \
         patch("services.orchestrator.orchestrate_run", AsyncMock()), \
         patch("db.supabase_client.get_supabase", return_value=_run_status_supabase("failed")):
        ok = jobs.generate_service_page_core(
            session={"client_id": "c1"}, keyword="x", user_id=None, error_sink=errors,
        )
    assert ok is None
    # The real reason is surfaced to the caller's sink, not swallowed.
    assert errors == ["run status failed"]


def test_generate_service_page_core_no_client():
    from fanout import jobs

    errors: list[str] = []
    ok = jobs.generate_service_page_core(session={}, keyword="x", user_id=None, error_sink=errors)
    assert ok is None
    assert errors == ["session has no client_id"]


def test_generate_service_page_core_error_sink_optional():
    # Back-compat: callers that don't pass error_sink (the Generate button path)
    # still work unchanged and never raise on the sink being absent.
    from fanout import jobs

    ok = jobs.generate_service_page_core(session={}, keyword="x", user_id=None)
    assert ok is None


def test_generate_article_core_surfaces_writer_abort_to_sink():
    # A blog WriterAbort (the load-bearing brief/writer failure — e.g. what the
    # 'liraglutide vs semaglutide' cluster hit) must surface its stable code to the
    # caller's sink, so the scheduler dead-letters with the ACTUAL reason instead
    # of a generic 'content generation failed'.
    from fanout import jobs
    from fanout.writer.models import WriterAbort

    errors: list[str] = []
    brief_row = {"output_json": {"intent_type": None, "metadata": {}}}
    sie_row = {"output_json": {}}
    with patch("fanout.jobs._cluster_intent_override", return_value=(None, False)), \
         patch("fanout.jobs._sync_cluster_intent"), \
         patch("fanout.briefgen.cache.get_fresh_brief", return_value=brief_row), \
         patch("fanout.sie.cache.get_fresh_analysis", return_value=sie_row), \
         patch("fanout.writer.adapter.build_writer_inputs",
               return_value=(object(), object(), [])), \
         patch("fanout.writer.pipeline.build_writer_deps", return_value=object()), \
         patch("fanout.writer.pipeline.generate_article",
               side_effect=WriterAbort("empty_serp", "no SERP results")):
        ok = jobs.generate_article_core(
            "s1", "cl1", "liraglutide vs semaglutide", 2840, error_sink=errors,
        )
    assert ok is False
    assert errors == ["empty_serp: no SERP results"]

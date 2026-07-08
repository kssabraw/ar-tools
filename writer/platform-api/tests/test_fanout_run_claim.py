"""Queued-run claim lifecycle (fanout storage/silo.py + jobs._claims_start).

The pipeline worker pool caps concurrent runs, so a submitted job can wait for
a slot. Endpoints claim runs as `queued` (try_claim_run); the worker flips the
claim to `running` when it actually picks the job up (try_mark_started); a
/cancel while still queued lands `cancelled` and the worker then skips the job
entirely. These tests wire the real supabase client to an httpx.MockTransport
and pin the guarded transitions.
"""

from unittest.mock import patch

import httpx
import pytest

pytest.importorskip("supabase")

from fanout.storage import silo  # noqa: E402


def _client(handler):
    from supabase import create_client

    fake_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2ln"
    client = create_client("http://mock.local", fake_jwt)
    client.postgrest.session._transport = httpx.MockTransport(handler)
    return client


def _patch_row_response(seen, rows):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        import json

        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(rows).encode(),
        )

    return handler


def test_try_claim_run_claims_as_queued_and_excludes_live_statuses():
    seen: dict = {}
    with patch.object(silo, "get_service_client",
                      return_value=_client(_patch_row_response(seen, [{"id": "s1"}]))):
        assert silo.try_claim_run("s1") is True
    assert '"status": "queued"' in seen["body"] or '"status":"queued"' in seen["body"]
    # the guard: a session already queued OR running must not be re-claimed
    assert "not.in.%28queued%2Crunning%29" in seen["url"] or 'not.in.(queued,running)' in seen["url"]


def test_try_claim_run_false_when_already_claimed():
    seen: dict = {}
    with patch.object(silo, "get_service_client",
                      return_value=_client(_patch_row_response(seen, []))):
        assert silo.try_claim_run("s1") is False


def test_try_mark_started_flips_only_queued():
    seen: dict = {}
    with patch.object(silo, "get_service_client",
                      return_value=_client(_patch_row_response(seen, [{"id": "s1"}]))):
        assert silo.try_mark_started("s1") is True
    assert '"status": "running"' in seen["body"] or '"status":"running"' in seen["body"]
    assert "status=eq.queued" in seen["url"]


def test_try_mark_started_false_when_cancelled_while_queued():
    seen: dict = {}
    with patch.object(silo, "get_service_client",
                      return_value=_client(_patch_row_response(seen, []))):
        assert silo.try_mark_started("s1") is False


def test_try_mark_cancelled_covers_queued_and_running():
    seen: dict = {}
    with patch.object(silo, "get_service_client",
                      return_value=_client(_patch_row_response(seen, [{"id": "s1"}]))):
        assert silo.try_mark_cancelled("s1") is True
    assert "in.%28queued%2Crunning%29" in seen["url"] or "in.(queued,running)" in seen["url"]


def test_claims_start_skips_job_when_no_longer_queued():
    """A run cancelled while waiting for a worker slot must never execute —
    no metering, no external calls."""
    from fanout import jobs

    ran = []

    @jobs._claims_start
    def fake_job(session_id: str) -> None:
        ran.append(session_id)

    with patch.object(jobs.store, "try_mark_started", return_value=False):
        assert fake_job("s1") is None
    assert ran == []

    with patch.object(jobs.store, "try_mark_started", return_value=True):
        fake_job("s2")
    assert ran == ["s2"]


def test_summary_short_circuits_queued_to_cheap_payload():
    """A queued session's summary must report status=queued (so the UI can show
    the waiting card) without running the full count aggregation."""
    session = {
        "status": "queued",
        "last_error": None,
        "approval_required": False,
        "estimated_cost_usd": 1.5,
        "actual_cost_usd": 0,
        "cost_breakdown": {},
    }
    with patch.object(silo, "get_session", return_value=session):
        out = silo.get_pipeline_summary("s1")
    assert out["status"] == "queued"
    assert out["plan"] is None
    assert out["expansion"] == silo._EMPTY_EXPANSION

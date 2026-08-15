"""Queued-run claim lifecycle (fanout storage/silo.py).

Endpoints claim runs as `queued` (try_claim_run); the durable worker then flips
the claim to `running` when it picks the job up (try_mark_running_durable, tested
in test_fanout_durable_expand.py); a /cancel while still queued lands `cancelled`
(try_mark_cancelled) and the durable claim then refuses the run. These tests wire
the real supabase client to an httpx.MockTransport and pin the guarded
transitions.
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


def test_try_mark_running_durable_flips_queued_or_running():
    """The durable claim flips a queued OR already-running session to running (so
    a reaper/drain requeue after a crash re-runs) — unlike the retired
    queued-only try_mark_started."""
    seen: dict = {}
    with patch.object(silo, "get_service_client",
                      return_value=_client(_patch_row_response(seen, [{"id": "s1"}]))):
        assert silo.try_mark_running_durable("s1") is True
    assert '"status": "running"' in seen["body"] or '"status":"running"' in seen["body"]
    assert "in.%28queued%2Crunning%29" in seen["url"] or "in.(queued,running)" in seen["url"]


def test_try_mark_running_durable_false_when_not_runnable():
    """A cancelled/finished session (not queued/running) isn't claimable, so a
    requeued row skips instead of re-running."""
    seen: dict = {}
    with patch.object(silo, "get_service_client",
                      return_value=_client(_patch_row_response(seen, []))):
        assert silo.try_mark_running_durable("s1") is False


def test_try_mark_cancelled_covers_queued_and_running():
    seen: dict = {}
    with patch.object(silo, "get_service_client",
                      return_value=_client(_patch_row_response(seen, [{"id": "s1"}]))):
        assert silo.try_mark_cancelled("s1") is True
    assert "in.%28queued%2Crunning%29" in seen["url"] or "in.(queued,running)" in seen["url"]


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

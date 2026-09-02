"""Contract tests for ``POST /director/module-changes`` — the CI reporter's
inbound for DORA's guide sync. Exercised through FastAPI's TestClient on the
real router so the ordering that matters is proven end-to-end: the gate, the
secret, and the size ceiling are all checked BEFORE the body is parsed, and a
malformed body is a clean 422 rather than a 500."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import settings
from routers import director as R
from services import guide_sync

SECRET = "s3cr3t-token"
GOOD = {
    "commit_sha": "0123456789abcdef",
    "commit_range": "aaa..bbb",
    "changes": [{"module": "rank_tracker", "files": ["frontend/src/pages/Rankings.tsx"],
                 "diff": "+x", "commits": [{"sha": "0123456789abcdef", "title": "Add export"}]}],
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "director_enabled", True)
    monkeypatch.setattr(settings, "guide_sync_enabled", True)
    monkeypatch.setattr(settings, "guide_sync_secret", SECRET)
    app = FastAPI()
    app.include_router(R.router)
    return TestClient(app)


def _post(client, body, secret=SECRET, headers=None):
    h = {"Content-Type": "application/json"}
    if secret is not None:
        h["Authorization"] = f"Bearer {secret}"
    h.update(headers or {})
    data = body if isinstance(body, (bytes, str)) else json.dumps(body)
    return client.post("/director/module-changes", content=data, headers=h)


def test_secret_matches_is_constant_time_and_unicode_safe():
    assert R.secret_matches("abc", "abc")
    assert not R.secret_matches("abd", "abc")
    assert not R.secret_matches("", "abc")
    assert not R.secret_matches("abc", "")
    # A non-ASCII header value is simply wrong — never a TypeError → 500.
    assert not R.secret_matches("ünïcode", "abc")


def test_disabled_gate_503_before_anything(client, monkeypatch):
    monkeypatch.setattr(settings, "director_enabled", False)
    with patch.object(guide_sync, "ingest_module_changes") as ingest:
        r = _post(client, GOOD)
    assert r.status_code == 503 and r.json()["detail"] == "guide_sync_disabled"
    ingest.assert_not_called()


def test_unconfigured_secret_503(client, monkeypatch):
    monkeypatch.setattr(settings, "guide_sync_secret", "")
    r = _post(client, GOOD)
    assert r.status_code == 503 and r.json()["detail"] == "guide_sync_not_configured"


def test_wrong_or_missing_secret_401_even_with_malformed_body(client):
    with patch.object(guide_sync, "ingest_module_changes") as ingest:
        assert _post(client, GOOD, secret="nope").status_code == 401
        assert _post(client, GOOD, secret=None).status_code == 401
        # The body is never parsed for an unauthenticated caller.
        assert _post(client, b"{not json", secret="nope").status_code == 401
    ingest.assert_not_called()


def test_x_header_secret_also_accepted(client):
    with patch.object(guide_sync, "ingest_module_changes", return_value={"accepted": [], "skipped": 0}):
        r = _post(client, GOOD, secret=None, headers={"X-Guide-Sync-Secret": SECRET})
    assert r.status_code == 200


def test_oversized_declared_body_413(client, monkeypatch):
    monkeypatch.setattr(settings, "guide_sync_max_body_bytes", 100)
    with patch.object(guide_sync, "ingest_module_changes") as ingest:
        r = _post(client, {"commit_sha": "0123456789abcdef", "changes": [{"module": "x", "diff": "y" * 500}]})
    assert r.status_code == 413
    ingest.assert_not_called()


def test_malformed_json_422_not_500(client):
    with patch.object(guide_sync, "ingest_module_changes") as ingest:
        r = _post(client, b"{not json")
    assert r.status_code == 422 and r.json()["detail"].startswith("invalid_payload")
    ingest.assert_not_called()


def test_schema_violation_422(client):
    r = _post(client, {"commit_sha": "abc", "changes": []})  # sha too short
    assert r.status_code == 422


def test_ok_path_hands_validated_payload_to_ingest_and_clips_files(client):
    big = {**GOOD, "changes": [{**GOOD["changes"][0], "files": [f"frontend/src/f{i}.tsx" for i in range(700)]}]}
    with patch.object(guide_sync, "ingest_module_changes",
                      return_value={"accepted": [{"run_id": "r1"}], "skipped": 0}) as ingest:
        r = _post(client, big)
    assert r.status_code == 200 and r.json() == {"ok": True, "accepted": [{"run_id": "r1"}], "skipped": 0}
    payload = ingest.call_args.args[0]
    assert payload["commit_sha"] == "0123456789abcdef"
    assert len(payload["changes"][0]["files"]) == 500  # clipped, not rejected
    assert payload["changes"][0]["commits"][0]["title"] == "Add export"


def test_ingest_failure_502(client):
    with patch.object(guide_sync, "ingest_module_changes", side_effect=RuntimeError("db down")):
        r = _post(client, GOOD)
    assert r.status_code == 502 and r.json()["detail"] == "guide_sync_error"

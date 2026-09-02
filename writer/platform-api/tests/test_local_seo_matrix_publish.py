"""Tests for the matrix bulk publish (Phase 5): the publishable selector, the
publishing-cell reconcile, the enqueue, and the per-cell publish job."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from services import local_seo_matrix as core
from services import local_seo_matrix_store as store

MATRIX = {
    "id": "m1", "client_id": "c1", "publish_destination": "wordpress", "publish_status": "publish",
    "services": core.normalize_services(["Roof restoration"]),
    "locations": core.normalize_locations(["Melbourne", "Hawthorn", "Caulfield", "Moorabbin"]),
    "location": "Melbourne,Victoria,Australia", "location_code": 1, "url_pattern": core.DEFAULT_URL_PATTERN,
}


def _cells():
    cells = core.build_cells(["Roof restoration"], ["Melbourne", "Hawthorn", "Caulfield", "Moorabbin"])
    for i, c in enumerate(cells):
        c["id"] = f"cell-{i}"
    return cells


def test_select_publishable_defaults_and_by_id():
    cells = _cells()
    cells[0].update(status="done", page_id="p0")
    cells[1].update(status="publish_failed", page_id="p1")
    cells[2].update(status="publish_blocked", page_id="p2")
    cells[3].update(status="published", page_id="p3")
    assert [c["id"] for c in core.select_publishable(cells)] == ["cell-0", "cell-1"]
    assert [c["id"] for c in core.select_publishable(cells, ["cell-2", "cell-3"])] == ["cell-2", "cell-3"]
    # A cell with no page (missing / generating) is never publishable, even by id.
    cells[0].update(status="done", page_id=None)
    assert core.select_publishable(cells, ["cell-0"]) == []


def test_reconcile_handles_publishing_cells():
    cells = _cells()
    for i, c in enumerate(cells):
        c.update(status="publishing", job_id=f"pj-{i}", page_id=f"p{i}")
    jobs = {
        "pj-0": {"status": "running"},
        "pj-1": {"status": "complete", "result": {"status": "published", "url": "https://x/a/", "error": None}},
        "pj-2": {"status": "failed", "error": "boom"},
        # pj-3 missing (reaped)
    }
    patches = dict(core.reconcile_cell_updates(cells, jobs))
    assert cells[0]["id"] not in patches
    assert patches["cell-1"] == {"status": "published", "url": "https://x/a/", "error": None}
    assert patches["cell-2"] == {"status": "publish_failed", "error": "boom"}
    assert patches["cell-3"] == {"status": "publish_failed", "error": "job_not_found"}
    # A complete job carrying an unexpected status is recorded as a failure.
    assert core._reconcile_publishing({"status": "complete", "result": {"status": "weird"}})["status"] == "publish_failed"


def test_start_publish_enqueues_per_cell_with_matrix_defaults_and_force_rules():
    cells = _cells()
    cells[0].update(status="done", page_id="p0")
    cells[1].update(status="publish_blocked", page_id="p1")
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "pj-0"}]
    with patch.object(store, "_matrix_row", return_value=MATRIX), \
         patch.object(store, "reconcile", return_value=0), \
         patch.object(store, "_cells", return_value=cells), \
         patch.object(store, "get_supabase", return_value=sb), \
         patch.object(store, "_apply_patches") as apply:
        result = store.start_publish("m1", "c1", "u", force_voice=True)  # no ids → force ignored
    assert result == {"job_ids": ["pj-0"], "cell_ids": ["cell-0"]}
    row = sb.table.return_value.insert.call_args[0][0][0]
    assert row["job_type"] == "local_seo_matrix_publish"
    assert row["payload"] == {
        "client_id": "c1", "matrix_id": "m1", "matrix_cell_id": "cell-0", "page_id": "p0", "user_id": "u",
        "destination": "wordpress", "status": "publish", "force_voice": False,
    }
    assert apply.call_args[0][0][0] == ("cell-0", {"status": "publishing", "job_id": "pj-0", "error": None})

    # Explicit id on the blocked cell + force_voice → honoured, with an override destination.
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "pj-1"}]
    with patch.object(store, "_matrix_row", return_value=MATRIX), \
         patch.object(store, "reconcile", return_value=0), \
         patch.object(store, "_cells", return_value=cells), \
         patch.object(store, "get_supabase", return_value=sb), \
         patch.object(store, "_apply_patches"):
        result = store.start_publish("m1", "c1", "u", destination="google_docs", force_voice=True, cell_ids=["cell-1"])
    payload = sb.table.return_value.insert.call_args[0][0][0]["payload"]
    assert result["cell_ids"] == ["cell-1"] and payload["force_voice"] is True and payload["destination"] == "google_docs"


@pytest.mark.asyncio
async def test_run_publish_job_records_outcome_on_cell_and_job():
    from services import local_seo_service as svc

    job = {"id": "pj-0", "payload": {
        "client_id": "c1", "matrix_id": "m1", "matrix_cell_id": "cell-0", "page_id": "p0", "user_id": "u",
        "destination": "wordpress", "status": "publish", "force_voice": False,
    }}
    sb = MagicMock()

    async def ok(page_id, user_id, destination, status, force_voice):
        assert (page_id, destination, status, force_voice) == ("p0", "wordpress", "publish", False)
        return {"success": True, "url": "https://fcr.com.au/roof-restoration-melbourne/"}

    with patch.object(svc, "publish_page", new=ok), patch.object(store, "get_supabase", return_value=sb), \
         patch.object(store, "record_publish_outcome") as rec:
        await store.run_publish_job(job)
    rec.assert_called_once_with("cell-0", "p0", "published", "https://fcr.com.au/roof-restoration-melbourne/", None)
    job_patch = sb.table.return_value.update.call_args[0][0]
    assert job_patch["status"] == "complete" and job_patch["result"]["status"] == "published"

    async def blocked(*a, **k):
        raise HTTPException(status_code=409, detail="voice_violation: cheapest")

    with patch.object(svc, "publish_page", new=blocked), patch.object(store, "get_supabase", return_value=sb), \
         patch.object(store, "record_publish_outcome") as rec:
        await store.run_publish_job(job)
    assert rec.call_args[0][2] == "publish_blocked"
    assert sb.table.return_value.update.call_args[0][0]["result"]["status"] == "publish_blocked"

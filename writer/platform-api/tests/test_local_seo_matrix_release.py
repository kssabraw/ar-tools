"""Tests for services.local_seo_matrix_release — the drip release (Phase 4) —
plus the auto-publish outcome mapping at the generate seam."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from services import local_seo_matrix as core
from services import local_seo_matrix_release as rel
from services import local_seo_matrix_store as store

NOW = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)  # a Wednesday

MATRIX = {
    "id": "m1", "client_id": "c1", "name": "Roofing", "location": "Melbourne,Victoria,Australia",
    "location_code": 1000567, "url_pattern": core.DEFAULT_URL_PATTERN, "base_url": "https://fcr.com.au",
    "page_template_url": None, "entity_provider": None, "created_by": "owner",
    "publish_destination": "wordpress", "publish_status": "draft",
    "services": core.normalize_services(["Roof restoration", "Gutters"]),
    "locations": core.normalize_locations(["Melbourne", "Hawthorn"]),
    "release_enabled": True, "release_mode": "weekly", "release_weekday": 2, "release_day_of_month": None,
    "release_per_count": 2, "release_status": "active", "release_next_run_at": None, "release_last_run_at": None,
}


def _cells():
    cells = core.build_cells(["Roof restoration", "Gutters"], ["Melbourne", "Hawthorn"], seed_city="Melbourne")
    for i, c in enumerate(cells):
        c["id"] = f"cell-{i}"
    return cells


# ── pure ──────────────────────────────────────────────────────────────────────

def test_schedule_mapping_round_trips_through_the_shared_advance():
    sched = rel.schedule_of(MATRIX)
    assert sched == {"mode": "weekly", "weekday": 2, "day_of_month": None}
    from services.website_release import advance

    patch_ = rel.to_matrix_patch(advance(sched, remaining=3, now=NOW))
    assert patch_["release_last_run_at"] == NOW.isoformat()
    assert patch_["release_next_run_at"].startswith("2026-09-09")  # next Wednesday
    assert "release_status" not in patch_
    done = rel.to_matrix_patch(advance(sched, remaining=0, now=NOW))
    assert done["release_status"] == "complete" and done["release_next_run_at"] is None


def test_validate_body_normalises_and_rejects_bad_mode():
    cols = rel.validate_body({"mode": "monthly", "per_release_count": 0, "enabled": False}, NOW)
    assert cols["release_mode"] == "monthly" and cols["release_day_of_month"] == 2
    assert cols["release_per_count"] == 1 and cols["release_enabled"] is False
    assert cols["release_next_run_at"].startswith("2026-10-02")
    with pytest.raises(ValueError):
        rel.validate_body({"mode": "hourly"}, NOW)


def test_schedule_view_and_releasable_count():
    view = rel.schedule_view(MATRIX)
    assert view["enabled"] is True and view["per_release_count"] == 2 and view["mode"] == "weekly"
    cells = _cells()
    cells[0]["released_at"] = "2026-09-01T00:00:00Z"
    cells[1]["status"] = "done"
    assert rel.releasable_count(cells) == 2


def test_publish_outcome_mappers():
    assert core.publish_outcome_from_error("voice_violation: cheapest | budget") == (
        "publish_blocked", None, "voice_violation: cheapest | budget",
    )
    assert core.publish_outcome_from_error("wordpress_not_configured")[0] == "publish_failed"
    assert core.publish_outcome_from_error("")[0] == "publish_failed"
    assert core.publish_outcome_from_result({"success": True, "url": "https://x/a/", "doc_url": "d"}) == ("published", "https://x/a/", None)
    assert core.publish_outcome_from_result({"doc_url": "https://docs/1"}) == ("published", "https://docs/1", None)


# ── run_release ───────────────────────────────────────────────────────────────

def test_run_release_claims_location_major_and_enqueues_with_publish_after():
    cells = _cells()
    sb = MagicMock()
    with patch.object(rel, "is_frozen", return_value=False), \
         patch.object(store, "_matrix_row", return_value=MATRIX), \
         patch.object(store, "reconcile", return_value=0), \
         patch.object(store, "_cells", return_value=cells), \
         patch.object(store, "enqueue_cells", return_value=["j1", "j2"]) as enqueue, \
         patch.object(rel, "get_supabase", return_value=sb), \
         patch.object(rel, "_now", return_value=NOW):
        result = rel.run_release("m1", "c1", 2, "owner")
    # Both Melbourne cells first (location-major: cell-0 = roof/Melbourne,
    # cell-2 = gutters/Melbourne), 2 Hawthorn cells remain.
    assert result["released"] == ["cell-0", "cell-2"] and result["remaining"] == 2
    claimed = sb.table.return_value.update.call_args[0][0]
    assert claimed["released_at"] == NOW.isoformat()
    assert sb.table.return_value.update.return_value.in_.call_args[0] == ("id", ["cell-0", "cell-2"])
    args, kwargs = enqueue.call_args
    assert [c["id"] for c in args[1]] == ["cell-0", "cell-2"] and args[3] == "owner"
    assert kwargs["publish_after"] is True


def test_run_release_refuses_frozen_and_noops_on_empty_grid():
    with patch.object(rel, "is_frozen", return_value=True):
        with pytest.raises(HTTPException) as exc:
            rel.run_release("m1", "c1", 1, "u")
    assert exc.value.status_code == 409 and exc.value.detail == "client_frozen"
    cells = _cells()
    for c in cells:
        c["status"] = "done"
    with patch.object(rel, "is_frozen", return_value=False), \
         patch.object(store, "_matrix_row", return_value=MATRIX), \
         patch.object(store, "reconcile", return_value=0), \
         patch.object(store, "_cells", return_value=cells), \
         patch.object(store, "enqueue_cells") as enqueue:
        assert rel.run_release("m1", "c1", 3, "u") == {"released": [], "remaining": 0}
    enqueue.assert_not_called()


def test_enqueue_cells_payload_carries_publish_settings():
    cells = _cells()
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "j1"}]
    with patch.object(store, "get_supabase", return_value=sb), patch.object(store, "_apply_patches"):
        ids = store.enqueue_cells(MATRIX, cells[:1], cells, "owner", publish_after=True)
    assert ids == ["j1"]
    payload = sb.table.return_value.insert.call_args[0][0][0]["payload"]
    assert payload["publish_after"] is True
    assert payload["publish_destination"] == "wordpress" and payload["publish_status"] == "draft"
    with patch.object(store, "get_supabase", return_value=sb), patch.object(store, "_apply_patches"):
        store.enqueue_cells(MATRIX, cells[:1], cells, "owner")
    assert "publish_after" not in sb.table.return_value.insert.call_args[0][0][0]["payload"]


# ── set_release / tick ────────────────────────────────────────────────────────

def test_set_release_fires_immediate_and_completes_when_nothing_remains():
    patches: list[dict] = []
    with patch.object(store, "_matrix_row", return_value=MATRIX), \
         patch.object(store, "_cells", return_value=[]), \
         patch.object(rel, "_patch_matrix", side_effect=lambda _id, p: patches.append(p)), \
         patch.object(rel, "run_release", return_value={"released": ["cell-0", "cell-1"], "remaining": 0}) as run, \
         patch.object(rel, "_now", return_value=NOW):
        result = rel.set_release("m1", "c1", {"mode": "daily", "immediate_count": 2, "per_release_count": 1}, "u")
    run.assert_called_once_with("m1", "c1", 2, "u")
    assert result["released_now"] == ["cell-0", "cell-1"]
    assert patches[0]["release_mode"] == "daily" and patches[0]["release_status"] == "active"
    assert patches[1]["release_status"] == "complete" and patches[1]["release_next_run_at"] is None


def test_tick_releases_due_skips_frozen_and_advances():
    due = [dict(MATRIX, id="m1", client_id="c1"), dict(MATRIX, id="m2", client_id="frozen")]
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.lte.return_value
    chain.execute.return_value.data = due
    patches: list[tuple[str, dict]] = []
    with patch.object(rel.settings, "local_seo_matrix_enabled", True), \
         patch.object(rel, "get_supabase", return_value=sb), \
         patch.object(rel, "is_frozen", side_effect=lambda cid: cid == "frozen"), \
         patch.object(rel, "run_release", return_value={"released": ["x"], "remaining": 5}) as run, \
         patch.object(rel, "_patch_matrix", side_effect=lambda i, p: patches.append((i, p))), \
         patch.object(rel, "_now", return_value=NOW):
        fired = rel.enqueue_due_matrix_releases()
    assert fired == 1
    run.assert_called_once_with("m1", "c1", 2, "owner")
    assert patches[0][0] == "m1" and patches[0][1]["release_next_run_at"].startswith("2026-09-09")
    with patch.object(rel.settings, "local_seo_matrix_enabled", False):
        assert rel.enqueue_due_matrix_releases() == 0


# ── the auto-publish at the generate seam ─────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_after_generate_records_outcomes():
    from services import local_seo_service as svc

    payload = {"matrix_cell_id": "cell-0", "user_id": "u", "publish_destination": "wordpress", "publish_status": "publish"}

    async def ok(page_id, user_id, destination, status):
        assert (destination, status) == ("wordpress", "publish")
        return {"success": True, "url": "https://fcr.com.au/roof-restoration-melbourne/"}

    async def blocked(*a, **k):
        raise HTTPException(status_code=409, detail="voice_violation: cheapest")

    async def broken(*a, **k):
        raise RuntimeError("boom")

    with patch.object(svc, "publish_page", new=ok), patch.object(store, "record_publish_outcome") as rec:
        await svc._publish_after_generate("p1", payload, "job")
    rec.assert_called_once_with("cell-0", "p1", "published", "https://fcr.com.au/roof-restoration-melbourne/", None)
    with patch.object(svc, "publish_page", new=blocked), patch.object(store, "record_publish_outcome") as rec:
        await svc._publish_after_generate("p1", payload, "job")
    assert rec.call_args[0][2] == "publish_blocked" and "cheapest" in rec.call_args[0][4]
    with patch.object(svc, "publish_page", new=broken), patch.object(store, "record_publish_outcome") as rec:
        await svc._publish_after_generate("p1", payload, "job")
    assert rec.call_args[0][2] == "publish_failed"

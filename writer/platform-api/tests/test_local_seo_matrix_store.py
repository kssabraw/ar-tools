"""Store-half tests for services.local_seo_matrix_store — the gating + payload
composition of the immediate run, with the DB and coverage marking mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from services import local_seo_matrix as core
from services import local_seo_matrix_store as store

MATRIX = {
    "id": "m1", "client_id": "c1", "name": "Roofing", "location": "Melbourne,Victoria,Australia",
    "location_code": 1000567, "url_pattern": core.DEFAULT_URL_PATTERN, "base_url": "https://fcr.com.au",
    "page_template_url": None, "entity_provider": None,
    "services": core.normalize_services(["Roof restoration"]),
    "locations": core.normalize_locations([
        "Melbourne",
        {"name": "Hawthorn", "location_code": 21030, "canonical": "Hawthorn,Victoria,Australia"},
    ]),
}


def _cells():
    cells = core.build_cells(["Roof restoration"], ["Melbourne", "Hawthorn"], seed_city="Melbourne")
    for i, c in enumerate(cells):
        c["id"] = f"cell-{i}"
    return cells


def test_location_for_cell_uses_row_code_else_metro():
    cells = _cells()
    assert store._location_for_cell(MATRIX, cells[0]) == ("Melbourne,Victoria,Australia", 1000567)
    assert store._location_for_cell(MATRIX, cells[1]) == ("Hawthorn,Victoria,Australia", 21030)


def _fake_sb(inserted_ids):
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": j} for j in inserted_ids]
    return sb


def test_start_generate_enqueues_one_job_per_cell_with_matrix_payload():
    cells = _cells()
    sb = _fake_sb(["job-a", "job-b"])
    with patch.object(store, "_runnable", return_value=(MATRIX, cells, cells)), \
         patch.object(store, "get_supabase", return_value=sb), \
         patch.object(store, "_apply_patches") as apply:
        result = store.start_generate("m1", "c1", "user-1")
    assert result["job_ids"] == ["job-a", "job-b"]
    assert result["cell_ids"] == ["cell-0", "cell-1"]
    assert result["estimate"]["count"] == 2 and result["estimate"]["gates"] == []
    rows = sb.table.return_value.insert.call_args[0][0]
    assert [r["job_type"] for r in rows] == ["local_seo_generate", "local_seo_generate"]
    p0, p1 = rows[0]["payload"], rows[1]["payload"]
    assert p0["keyword"] == "Roof restoration Melbourne" and p0["location_code"] == 1000567
    assert p1["keyword"] == "Roof restoration Hawthorn" and p1["location_code"] == 21030
    assert p0["matrix_id"] == "m1" and p0["matrix_cell_id"] == "cell-0" and p0["user_id"] == "user-1"
    assert rows[0]["scheduled_at"] < rows[1]["scheduled_at"]  # staggered
    # Cells flipped to queued with their job ids.
    patched = [c[0][0][0] for c in apply.call_args_list]
    assert patched == [("cell-0", {"status": "queued", "job_id": "job-a", "error": None}),
                       ("cell-1", {"status": "queued", "job_id": "job-b", "error": None})]


def test_start_generate_blocks_on_gates():
    cells = _cells()
    with patch.object(store, "_runnable", return_value=(MATRIX, cells, cells)), \
         patch.object(store.settings, "local_seo_matrix_max_cells_per_run", 1):
        with pytest.raises(HTTPException) as exc:
            store.start_generate("m1", "c1", "user-1")
    assert exc.value.status_code == 400 and exc.value.detail == "matrix_cell_limit"

    big = [dict(c, id=f"x{i}") for i in range(201) for c in cells[:1]]
    with patch.object(store, "_runnable", return_value=(MATRIX, big, cells)):
        with pytest.raises(HTTPException) as exc:
            store.start_generate("m1", "c1", "user-1")
    assert exc.value.status_code == 409 and exc.value.detail == "matrix_signoff_required"
    with patch.object(store, "_runnable", return_value=(MATRIX, big, [])):
        assert store.start_generate("m1", "c1", "user-1", signoff_acknowledged=True)["job_ids"] == []


def test_estimate_run_reports_gates_without_raising():
    cells = _cells()
    with patch.object(store, "_runnable", return_value=(MATRIX, cells, cells)), \
         patch.object(store.settings, "local_seo_matrix_max_cells_per_run", 1):
        est = store.estimate_run("m1", "c1")
    assert est["count"] == 2 and est["cell_ids"] == ["cell-0", "cell-1"]
    assert [g["kind"] for g in est["gates"]] == ["matrix_cell_limit"]


def test_validate_pattern_400s():
    with pytest.raises(HTTPException) as exc:
        store._validate_pattern("/{service}/")
    assert exc.value.status_code == 400 and exc.value.detail == "url_pattern_missing_location_token"
    assert store._validate_pattern("") == core.DEFAULT_URL_PATTERN

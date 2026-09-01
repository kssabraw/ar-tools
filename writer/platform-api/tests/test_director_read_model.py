"""Unit tests for services.director.read_model — provider isolation (build
spec §12): a failing provider degrades the model to a gap, never breaks the
read; E1 fail-loud: an unknown producer source surfaces as unwatched_seam,
never silently skipped."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from services.director import providers, read_model

TODAY = date(2026, 8, 28)


def _empty_board(client_id=None):
    return {"as_of": TODAY.isoformat(), "clients": [], "workload": {}}


def test_build_read_model_degrades_on_provider_failure_not_crash():
    with (
        patch.object(read_model, "get_supabase", return_value=MagicMock()),
        patch.object(read_model.pm_signals, "build_board_digest", side_effect=RuntimeError("db down")),
        patch.object(providers, "prov_strategy", side_effect=RuntimeError("boom")),
        patch.object(providers, "prov_autonomy", return_value=None),
        patch.object(providers, "prov_producers", return_value=None),
        patch.object(providers, "prov_interventions", return_value=None),
        patch.object(providers, "prov_qa", return_value=None),
        patch.object(providers, "prov_content", return_value=None),
        patch.object(providers, "prov_duplicates", return_value=None),
        patch.object(providers, "prov_pace_audit", return_value=None),
        patch.object(providers, "prov_sermastr_audit", return_value=None),
    ):
        model = read_model.build_read_model(None, TODAY)

    # The board read itself failed too — build_read_model must still return a
    # coherent (empty) model, not raise.
    assert model["strategy"] is None
    assert model["delivery"] is None or model["delivery"] == {}
    assert model["flow"] == {"flags": [], "count": 0}


def test_build_read_model_assembles_a_healthy_model():
    board = {
        "as_of": TODAY.isoformat(),
        "clients": [{"client_id": "c1", "open_count": 2}],
        "workload": {"members": []},
    }
    with (
        patch.object(read_model, "get_supabase", return_value=MagicMock()),
        patch.object(read_model.pm_signals, "build_board_digest", return_value=board),
        patch.object(providers, "prov_strategy", return_value={"status_counts": {}, "approved_unplaced": []}),
        patch.object(providers, "prov_autonomy", return_value=None),
        patch.object(providers, "prov_producers", return_value={"open_by_source": {"manual": 1}, "unwatched_seam": None}),
        patch.object(providers, "prov_interventions", return_value=None),
        patch.object(providers, "prov_qa", return_value=None),
        patch.object(providers, "prov_content", return_value=None),
        patch.object(providers, "prov_duplicates", return_value=None),
        patch.object(providers, "prov_pace_audit",
                     return_value={"decisions": {"total": 3, "approved": 2}}),
        patch.object(providers, "prov_sermastr_audit", return_value=None),
    ):
        model = read_model.build_read_model(None, TODAY)

    assert model["portfolio"] is True
    # The agent track-record blocks are wired into the model (scalar client_id).
    assert model["pace_audit"] == {"decisions": {"total": 3, "approved": 2}}
    assert "sermastr_audit" in model
    assert model["delivery"] == {"clients": board["clients"]}
    assert model["producers"]["open_by_source"] == {"manual": 1}
    assert model["flow"] == {"flags": [], "count": 0}


def test_build_read_model_single_client_scopes_client_ids():
    board = {"as_of": TODAY.isoformat(), "clients": [{"client_id": "c1"}], "workload": {}}
    captured = {}

    def _capture_strategy(supabase, client_ids, today):
        captured["client_ids"] = client_ids
        return None

    with (
        patch.object(read_model, "get_supabase", return_value=MagicMock()),
        patch.object(read_model.pm_signals, "build_board_digest", return_value=board),
        patch.object(providers, "prov_strategy", side_effect=_capture_strategy),
        patch.object(providers, "prov_autonomy", return_value=None),
        patch.object(providers, "prov_producers", return_value=None),
        patch.object(providers, "prov_interventions", return_value=None),
        patch.object(providers, "prov_qa", return_value=None),
        patch.object(providers, "prov_content", return_value=None),
        patch.object(providers, "prov_duplicates", return_value=None),
    ):
        read_model.build_read_model("c1", TODAY)

    assert captured["client_ids"] == ["c1"]


def test_e1_unwatched_producer_source_surfaces_end_to_end_not_dropped():
    """A tasks.source the read model doesn't recognize must appear as an
    unwatched_seam flag on the final model, never be silently absorbed."""
    tasks_rows = [
        {"id": "t1", "client_id": "c1", "source": "manual"},
        {"id": "t2", "client_id": "c1", "source": "some_new_producer_nobody_registered"},
    ]
    sb = MagicMock()
    table_mock = MagicMock()
    table_mock.select.return_value = table_mock
    table_mock.eq.return_value = table_mock
    table_mock.is_.return_value = table_mock
    table_mock.in_.return_value = table_mock
    table_mock.limit.return_value = table_mock
    table_mock.execute.return_value = MagicMock(data=tasks_rows)
    sb.table.return_value = table_mock

    board = {"as_of": TODAY.isoformat(), "clients": [{"client_id": "c1"}], "workload": {}}

    with (
        patch.object(read_model, "get_supabase", return_value=sb),
        patch.object(read_model.pm_signals, "build_board_digest", return_value=board),
        patch.object(providers, "prov_strategy", return_value=None),
        patch.object(providers, "prov_autonomy", return_value=None),
        patch.object(providers, "prov_interventions", return_value=None),
        patch.object(providers, "prov_qa", return_value=None),
        patch.object(providers, "prov_content", return_value=None),
        patch.object(providers, "prov_duplicates", return_value=None),
        # prov_producers itself runs for real against the fake table.
    ):
        model = read_model.build_read_model(None, TODAY)

    flags = model["flow"]["flags"]
    unwatched = [f for f in flags if f["seam"] == "unwatched_seam"]
    assert len(unwatched) == 1
    assert unwatched[0]["evidence"]["source"] == "some_new_producer_nobody_registered"

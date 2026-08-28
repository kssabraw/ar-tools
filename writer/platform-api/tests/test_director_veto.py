"""Unit tests for services.director.veto — the autonomy pre-flight veto
(build spec §8): fail-open pre-flight downgrade of an about-to-auto-execute
candidate on an in-flight conflicting target, plus a wiring test proving the
insertion point in autonomy_executor's act loop (before the budget reserve)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services import autonomy_executor as ax
from services.director import veto as V


def _fake_supabase(jobs=None, tasks=None, interventions=None):
    rows_by_table = {"async_jobs": jobs or [], "tasks": tasks or [], "interventions": interventions or []}

    def table(name):
        mock = MagicMock()
        mock.select.return_value = mock
        mock.eq.return_value = mock
        mock.in_.return_value = mock
        mock.is_.return_value = mock
        mock.execute.return_value = MagicMock(data=rows_by_table.get(name, []))
        return mock

    sb = MagicMock()
    sb.table.side_effect = table
    return sb


def test_preflight_conflict_no_keyword_never_conflicts():
    # rebuild_action_plan carries no keyword — nothing to conflict on, and no
    # DB call is even needed to reach that conclusion.
    assert V.preflight_conflict({"action": "rebuild_action_plan"}, "c1") is False


def test_preflight_conflict_true_on_inflight_async_job():
    sb = _fake_supabase(jobs=[{"id": "j1", "payload": {"keyword": "Roof Repair"}}])
    with patch.object(V, "get_supabase", return_value=sb):
        assert V.preflight_conflict({"keyword": "roof repair"}, "c1") is True


def test_preflight_conflict_true_on_live_task_target():
    sb = _fake_supabase(tasks=[{"id": "t1", "target": {"keyword": "roof repair"}}])
    with patch.object(V, "get_supabase", return_value=sb):
        assert V.preflight_conflict({"keyword": "Roof Repair"}, "c1") is True


def test_preflight_conflict_true_on_open_intervention_target():
    sb = _fake_supabase(interventions=[{"id": "iv1", "target": {"keyword": "roof repair"}}])
    with patch.object(V, "get_supabase", return_value=sb):
        assert V.preflight_conflict({"keyword": "roof repair"}, "c1") is True


def test_preflight_conflict_false_when_nothing_matches():
    sb = _fake_supabase(jobs=[{"id": "j1", "payload": {"keyword": "plumber"}}])
    with patch.object(V, "get_supabase", return_value=sb):
        assert V.preflight_conflict({"keyword": "roof repair"}, "c1") is False


def test_preflight_conflict_fails_open_on_exception():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("db down")
    with patch.object(V, "get_supabase", return_value=sb):
        assert V.preflight_conflict({"keyword": "roof repair"}, "c1") is False


# --- wiring: the veto downgrades outcome to "propose" BEFORE the budget reserve ---

def _loop_setup(monkeypatch, *, veto_enabled: bool, veto_result: bool):
    from services import campaign_goals, freeze

    monkeypatch.setattr(ax.settings, "autonomy_enabled", True)
    monkeypatch.setattr(ax.settings, "autonomy_max_tier", 2)
    monkeypatch.setattr(ax.settings, "autonomy_max_content_per_week", 3)
    monkeypatch.setattr(ax.settings, "autonomy_local_seo_cost_usd", 1.0)
    monkeypatch.setattr(ax.settings, "director_autonomy_veto_enabled", veto_enabled)
    monkeypatch.setattr(
        ax, "_client_row",
        lambda cid: {"id": "c1", "name": "Acme", "autonomy_tier": 2,
                     "retainer_monthly": 3000.0, "is_sab": False,
                     "business_location": "123 Main St, Miami, FL 33101"},
    )
    monkeypatch.setattr(campaign_goals, "assess_goals", lambda cid, today=None: [{"status": "behind"}])
    monkeypatch.setattr(freeze, "is_frozen", lambda cid: False)
    monkeypatch.setattr(
        ax, "_latest_action_plan",
        lambda cid: {"items": [
            {"kind": "quick_win", "keyword": "electrician miami", "cta_label": "Create page"},
        ]},
    )
    monkeypatch.setattr(
        ax, "_keyword_city_resolver",
        lambda client: (lambda kw: {"location": "Miami,Florida,United States", "location_code": 1013}),
    )
    monkeypatch.setattr(ax.autonomy_budget, "budget_for_client", lambda row: 500.0)
    monkeypatch.setattr(ax.autonomy_budget, "spent_this_month", lambda cid, today=None: 0.0)
    reserved: list[float] = []
    monkeypatch.setattr(
        ax.autonomy_budget, "reserve",
        lambda cid, amt, *, cap, today=None: (reserved.append(amt), True)[1],
    )
    monkeypatch.setattr(ax, "_write_ledger", lambda *a, **k: None)
    monkeypatch.setattr(ax, "_emit_digest", lambda *a, **k: None)
    monkeypatch.setattr("services.director.veto.preflight_conflict", lambda rec, client_id: veto_result)
    return reserved


def test_veto_downgrades_to_propose_before_budget_reserve(monkeypatch):
    reserved = _loop_setup(monkeypatch, veto_enabled=True, veto_result=True)
    ran: list[dict] = []
    out = ax.run_autonomy_for_client("c1", execute=lambda cand, cid: ran.append(cand))

    # The vetoed candidate never executed and the budget was never reserved —
    # the veto sits BEFORE the reserve call in the act loop.
    assert ran == []
    assert reserved == []
    assert "generate_local_seo_page" in out["proposed"]


def test_veto_disabled_by_default_lets_execution_through(monkeypatch):
    reserved = _loop_setup(monkeypatch, veto_enabled=False, veto_result=True)
    ran: list[dict] = []
    out = ax.run_autonomy_for_client("c1", execute=lambda cand, cid: ran.append(cand))

    # veto_result=True would have vetoed everything had the flag been on —
    # proving the flag, not the predicate, gates whether it ever runs.
    assert "generate_local_seo_page" in [c["action"] for c in ran]
    assert reserved == [1.0]
    assert "generate_local_seo_page" not in out["proposed"]

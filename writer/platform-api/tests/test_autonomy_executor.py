"""Unit tests for the autonomy executor (pure core + a mocked loop pass)."""

from services import autonomy_executor as ax


# --- pure: gather_candidates ------------------------------------------------

def test_gather_candidates_no_behind_goals_is_empty():
    goals = [{"status": "on_track"}, {"status": "achieved"}]
    assert ax.gather_candidates(goals, {"items": [{"kind": "quick_win", "keyword": "x"}]}) == []


def test_gather_candidates_behind_emits_free_rebuild_first():
    out = ax.gather_candidates([{"status": "behind"}], None)
    assert out[0]["action"] == "rebuild_action_plan"
    assert out[0]["cost_usd"] == 0.0 and out[0]["requires"] == "none"


def test_gather_candidates_maps_content_items_to_approval_proposals():
    plan = {"items": [
        {"kind": "quick_win", "keyword": "roof repair", "recommendation": "Reoptimize"},
        {"kind": "opportunity", "keyword": "gutter guards", "recommendation": "Refresh"},
        {"kind": "rank_drop", "keyword": "skip me"},        # not content-shaped
        {"kind": "quick_win", "keyword": ""},               # no keyword → skipped
    ]}
    out = ax.gather_candidates([{"status": "overdue"}], plan)
    content = [c for c in out if c["action"] == "start_content_run"]
    assert {c["keyword"] for c in content} == {"roof repair", "gutter guards"}
    assert all(c["requires"] == "approval" for c in content)  # never auto in v1


# --- pure: decide_candidates + AUTO_EXECUTE ---------------------------------

def test_decide_rebuild_autos_content_proposes_at_tier1():
    cands = ax.gather_candidates(
        [{"status": "behind"}],
        {"items": [{"kind": "quick_win", "keyword": "roof repair"}]},
    )
    decided = ax.decide_candidates(
        cands, client_tier=1, budget_left=100.0, freeze=False,
        content_this_week=0, content_cap=3,
    )
    by_action = {d["action"]: d["outcome"] for d in decided}
    assert by_action["rebuild_action_plan"] == "auto"
    assert by_action["start_content_run"] == "propose"   # requires=approval


def test_freeze_escalates_everything():
    cands = ax.gather_candidates([{"status": "behind"}], None)
    decided = ax.decide_candidates(
        cands, client_tier=2, budget_left=100.0, freeze=True,
        content_this_week=0, content_cap=3,
    )
    assert all(d["outcome"] == "escalate" for d in decided)


def test_auto_execute_allowlist_is_just_rebuild():
    assert ax.AUTO_EXECUTE == frozenset({"rebuild_action_plan"})


# --- mocked loop ------------------------------------------------------------

def test_run_autonomy_disabled_short_circuits(monkeypatch):
    monkeypatch.setattr(ax.settings, "autonomy_enabled", False)
    assert ax.run_autonomy_for_client("c1")["status"] == "disabled"


def test_run_autonomy_executes_only_rebuild_records_the_rest(monkeypatch):
    from services import campaign_goals, freeze

    monkeypatch.setattr(ax.settings, "autonomy_enabled", True)
    monkeypatch.setattr(ax.settings, "autonomy_max_tier", 2)
    monkeypatch.setattr(ax.settings, "autonomy_max_content_per_week", 3)
    monkeypatch.setattr(
        ax, "_client_row",
        lambda cid: {"id": "c1", "name": "Acme", "autonomy_tier": 1,
                     "retainer_monthly": 3000.0, "is_sab": False},
    )
    monkeypatch.setattr(campaign_goals, "assess_goals", lambda cid, today=None: [{"status": "behind"}])
    monkeypatch.setattr(freeze, "is_frozen", lambda cid: False)
    monkeypatch.setattr(
        ax, "_latest_action_plan",
        lambda cid: {"items": [{"kind": "quick_win", "keyword": "roof repair"}]},
    )
    monkeypatch.setattr(ax.autonomy_budget, "budget_for_client", lambda row: 500.0)
    monkeypatch.setattr(ax.autonomy_budget, "spent_this_month", lambda cid, today=None: 0.0)
    # ledger + digest are best-effort I/O — stub them out.
    monkeypatch.setattr(ax, "_write_ledger", lambda *a, **k: None)
    monkeypatch.setattr(ax, "_emit_digest", lambda *a, **k: None)

    ran: list[str] = []
    out = ax.run_autonomy_for_client("c1", execute=lambda action, cid: ran.append(action))

    assert out["status"] == "ran" and out["tier"] == 1
    assert ran == ["rebuild_action_plan"]           # only the free, safe action ran
    assert out["executed"] == ["rebuild_action_plan"]
    assert "start_content_run" in out["proposed"]   # content surfaced, never run
    assert out["cost_usd"] == 0.0


def test_run_autonomy_not_opted_in_skips(monkeypatch):
    monkeypatch.setattr(ax.settings, "autonomy_enabled", True)
    monkeypatch.setattr(
        ax, "_client_row",
        lambda cid: {"id": "c1", "name": "Acme", "autonomy_tier": 0},
    )
    assert ax.run_autonomy_for_client("c1")["status"] == "not_opted_in"

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


def test_gather_candidates_without_url_or_location_are_approval_proposals():
    # "Reoptimize" quick-wins + opportunities want an EXISTING page improved but
    # carry no URL → proposals (reoptimize_page, requires=approval). A create-page
    # item with no client location can't be auto-targeted → also a proposal.
    plan = {"items": [
        {"kind": "quick_win", "keyword": "roof repair", "cta_label": "Reoptimize"},
        {"kind": "opportunity", "keyword": "gutter guards"},
        {"kind": "quick_win", "keyword": "new metal roofs", "cta_label": "Create page"},
        {"kind": "rank_drop", "keyword": "skip me"},        # not content-shaped
        {"kind": "quick_win", "keyword": ""},               # no keyword → skipped
    ]}
    out = ax.gather_candidates([{"status": "overdue"}], plan, client_location=None)
    content = [c for c in out if c["action"] != "rebuild_action_plan"]
    assert {c["keyword"] for c in content} == {"roof repair", "gutter guards", "new metal roofs"}
    assert all(c["requires"] == "approval" for c in content)  # nothing auto without a target


def test_gather_candidates_create_page_with_location_is_auto_eligible():
    plan = {"items": [
        {"kind": "quick_win", "keyword": "emergency electrician", "cta_label": "Create page"},
        {"kind": "quick_win", "keyword": "panel upgrade", "cta_label": "Reoptimize"},
    ]}
    out = ax.gather_candidates([{"status": "behind"}], plan, client_location="Austin, TX")
    auto = [c for c in out if c["requires"] == "none" and c["action"] != "rebuild_action_plan"]
    assert len(auto) == 1
    c = auto[0]
    assert c["action"] == "generate_local_seo_page"
    assert c["keyword"] == "emergency electrician" and c["location"] == "Austin, TX"
    assert c["cost_usd"] == ax.settings.autonomy_local_seo_cost_usd
    # the "Reoptimize" one stays a proposal (needs a URL)
    assert any(c["action"] == "reoptimize_page" and c["requires"] == "approval" for c in out)


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
    assert by_action["reoptimize_page"] == "propose"   # requires=approval (no URL)


def test_freeze_escalates_everything():
    cands = ax.gather_candidates([{"status": "behind"}], None)
    decided = ax.decide_candidates(
        cands, client_tier=2, budget_left=100.0, freeze=True,
        content_this_week=0, content_cap=3,
    )
    assert all(d["outcome"] == "escalate" for d in decided)


def test_auto_execute_allowlist():
    assert ax.AUTO_EXECUTE == frozenset({"rebuild_action_plan", "generate_local_seo_page"})


# --- mocked loop ------------------------------------------------------------

def test_run_autonomy_disabled_short_circuits(monkeypatch):
    monkeypatch.setattr(ax.settings, "autonomy_enabled", False)
    assert ax.run_autonomy_for_client("c1")["status"] == "disabled"


def _loop_setup(monkeypatch, *, budget=500.0, spent=0.0, location="Austin, TX"):
    from services import campaign_goals, freeze

    monkeypatch.setattr(ax.settings, "autonomy_enabled", True)
    monkeypatch.setattr(ax.settings, "autonomy_max_tier", 2)
    monkeypatch.setattr(ax.settings, "autonomy_max_content_per_week", 3)
    monkeypatch.setattr(ax.settings, "autonomy_local_seo_cost_usd", 1.0)
    monkeypatch.setattr(
        ax, "_client_row",
        lambda cid: {"id": "c1", "name": "Acme", "autonomy_tier": 2,
                     "retainer_monthly": 3000.0, "is_sab": False,
                     "business_location": location},
    )
    monkeypatch.setattr(campaign_goals, "assess_goals", lambda cid, today=None: [{"status": "behind"}])
    monkeypatch.setattr(freeze, "is_frozen", lambda cid: False)
    monkeypatch.setattr(
        ax, "_latest_action_plan",
        lambda cid: {"items": [
            {"kind": "quick_win", "keyword": "emergency electrician", "cta_label": "Create page"},
            {"kind": "quick_win", "keyword": "panel upgrade", "cta_label": "Reoptimize"},
        ]},
    )
    monkeypatch.setattr(ax.autonomy_budget, "budget_for_client", lambda row: budget)
    monkeypatch.setattr(ax.autonomy_budget, "spent_this_month", lambda cid, today=None: spent)
    monkeypatch.setattr(ax.autonomy_budget, "reserve", lambda cid, amt, *, cap, today=None: True)
    monkeypatch.setattr(ax, "_write_ledger", lambda *a, **k: None)
    monkeypatch.setattr(ax, "_emit_digest", lambda *a, **k: None)


def test_run_autonomy_auto_commissions_create_page_proposes_reoptimize(monkeypatch):
    _loop_setup(monkeypatch)
    ran: list[dict] = []
    out = ax.run_autonomy_for_client("c1", execute=lambda cand, cid: ran.append(cand))

    assert out["status"] == "ran" and out["tier"] == 2
    ran_actions = [c["action"] for c in ran]
    # the free rebuild AND the create-page local-SEO page both auto-ran
    assert ran_actions == ["rebuild_action_plan", "generate_local_seo_page"]
    gen = next(c for c in ran if c["action"] == "generate_local_seo_page")
    assert gen["keyword"] == "emergency electrician" and gen["location"] == "Austin, TX"
    # the "Reoptimize" one (no URL) was proposed, not run
    assert "reoptimize_page" in out["proposed"]
    assert out["cost_usd"] == 1.0   # one local-SEO page reserved


def test_run_autonomy_over_budget_proposes_the_paid_page(monkeypatch):
    # $0 budget: the create-page candidate can't be reserved → proposed, not run.
    _loop_setup(monkeypatch, budget=0.0)
    ran: list[dict] = []
    out = ax.run_autonomy_for_client("c1", execute=lambda cand, cid: ran.append(cand))
    assert [c["action"] for c in ran] == ["rebuild_action_plan"]   # only the free action
    assert "generate_local_seo_page" in out["proposed"]
    assert out["cost_usd"] == 0.0


def test_run_autonomy_not_opted_in_skips(monkeypatch):
    monkeypatch.setattr(ax.settings, "autonomy_enabled", True)
    monkeypatch.setattr(
        ax, "_client_row",
        lambda cid: {"id": "c1", "name": "Acme", "autonomy_tier": 0},
    )
    assert ax.run_autonomy_for_client("c1")["status"] == "not_opted_in"

"""Unit tests for the autonomy policy engine (pure — no I/O)."""

from services import autonomy_policy as ap


def _p(action, **kw):
    return {"action": action, **kw}


def test_effective_tier_caps_and_floors():
    assert ap.effective_tier(3, 2) == 2        # capped at the ceiling
    assert ap.effective_tier(1, 2) == 1
    assert ap.effective_tier(None, 2) == 0     # missing = off
    assert ap.effective_tier(-5, 2) == 0       # negative = off
    assert ap.effective_tier(2, 0) == 0        # a 0 ceiling disables everything


def test_freeze_beats_everything():
    d = ap.classify(_p("rebuild_action_plan"), client_tier=2, freeze=True)
    assert d.outcome == "escalate" and "frozen" in d.reason.lower()


def test_senior_and_passthrough_escalate():
    assert ap.classify(_p("start_content_run", requires="senior"), client_tier=2).outcome == "escalate"
    assert ap.classify(_p("disavow"), client_tier=2).outcome == "escalate"


def test_unknown_action_escalates():
    d = ap.classify(_p("do_something_weird"), client_tier=2)
    assert d.outcome == "escalate" and "unknown" in d.reason.lower()


def test_out_of_tier_proposes():
    # publish_to_client_site is tier 3; a tier-2 client can't auto it.
    d = ap.classify(_p("publish_to_client_site"), client_tier=2)
    assert d.outcome == "propose"
    # a Tier-2 content action for a Tier-1 client → propose (not auto).
    d = ap.classify(_p("start_content_run"), client_tier=1)
    assert d.outcome == "propose"


def test_tier1_action_autos_for_tier1_client():
    d = ap.classify(_p("schedule_gbp_posts"), client_tier=1, budget_left=100.0)
    assert d.outcome == "auto"


def test_over_budget_proposes():
    d = ap.classify(_p("start_content_run", cost_usd=50.0), client_tier=2, budget_left=10.0)
    assert d.outcome == "propose" and "budget" in d.reason.lower()
    # exactly at budget is allowed (cost == budget_left is not "over").
    assert ap.classify(_p("start_content_run", cost_usd=10.0), client_tier=2, budget_left=10.0).outcome == "auto"


def test_rate_cap_proposes_only_content():
    at_cap = ap.classify(_p("start_content_run"), client_tier=2, content_this_week=3, content_cap=3)
    assert at_cap.outcome == "propose" and "rate" in at_cap.reason.lower()
    # a non-content Tier-≤2 action is unaffected by the content cap.
    assert ap.classify(_p("run_maps_scan"), client_tier=2, content_this_week=9, content_cap=3).outcome == "auto"


def test_happy_path_autos():
    d = ap.classify(_p("reoptimize_page", cost_usd=2.0), client_tier=2,
                    budget_left=100.0, content_this_week=1, content_cap=3)
    assert d.outcome == "auto" and d.is_auto

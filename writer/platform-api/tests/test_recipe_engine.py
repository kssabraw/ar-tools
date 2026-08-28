"""Unit tests for services.recipe_engine — the pure allocation engine.

Conformance-tested against the SOP §4 worked example
(docs/sops/Link_Building_Recipe_Engine.md): a $2,000/mo local plumber at the
66% margin target, reviews at 22, RD below competition, and an open maps drop.
No network / no DB — `allocate` is pure.
"""

from __future__ import annotations

from services import recipe_engine as re_


def _task_types(plan: dict) -> list[str]:
    return [t["task_type"] for t in plan["tasks"]]


def _line(plan: dict, task_type: str) -> dict:
    return next(t for t in plan["tasks"] if t["task_type"] == task_type)


# ---------------------------------------------------------------------------
# §4 worked example (conformance test)
# ---------------------------------------------------------------------------
def test_worked_example_trace():
    plan = re_.allocate(
        2000,
        {"deficient": ["referring_domains"], "review_gap": 3, "maps_drop": True},
        content_page_cap=64,  # the example's "up to ~64 pages"
    )
    # Deployable = 2000 × 0.34 = 680
    assert plan["deployable"] == 680.0
    assert plan["margin_used"] == 0.34
    # Reviews to threshold: 3 × $15 = $45
    reviews = _line(plan, "reviews")
    assert reviews["quantity"] == 3 and reviews["line_cost"] == 45.0
    # RD top-up: RMA v2 + Cloud Stack ($10 each; DAS is already in the baseline)
    assert "respect_mah_authoritay_v2" in _task_types(plan)
    assert "cloud_stack" in _task_types(plan)
    # Drop → 1 GBP Sniper run ($10)
    assert _line(plan, "gbp_sniper")["line_cost"] == 10.0
    # Remainder → 64 on-vector content pages × $5 = $320 → fully allocated
    pages = _line(plan, "content_page")
    assert pages["quantity"] == 64 and pages["line_cost"] == 320.0
    assert plan["remaining"] == 0.0
    assert plan["spent"] == 680.0
    assert "under_funded" not in plan["flags"]


def test_baseline_stack_totals():
    # Full baseline = $135; SAB variant (no GBP Blast) = $130 (§2).
    full = sum(i["quantity"] * i["unit_cost"] for i in re_.BASELINE_STACK)
    sab = sum(
        i["quantity"] * i["unit_cost"]
        for i in re_.BASELINE_STACK
        if not i.get("sab_excluded")
    )
    assert full == 135.0
    assert sab == 130.0


def test_sab_skips_gbp_blast():
    plan = re_.allocate(2000, {}, is_sab=True)
    assert "gbp_blast" not in _task_types(plan)


def test_under_funded_flags_when_baseline_exceeds_budget():
    plan = re_.allocate(400, {})  # deployable 136 < reporting alone
    assert "under_funded" in plan["flags"]
    assert plan["remaining"] < 0


def test_margin_past_50_percent_escalates_and_clamps():
    plan = re_.allocate(2000, {}, margin=0.60)
    assert "escalate_margin_below_50" in plan["flags"]
    assert plan["margin_used"] == 0.50


def test_frozen_client_gets_empty_plan():
    plan = re_.allocate(2000, {"frozen": True})
    assert plan["tasks"] == []
    assert plan["flags"] == ["frozen"]
    assert plan["spent"] == 0.0


def test_agency_assassin_added_for_large_retainers_when_budget_allows():
    plan = re_.allocate(2000, {})  # default content cap leaves budget over $85
    assert "agency_assassin" in _task_types(plan)


def test_agency_assassin_not_added_below_1200():
    plan = re_.allocate(1000, {})
    assert "agency_assassin" not in _task_types(plan)


def test_enterprise_funding_order_prefers_entity():
    plan = re_.allocate(
        3000,
        {"deficient": ["referring_domains", "entity"]},
        client_type="enterprise",
    )
    types = _task_types(plan)
    # entity tooling (social_post) is funded before the RD tools for enterprise
    assert types.index("social_post") < types.index("respect_mah_authoritay_v2")


def test_capacity_cap_flags():
    plan = re_.allocate(5000, {}, content_page_cap=10)
    pages = _line(plan, "content_page")
    assert pages["quantity"] == 10
    assert "capacity_capped" in plan["flags"]


# ---------------------------------------------------------------------------
# budget_envelope — what a retainer funds, without needing a stored plan.
#
# Most clients have never had a monthly plan generated, so reading
# monthly_task_plans alone leaves the assistant planning as if money were no
# object. BSA Claims ($500/mo) can't even cover the mandatory Baseline Stack.
# ---------------------------------------------------------------------------


def test_budget_envelope_matches_the_allocation_formula():
    env = re_.budget_envelope(2500.0)
    assert env["deployable"] == 850.0                      # 2500 × 0.34
    assert env["reporting_cost"] == re_.REPORTING_COST
    assert env["baseline_stack_cost"] == 135.0
    assert env["discretionary"] == 565.0                   # 850 − 150 − 135
    assert env["covers_baseline"] is True


def test_budget_envelope_goes_negative_when_the_retainer_cannot_fund_baseline():
    # The real BSA Claims case — a strategist must be told, not shown zero.
    env = re_.budget_envelope(500.0)
    assert env["discretionary"] == -115.0
    assert env["covers_baseline"] is False


def test_budget_envelope_excludes_the_gbp_blast_for_sab_clients():
    physical = re_.budget_envelope(2500.0)
    sab = re_.budget_envelope(2500.0, is_sab=True)
    assert sab["baseline_stack_cost"] == physical["baseline_stack_cost"] - 5.0
    assert sab["discretionary"] > physical["discretionary"]


def test_budget_envelope_handles_a_missing_retainer():
    env = re_.budget_envelope(None)
    assert env["deployable"] == 0.0 and env["covers_baseline"] is False


def test_budget_envelope_respects_the_drop_margin():
    env = re_.budget_envelope(2500.0, margin=re_.DROP_MARGIN)
    assert env["deployable"] == 1250.0 and env["discretionary"] == 965.0


# ---------------------------------------------------------------------------
# review_gap_from_gbp — the bug fix: the count lives in clients.gbp JSONB, not
# a (nonexistent) top-level clients.gbp_review_count column.
# ---------------------------------------------------------------------------
def test_review_gap_below_threshold():
    gap, signal = re_.review_gap_from_gbp({"gbp_review_count": 10})
    assert gap == re_.REVIEW_THRESHOLD - 10  # 15
    assert "10" in signal and str(re_.REVIEW_THRESHOLD) in signal


def test_review_gap_at_or_above_threshold_is_none():
    assert re_.review_gap_from_gbp({"gbp_review_count": re_.REVIEW_THRESHOLD}) == (None, None)
    assert re_.review_gap_from_gbp({"gbp_review_count": 60}) == (None, None)


def test_review_gap_no_count_or_no_gbp_is_none():
    assert re_.review_gap_from_gbp(None) == (None, None)
    assert re_.review_gap_from_gbp({}) == (None, None)
    assert re_.review_gap_from_gbp({"gbp_rating": 4.8}) == (None, None)


def test_review_gap_accepts_legacy_key_variants():
    # rating_and_review_count tolerates review_count / reviews_count fallbacks.
    assert re_.review_gap_from_gbp({"review_count": 5})[0] == re_.REVIEW_THRESHOLD - 5
    assert re_.review_gap_from_gbp({"reviews_count": "8"})[0] == re_.REVIEW_THRESHOLD - 8

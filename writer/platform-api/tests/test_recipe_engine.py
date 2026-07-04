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

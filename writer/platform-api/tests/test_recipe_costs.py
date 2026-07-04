"""Unit tests for the Recipe Engine price catalog + cost_of (the deterministic
cost grounding the strategist uses instead of LLM-guessed dollars) and the
tool_costs API-operation catalog."""

from __future__ import annotations

from services import recipe_engine, tool_costs


# ---------------------------------------------------------------------------
# recipe_engine.price_catalog / cost_of
# ---------------------------------------------------------------------------
def test_price_catalog_has_real_sop_prices():
    cat = recipe_engine.price_catalog()
    assert cat["content_page"]["unit_cost"] == recipe_engine.CONTENT_PAGE_COST == 5.0
    assert cat["niche_edit"]["unit_cost"] == 75.0
    assert cat["reviews"]["unit_cost"] == 15.0
    # baseline-stack + funding-menu tactics are all present
    assert "citations" in cat and "cloud_stack" in cat and "gbp_sniper" in cat


def test_cost_of_computes_from_catalog():
    items = [{"task_type": "content_page", "quantity": 5}]
    assert recipe_engine.cost_of(items) == 25.0
    mixed = [{"task_type": "content_page", "quantity": 2}, {"task_type": "niche_edit", "quantity": 1}]
    assert recipe_engine.cost_of(mixed) == 10.0 + 75.0


def test_cost_of_skips_unknown_and_nonpositive():
    assert recipe_engine.cost_of([{"task_type": "nope", "quantity": 3}]) is None
    assert recipe_engine.cost_of([{"task_type": "content_page", "quantity": 0}]) is None
    assert recipe_engine.cost_of([{"task_type": "content_page", "quantity": -2}]) is None


def test_cost_of_empty_or_malformed_is_none():
    assert recipe_engine.cost_of(None) is None
    assert recipe_engine.cost_of([]) is None
    assert recipe_engine.cost_of(["not a dict"]) is None
    assert recipe_engine.cost_of([{"task_type": "content_page", "quantity": "x"}]) is None


def test_cost_of_accepts_a_supplied_catalog():
    catalog = {"widget": {"unit_cost": 3.0}}
    assert recipe_engine.cost_of([{"task_type": "widget", "quantity": 4}], catalog) == 12.0
    # a task_type not in the supplied catalog contributes nothing
    assert recipe_engine.cost_of([{"task_type": "content_page", "quantity": 1}], catalog) is None


# ---------------------------------------------------------------------------
# tool_costs
# ---------------------------------------------------------------------------
def test_tool_catalog_researched_prices():
    cat = tool_costs.tool_catalog()
    # the solid vendor-priced ops are verified with real dollars
    assert cat["geo_grid_scan"]["verified"] and cat["geo_grid_scan"]["unit_cost"] == 0.37
    assert cat["backlink_intel"]["verified"] and cat["backlink_intel"]["unit_cost"] == 0.03
    assert cat["serp_snapshot"]["verified"] and cat["competitor_gbp"]["verified"]
    assert tool_costs.RESEARCHED_AT == "2026-07-04"


def test_all_ops_now_verified():
    # every tool op has a researched, confirmed price (LLM rates confirmed too)
    assert tool_costs.unverified_operations() == []
    cat = tool_costs.tool_catalog()
    assert all(e["verified"] for e in cat.values())
    assert cat["brand_scan"]["unit_cost"] == 0.02
    assert cat["page_audit"]["unit_cost"] == 0.10
    assert cat["keyword_research"]["unit_cost"] == 0.50

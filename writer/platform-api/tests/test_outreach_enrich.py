"""Pure-logic tests for the enrichment spend gate — no network, no database.

What is worth pinning here is the gate, not the plumbing: the estimate arithmetic, the per-user
daily budget refusal (which names its numbers, like every spend refusal in this module), and the
selection validation that refuses an empty or over-cap order rather than silently doing nothing or
truncating.
"""
import pytest

from services import outreach as svc
from services.outreach import OutreachError


def test_enrich_cost_is_billable_times_rate():
    assert svc.enrich_cost_cents(10, 5) == 50
    assert svc.enrich_cost_cents(0, 5) == 0
    assert svc.enrich_cost_cents(-3, 5) == 0


def test_spent_today_sums_order_estimates():
    orders = [{"est_cost_cents": 50}, {"est_cost_cents": 25}, {"est_cost_cents": None}]
    assert svc.enrich_spent_today_cents(orders) == 75


def test_budget_denial_names_the_numbers_and_passes_at_the_line():
    # $10 budget = 1000¢. 800 spent + 250 = 1050 > 1000 → refused.
    denial = svc.enrich_budget_denial(800, 250, 10.0)
    assert denial is not None and "10.00" in denial
    # Exactly at the line is allowed.
    assert svc.enrich_budget_denial(750, 250, 10.0) is None


def test_selection_is_deduped_and_bounded():
    assert svc.validate_enrich_selection(["a", "b", "a"], 10) == ["a", "b"]


def test_an_empty_selection_is_refused():
    with pytest.raises(OutreachError) as e:
        svc.validate_enrich_selection([], 10)
    assert e.value.code == "empty_selection"


def test_an_over_cap_selection_is_refused_not_truncated():
    with pytest.raises(OutreachError) as e:
        svc.validate_enrich_selection(["a", "b", "c"], 2)
    assert e.value.code == "selection_too_large"

"""Unit tests for the autonomy budget governor (pure sizing/arithmetic)."""

from datetime import date

from services import autonomy_budget as ab
from services import recipe_engine


def test_month_key_is_first_of_month():
    assert ab.month_key(date(2026, 8, 28)) == date(2026, 8, 1)
    assert ab.month_key(date(2026, 1, 1)) == date(2026, 1, 1)


def test_remaining_floors_at_zero():
    assert ab.remaining(100.0, 30.0) == 70.0
    assert ab.remaining(100.0, 100.0) == 0.0
    assert ab.remaining(100.0, 250.0) == 0.0   # never negative


def test_monthly_budget_matches_recipe_envelope():
    retainer = 3000.0
    env = recipe_engine.budget_envelope(retainer)
    # deployable = retainer × margin, gross.
    assert ab.monthly_budget(retainer, source="deployable") == round(env["deployable"], 2)
    # discretionary = after reporting + baseline (the honest ceiling, the default).
    assert ab.monthly_budget(retainer, source="discretionary") == round(max(0.0, env["discretionary"]), 2)


def test_monthly_budget_never_negative():
    # A retainer too small to cover reporting + baseline → discretionary < 0,
    # but the budget floors at 0 (nothing to spend autonomously).
    assert ab.monthly_budget(100.0, source="discretionary") == 0.0


def test_monthly_budget_none_retainer_is_zero():
    assert ab.monthly_budget(None) == 0.0

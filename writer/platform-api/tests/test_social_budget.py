"""Unit tests for the social budget meter's pure helpers (no DB)."""

from datetime import date

from services.social import budget


def test_month_key():
    assert budget.month_key(date(2026, 9, 5)) == date(2026, 9, 1)
    assert budget.month_key(date(2026, 1, 31)) == date(2026, 1, 1)


def test_remaining_floored():
    assert budget.remaining(75.0, 30.0) == 45.0
    assert budget.remaining(75.0, 100.0) == 0.0   # never negative
    assert budget.remaining(50, 50) == 0.0


def test_resolve_ceiling_uses_policy_when_positive():
    assert budget.resolve_ceiling({"monthly_ceiling_usd": 120}) == 120.0
    assert budget.resolve_ceiling({"monthly_ceiling_usd": "90.5"}) == 90.5


def test_resolve_ceiling_falls_back_to_default():
    from config import settings
    d = settings.social_monthly_ceiling_default_usd
    assert budget.resolve_ceiling(None) == round(d, 2)
    assert budget.resolve_ceiling({}) == round(d, 2)                 # no key
    assert budget.resolve_ceiling({"monthly_ceiling_usd": None}) == round(d, 2)
    assert budget.resolve_ceiling({"monthly_ceiling_usd": 0}) == round(d, 2)      # 0 => not "unlimited", use default
    assert budget.resolve_ceiling({"monthly_ceiling_usd": "oops"}) == round(d, 2)  # unparseable


def test_resolve_ceiling_explicit_default():
    assert budget.resolve_ceiling(None, default=200.0) == 200.0
    assert budget.resolve_ceiling({"monthly_ceiling_usd": -5}, default=200.0) == 200.0  # negative => default

"""Step 3 — Per-H2-group fair-share word budget allocation.

Regression tests for the bug where a promised H2 with no H3 children
shipped under-length while a sibling H2 carrying authority-gap H3s ran
the longest in the article. The fix allocates an equal share per H2
group and applies the 1.2x authority-gap multiplier *within* the group.
"""

from __future__ import annotations

from modules.writer.budget import (
    AUTHORITY_GAP_MULTIPLIER,
    CONCLUSION_BUDGET_TARGET,
    MIN_SECTION_BUDGET,
    allocate_budget,
)


def _h2(order: int, text: str = "") -> dict:
    return {"order": order, "level": "H2", "type": "content", "text": text or f"H2 {order}"}


def _h3(order: int, *, text: str = "", auth_gap: bool = False) -> dict:
    item = {"order": order, "level": "H3", "type": "content", "text": text or f"H3 {order}"}
    if auth_gap:
        item["source"] = "authority_gap_sme"
    return item


def test_empty_returns_empty():
    assert allocate_budget([], word_budget=2500) == {}


def test_single_h2_no_children_gets_all_body_budget():
    # 1 group → 1 share. Body budget = 2500 - 125 = 2375.
    structure = [_h2(1)]
    budgets = allocate_budget(structure, word_budget=2500)
    assert set(budgets.keys()) == {1}
    assert budgets[1] == 2500 - CONCLUSION_BUDGET_TARGET


def test_promised_h2_not_starved_by_auth_gap_sibling():
    """Regression: with one H2 group carrying two auth-gap H3s and a
    sibling H2 with zero children, the empty H2 used to receive a
    fraction (1 / (1 + 1 + 1.2 + 1.2) = ~23%) of body budget. With
    per-group fair shares, both groups should get ~50% of body budget.
    """
    structure = [
        _h2(1, "Sibling with auth-gap H3s"),
        _h3(2, auth_gap=True),
        _h3(3, auth_gap=True),
        _h2(4, "Promised spine, no children"),
    ]
    budgets = allocate_budget(structure, word_budget=2500)

    body_budget = 2500 - CONCLUSION_BUDGET_TARGET
    per_group = body_budget / 2

    # Promised spine (no children) gets the full per-group share.
    assert abs(budgets[4] - per_group) <= 1

    # Sibling group splits per_group between H2 + 2 auth-gap H3s with
    # weights 1.0 / 1.2 / 1.2 → total 3.4.
    total_w = 1.0 + AUTHORITY_GAP_MULTIPLIER + AUTHORITY_GAP_MULTIPLIER
    assert abs(budgets[1] - per_group * (1.0 / total_w)) <= 1
    assert abs(budgets[2] - per_group * (AUTHORITY_GAP_MULTIPLIER / total_w)) <= 1
    assert abs(budgets[3] - per_group * (AUTHORITY_GAP_MULTIPLIER / total_w)) <= 1

    # The starved-promised-section invariant: the empty H2 must receive
    # at least as many words as any single section in the auth-gap-rich
    # sibling group.
    sibling_max = max(budgets[1], budgets[2], budgets[3])
    assert budgets[4] >= sibling_max


def test_auth_gap_multiplier_applies_within_group():
    """Auth-gap H3s still get more words than their parent H2 within
    the same group — the multiplier survives, it's just scoped."""
    structure = [
        _h2(1),
        _h3(2, auth_gap=True),
        _h3(3, auth_gap=False),
    ]
    budgets = allocate_budget(structure, word_budget=2500)

    # Auth-gap H3 > parent H2 and > non-auth-gap H3 in the same group.
    assert budgets[2] > budgets[1]
    assert budgets[2] > budgets[3]
    # Non-auth-gap H3 == parent H2 weight.
    assert budgets[1] == budgets[3]


def test_three_groups_equal_shares_match_user_failure_layout():
    """Mirrors the user-reported article: 3 H2 groups, where the
    promised "Optimize" H2 has no H3 children but is sandwiched between
    auth-gap-rich groups. All three groups should get ~equal shares."""
    structure = [
        _h2(1, "Pricing"),
        _h3(2, text="Shop Score", auth_gap=True),
        _h2(3, "Optimize Product Listings"),  # no children
        _h2(4, "Returns"),
        _h3(5, text="Southeast Asia", auth_gap=True),
        _h3(6, text="Cold-start trust", auth_gap=True),
    ]
    budgets = allocate_budget(structure, word_budget=2500)

    body_budget = 2500 - CONCLUSION_BUDGET_TARGET
    per_group = body_budget / 3

    # Sum of words per group ≈ per_group for each group.
    pricing_total = budgets[1] + budgets[2]
    optimize_total = budgets[3]
    returns_total = budgets[4] + budgets[5] + budgets[6]
    assert abs(pricing_total - per_group) <= 2
    assert abs(optimize_total - per_group) <= 2
    assert abs(returns_total - per_group) <= 2

    # Promised "Optimize" H2 must out-word any single section anywhere.
    other_section_words = [budgets[1], budgets[2], budgets[4], budgets[5], budgets[6]]
    assert budgets[3] >= max(other_section_words)


def test_min_floor_respected():
    """Even with many groups and a small word budget, each section
    receives at least MIN_SECTION_BUDGET words."""
    structure = [_h2(i) for i in range(1, 11)]
    budgets = allocate_budget(structure, word_budget=400)
    for order in range(1, 11):
        assert budgets[order] >= MIN_SECTION_BUDGET


def test_faq_and_h1_excluded():
    structure = [
        {"order": 1, "level": "H1", "type": "content", "text": "Title"},
        _h2(2),
        {"order": 3, "level": "H2", "type": "faq-header", "text": "FAQ"},
        {"order": 4, "level": "H3", "type": "faq-question", "text": "Q?"},
    ]
    budgets = allocate_budget(structure, word_budget=2500)
    # Only the H2 content section should appear.
    assert set(budgets.keys()) == {2}

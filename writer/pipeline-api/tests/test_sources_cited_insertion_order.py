"""Sources Cited insertion order regression — must come AFTER all
existing article sections, not after conclusion specifically.

Regression: when conclusion is followed by FAQ in the article (the
post-d80e4bd layout), the old behavior of `_conclusion_order(article)`
returned conclusion.order, then sources sections got assigned
conclusion_order+1 and +2 — colliding with FAQ orders. Stable-sort
rendering then put Sources Cited INSIDE the FAQ block.

Fix: insertion anchor is max(article.order), not conclusion.order.
"""

from __future__ import annotations

from modules.sources_cited.pipeline import _conclusion_order


def test_insertion_anchor_returns_max_order_when_faq_after_conclusion():
    """The user's article has conclusion at order 6 and FAQ at orders
    7/8 — sources must be inserted after order 8, not order 6."""
    article = [
        {"order": 1, "type": "content", "level": "H1"},
        {"order": 2, "type": "intro", "level": "none"},
        {"order": 3, "type": "content", "level": "H2"},
        {"order": 4, "type": "content", "level": "H2"},
        {"order": 5, "type": "content", "level": "H2"},
        {"order": 6, "type": "conclusion", "level": "H2"},
        {"order": 7, "type": "faq-header", "level": "H2"},
        {"order": 8, "type": "faq-question", "level": "H3"},
    ]
    anchor = _conclusion_order(article)
    assert anchor == 8, (
        f"insertion anchor must be max(order)=8 (after FAQ); "
        f"old behavior returned conclusion.order=6 which collided "
        f"with FAQ at order 7"
    )


def test_insertion_anchor_returns_max_when_conclusion_is_last():
    """Backward compat: if the layout is the older body→FAQ→conclusion
    (no FAQ-after-conclusion), conclusion IS the max — anchor still
    returns the right value."""
    article = [
        {"order": 1, "type": "content", "level": "H1"},
        {"order": 2, "type": "content", "level": "H2"},
        {"order": 3, "type": "faq-header", "level": "H2"},
        {"order": 4, "type": "faq-question", "level": "H3"},
        {"order": 5, "type": "conclusion", "level": "none"},
    ]
    anchor = _conclusion_order(article)
    assert anchor == 5


def test_insertion_anchor_returns_max_when_no_conclusion_present():
    """Defensive: if no conclusion exists for any reason, anchor is
    still max(order)."""
    article = [
        {"order": 1, "type": "content", "level": "H1"},
        {"order": 2, "type": "content", "level": "H2"},
        {"order": 3, "type": "content", "level": "H2"},
    ]
    anchor = _conclusion_order(article)
    assert anchor == 3


def test_insertion_anchor_zero_for_empty_article():
    """Defensive: empty article returns 0 (the default for max)."""
    assert _conclusion_order([]) == 0

"""Step 3 — Word budget allocation across heading sections.

Per content-writer-module-prd-v1.3.md §6 Step 3:
- Conclusion gets a fixed 100-150 words regardless.
- Each H2 group (parent H2 + its child H3s) gets an equal share of the
  remaining body budget. This protects promised H2 sections that have no
  H3 children from being starved by sibling H2 groups that happen to
  carry one or more authority-gap H3s.
- Within a group, the parent H2 and each H3 split that group's share,
  with authority-gap H3s receiving a 1.2x multiplier *inside* the group
  (so the multiplier reallocates words within the group rather than
  pulling from neighboring promised H2s).

Why per-group fair shares (vs. the previous flat per-section weighting):
  The original allocator weighted every content section equally across
  the whole article and bumped authority-gap H3s by 1.2x. That made the
  total weight of a group scale with its H3 count, so a promised H2 with
  zero children competed for budget against a sibling group that
  contributed three or four weighted children. In practice that produced
  articles where a promised "spine" H2 shipped as 3 short paragraphs
  while an authority-gap-rich sibling ran the longest section in the
  article. Per-group fair shares fix the spine-vs-sibling imbalance
  without removing the authority-gap multiplier — auth-gap H3s still
  outweigh their parent H2 inside the group, just not at the article
  level.
"""

from __future__ import annotations

from typing import Any

CONCLUSION_BUDGET_TARGET = 125  # midpoint of 100-150
AUTHORITY_GAP_MULTIPLIER = 1.2
MIN_SECTION_BUDGET = 50


def _group_h2s(content_items: list[dict[str, Any]]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Walk content items in `order` and group each H2 with its
    consecutive H3 children (until the next H2)."""
    sorted_items = sorted(content_items, key=lambda h: h.get("order", 0))
    groups: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    current_h2: dict[str, Any] | None = None
    current_h3s: list[dict[str, Any]] = []
    for item in sorted_items:
        level = item.get("level")
        if level == "H2":
            if current_h2 is not None:
                groups.append((current_h2, current_h3s))
            current_h2 = item
            current_h3s = []
        elif level == "H3" and current_h2 is not None:
            current_h3s.append(item)
    if current_h2 is not None:
        groups.append((current_h2, current_h3s))
    return groups


def allocate_budget(
    heading_structure: list[dict[str, Any]],
    word_budget: int = 2500,
) -> dict[int, int]:
    """Returns map: heading_order -> section_budget (in words).

    FAQ headers and FAQ questions are excluded (they're written outside the budget).
    H1 and h1-enrichment also get 0 (handled separately).
    """
    content_items = [
        h for h in heading_structure
        if isinstance(h, dict)
        and h.get("type") == "content"
        and h.get("level") in ("H2", "H3")
    ]

    if not content_items:
        return {}

    # Reserve for conclusion
    available = max(word_budget - CONCLUSION_BUDGET_TARGET, 100)

    groups = _group_h2s(content_items)

    # Orphan H3s (H3 entries appearing before any H2 — shouldn't happen
    # in well-formed briefs, but guard anyway). Treat them as singleton
    # groups so they still get a share rather than dropping out silently.
    # Use object identity (id) rather than `in` because `in` would invoke
    # dict equality and could falsely match two H3 dicts with identical
    # field values.
    grouped_h3_ids = {id(h3) for _, h3s in groups for h3 in h3s}
    orphan_h3s = [
        h for h in content_items
        if h.get("level") == "H3" and id(h) not in grouped_h3_ids
    ]
    group_count = len(groups) + len(orphan_h3s)
    if group_count == 0:
        return {}

    per_group = available / group_count

    budget_map: dict[int, int] = {}

    for h2_item, h3_items in groups:
        # Within-group weights: parent H2 = 1.0, each H3 = 1.0 (or 1.2
        # for authority-gap H3s). The auth-gap multiplier reallocates
        # words *inside* the group instead of pulling from siblings.
        weights: list[tuple[int, float]] = [(h2_item.get("order", 0), 1.0)]
        for h3 in h3_items:
            order = h3.get("order", 0)
            is_auth_gap = h3.get("source") == "authority_gap_sme"
            weights.append((order, AUTHORITY_GAP_MULTIPLIER if is_auth_gap else 1.0))
        total_w = sum(w for _, w in weights) or 1.0
        for order, w in weights:
            budget_map[order] = max(int(round(per_group * (w / total_w))), MIN_SECTION_BUDGET)

    for orphan in orphan_h3s:
        order = orphan.get("order", 0)
        budget_map[order] = max(int(round(per_group)), MIN_SECTION_BUDGET)

    return budget_map

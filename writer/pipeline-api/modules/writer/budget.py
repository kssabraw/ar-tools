"""Step 3 — Word budget allocation across heading sections.

Per content-writer-module-prd-v1.3.md §6 Step 3:
- base_section_budget = word_budget / total_content_sections
- Authority gap H3s get 1.2x multiplier
- Conclusion gets a fixed 100-150 words regardless
- If total exceeds budget, scale non-conclusion sections down proportionally
"""

from __future__ import annotations

from typing import Any

CONCLUSION_BUDGET_TARGET = 125  # midpoint of 100-150
AUTHORITY_GAP_MULTIPLIER = 1.2


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

    # Compute weights
    weights: dict[int, float] = {}
    for item in content_items:
        order = item.get("order", 0)
        is_authority_gap = (
            item.get("level") == "H3"
            and item.get("source") == "authority_gap_sme"
        )
        weights[order] = AUTHORITY_GAP_MULTIPLIER if is_authority_gap else 1.0

    total_weight = sum(weights.values())
    base = available / total_weight if total_weight else 0

    budget_map: dict[int, int] = {}
    for order, w in weights.items():
        budget_map[order] = max(int(round(base * w)), 50)

    return budget_map

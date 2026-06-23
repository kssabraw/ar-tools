"""Writer registries transcribed verbatim from the bundle (M14 slice 3).

Sources: PRD #1 §5.11 (CTA templates), §5.14 (per-H2 body-length floor table /
`intent_format_template.h2_pattern`). Pure data — no logic. The Brief already carries
`format_directives.min_h2_body_words`; these floors are the fallback when the brief
leaves it 0 (and the per-intent `h2_pattern` name for logging).
"""

from __future__ import annotations

from .models import IntentType

# §5.14 — per-H2 body-length floor by intent (intent_format_template.h2_pattern).
H2_PATTERN: dict[IntentType, str] = {
    IntentType.how_to: "sequential_steps",
    IntentType.listicle: "ranked_items",
    IntentType.comparison: "parallel_axes",
    IntentType.informational: "topic_questions",
    IntentType.informational_commercial: "buyer_education_axes",
    IntentType.ecom: "feature_benefit",
    IntentType.local_seo: "place_bound_topics",
    IntentType.news: "news_lede",
}

H2_BODY_FLOOR: dict[IntentType, int] = {
    IntentType.how_to: 120,
    IntentType.listicle: 80,
    IntentType.comparison: 150,
    IntentType.informational: 180,
    IntentType.informational_commercial: 180,
    IntentType.ecom: 150,
    IntentType.local_seo: 150,
    IntentType.news: 100,
}

# §5.11 — intent CTA templates (used when no icp_text; our path always uses these).
CTA_TEMPLATE: dict[IntentType, str] = {
    IntentType.how_to: "Try these steps in your next task and measure the result.",
    IntentType.informational: "Explore the related sub-topics next.",
    IntentType.comparison: (
        "Run this comparison against your current solution to see where the "
        "trade-offs land for your team."
    ),
    IntentType.local_seo: "When you're ready to evaluate options, look for the criteria that matter most.",
    IntentType.ecom: "When you're ready to evaluate options, look for the criteria that matter most.",
    IntentType.informational_commercial: (
        "When you're ready to evaluate options, look for the criteria that matter most."
    ),
    IntentType.news: "Watch for follow-on coverage as the situation develops.",
    IntentType.listicle: "Explore the related sub-topics next.",
}


def h2_body_floor(intent: IntentType, brief_floor: int = 0) -> int:
    """The brief's `min_h2_body_words` wins when set; otherwise the intent floor."""
    return brief_floor if brief_floor and brief_floor > 0 else H2_BODY_FLOOR.get(intent, 120)


def cta_template(intent: IntentType) -> str:
    return CTA_TEMPLATE.get(intent, CTA_TEMPLATE[IntentType.informational])

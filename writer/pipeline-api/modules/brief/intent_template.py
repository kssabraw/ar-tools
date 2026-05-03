"""Per-intent heading-skeleton templates (Brief Generator PRD v2.1).

The template defines:
  - `h2_pattern`         — abstract shape of the H2 sequence
  - `h2_framing_rule`    — what each H2's wording must look like (validated
    deterministically in Step 11 via regex; rewritten by LLM on miss)
  - `ordering`           — strict_sequential / logical / none — drives
    downstream how-to reorder step
  - `anchor_slots`       — short semantic-anchor strings that Step 7.5
    embeds and matches against the candidate pool. Anchors describe
    *phases* of the article, not specific topics, so they generalize
    across keywords (e.g. how-to anchors: "plan", "set up", "launch",
    "iterate" — same skeleton works for opening a TikTok shop, building
    a deck, or launching a podcast).
  - `min_h2_count` / `max_h2_count` — soft bounds the assembly pass uses
    to set MMR target_count. The brief-wide global cap (15 / 20) still
    overrides on the high end.

`templates_by_intent()` returns a fresh template per call so callers
can mutate fields safely (e.g. assembly tweaking max_h2_count to match
the pool size). The dictionaries are constructed once at import time;
`copy()` is shallow but the `anchor_slots` list is rebuilt to avoid
shared-list mutation.

Out-of-scope intents in v1 (per Phase 1 proposal): `news`, `local-seo`.
Both still classify correctly, but their templates use
`framing_rule="no_constraint"` and empty `anchor_slots` so neither the
slot-reservation pass nor the framing validator does anything.
`guide` / `definition` / `review` are aliases — the classifier already
collapses them to `informational` / `informational-commercial`, so the
registry keys to the canonical intent set only.
"""

from __future__ import annotations

from models.brief import (
    H2FramingRule,
    H2Ordering,
    H2Pattern,
    IntentFormatTemplate,
    IntentType,
)


# ---------------------------------------------------------------------------
# Anchor-slot text definitions
# ---------------------------------------------------------------------------
# Each anchor is a short phrase the embedding model can match against
# real heading candidates. Stick to phase-level concepts ("plan", "set up")
# rather than topic-specific phrases — the latter wouldn't generalize.

_HOW_TO_ANCHORS: list[str] = [
    "plan and prepare",
    "set up and configure",
    "launch and execute",
    "measure results and iterate",
]

_LISTICLE_ANCHORS: list[str] = []  # Listicle slots are pure ranked items;
# semantic anchoring would constrain the topical pool unnecessarily. We
# rely on framing validation instead.

_COMPARISON_ANCHORS: list[str] = [
    "pricing and cost",
    "features and capabilities",
    "performance and reliability",
    "support and ecosystem",
]

_INFORMATIONAL_ANCHORS: list[str] = [
    "definition and overview",
    "how it works",
    "who it is for",
    "common pitfalls",
]

_INFOCOMMERCIAL_ANCHORS: list[str] = [
    "what to look for",
    "comparing options",
    "common mistakes to avoid",
    "how to evaluate",
]

_ECOM_ANCHORS: list[str] = [
    "what is included",
    "pricing and plans",
    "compatibility and requirements",
    "warranty and support",
]


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

def _template(
    intent: IntentType,
    pattern: H2Pattern,
    framing_rule: H2FramingRule,
    ordering: H2Ordering,
    anchors: list[str],
    *,
    min_h2: int,
    max_h2: int,
    description: str,
) -> IntentFormatTemplate:
    return IntentFormatTemplate(
        intent=intent,
        h2_pattern=pattern,
        h2_framing_rule=framing_rule,
        ordering=ordering,
        min_h2_count=min_h2,
        max_h2_count=max_h2,
        anchor_slots=list(anchors),
        description=description,
    )


def _build_registry() -> dict[IntentType, IntentFormatTemplate]:
    return {
        "how-to": _template(
            "how-to",
            "sequential_steps",
            "verb_leading_action",
            "strict_sequential",
            _HOW_TO_ANCHORS,
            min_h2=4,
            max_h2=12,
            description=(
                "Sequential procedural steps (verb-leading H2s) for how-to "
                "intent. Anchors cover plan → set up → launch → iterate."
            ),
        ),
        "listicle": _template(
            "listicle",
            "ranked_items",
            "ordinal_then_noun_phrase",
            "none",
            _LISTICLE_ANCHORS,
            min_h2=5,
            max_h2=10,
            description=(
                "Ranked / numbered items. No anchor slots — the listicle "
                "pool is dictated by topic, not phase."
            ),
        ),
        "comparison": _template(
            "comparison",
            "parallel_axes",
            "axis_noun_phrase",
            "logical",
            _COMPARISON_ANCHORS,
            min_h2=3,
            max_h2=6,
            description=(
                "Parallel evaluation axes (Pricing, Features, Support). "
                "Anchors enforce axis coverage."
            ),
        ),
        "informational": _template(
            "informational",
            "topic_questions",
            "question_or_topic_phrase",
            "logical",
            _INFORMATIONAL_ANCHORS,
            min_h2=4,
            max_h2=6,
            description=(
                "Question/topic H2s for definitional and explainer pieces."
            ),
        ),
        "informational-commercial": _template(
            "informational-commercial",
            "buyer_education_axes",
            "buyer_education_phrase",
            "logical",
            _INFOCOMMERCIAL_ANCHORS,
            min_h2=4,
            max_h2=6,
            description=(
                "Buyer-education axes — what to look for, how to compare, "
                "common mistakes — with no endorsement framing."
            ),
        ),
        "ecom": _template(
            "ecom",
            "feature_benefit",
            "axis_noun_phrase",
            "logical",
            _ECOM_ANCHORS,
            min_h2=4,
            max_h2=6,
            description=(
                "Feature-benefit / product-spec axes for commercial pages."
            ),
        ),
        # v1 deferred — keep templates so the schema is complete, but
        # neither pass enforces anything.
        "local-seo": _template(
            "local-seo",
            "place_bound_topics",
            "no_constraint",
            "logical",
            [],
            min_h2=3,
            max_h2=6,
            description="Local-SEO: framing enforcement deferred to v1.x.",
        ),
        "news": _template(
            "news",
            "news_lede",
            "no_constraint",
            "strict_sequential",
            [],
            min_h2=3,
            max_h2=5,
            description="News: framing enforcement out of scope for v1.",
        ),
    }


_REGISTRY: dict[IntentType, IntentFormatTemplate] = _build_registry()


def get_template(intent: IntentType) -> IntentFormatTemplate:
    """Return a fresh copy of the template for `intent`.

    Falls back to the `informational` template for any intent we don't
    have a registration for (defensive — the IntentType literal already
    constrains valid values, but a future enum addition without a
    corresponding template registration would otherwise crash here).
    """
    template = _REGISTRY.get(intent) or _REGISTRY["informational"]
    return template.model_copy(deep=True)

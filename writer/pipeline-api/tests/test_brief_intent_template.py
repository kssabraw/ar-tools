"""Per-intent heading skeleton template registry - Brief Generator PRD v2.1."""

from __future__ import annotations

import pytest

from models.brief import IntentFormatTemplate
from modules.brief.intent_template import get_template


@pytest.mark.parametrize("intent,expected_pattern,expected_rule", [
    ("how-to", "sequential_steps", "verb_leading_action"),
    ("listicle", "ranked_items", "ordinal_then_noun_phrase"),
    ("comparison", "parallel_axes", "axis_noun_phrase"),
    ("informational", "topic_questions", "question_or_topic_phrase"),
    ("informational-commercial", "buyer_education_axes", "buyer_education_phrase"),
    ("ecom", "feature_benefit", "axis_noun_phrase"),
    ("local-seo", "place_bound_topics", "no_constraint"),
    ("news", "news_lede", "no_constraint"),
])
def test_template_registry_covers_every_intent(intent, expected_pattern, expected_rule):
    template = get_template(intent)
    assert isinstance(template, IntentFormatTemplate)
    assert template.intent == intent
    assert template.h2_pattern == expected_pattern
    assert template.h2_framing_rule == expected_rule


def test_how_to_template_has_phase_anchors():
    """The how-to template must carry phase-level anchors so Step 7.5 can
    reserve plan / set up / launch / iterate slots regardless of topic."""
    template = get_template("how-to")
    assert len(template.anchor_slots) == 4
    # Anchors should be phase-level, not topic-level - they read as
    # generic verbs/phrases applicable to any how-to keyword.
    joined = " ".join(template.anchor_slots).lower()
    assert "plan" in joined
    assert "set up" in joined or "configure" in joined
    assert "launch" in joined or "execute" in joined
    assert "iterate" in joined or "measure" in joined


def test_listicle_template_has_no_anchors():
    """Listicle slots are pure ranked items - semantic anchors would
    over-constrain. Framing validator does the work instead."""
    template = get_template("listicle")
    assert template.anchor_slots == []


def test_comparison_template_anchors_cover_pricing_features_support():
    template = get_template("comparison")
    joined = " ".join(template.anchor_slots).lower()
    assert "pricing" in joined or "cost" in joined
    assert "feature" in joined
    assert "support" in joined or "ecosystem" in joined


def test_news_and_local_seo_templates_use_no_constraint():
    """v1 deferred intents must opt out of framing enforcement so the
    validator becomes a no-op for them."""
    for intent in ("news", "local-seo"):
        template = get_template(intent)
        assert template.h2_framing_rule == "no_constraint"


def test_get_template_returns_fresh_copy_each_call():
    """Callers can mutate the returned template (e.g. clamping
    max_h2_count) without contaminating other runs."""
    a = get_template("how-to")
    a.max_h2_count = 999
    a.anchor_slots.append("zzz")
    b = get_template("how-to")
    assert b.max_h2_count != 999
    assert "zzz" not in b.anchor_slots


def test_unknown_intent_falls_back_to_informational():
    # Pass a value outside the literal - the registry's defensive
    # fallback should still return an IntentFormatTemplate.
    template = get_template("nonexistent-intent")  # type: ignore[arg-type]
    assert template.intent == "informational"


def test_template_min_h2_count_is_at_least_3():
    """Every template should ask for at least 3 H2s - anything less
    produces an underweight outline."""
    for intent in (
        "how-to", "listicle", "comparison", "informational",
        "informational-commercial", "ecom", "local-seo", "news",
    ):
        template = get_template(intent)
        assert template.min_h2_count >= 3, (
            f"{intent} has min_h2_count={template.min_h2_count}"
        )


# ---------------------------------------------------------------------------
# PRD v2.3 / Phase 3 - min_h2_body_words derivation
# ---------------------------------------------------------------------------


import pytest as _pytest


@_pytest.mark.parametrize("intent,expected_floor", [
    ("how-to", 120),
    ("listicle", 80),
    ("comparison", 150),
    ("informational", 180),
    ("informational-commercial", 180),
    ("ecom", 150),
    ("local-seo", 150),
    ("news", 100),
])
def test_min_h2_body_words_per_intent(intent, expected_floor):
    """Phase 3 - the brief generator stamps a per-intent
    min_h2_body_words floor on format_directives at assembly time.
    Each intent's template has its own floor calibrated for typical
    article shape."""
    from modules.brief.pipeline import _min_h2_body_words_for_template
    template = get_template(intent)
    assert _min_h2_body_words_for_template(template) == expected_floor


def test_min_h2_body_words_falls_back_when_template_is_none():
    from modules.brief.pipeline import _min_h2_body_words_for_template
    assert _min_h2_body_words_for_template(None) == 100

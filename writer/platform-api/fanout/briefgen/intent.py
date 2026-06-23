"""Brief Generator Step 3 — intent classification + format template + A1 decision-fit
detector (M13 slice 5a).

Step 3.2 classifies the query into one of 8 intents (LLM, injected). Step 3.3 maps that
deterministically to a per-intent heading-skeleton `intent_format_template` (no LLM).
The A1 decision-fit detector (aio §3.2) is folded into the SAME classification call —
it shares the query + SERP context, so it costs no extra round-trip. The decision-fit
GATE (is_multi_answer ∧ confidence ≥ τ ∧ ≥2 distinct conditions) is pure.

Pure: the template registry/lookup, the format-directive derivation, the decision-fit
gate, the review-required rule. Egress: `classify_intent` (one tool-use call).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

INTENT_TYPES = (
    "informational", "listicle", "how-to", "comparison", "ecom",
    "local-seo", "news", "informational-commercial",
)

# Unambiguous comparison markers in the keyword itself — "X vs Y" is comparison by
# definition, so a deterministic override beats an occasional LLM misread (live: the
# classifier called "cagrilintide peptide vs retatrutide" informational).
_COMPARISON_RE = re.compile(
    r"\b(vs\.?|versus|compared\s+(?:to|with)|comparison)\b", re.IGNORECASE
)


def looks_comparison(keyword: str) -> bool:
    return bool(_COMPARISON_RE.search(keyword or ""))
# Classifier aliases collapse to canonical intents (bundle §Step 3.3).
ALIASES = {"guide": "informational", "definition": "informational", "review": "informational-commercial"}

INTENT_REVIEW_THRESHOLD = 0.75   # < this AND Step 3.1 didn't fire -> intent_review_required
DECISION_FIT_TAU = 0.7           # A1 gate confidence floor (aio §3.2)

# Per-intent heading-skeleton registry (bundle §Step 3.3 table).
INTENT_TEMPLATES: dict[str, dict] = {
    "how-to": {
        "h2_pattern": "sequential_steps", "h2_framing_rule": "verb_leading_action",
        "ordering": "strict_sequential", "min_h2_count": 4, "max_h2_count": 12,
        "anchor_slots": ["plan and prepare", "set up and configure", "launch and execute",
                         "measure results and iterate"],
        "description": "Sequential procedural steps (verb-leading H2s) for how-to intent.",
    },
    "listicle": {
        "h2_pattern": "ranked_items", "h2_framing_rule": "ordinal_then_noun_phrase",
        "ordering": "none", "min_h2_count": 5, "max_h2_count": 10, "anchor_slots": [],
        "description": "Ranked items, no anchor reservation.",
    },
    "comparison": {
        "h2_pattern": "parallel_axes", "h2_framing_rule": "axis_noun_phrase",
        "ordering": "logical", "min_h2_count": 3, "max_h2_count": 6,
        "anchor_slots": ["pricing", "features", "performance", "support"],
        "description": "Parallel comparison axes.",
    },
    "informational": {
        "h2_pattern": "topic_questions", "h2_framing_rule": "question_or_topic_phrase",
        "ordering": "logical", "min_h2_count": 4, "max_h2_count": 6,
        "anchor_slots": ["definition", "how it works", "who", "pitfalls"],
        "description": "Topic questions for informational/definition/guide intent.",
    },
    "informational-commercial": {
        "h2_pattern": "buyer_education_axes", "h2_framing_rule": "buyer_education_phrase",
        "ordering": "logical", "min_h2_count": 4, "max_h2_count": 6,
        "anchor_slots": ["what to look for", "comparing", "mistakes", "evaluate"],
        "description": "Buyer-education axes for review/commercial-informational intent.",
    },
    "ecom": {
        "h2_pattern": "feature_benefit", "h2_framing_rule": "axis_noun_phrase",
        "ordering": "logical", "min_h2_count": 4, "max_h2_count": 6,
        "anchor_slots": ["what is included", "pricing", "compatibility", "warranty"],
        "description": "Feature/benefit axes for ecom intent.",
    },
    "local-seo": {
        "h2_pattern": "place_bound_topics", "h2_framing_rule": "no_constraint",
        "ordering": "logical", "min_h2_count": 3, "max_h2_count": 6, "anchor_slots": [],
        "description": "Place-bound topics (Step 11 validator is a noop).",
    },
    "news": {
        "h2_pattern": "news_lede", "h2_framing_rule": "no_constraint",
        "ordering": "strict_sequential", "min_h2_count": 3, "max_h2_count": 5,
        "anchor_slots": [],
        "description": "News lede (Step 11 validator is a noop).",
    },
}

# min_h2_body_words floor, stamped at assembly from h2_pattern (bundle v2.3 note). The
# exact per-pattern numbers are calibration items; 180 is the live-contract default,
# lowered for the higher-H2-count patterns.
_MIN_H2_BODY_WORDS = {"ranked_items": 140, "sequential_steps": 150}
_DEFAULT_MIN_H2_BODY_WORDS = 180


def get_intent_template(intent_type: str) -> dict:
    """Deterministic Step-3.3 lookup. Aliases collapse; an unknown intent falls back to
    `informational` (never raises). Returns a copy carrying the canonical `intent`."""
    canonical = ALIASES.get(intent_type, intent_type)
    tpl = INTENT_TEMPLATES.get(canonical) or INTENT_TEMPLATES["informational"]
    canonical = canonical if canonical in INTENT_TEMPLATES else "informational"
    return {"intent": canonical, **tpl}


def format_directives_for(template: dict) -> dict:
    """Stamp `format_directives` from the intent template (bundle §5.10 / live contract).
    Standard structural defaults + a per-pattern `min_h2_body_words` floor."""
    pattern = template.get("h2_pattern", "")
    return {
        "require_tables": True,
        "min_tables_per_article": 1,
        "min_lists_per_article": 2,
        "require_bulleted_lists": True,
        "min_h2_body_words": _MIN_H2_BODY_WORDS.get(pattern, _DEFAULT_MIN_H2_BODY_WORDS),
        "answer_first_paragraphs": True,
        "preferred_paragraph_max_words": 80,
    }


def decision_fit_qualifies(detection: dict, *, tau: float = DECISION_FIT_TAU) -> bool:
    """A1 gate (aio §3.2): is_multi_answer AND confidence ≥ τ AND ≥2 DISTINCT conditions
    (deduped — one condition isn't a branch)."""
    if not detection.get("is_multi_answer"):
        return False
    if float(detection.get("confidence") or 0.0) < tau:
        return False
    conds = detection.get("candidate_conditions") or []
    distinct = {
        (c.get("condition") or "").strip().lower()
        for c in conds if isinstance(c, dict) and (c.get("condition") or "").strip()
    }
    return len(distinct) >= 2


@dataclass
class IntentResult:
    intent_type: str
    intent_confidence: float
    intent_review_required: bool
    intent_format_template: dict
    format_directives: dict
    decision_fit_detection: dict = field(default_factory=dict)
    decision_fit_qualifies: bool = False


def classify_intent(
    keyword: str, *, serp_titles: list[str], serp_h2s: list[str], paa: list[str], llm,
    keyword_precheck_fired: bool = False, intent_override: str | None = None,
) -> IntentResult:
    """Step 3.2 + A1 in one tool-use call. The LLM returns the intent label + confidence
    + the decision-fit detection; the template, format directives, review flag, and the
    A1 gate are derived deterministically here."""
    schema = {
        "type": "object",
        "properties": {
            "intent_type": {"type": "string", "enum": list(INTENT_TYPES)},
            "intent_confidence": {"type": "number"},
            "decision_fit_detection": {
                "type": "object",
                "properties": {
                    "is_multi_answer": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "candidate_conditions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "condition": {"type": "string"},
                                "distinguishing_factor": {"type": "string"},
                            },
                            "required": ["condition"],
                        },
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["is_multi_answer", "confidence"],
            },
        },
        "required": ["intent_type", "intent_confidence", "decision_fit_detection"],
    }
    listing = (
        "Top SERP titles:\n" + "\n".join(f"- {t}" for t in serp_titles[:20])
        + "\n\nTop SERP H2s:\n" + "\n".join(f"- {h}" for h in serp_h2s[:20])
        + "\n\nPeople Also Ask:\n" + "\n".join(f"- {q}" for q in paa[:15])
    )
    out = llm.call_tool(
        system=(
            "You classify search intent for an article brief and detect 'decision-fit'. "
            "Pick the single best intent_type. For decision-fit: does answering this query "
            "well require DIFFERENT recommendations depending on the reader's situation "
            "(vs one best answer)? If so list the distinct reader conditions. A flat "
            "comparison the reader doesn't have to choose from is NOT decision-fit."
        ),
        user=f"Query: {keyword}\n\n{listing}",
        tool_name="classify_intent",
        tool_description="Return the intent type, confidence, and decision-fit detection.",
        input_schema=schema,
        purpose="brief_intent_classification",
    )
    intent_type = out.get("intent_type", "informational")
    confidence = float(out.get("intent_confidence") or 0.0)
    # Owner override (a locked cluster intent) is authoritative — honor it as-is.
    if intent_override in INTENT_TYPES:
        intent_type = intent_override
        confidence = max(confidence, 0.95)
    # Deterministic comparison override — a "X vs Y" keyword is a comparison regardless
    # of the LLM label; bump confidence so it doesn't trip intent_review_required.
    elif looks_comparison(keyword) and intent_type != "comparison":
        logger.info(
            "intent_comparison_override",
            extra={"event": "intent_comparison_override", "keyword": keyword,
                   "llm_intent": intent_type},
        )
        intent_type = "comparison"
        confidence = max(confidence, 0.95)
    template = get_intent_template(intent_type)
    detection = out.get("decision_fit_detection") or {}
    return IntentResult(
        intent_type=template["intent"], intent_confidence=confidence,
        intent_review_required=(confidence < INTENT_REVIEW_THRESHOLD and not keyword_precheck_fired),
        intent_format_template=template, format_directives=format_directives_for(template),
        decision_fit_detection=detection, decision_fit_qualifies=decision_fit_qualifies(detection),
    )

"""Pydantic models for the Brief Generator module — schema v2.0.

Implements the output schema specified in
docs/modules/content-brief-generator-prd-v2_0.md §6.

Key v2.0 architectural changes versus v1.7/v1.8:
- Title + scope statement are now first-class outputs (Step 3.5)
- Hypothetical searcher persona is captured (Step 6)
- `semantic_score` renamed to `title_relevance` (cosine to title, not seed)
- `region_id` and `scope_classification` carried on every heading
- New discard reasons gate on title relevance + region elimination + scope
- Coverage-graph regions replace v1.7's two-tier semantic clusters; the
  cluster_id / cluster_evidence fields are gone
- Silos now reuse Step 5 regions (`routed_from`) and absorb scope-rejects
- spin_off_articles[] removed; silo_candidates is the unified concept
- Embedding model upgraded to text-embedding-3-large

All models lock to extra='forbid' (Pydantic equivalent of JSON Schema
additionalProperties: false), per PRD §12 strict-validation requirement.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


_FORBID_EXTRA = ConfigDict(extra="forbid")


# ---- Enumerations ----

IntentType = Literal[
    "informational",
    "listicle",
    "how-to",
    "comparison",
    "ecom",
    "local-seo",
    "news",
    "informational-commercial",
]

HeadingLevel = Literal["H1", "H2", "H3"]
HeadingType = Literal["content", "faq-header", "faq-question", "conclusion"]

HeadingSource = Literal[
    "serp",
    "paa",
    "reddit",
    "authority_gap_sme",
    "synthesized",
    "autocomplete",
    "keyword_suggestion",
    "llm_fanout_chatgpt",
    "llm_fanout_claude",
    "llm_fanout_gemini",
    "llm_fanout_perplexity",
    "llm_response_chatgpt",
    "llm_response_claude",
    "llm_response_gemini",
    "llm_response_perplexity",
    "persona_gap",
]

FAQSource = Literal["paa", "reddit", "llm_extracted", "persona_gap"]

# PRD v2.2 / Phase 2 — FAQ intent role assigned by Step 10.5's LLM classifier.
# `matches_primary_intent` = FAQ aligns with the primary keyword's intent
# cluster; `adjacent_intent` = topically related but a different stakeholder
# question (kept only as fallback when fewer than 3 primary FAQs survive).
# `different_audience` candidates are dropped at the gate and never reach
# the brief output, so the enum here is only the kept values.
FAQIntentRole = Literal["matches_primary_intent", "adjacent_intent"]

# PRD v2.2 / Phase 2 — H3 parent-fit classification from Step 8.7.
# `good` = H3 belongs under its current parent H2; default state for H3s
# we don't surface a flag for. `marginal` = LLM signaled "could go either
# way" — kept under current parent + flagged for review. `wrong_parent`
# and `promote_to_h2` are NOT kept on the candidate (those route to silos
# / re-attach to a different H2), so the literal here only carries the
# kept values that downstream renderers may surface.
H3ParentFitClassification = Literal["good", "marginal"]

ScopeClassification = Literal["in_scope", "borderline"]

DiscardReason = Literal[
    "below_relevance_floor",
    "above_restatement_ceiling",
    "region_off_topic",
    "region_restates_title",
    "below_priority_threshold",
    "global_cap_exceeded",
    "duplicate",
    "low_cluster_coherence",
    "scope_verification_out_of_scope",
    # Step 8.6 (H3 Selection) additions — PRD v2.0.x
    "h3_below_parent_relevance_floor",
    "h3_above_parent_restatement_ceiling",
    "displaced_by_authority_gap_h3",
    # PRD v2.2 / Phase 2 — Step 8.7 H3 Parent-Fit Verification
    "h3_wrong_parent",                # re-attached or routed to silo
    "h3_promoted_to_h2_candidate",    # routed to silo as standalone topic
    # PRD v2.2 / Phase 2 — Step 10.5 FAQ Intent Gate
    "faq_intent_mismatch",
]

SiloRoutedFrom = Literal[
    "non_selected_region",
    "scope_verification",
    # Step 8.5b — Authority Gap H3 rejected by H3 scope verification (PRD v2.0.3)
    "scope_verification_h3",
    # Step 5.1 relevance gate — heading discarded as below_relevance_floor.
    # These candidates are below the title's relevance floor (so excluded
    # from the parent article) but may still represent adjacent topics
    # worth surfacing as standalone silos (filtered by search demand + the
    # Step 12.4 viability LLM check before reaching the user).
    "relevance_floor_reject",
    # PRD v2.2 / Phase 2 — Step 8.7 outcomes
    # H3 was classified `wrong_parent` and no other selected H2 had
    # capacity (or the H3 was below all parent_relevance floors).
    "h3_parent_mismatch",
    # H3 was classified `promote_to_h2` — represents a different topic
    # than its assigned parent and warrants its own article.
    "h3_promote_candidate",
    # Unused LLM fanout query — candidate sourced from llm_fanout_*
    # that wasn't selected as an H2 and didn't fit any other singleton
    # routing path. Surfaced as a silo bypassing the search-demand floor
    # (the LLMs already nominated the query, which is its own demand
    # signal); still gated by the Step 12.4 viability LLM check.
    "llm_fanout_unused",
]


# ---- Request envelope ----

class BriefRequest(BaseModel):
    """Input envelope to POST /brief."""
    model_config = _FORBID_EXTRA

    run_id: str = Field(..., description="Idempotency key from platform-api")
    attempt: int = 1
    keyword: str = Field(..., min_length=1, max_length=150)
    location_code: int = 2840  # United States

    # Captured for audit trail. The brief content is client-agnostic per
    # PRD §2; client_id never feeds into LLM inputs and never scopes the
    # cache. Two clients running the same keyword share the cached output.
    client_id: Optional[str] = None

    # When true, skip the cache lookup and force regeneration. Successful
    # regeneration overwrites the cached row.
    force_refresh: bool = False

    intent_override: Optional[IntentType] = None


# ---- Persona (Step 6 output) ----

class PersonaInfo(BaseModel):
    """Hypothetical searcher persona derived from topic + SERP signal.

    Per PRD §2: brand and ICP context never feed into persona generation;
    the persona is always inferred from the keyword and SERP alone.
    """
    model_config = _FORBID_EXTRA

    description: str = ""
    background_assumptions: list[str] = []
    primary_goal: str = ""


# ---- Heading items ----

class HeadingItem(BaseModel):
    model_config = _FORBID_EXTRA

    level: HeadingLevel
    text: str
    type: HeadingType
    source: HeadingSource
    original_source: Optional[str] = None
    title_relevance: float = 0.0
    exempt: bool = False
    serp_frequency: int = 0
    avg_serp_position: Optional[float] = None
    llm_fanout_consensus: int = 0
    information_gain_score: float = 0.0
    heading_priority: float = 0.0
    region_id: Optional[str] = None
    scope_classification: Optional[ScopeClassification] = None
    # Step 8.6 (H3 Selection): only set on H3 entries that flow through
    # the parent-relevance MMR; null for H1, H2, and authority-gap H3s.
    parent_h2_text: Optional[str] = None
    parent_relevance: float = 0.0
    # Step 9 (v2.0.3): populated only for source='authority_gap_sme' entries —
    # the agent's own justification that the H3 stays within the brief's scope.
    scope_alignment_note: Optional[str] = None
    # PRD v2.2 / Phase 2 — Step 8.7 H3 Parent-Fit Verification.
    # Populated only on H3 entries the LLM examined; defaults to None on
    # H1, H2, and on H3s that bypassed Step 8.7 (e.g. when the LLM call
    # failed and the fallback accepted everyone). `good` is left as None
    # for terseness — only `marginal` is surfaced explicitly so consumers
    # can highlight reviewer-attention H3s.
    parent_fit_classification: Optional[H3ParentFitClassification] = None
    order: int = 0


# ---- FAQs ----

class FAQItem(BaseModel):
    model_config = _FORBID_EXTRA

    question: str
    source: FAQSource
    faq_score: float = 0.0
    # PRD v2.2 / Phase 2 — Step 10.5 FAQ Intent Gate.
    # `matches_primary_intent` = LLM confirmed FAQ aligns with the primary
    # keyword's intent cluster (the expected case). `adjacent_intent` =
    # FAQ is on-topic but represents a different stakeholder question
    # (only kept as fallback when fewer than 3 matches_primary_intent
    # candidates survive both the cosine floor and the LLM filter).
    # `None` = Step 10.5 was a no-op for this FAQ (LLM call failed and
    # fallback accepted everything, or the gate was disabled).
    intent_role: Optional[FAQIntentRole] = None


# ---- Structural + format directives ----

class StructuralConstants(BaseModel):
    model_config = _FORBID_EXTRA

    class _Conclusion(BaseModel):
        model_config = _FORBID_EXTRA

        type: Literal["conclusion"] = "conclusion"
        level: Optional[str] = None
        text: str = "[Conclusion placeholder]"

    conclusion: _Conclusion = _Conclusion()


class FormatDirectives(BaseModel):
    model_config = _FORBID_EXTRA

    require_bulleted_lists: bool = True
    require_tables: bool = True
    min_lists_per_article: int = 2
    min_tables_per_article: int = 1
    preferred_paragraph_max_words: int = 80
    answer_first_paragraphs: bool = True
    # PRD v2.3 / Phase 3 — minimum words per H2 SECTION GROUP (parent H2
    # body + all child H3 bodies, after stripping `{{cit_N}}` markers).
    # The Writer's new Step 6.7 validator retries any H2 group falling
    # below this floor once, then warns-and-accepts. Default per intent
    # pattern is set at brief assembly time from the
    # `intent_format_template`; the schema default below is used only by
    # legacy callers / fixtures that don't supply a template.
    min_h2_body_words: int = 100


# ---- Intent format template (Phase 1 / Brief PRD v2.1 Step 7.5 + Step 11) ----
#
# `intent_format_template` commits the brief to a per-intent heading-skeleton
# shape so the H2 outline matches the keyword's intent (sequential steps for
# how-to, ranked items for listicle, etc.). The template feeds:
#   - Step 7.5: anchor-slot reservation in MMR — preferred slots are filled
#     by the highest-priority candidate whose embedding aligns with the
#     slot's semantic anchor before generic MMR fills the rest.
#   - Step 11: framing validator — every selected H2 must satisfy the
#     template's framing regex; failures route through one LLM rewrite pass.

H2Pattern = Literal[
    "sequential_steps",       # how-to: Plan → Set Up → Launch → Iterate
    "ranked_items",           # listicle: 1. X, 2. Y, 3. Z
    "parallel_axes",          # comparison: Pricing, Features, Support
    "topic_questions",        # informational: What is X, How X works
    "buyer_education_axes",   # informational-commercial: What to look for, …
    "feature_benefit",        # ecom: Pricing, What's Included, Compatibility
    "place_bound_topics",     # local-seo: deferred (not enforced in v1)
    "news_lede",              # news: out of scope for v1; framing validator NOOPs
]


H2FramingRule = Literal[
    "verb_leading_action",        # how-to step framing
    "ordinal_then_noun_phrase",   # listicle
    "axis_noun_phrase",           # comparison axes / ecom feature-benefit
    "question_or_topic_phrase",   # informational
    "buyer_education_phrase",     # informational-commercial
    "no_constraint",              # news / local-seo / fallback
]


H2Ordering = Literal["strict_sequential", "logical", "none"]


class IntentFormatTemplate(BaseModel):
    """Per-intent heading-skeleton template emitted by Step 3 (PRD v2.1).

    `anchor_slots` carries short semantic-anchor strings (e.g. ``"plan"``,
    ``"set up"``, ``"launch"``, ``"iterate"`` for how-to). Step 7.5 embeds
    these and reserves H2 slots by matching candidate embeddings against
    the anchors. When the candidate pool genuinely contains procedural
    coverage, anchor slots fill before generic MMR runs; when it does
    not, MMR proceeds normally and the framing validator (Step 11)
    rewrites the H2 framing instead.
    """
    model_config = _FORBID_EXTRA

    intent: IntentType
    h2_pattern: H2Pattern
    h2_framing_rule: H2FramingRule
    ordering: H2Ordering
    min_h2_count: int = Field(default=4, ge=1)
    max_h2_count: int = Field(default=10, ge=1)
    # Semantic anchors for Step 7.5. Empty list = no anchor reservation
    # (template falls through to plain MMR).
    anchor_slots: list[str] = []
    # Operator-facing description; not consumed by code, only logged + surfaced.
    description: str = ""


# ---- Discarded headings ----

class DiscardedHeading(BaseModel):
    model_config = _FORBID_EXTRA

    text: str
    source: HeadingSource
    original_source: Optional[str] = None
    title_relevance: float = 0.0
    serp_frequency: int = 0
    avg_serp_position: Optional[float] = None
    llm_fanout_consensus: int = 0
    heading_priority: float = 0.0
    region_id: Optional[str] = None
    discard_reason: DiscardReason


# ---- Silo candidates ----

class SiloSourceHeading(BaseModel):
    """A heading that contributed to a silo candidate.

    `discard_reason` is nullable because non-selected-region members may
    have been eligible for selection but lost the MMR competition (no
    discard reason yet); scope-verification rejects always carry one.
    """
    model_config = _FORBID_EXTRA

    text: str
    source: HeadingSource
    title_relevance: float = 0.0
    heading_priority: float = 0.0
    discard_reason: Optional[DiscardReason] = None


class SiloCandidate(BaseModel):
    model_config = _FORBID_EXTRA

    suggested_keyword: str
    cluster_coherence_score: float = 0.0
    review_recommended: bool = False
    recommended_intent: IntentType
    routed_from: SiloRoutedFrom
    source_headings: list[SiloSourceHeading] = []

    # Step 12 refinements (PRD §5 Step 12.6)
    # Counts of each discard_reason among the silo's member headings —
    # gives consumers a quick view of why these headings were rejected.
    discard_reason_breakdown: dict[str, int] = {}
    # Step 12.3 — five-signal demand score, hard floor 0.30 to qualify.
    search_demand_score: float = 0.0
    # Step 12.4 — viability LLM verdict; defaults true under double-failure
    # fallback (see metadata.silo_viability_fallback_applied).
    viable_as_standalone_article: bool = True
    viability_reasoning: str = ""
    estimated_intent: IntentType = "informational"
    # Step 12.5 — populated by v2.1 cross-brief dedup; defaults to 1 in v2.0.
    cross_brief_occurrence_count: int = 1


# ---- Metadata ----

class LLMFanoutCounts(BaseModel):
    model_config = _FORBID_EXTRA

    chatgpt: int = 0
    claude: int = 0
    gemini: int = 0
    perplexity: int = 0


class LLMUnavailable(BaseModel):
    model_config = _FORBID_EXTRA

    chatgpt: bool = False
    claude: bool = False
    gemini: bool = False
    perplexity: bool = False


class IntentSignals(BaseModel):
    model_config = _FORBID_EXTRA

    shopping_box: bool = False
    news_box: bool = False
    local_pack: bool = False
    featured_snippet: bool = False
    comparison_tables: bool = False


class BriefMetadata(BaseModel):
    """Operational + tuning metadata. Threshold values used during the
    run are echoed back so consumers (and offline tuners) know exactly
    which configuration produced the output."""
    model_config = _FORBID_EXTRA

    word_budget: int = 2500
    faq_count: int = 0
    h2_count: int = 0
    h3_count: int = 0
    total_content_subheadings: int = 0
    discarded_headings_count: int = 0
    silo_candidates_count: int = 0
    competitors_analyzed: int = 20
    reddit_threads_analyzed: int = 0

    # Shortfall tracking (PRD §5 Step 8 — accept shortfall, don't pad)
    h2_shortfall: bool = False
    h2_shortfall_reason: Optional[str] = None

    # H3 distribution (PRD §5 Step 8.6)
    h3_count_average: float = 0.0
    h2s_with_zero_h3s: int = 0

    # Coverage graph stats (PRD §5 Step 5)
    regions_detected: int = 0
    regions_eliminated_off_topic: int = 0
    regions_eliminated_restate_title: int = 0
    regions_contributing_h2s: int = 0

    # Scope verification stats (PRD §5 Step 8.5)
    scope_verification_borderline_count: int = 0
    scope_verification_rejected_count: int = 0

    # Silo pipeline rejection counters (PRD §5 Step 12.1 / 12.3 / 12.4)
    silo_candidates_rejected_by_discard_reason: int = 0
    silo_candidates_rejected_by_search_demand: int = 0
    silo_candidates_rejected_by_viability_check: int = 0
    silo_viability_fallback_applied: bool = False

    llm_fanout_queries_captured: LLMFanoutCounts = LLMFanoutCounts()
    llm_response_subtopics_extracted: LLMFanoutCounts = LLMFanoutCounts()
    intent_signals: IntentSignals = IntentSignals()

    # Threshold values used during this run (echoed for tuning)
    embedding_model: Literal["text-embedding-3-large"] = "text-embedding-3-large"
    relevance_floor_threshold: float = 0.55
    restatement_ceiling_threshold: float = 0.78
    inter_heading_threshold: float = 0.75
    edge_threshold: float = 0.65
    mmr_lambda: float = 0.7

    # Step 8.6 H3 thresholds (echoed for tuning).
    # Phase 2 / PRD v2.2 tightened the floor 0.60 → 0.65 and removed the
    # adjacent-region relaxation (H3s must now sit in the SAME region as
    # the parent H2, not just an adjacent one). Default echoes the new
    # value so tuning sessions see the live config.
    parent_relevance_floor_threshold: float = 0.65
    parent_restatement_ceiling_threshold: float = 0.85
    inter_h3_threshold: float = 0.78

    # Step 12.3 silo search-demand floor
    silo_search_demand_threshold: float = 0.30

    low_serp_coverage: bool = False
    reddit_unavailable: bool = False
    llm_fanout_unavailable: LLMUnavailable = LLMUnavailable()

    # Root domains of all SERP results — consumed by Research & Citations
    # to exclude competitor URLs from citation candidates.
    competitor_domains: list[str] = []

    # Phase 1 / PRD v2.1 — Step 7.5 anchor-slot reservation + Step 11 framing.
    # `anchor_slots_reserved_count` is the number of H2 slots filled by the
    # anchor-reservation pass before generic MMR ran. `anchor_slots_total`
    # is the size of the anchor list emitted by the template (so consumers
    # can compute reservation rate). `framing_rewrites_applied` counts H2s
    # whose text was rewritten by the framing validator's LLM pass; the
    # accept_after_retry counter exists because the validator is best-
    # effort (one retry, then warn-and-accept).
    anchor_slots_total: int = 0
    anchor_slots_reserved_count: int = 0
    framing_rewrites_applied: int = 0
    framing_rewrites_accepted_with_violation: int = 0

    # Phase 2 / PRD v2.2 — Step 8.7 H3 Parent-Fit Verification counters.
    # `marginal_count` covers H3s the LLM flagged for review; `wrong_parent_
    # count` covers H3s re-attached to a different H2 OR routed to silos;
    # `promoted_count` covers H3s the LLM said deserve their own article
    # (always routed to silos). `fallback_applied` is true when both LLM
    # attempts failed and we accepted every H3 as `good`.
    h3_parent_fit_marginal_count: int = 0
    h3_parent_fit_wrong_parent_count: int = 0
    h3_parent_fit_promoted_count: int = 0
    h3_parent_fit_fallback_applied: bool = False

    # Phase 2 / PRD v2.2 — Step 10.5 FAQ Intent Gate counters.
    # `floor_rejected_count` counts FAQs killed by the cosine-floor cut
    # against the intent profile; `llm_rejected_count` counts FAQs killed
    # by the `different_audience` LLM verdict. `relaxation_applied` =
    # fewer than 3 `matches_primary_intent` survivors so we kept
    # `adjacent_intent` candidates to reach the 3-FAQ floor.
    faq_intent_gate_floor_rejected_count: int = 0
    faq_intent_gate_llm_rejected_count: int = 0
    faq_intent_gate_relaxation_applied: bool = False
    # Phase 2 review fix #4 — when the gate would otherwise produce
    # zero kept on a non-empty pool, it falls back to admitting the
    # original candidates as `adjacent_intent` so PRD §5 Step 10's
    # 3–5 FAQ guarantee is honored. True = the brief's FAQs are the
    # original (potentially stakeholder-mismatched) pool. Operators
    # should treat a True value as a strong signal to review the
    # intent_profile config or the candidate pool.
    faq_intent_gate_full_relaxation_applied: bool = False
    # Echoed for tuning, like the other threshold values above.
    faq_intent_floor_threshold: float = 0.55

    schema_version: Literal["2.3"] = "2.3"


# ---- Top-level response ----

class BriefResponse(BaseModel):
    """Brief Generator output (schema v2.0, see PRD §6)."""
    model_config = _FORBID_EXTRA

    keyword: str
    title: str
    h1: str = ""
    scope_statement: str
    title_rationale: str = ""
    intent_type: IntentType
    intent_confidence: float = 0.0
    intent_review_required: bool = False
    persona: PersonaInfo = PersonaInfo()
    heading_structure: list[HeadingItem] = []
    faqs: list[FAQItem] = []
    structural_constants: StructuralConstants = StructuralConstants()
    format_directives: FormatDirectives = FormatDirectives()
    discarded_headings: list[DiscardedHeading] = []
    silo_candidates: list[SiloCandidate] = []
    # PRD v2.1 — per-intent heading skeleton template (Step 3 output, used
    # by Step 7.5 + Step 11). Optional so legacy fixtures + cached v2.0
    # rows that don't carry it can still be deserialized for diagnostic
    # use; in the live pipeline this is always populated.
    intent_format_template: Optional[IntentFormatTemplate] = None
    metadata: BriefMetadata

"""Pydantic models for the Content Writer module - schema v1.7.

Per writer-module-v1_5-change-spec_2.md plus content-writer-module-prd-v1.3.md.
PRD v2.3 / Phase 3: bumped to 1.6 with new Step 6.7 H2 body length
validator + `under_length_h2_sections` metadata field.
PRD v1.7 / Phase 4: bumped to 1.7 with new Step 4F.1 citation-coverage
validator (C1-C9 patterns + auto-soften for operational claims) +
new `under_cited_sections` and `operational_claims_softened` metadata.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# 1.9: Writer consumes client_context.reference_page_structure (blog-post layout
# mirroring in the intro). 1.8 variants kept for backward compatibility.
SchemaVersion = Literal[
    "1.9", "1.9-no-context", "1.9-degraded",
    "1.8", "1.8-no-context", "1.8-degraded",
]
ArticleLevel = Literal["H1", "H2", "H3", "none"]
ArticleType = Literal[
    "content", "faq-header", "faq-question", "conclusion", "h1-enrichment", "title", "intro", "key-takeaways",
]
ReconciliationAction = Literal[
    "keep",
    "exclude_due_to_brand_conflict",
    "reduce_due_to_brand_preference",
    "use_due_to_brand_preference",
    "keep_avoiding",
]
SIEClassification = Literal["required", "avoid"]
ConflictResolution = Literal[
    "exclude_due_to_brand_conflict",
    "reduce_due_to_brand_preference",
    "brand_preference_overridden_by_sie",
]


class ClientContextInput(BaseModel):
    brand_guide_text: str = ""
    icp_text: str = ""
    website_analysis: Optional[dict[str, Any]] = None
    website_analysis_unavailable: bool = False
    # Pre-rendered "mirror this layout" block from the client's reference blog
    # post (clients.page_structures.blog_post). The blog brief is client-agnostic
    # and globally cached, so the heading structure can't carry client-specific
    # layout; instead the Writer uses this as soft guidance for the opening
    # pattern. Optional — None/absent leaves writing behavior unchanged.
    reference_page_structure: Optional[str] = None
    # Companion to the above for the body sections (page_structure_render
    # mode="structure"): the client's structural texture — heading-nesting depth,
    # section-length variation, recurring blocks — applied as style over the
    # SEO-driven outline. Optional — None/absent leaves body writing unchanged.
    reference_page_body_structure: Optional[str] = None


class WriterRequest(BaseModel):
    run_id: str
    attempt: int = 1
    brief_output: dict[str, Any]
    sie_output: dict[str, Any]
    research_output: Optional[dict[str, Any]] = None
    client_context: Optional[ClientContextInput] = None
    # Free-form per-run editorial guidance typed by the user at run creation
    # ("mention Zero Down Supply Chain Services as one of the top 10 best").
    # Threaded into the section/intro/conclusion prompts. Deliberately not
    # part of brief_output - the brief is client-agnostic and globally
    # cached. Optional - None/absent leaves writing behavior unchanged.
    user_notes: Optional[str] = None


# ---- Brand voice card (output of Step 3.5a) ----

class ClientContactInfo(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    hours: Optional[str] = None


class BrandVoiceCard(BaseModel):
    brand_name: str = ""
    tone_adjectives: list[str] = []
    voice_directives: list[str] = []
    audience_summary: str = ""
    audience_personas: list[str] = []
    audience_verticals: list[str] = []
    audience_company_size: str = ""
    audience_pain_points: list[str] = []
    audience_goals: list[str] = []
    preferred_terms: list[str] = []
    banned_terms: list[str] = []
    discouraged_terms: list[str] = []
    client_services: list[str] = []
    client_locations: list[str] = []
    client_contact_info: ClientContactInfo = ClientContactInfo()


# ---- Brand conflict log entry (output of Step 3.5b) ----

class BrandConflictEntry(BaseModel):
    term: str
    sie_classification: SIEClassification
    resolution: ConflictResolution
    brand_guide_reasoning: str = ""
    applicable_section_ids: list[str] = []


class ClientContextSummary(BaseModel):
    brand_guide_provided: bool = False
    icp_provided: bool = False
    website_analysis_used: bool = False
    reference_structure_used: bool = False
    schema_version_effective: SchemaVersion = "1.9"


# ---- Article output ----

class ArticleSection(BaseModel):
    order: int
    level: ArticleLevel
    type: ArticleType
    heading: Optional[str] = None
    body: str = ""
    word_count: int = 0
    section_budget: int = 0
    citations_referenced: list[str] = []


class CitationUsageEntry(BaseModel):
    citation_id: str
    used: bool = False
    sections_used_in: list[int] = []
    marker_placed: bool = False


class CitationUsage(BaseModel):
    total_citations_available: int = 0
    citations_used: int = 0
    citations_unused: int = 0
    usage: list[CitationUsageEntry] = []


class FormatCompliance(BaseModel):
    lists_present: int = 0
    tables_present: int = 0
    lists_required: int = 0
    tables_required: int = 0
    answer_first_applied: bool = True
    directives_satisfied: bool = True


class WriterMetadata(BaseModel):
    total_word_count: int = 0
    word_budget: int = 2500
    faq_word_count: int = 0
    budget_utilization_pct: float = 0.0
    word_count_conflict: bool = False
    no_required_terms: bool = False
    section_count: int = 0
    faq_count: int = 0
    citations_used: int = 0
    citations_unused: int = 0
    no_citations: bool = False
    retry_count: int = 0
    # Banned terms that leaked into body content after the section LLM's
    # one-retry attempt. The run does NOT abort on body leakage (the
    # distillation LLM occasionally over-classifies common words like
    # "leverage" as banned). Headings remain hard-abort. Reviewers can
    # find and fix these terms during article QA.
    banned_terms_leaked_in_body: list[str] = []
    # PRD v2.3 / Phase 3 - Step 6.7 H2 body length validator outcomes.
    # `under_length_h2_sections` carries the H2 sections (by their order
    # in heading_structure) that fell below `format_directives.
    # min_h2_body_words` after a single retry. The retry pass is
    # warn-and-accept - production never aborts on under-length, but the
    # flagged sections are surfaced so editors can review or expand
    # them post-publish.
    under_length_h2_sections: list[dict] = []
    h2_body_length_retries_attempted: int = 0
    h2_body_length_retries_succeeded: int = 0
    # PRD v1.7 / Phase 4 - Step 4F.1 citation-coverage validator outcomes.
    # `under_cited_sections` carries the H2 sections whose detected
    # citable claims (C1-C9) fell under the 50% citation-coverage
    # threshold even after a single retry. `operational_claims_softened`
    # records every C7-C9 phrase that was deterministically rewritten
    # to hedge phrasing because no citation could be added during the
    # retry. Both are warn-and-accept - runs never abort on coverage.
    under_cited_sections: list[dict] = []
    operational_claims_softened: list[dict] = []
    citation_coverage_retries_attempted: int = 0
    citation_coverage_retries_succeeded: int = 0
    # Step 3.6 - Brand & ICP placement plan outcome. The pipeline pre-
    # allocates exactly one H2 to anchor the brand mention and one H2 to
    # anchor the ICP callout, so editors can see (and override) the
    # decisions. The `_order` fields refer to the heading_structure
    # `order` *before* article-end resequencing - the `_text` fields are
    # the unambiguous editor-facing reference. All fields are `None`
    # when no anchor was assigned (e.g. brand_voice_card empty, no
    # audience signals available, or no content H2s).
    brand_anchor_h2_order: Optional[int] = None
    brand_anchor_h2_text: Optional[str] = None
    icp_anchor_h2_order: Optional[int] = None
    icp_anchor_h2_text: Optional[str] = None
    icp_hook_phrase: Optional[str] = None
    # Post-write verification: the section writer is *told* to mention
    # the brand exactly once, but the LLM can ignore the directive.
    # `brand_mention_landed=False` means the anchor section's body did
    # not contain the brand_name - surface for editor review (matches
    # the warn-and-accept pattern from h2_body_length / coverage).
    # `None` when no brand anchor was assigned (no verification needed).
    brand_mention_landed: Optional[bool] = None
    # Step 6.8 - ICP callout LLM judge (post-write). The judge tolerates
    # paraphrase ("margin erosion from refunds" → "shrinking unit
    # economics on returned orders") which a regex check cannot. `None`
    # means either no ICP anchor was assigned or the judge call failed
    # - unknown is the honest answer; flagging False would mislead.
    # `icp_callout_evidence` is a short verbatim quote from the body
    # when `landed=True`, for editor audit. `icp_callout_judge_status`
    # is an observability tag: "landed" / "not_landed" / "no_anchor" /
    # "empty_body" / "anchor_not_in_article" / "judge_error:<type>" /
    # "judge_payload_invalid".
    icp_callout_landed: Optional[bool] = None
    icp_callout_evidence: Optional[str] = None
    icp_callout_judge_status: Optional[str] = None
    # Step 0.5 - Heading sanitizer drops. The writer cleans two
    # structural drift modes from upstream briefs before generating
    # any content: duplicate body H2s with identical heading text, and
    # body H2s whose heading reads as "Frequently Asked Questions" /
    # "FAQs" / "Q&A" (which used to land BEFORE the conclusion while
    # the real faq-header block landed after, producing the
    # "conclusion in the middle of the FAQs" rendering bug). H3
    # children of dropped body H2s are dropped along with them. Empty
    # lists are the steady state; non-empty entries flag editor review.
    duplicate_h2_headings_dropped: list[dict] = []
    faq_like_h2_content_dropped: list[dict] = []
    h3_children_dropped_under_h2: list[dict] = []
    # Step 6.6 - AIO heading main-entity enforcement (§X.4). Runs after the
    # Heading SEO Optimizer; ensures every content H2 carries the brief's
    # main_entity (canonical/variant). Entity-presence only - the "one
    # point per heading" rule is deliberately not enforced. Warn-and-accept:
    # `headings_entity_violation_count` H2s could not be fixed and were kept
    # as-is for editor review. All zero / None when the brief carries no
    # main_entity (schema < 2.7).
    main_entity_used: Optional[str] = None
    headings_entity_enforced_count: int = 0
    headings_entity_rewrites_applied: int = 0
    headings_entity_violation_count: int = 0
    headings_entity_violations: list[dict] = []
    # Post-assembly structure validator warnings (orphan "Step N" refs,
    # intro out of position, missing conclusion, FAQ before conclusion).
    # Previously log-only; carried here so the run-detail QA panel can
    # surface them. Empty list is the steady state.
    structure_warnings: list[str] = []
    # End-of-run format QA (modules.writer.format_qa) - one Haiku call
    # judging whether the final H2 outline is the right ARCHETYPE for the
    # keyword (the only check that validates the plan itself, not the
    # article's conformance to it). All None = check skipped or failed
    # (unknown, the honest answer). matches_intent=False flags the run
    # for editor review - warn-and-accept, never aborts.
    format_qa_matches_intent: Optional[bool] = None
    format_qa_expected_archetype: Optional[str] = None
    format_qa_note: Optional[str] = None
    # Notes-landed judge (format_qa.check_notes_landed) - did the article
    # honor the per-run user_notes? One verdict per directive:
    # {"note", "landed", "evidence"}. Empty + None = no notes were given,
    # the check is disabled, or the judge failed (unknown).
    user_notes_verdicts: list[dict] = []
    user_notes_landed_all: Optional[bool] = None
    schema_version: SchemaVersion = "1.9"
    brief_schema_version: str = "2.0"
    generation_time_ms: int = 0


class WriterResponse(BaseModel):
    keyword: str
    intent_type: str
    title: str
    article: list[ArticleSection]
    citation_usage: CitationUsage
    format_compliance: FormatCompliance
    brand_voice_card_used: Optional[BrandVoiceCard] = None
    brand_conflict_log: list[BrandConflictEntry] = []
    client_context_summary: ClientContextSummary = ClientContextSummary()
    # Per-zone term usage breakdown (related keywords, entities, quadgrams).
    # Keyed by zone name: "title", "h1", "subheadings", "body". Computed
    # post-hoc by modules.writer.term_usage; always present.
    term_usage_by_zone: dict[str, dict] = {}
    metadata: WriterMetadata

"""Brief Generator Output model (M13) — the Writer's **Input A**.

Faithful to the production v2.6 `brief_output` contract recovered in
`docs/blog-writer-live-contract.md` (§"Writer module I/O contract"), which is
ground truth where it disagrees with the bundle's v2.3. This is the persisted
`fanout.briefs.output_json` shape and the native contract the M14 Writer adapter
consumes (no adaptation layer).

`model_config = extra="allow"` deliberately: (1) production briefs carry scoring
metadata fields we leave null, and (2) the **answer-engine-first** slices (MCS,
decision-fit, X.8) bump this schema with `aio_target` / `chatgpt_answer` / MCS
selection metadata — those land in their own slices rather than being speculatively
modeled here. The load-bearing fields the Writer keys off are typed below.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Brief Generator schema version (production live contract — supersedes the bundle's
# v2.3; the answer-engine-first X.8 slice bumps this when it adds AIO/MCS metadata).
SCHEMA_VERSION = "2.6"


class HeadingItem(BaseModel):
    """One heading in `heading_structure`. Load-bearing for the Writer:
    text/type/level/order/parent_h2_text. The rest is SERP-derived scoring metadata
    the adapter may leave null/0 (live contract §"heading_structure[0]")."""

    model_config = ConfigDict(extra="allow")

    text: str
    type: str = "content"                       # content | faq | authority_gap_sme | ...
    level: str = "H2"                            # H1 | H2 | H3
    order: int = 0
    parent_h2_text: str | None = None            # set for H3s -> their parent H2
    exempt: bool = False
    source: str | None = None                    # serp | llm_fanout | authority_gap | ...
    # SERP-derived scoring metadata (nullable; the answer-engine path adds MCS scores).
    serp_frequency: int | None = None
    avg_serp_position: float | None = None
    information_gain_score: float | None = None
    title_relevance: float | None = None
    parent_relevance: float | None = None
    heading_priority: float | None = None
    scope_classification: str | None = None
    scope_alignment_note: str | None = None
    parent_fit_classification: str | None = None
    llm_fanout_consensus: float | None = None
    region_id: str | None = None
    original_source: str | None = None


class FormatDirectives(BaseModel):
    """`format_directives` (live contract §"format_directives") — the structural
    rules the Writer enforces. Decision-fit (A5) adds a typed directive here in its
    own slice (aio-optimization-plan.md §3.3)."""

    model_config = ConfigDict(extra="allow")

    require_tables: bool = False
    min_tables_per_article: int = 0
    min_lists_per_article: int = 0
    require_bulleted_lists: bool = False
    min_h2_body_words: int = 0
    answer_first_paragraphs: bool = False
    preferred_paragraph_max_words: int = 0


class FAQ(BaseModel):
    model_config = ConfigDict(extra="allow")

    question: str
    answer: str | None = None


class BriefOutput(BaseModel):
    """Brief Generator v2.6 output = Writer Input A. Persisted as
    `fanout.briefs.output_json`. Field names are byte-faithful to the live contract;
    under-specified nested objects (persona/structural_constants/intent_format_template/
    metadata/insights) are kept permissive (the producing slices fill their shapes)."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    keyword: str

    # Title / scope (Step 3.5)
    h1: str = ""
    title: str = ""
    title_rationale: str | None = None
    scope_statement: str | None = None

    # Intent (Step 3) — intent_review_required gates the article run (<0.75 BLOCKS,
    # plan §7 #4); the parked-state handling is the pipeline slice, not this model.
    intent_type: str | None = None
    intent_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    intent_review_required: bool = False
    intent_format_template: dict | None = None

    # Structure
    format_directives: FormatDirectives = Field(default_factory=FormatDirectives)
    heading_structure: list[HeadingItem] = Field(default_factory=list)
    faqs: list[FAQ] = Field(default_factory=list)

    # Audience / research context (permissive — filled by the persona/sources slices)
    persona: dict | None = None
    structural_constants: dict | None = None
    editorial_critique: dict | None = None
    customer_review_insights: dict | None = None
    reddit_insights: dict | None = None
    llm_disagreement: dict | None = None

    # Step 12 is skipped (this app owns silos) but the keys are preserved for parity /
    # future spin-off intel (plan §2 / §7 #1).
    silo_candidates: list = Field(default_factory=list)
    discarded_headings: list = Field(default_factory=list)

    metadata: dict = Field(default_factory=dict)

"""Writer module models (M14) — Input A (Brief), Input C (SIE), and the v1.7 output.

Contracts are faithful to `docs/blog-writer-pipeline-bundle.md` PRD #1 (Content Writer
v1.7) §2 (inputs) + §6 (output schema). In THIS build the Writer's upstreams are produced
by sibling modules already in the repo, so the adapter (slice 2) is a pure field-mapper —
no adaptation layer:

  Input A  = `fanout.briefs.output_json`         (M13 BriefOutput v2.6)
  Input B  = (none — we have no Research/Citations module) -> `no_citations` mode
  Input C  = `fanout.keyword_analyses.output_json` (M12 SIEOutput v1.4, native shape)

All input models use `extra="allow"` so the richer persisted shapes (MCS metadata, SIE
report extras) pass through untouched. Input C is `app.sie.models.SIEOutput` reused
directly (re-exported here as `SieInput`).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from fanout.sie.models import SIEOutput as SieInput  # Input C — native shape, reused

# Effective schema versions the Writer may stamp (PRD §6). Our production path is
# the degraded `1.7-no-context` + `no_citations`; the others exist for parity.
SCHEMA_VERSION = "1.7"
SCHEMA_VERSION_NO_CONTEXT = "1.7-no-context"
ACCEPTED_SCHEMA_VERSIONS = (
    "1.7", "1.7-no-context", "1.7-degraded", "1.7-legacy-h1",
)

__all__ = [
    "IntentType", "Brief", "BriefHeading", "BriefFormatDirectives", "BriefFaq",
    "SieInput", "ArticleItem", "WriterOutput", "WriterAbort",
    "SCHEMA_VERSION", "SCHEMA_VERSION_NO_CONTEXT", "ACCEPTED_SCHEMA_VERSIONS",
]


class IntentType(str, Enum):
    """The 8 intent enums (PRD §2.1 / Brief Gen registry). Governs section patterns,
    body-length floors, and the CTA template."""

    informational = "informational"
    listicle = "listicle"
    how_to = "how-to"
    comparison = "comparison"
    ecom = "ecom"
    local_seo = "local-seo"
    news = "news"
    informational_commercial = "informational-commercial"


# ----- Input A — Brief Generator output (§2.1) ------------------------------


class BriefHeading(BaseModel):
    """One `heading_structure[]` entry. The Writer emits these in `order`."""

    model_config = ConfigDict(extra="allow")

    order: int = 0
    level: str = "H2"                         # H1 | H2 | H3
    text: str
    type: str = "content"                     # content | faq-header | faq-question | conclusion
    source: str | None = None                 # e.g. authority_gap_sme -> budget multiplier + stricter bar
    parent_h2_text: str | None = None
    citation_ids: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None      # brief H2 embedding (else embed on the fly)
    format_directive: dict | None = None      # per-section typed directive (e.g. decision_fit, §A5)


class BriefFormatDirectives(BaseModel):
    """`format_directives` (§2.1). Defaults match the PRD (answer-first on; 4-sentence
    paragraph cap; ≥1 list + ≥1 table when required)."""

    model_config = ConfigDict(extra="allow")

    require_bulleted_lists: bool = False
    require_tables: bool = False
    min_lists_per_article: int = 1
    min_tables_per_article: int = 1
    answer_first_paragraphs: bool = True
    max_sentences_per_paragraph: int = 4
    min_h2_body_words: int = 0                 # intent-specific floor (else from templates)


class BriefFaq(BaseModel):
    model_config = ConfigDict(extra="allow")

    question: str
    faq_score: float | None = None
    answer: str | None = None                 # brief may carry a draft answer; Writer rewrites


class Brief(BaseModel):
    """Input A — the Writer's view of the Brief Generator output (M13 BriefOutput).
    `extra="allow"` keeps the MCS/answer-engine metadata; the Writer reads the fields
    below."""

    model_config = ConfigDict(extra="allow")

    keyword: str
    title: str                                # H1 verbatim (no LLM regeneration, §2.1)
    seo_title: str = ""                       # distinct <title>/WP post title ("" -> fall back to H1)
    intent_type: IntentType = IntentType.informational
    scope_statement: str | None = None
    heading_structure: list[BriefHeading] = Field(default_factory=list)
    faqs: list[BriefFaq] = Field(default_factory=list)
    format_directives: BriefFormatDirectives = Field(default_factory=BriefFormatDirectives)
    metadata: dict = Field(default_factory=dict)   # word_budget, h2_count, h3_count


# ----- Output (§6) ----------------------------------------------------------


class ArticleItem(BaseModel):
    """One `article[]` element of the Writer output (§6)."""

    model_config = ConfigDict(extra="allow")

    order: int = 0
    level: str = "none"                        # H1 | H2 | H3 | none
    type: str = "content"                      # content | faq-* | conclusion | h1-enrichment | key-takeaways | intro | cta | title
    heading: str | None = None
    body: str = ""
    word_count: int = 0
    section_budget: int = 0
    citations_referenced: list[str] = Field(default_factory=list)


class WriterOutput(BaseModel):
    """The Content Writer v1.7 output object (§6). Load-bearing fields are typed; the
    brand/citation blocks are permissive dicts (empty in our `no_citations` /
    `1.7-no-context` path). Persisted as `fanout.article_outputs.article_json`."""

    model_config = ConfigDict(extra="allow")

    keyword: str
    intent_type: IntentType = IntentType.informational
    title: str = ""
    seo_title: str = ""                        # distinct <title>/WP post title ("" -> fall back to title)
    article: list[ArticleItem] = Field(default_factory=list)
    article_markdown: str = ""
    article_html: str = ""
    key_takeaways: list[str] = Field(default_factory=list)
    intro: dict = Field(default_factory=dict)      # {agree, promise, preview}
    cta: str = ""

    citation_usage: dict = Field(default_factory=dict)
    format_compliance: dict = Field(default_factory=dict)
    brand_voice_card_used: dict | None = None
    brand_conflict_log: list = Field(default_factory=list)
    client_context_summary: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


# ----- Error envelope (§7 / §19.6) ------------------------------------------


class WriterAbort(Exception):
    """A load-bearing failure that aborts the run with a stable `code` (PRD §7). The
    job catches it, persists nothing, and surfaces the code (partial output is worse
    than none for the required structural elements — D7)."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message or code
        super().__init__(f"{code}: {self.message}")

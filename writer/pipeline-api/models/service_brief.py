"""Pydantic models for the Service Page Brief Generator module.

The Service Page Brief Generator produces a structured, commercial-intent
brief for a single service page (the contract handed to a later Service Page
Writer). It is a **clean** schema (PRD decision D) — it does NOT extend the
blog `BriefResponse`. The brief is three layers:

  1. Strategy     — positioning angle (wedge), intent, objections.
  2. Architecture — the outline: section-level directives only, no prose.
  3. Conversion & SEO — CTA, schema, internal links, FAQ targets.

The module runs its OWN research pipeline (`ResearchBundle`) and must not
reuse other modules' stored outputs (it may reuse their code).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Bumped independently of the blog brief. Echoed in metadata + cache rows and
# validated by the orchestrator (Phase 2). Keep in sync with any output change.
SCHEMA_VERSION = "1.2"  # 1.1: reference_page_structure mirroring; 1.2: optional decision_fit

ServiceMode = Literal["local_service", "national_b2b"]
LengthBand = Literal["short", "medium", "long"]
HeadingLevel = Literal["H1", "H2", "H3"]
# A `service` page targets one service; a `location` page is a multi-service
# hub targeting one location (a section per major service). Both run through
# this same brief→writer→scoring stack — only synthesis / title / JSON-LD branch.
PageType = Literal["service", "location"]


# ----------------------------------------------------------------------
# Inputs
# ----------------------------------------------------------------------

class ClientContextInput(BaseModel):
    """Client config consumed by synthesis (PRD §3.1).

    Mirrors the platform's existing converged structured assets so Phase 2's
    orchestrator can pass them straight through from `client_context_snapshot`
    / the `clients` row: `brand_voice`, `detected_icp`, `differentiators`,
    `website_analysis`, `gbp`. Every field is optional — the module degrades
    (with a note) rather than failing when one is absent.
    """
    model_config = ConfigDict(extra="ignore")

    brand_voice: Optional[dict[str, Any]] = None
    icp: Optional[dict[str, Any]] = None
    # Company-wide value props: [{claim, mechanism, type}] — the "wedge" source.
    differentiators: list[dict[str, Any]] = Field(default_factory=list)
    # Rendered free-text fallbacks (used when the structured blobs are absent).
    brand_voice_text: Optional[str] = None
    icp_text: Optional[str] = None
    # {services[], locations[], contact_info{}} from clients.website_analysis.
    website_analysis: Optional[dict[str, Any]] = None
    gbp: Optional[dict[str, Any]] = None
    business_name: Optional[str] = None
    # Pre-rendered "mirror this layout" block from the client's reference
    # service page (clients.page_structures.service). Optional — when present,
    # synthesis is told to match its section layout/order. See platform-api's
    # services/page_structure_render.render_reference_structure.
    reference_page_structure: Optional[str] = None


class ServiceBriefRequest(BaseModel):
    """Input envelope to POST /service-brief."""
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Idempotency key from platform-api")
    attempt: int = 1
    service: str = Field(..., min_length=1, max_length=200)
    primary_query: str = Field(..., min_length=1, max_length=200)
    # Optional (PRD): present for local businesses, absent for national/B2B.
    # Influences research + mode classification.
    location: Optional[str] = None
    location_code: int = 2840  # United States
    # `service` (default) = single-service page; `location` = a multi-service
    # location hub. For a location page, `services` lists the major services to
    # cover (one section each) and `service` carries the location label.
    page_type: PageType = "service"
    services: list[str] = Field(default_factory=list)
    force_refresh: bool = False
    client_context: ClientContextInput = Field(default_factory=ClientContextInput)


# ----------------------------------------------------------------------
# Research bundle (PRD §4 — the module's own research output)
# ----------------------------------------------------------------------

class CompetitorSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    heading: str = ""
    section_type: str = ""  # hero | services | pricing | process | faq | proof | cta | ...
    approx_words: int = 0


class CompetitorSkeleton(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str
    page_type: str = "service_page"
    sections: list[CompetitorSection] = Field(default_factory=list)
    proof_assets: list[str] = Field(default_factory=list)  # case_study | certification | guarantee | review | award
    word_count: int = 0
    coverage: list[str] = Field(default_factory=list)  # topics/entities the page covers


class Gap(BaseModel):
    model_config = ConfigDict(extra="ignore")
    topic: str
    rationale: str = ""


class EntityCoverageItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    term: str
    category: str = "concepts"
    pages_found: int = 0
    salience: float = 0.0


class MinedQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str
    source: str = "paa"  # paa | autocomplete


class AioPresence(BaseModel):
    model_config = ConfigDict(extra="ignore")
    available: bool = False
    cited_domains: list[str] = Field(default_factory=list)
    fanout_questions: list[str] = Field(default_factory=list)


class SerpProfile(BaseModel):
    """Stage 1 output — the SERP's shape, derived from the LIVE SERP (never a
    static per-client flag — PRD §8.2)."""
    model_config = ConfigDict(extra="ignore")

    mode: ServiceMode
    length_band: LengthBand
    target_word_count: int
    local_pack: bool = False
    featured_snippet: bool = False
    organic_service_pages: int = 0
    directory_aggregator_count: int = 0
    informational_count: int = 0
    search_intent: Optional[str] = None


class ResearchBundle(BaseModel):
    """The single structured object consumed by synthesis (PRD §4 output)."""
    model_config = ConfigDict(extra="ignore")

    serp_profile: SerpProfile
    mode: ServiceMode
    length_band: LengthBand
    competitor_skeletons: list[CompetitorSkeleton] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    entity_coverage: list[EntityCoverageItem] = Field(default_factory=list)
    questions: list[MinedQuestion] = Field(default_factory=list)
    aio_presence: AioPresence = Field(default_factory=AioPresence)
    degraded_notes: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Output — the three-layer brief
# ----------------------------------------------------------------------

class Objection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    objection: str
    where_addressed: str = ""


class StrategyLayer(BaseModel):
    """Layer 1 — Strategy."""
    model_config = ConfigDict(extra="ignore")

    positioning_angle: str  # the wedge
    primary_query: str
    secondary_queries: list[str] = Field(default_factory=list)
    objections: list[Objection] = Field(default_factory=list)


class BriefSection(BaseModel):
    """Layer 2 — one Architecture section. SECTION-LEVEL DIRECTIVES ONLY — no
    sentence-level prose scripting (PRD §8.4 / non-goals)."""
    model_config = ConfigDict(extra="ignore")

    heading: str
    level: HeadingLevel = "H2"
    purpose: str
    must_cover: list[str] = Field(default_factory=list)
    proof_asset: Optional[str] = None
    length_target: int = 0
    citation_fit: bool = False
    # Why this section deviates from the competitor skeleton (PRD §5 / decision C).
    divergence_note: Optional[str] = None


class ConversionLayer(BaseModel):
    """Layer 3 — Conversion & SEO."""
    model_config = ConfigDict(extra="ignore")

    cta_strategy: str = ""
    cta_placement: list[str] = Field(default_factory=list)
    objection_preemption_map: dict[str, str] = Field(default_factory=dict)
    # NOTE: named `schema_types` (not `schema`) — `schema` shadows a pydantic method.
    schema_types: list[str] = Field(default_factory=lambda: ["Service", "FAQPage"])
    internal_links: list[str] = Field(default_factory=list)
    faq_targets: list[str] = Field(default_factory=list)
    paa_targets: list[str] = Field(default_factory=list)


class DecisionFitBranch(BaseModel):
    """One `condition -> recommended option` branch of a decision-fit map."""
    model_config = ConfigDict(extra="ignore")

    condition: str
    option: str


class DecisionFit(BaseModel):
    """Optional decision-fit map (schema 1.2). Present only when the page genuinely
    serves a situational choice ("which service/tier/urgency level fits the buyer").
    Synthesis emits it folded into its existing call; the writer weaves the branches
    into prose (condition-first). Dropped by assembly unless `applies` and there are
    at least two distinct, non-empty branches.
    """
    model_config = ConfigDict(extra="ignore")

    applies: bool = False
    branches: list[DecisionFitBranch] = Field(default_factory=list)
    default_statement: str = ""


class ServiceSiloCandidate(BaseModel):
    """Lightweight silo candidate. Shaped to feed the existing silo_dedup
    consumer in Phase 2, which reads `suggested_keyword`,
    `viable_as_standalone_article`, and `estimated_intent`."""
    model_config = ConfigDict(extra="ignore")

    suggested_keyword: str
    # silo_dedup persists this to silo_candidates.estimated_intent. Service
    # pages are commercial-intent; default accordingly.
    estimated_intent: str = "commercial"
    viable_as_standalone_article: bool = True
    source: str = "service_brief"


class ServiceBriefMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["1.2", "1.1", "1.0"] = "1.2"
    mode: ServiceMode
    length_band: LengthBand
    cost_usd: float = 0.0
    cache_hit: bool = False
    competitors_analyzed: int = 0
    section_count: int = 0
    objection_count: int = 0
    degraded_notes: list[str] = Field(default_factory=list)


class ServiceBriefResponse(BaseModel):
    """POST /service-brief response — the clean three-layer service brief."""
    model_config = ConfigDict(extra="ignore")

    service: str
    primary_query: str
    strategy: StrategyLayer
    architecture: list[BriefSection] = Field(default_factory=list)
    conversion: ConversionLayer
    silo_candidates: list[ServiceSiloCandidate] = Field(default_factory=list)
    # Optional situational-choice map (schema 1.2). None unless the page serves a
    # genuine "which one fits me" decision — the writer weaves it into prose.
    decision_fit: Optional[DecisionFit] = None
    # The research bundle is echoed for observability/debugging (and Phase 2's
    # writer); it is optional so cached/degraded paths can omit it.
    research_bundle: Optional[ResearchBundle] = None
    metadata: ServiceBriefMetadata

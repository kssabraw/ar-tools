"""Pydantic models for the Service Page Writer module.

Consumes a Service Page Brief (the clean 3-layer `ServiceBriefResponse`) and
produces a conversion-focused service page. Output prose is generated once as
structured blocks, then rendered deterministically into Markdown, semantic
HTML, and WordPress (Gutenberg) block markup, plus a Service + FAQPage JSON-LD
block. Reuses the blog writer's `ClientContextInput` so the orchestrator can
pass the same client_context shape it builds for the blog writer.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Independent of the blog writer's version. Echoed in metadata + validated by
# the orchestrator (Phase 2). Bump on any output-shape change.
SCHEMA_VERSION = "1.0"

# Reuse the blog writer's client-context model so distill_brand_voice works
# unchanged and the orchestrator can pass an identical client_context dict.
from models.writer import ClientContextInput  # noqa: E402

HeadingLevel = Literal["H1", "H2", "H3"]
BlockType = Literal["paragraph", "list", "subheading", "cta"]
PageType = Literal["service", "location"]


# ----------------------------------------------------------------------
# Inputs
# ----------------------------------------------------------------------

class ServiceWriterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Idempotency key from platform-api")
    attempt: int = 1
    # The ServiceBriefResponse dict (Strategy / Architecture / Conversion+SEO).
    service_brief_output: dict[str, Any]
    client_context: Optional[ClientContextInput] = None
    # `service` (default) = single-service page; `location` = a multi-service
    # location hub. For a location page, `location` carries the target area and
    # `services` lists the services covered — both only shape the title/meta and
    # JSON-LD (the section bodies come from the brief's architecture either way).
    page_type: PageType = "service"
    location: Optional[str] = None
    services: list[str] = Field(default_factory=list)
    # Reoptimization: when 'reoptimize', the writer regenerates guided by the
    # scorer's deficiencies, using the prior page's sections as the baseline.
    mode: Literal["generate", "reoptimize"] = "generate"
    # Prior service_writer sections (serialized) — baseline for reoptimize.
    prior_sections: list[dict[str, Any]] = Field(default_factory=list)
    # Scorer deficiencies: [{engine, engine_key, score, issues[], recommendations[]}].
    deficiencies: list[dict[str, Any]] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Structured content + renderings
# ----------------------------------------------------------------------

class Block(BaseModel):
    """One content block. The canonical structured form; all three renderings
    (markdown/html/wordpress) are derived deterministically from these."""
    model_config = ConfigDict(extra="ignore")

    type: BlockType
    text: str = ""              # paragraph / subheading / cta text
    items: list[str] = Field(default_factory=list)  # list items (type == "list")
    level: int = 3              # subheading depth (type == "subheading")
    href: Optional[str] = None  # optional cta link (type == "cta")


class WriterSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    order: int
    level: HeadingLevel = "H2"
    heading: str
    blocks: list[Block] = Field(default_factory=list)
    word_count: int = 0
    type: str = "content"  # content | faq | cta


class Renderings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    markdown: str = ""
    html: str = ""
    wordpress: str = ""  # Gutenberg block markup, paste-ready into the WP editor


# ----------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------

class ServiceWriterMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["1.0"] = "1.0"
    total_word_count: int = 0
    cost_usd: float = 0.0
    section_count: int = 0
    faq_count: int = 0
    brand_voice_card_used: Optional[dict] = None
    degraded_notes: list[str] = Field(default_factory=list)
    generation_time_ms: int = 0


class ServiceWriterResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    service: str
    primary_query: str
    title: str = ""
    meta_description: str = ""
    sections: list[WriterSection] = Field(default_factory=list)
    renderings: Renderings
    schema_jsonld: str = ""
    metadata: ServiceWriterMetadata

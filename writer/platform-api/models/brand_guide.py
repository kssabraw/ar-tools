"""Pydantic schemas for the Brand Guide Generator module (Phase 4 API surface)."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class BrandGuide(BaseModel):
    """A `brand_guides` row. The heavy jsonb layers (captured / visual_census /
    vibe_read / synthesized / renders) are passed through untyped — the frontend
    reads them structurally, and the shapes are owned by the pipeline services."""

    id: UUID
    client_id: UUID
    version: int
    status: str  # queued|capturing|synthesizing|rendering|awaiting_signoff|done|error
    source_url: Optional[str] = None
    captured: Optional[dict] = None
    visual_census: Optional[dict] = None
    vibe_read: Optional[dict] = None
    synthesized: Optional[dict] = None
    edited: bool = False
    renders: Optional[dict] = None
    storage_path: Optional[str] = None
    pdf_url: Optional[str] = None
    error: Optional[str] = None
    generated_at: Optional[str] = None
    created_at: str


class BrandGuideStatus(BaseModel):
    enabled: bool


class GenerateBrandGuideRequest(BaseModel):
    source_url: Optional[str] = None       # override; defaults to clients.website_url
    pages: Optional[list[str]] = None      # operator page-scope override (else nav auto-discovery)


class BrandGuideEditOp(BaseModel):
    """One structured-field edit (PRD §9). `op` ∈
    set_field | set_voice_example | swatch_rename | swatch_drop | swatch_flag_not_brand."""

    op: str
    field: Optional[str] = None            # set_field: tagline|positioning_statement|mission
    key: Optional[str] = None             # set_voice_example: headline|cta|product_blurb|email_opener
    value: Optional[str] = None           # set_field / set_voice_example
    hex: Optional[str] = None             # swatch_*
    name: Optional[str] = None            # swatch_rename


class BrandGuideEditRequest(BaseModel):
    edits: list[BrandGuideEditOp]


class LogoAdoptRequest(BaseModel):
    candidate_url: str
    replace: bool = False                  # required when clients.logo_url is already set


class LogoAdoptResponse(BaseModel):
    logo_url: str


class BrandGuideDownload(BaseModel):
    profile: str                           # internal | client
    url: str


class VoiceSuggestionResponse(BaseModel):
    """The suggest-only voice surface (§4.8) — copyable text + the editor deep-link.
    This module NEVER writes voice/ICP; the operator applies it in the editor."""

    text: str
    editor_path: str
    has_suggestions: bool

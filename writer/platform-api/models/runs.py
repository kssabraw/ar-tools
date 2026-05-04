"""Pydantic models for Run resources."""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RunCreateRequest(BaseModel):
    client_id: UUID
    keyword: str = Field(..., min_length=1, max_length=150)
    intent_override: Optional[str] = None
    sie_outlier_mode: Literal["safe", "aggressive"] = "safe"
    sie_force_refresh: bool = False
    # PRD v2.6 — when True, the brief generator skips its 7-day cache
    # lookup and produces a fresh brief. Set by the run-create UX when
    # the user explicitly chose "regenerate" on the cache-decision
    # modal.
    brief_force_refresh: bool = False


class RunListItem(BaseModel):
    id: UUID
    keyword: str
    title: Optional[str] = None
    client_id: UUID
    client_name: str
    status: str
    sie_cache_hit: Optional[bool] = None
    total_cost_usd: Optional[float] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ModuleOutputSummary(BaseModel):
    status: str
    output_payload: Optional[dict[str, Any]] = None
    cost_usd: Optional[float] = None
    duration_ms: Optional[int] = None
    module_version: Optional[str] = None


class ClientContextSnapshot(BaseModel):
    brand_guide_text: Optional[str] = None
    brand_guide_format: Optional[str] = None
    icp_text: Optional[str] = None
    icp_format: Optional[str] = None
    website_analysis: Optional[dict[str, Any]] = None
    website_analysis_unavailable: bool = False


class SIETermsByCategory(BaseModel):
    """Convenience three-bucket view of SIE required terms for the UI.

    The SIE module_output already carries `terms.required[]` with each
    TermRecord flagged via `is_entity` and `is_seed_fragment`. The UI
    can derive these buckets itself, but pre-computing them server-
    side makes rendering trivial and keeps category boundaries
    consistent with the writer's prompt-side bucketing.
    """

    entities: list[str] = []
    related_keywords: list[str] = []
    keyword_variants: list[str] = []


def bucket_sie_required_terms(
    required: Optional[list[dict[str, Any]]],
) -> SIETermsByCategory:
    """Split SIE `terms.required[]` into the three v1.4 buckets.

    Mirrors the writer's `_classify_term` ordering — entity check
    takes precedence over seed-fragment, default is related_keyword.
    Defensive against malformed entries (non-dicts, empty `term`,
    missing flags) and a `None` input (e.g., when SIE module_output
    lacks the `terms.required` field).
    """
    entities: list[str] = []
    related: list[str] = []
    variants: list[str] = []
    for term in required or []:
        if not isinstance(term, dict):
            continue
        term_str = (term.get("term") or "").strip()
        if not term_str:
            continue
        if term.get("is_entity"):
            entities.append(term_str)
        elif term.get("is_seed_fragment"):
            variants.append(term_str)
        else:
            related.append(term_str)
    return SIETermsByCategory(
        entities=entities,
        related_keywords=related,
        keyword_variants=variants,
    )


class RunDetail(BaseModel):
    id: UUID
    keyword: str
    title: Optional[str] = None
    h1: Optional[str] = None
    client_id: UUID
    status: str
    sie_cache_hit: Optional[bool] = None
    error_stage: Optional[str] = None
    error_message: Optional[str] = None
    total_cost_usd: Optional[float] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    client_context_snapshot: Optional[ClientContextSnapshot] = None
    module_outputs: dict[str, Optional[ModuleOutputSummary]] = Field(
        default_factory=lambda: {
            "brief": None,
            "sie": None,
            "research": None,
            "writer": None,
            "sources_cited": None,
        }
    )
    # Pre-bucketed SIE terms for the UI. Populated when the SIE
    # module_output is available. None for runs that haven't reached
    # the SIE stage yet.
    sie_terms_by_category: Optional[SIETermsByCategory] = None


class RunCreateResponse(BaseModel):
    run_id: UUID
    status: str


class RunPollResponse(BaseModel):
    run_id: UUID
    status: str
    completed_stages: list[str]
    error_stage: Optional[str] = None
    updated_at: str


class RunListResponse(BaseModel):
    data: list[RunListItem]
    total: int
    page: int

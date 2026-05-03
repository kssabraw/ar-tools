"""Pydantic models for Silo Candidate resources (Platform PRD v1.4)."""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


SiloStatus = Literal[
    "proposed",
    "approved",
    "rejected",
    "in_progress",
    "published",
    "superseded",
]


# Must stay in sync with pipeline-api's models.brief.SiloRoutedFrom.
# Adding a value to the pipeline-api literal without mirroring it here
# causes the /silos endpoint to 500 on the row Pydantic-validation step
# the moment any silo with the new routed_from value lands in the DB
# via silo_dedup. Order: oldest values first; keep comments aligned
# with the pipeline-api source so the next add is easy to find.
SiloRoutedFrom = Literal[
    "non_selected_region",
    "scope_verification",
    # PRD v2.0.3 — Step 8.5b authority-gap H3 scope-verification rejects
    "scope_verification_h3",
    # Step 5.1 relevance gate — heading discarded as below_relevance_floor
    # but surfaced as adjacent-topic silo
    "relevance_floor_reject",
    # PRD v2.2 — Step 8.7 H3 parent-fit verification outcomes
    "h3_parent_mismatch",
    "h3_promote_candidate",
    # PRD v2.4 — fanout candidate not used as H2; surfaced as silo
    # bypassing the search-demand floor
    "llm_fanout_unused",
]


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


class SiloListItem(BaseModel):
    """Compact row shape for the /silos dashboard list view."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_id: UUID
    suggested_keyword: str
    status: SiloStatus
    occurrence_count: int
    cluster_coherence_score: Optional[float] = None
    search_demand_score: Optional[float] = None
    viable_as_standalone_article: bool = True
    estimated_intent: Optional[IntentType] = None
    routed_from: Optional[SiloRoutedFrom] = None
    first_seen_run_id: UUID
    last_seen_run_id: UUID
    promoted_to_run_id: Optional[UUID] = None
    last_promotion_failed_at: Optional[str] = None
    created_at: str
    updated_at: str


class SiloDetail(SiloListItem):
    """Full row including provenance + heading evidence (drawer view)."""

    source_run_ids: list[UUID] = []
    viability_reasoning: Optional[str] = None
    discard_reason_breakdown: dict[str, int] = {}
    source_headings: list[dict[str, Any]] = []


class SiloListResponse(BaseModel):
    items: list[SiloListItem]
    total: int
    page: int
    page_size: int


class SiloStatusUpdateRequest(BaseModel):
    """Used by `PATCH /silos/{id}` for approve / reject transitions."""

    status: Literal["approved", "rejected"]


class SiloPromoteResponse(BaseModel):
    """Returned by promote endpoints — links the silo to its new run."""

    silo_id: UUID
    run_id: UUID
    status: SiloStatus


class SiloBulkRequest(BaseModel):
    """Used by bulk-action endpoints. The IDs must all belong to the
    same client (validated server-side)."""

    ids: list[UUID] = Field(..., min_length=1, max_length=200)


class SiloBulkResponse(BaseModel):
    """Result of a bulk action."""

    succeeded: list[UUID] = []
    failed: list[dict[str, str]] = []  # [{id, reason}]
    runs_dispatched: list[UUID] = []   # for bulk-approve-and-generate


class SiloMetricsResponse(BaseModel):
    """Dashboard header metrics for a client."""

    client_id: UUID
    counts_by_status: dict[str, int] = {}
    average_occurrence_count: float = 0.0
    high_frequency_threshold: int = 3
    high_frequency_count: int = 0

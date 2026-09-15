"""PAA → SEO Neo v1 — request/response models (the content half)."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PaaPullRequest(BaseModel):
    """Pull People-Also-Ask questions for a service-in-geo (reuses one SERP call)."""

    service_keyword: str
    geo_mode: str = "geo"  # 'geo' (default, geo-modified) | 'naked'
    location: Optional[str] = None  # override the client's business_location city


class PaaCandidateInput(BaseModel):
    """A chosen PAA question to persist in a set (as returned by the pull)."""

    question: str
    slug: Optional[str] = None
    volume: Optional[int] = None
    cpc_usd: Optional[float] = None
    competition: Optional[str] = None


class PaaSetCreateRequest(BaseModel):
    service_keyword: str
    items: list[PaaCandidateInput]
    geo_mode: str = "geo"
    location: Optional[str] = None
    location_code: Optional[int] = None
    # The "link high" service page: explicit wins; else the pull's auto-match is
    # passed back here so the server can record its provenance.
    service_page_url: Optional[str] = None
    auto_service_page_url: Optional[str] = None


class PaaCreatePostsRequest(BaseModel):
    # Acknowledge the cannibalization sign-off (slug collision / existing page /
    # scale) to proceed past an acknowledgeable gate.
    acknowledge: bool = False


# ── Phase 2 — the prep-sheet manifest (track / cost / QA / hand-off) ──────────


class PaaManifestAssetUpdate(BaseModel):
    """Operator edit to a manifest asset row (only whitelisted fields apply)."""

    label: Optional[str] = None
    url: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None  # authority/media: planned | handed_off | done
    cost_task_type: Optional[str] = None
    cost_quantity: Optional[float] = None
    position: Optional[int] = None


class PaaManifestAssetCreate(BaseModel):
    """Add a manual asset row (a hand-captured content/authority/media URL)."""

    category: str  # paa_post | gbp_post | syndication | image | authority | media
    label: str
    kind: Optional[str] = None
    url: Optional[str] = None
    note: Optional[str] = None
    status: Optional[str] = None
    confidence_tag: Optional[str] = None
    cost_task_type: Optional[str] = None
    cost_quantity: Optional[float] = None

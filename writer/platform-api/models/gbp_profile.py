"""Pydantic request/response schemas for the GBP Profile Editor module.

Every response field the frontend reads is declared here — Pydantic silently
strips undeclared keys before the frontend sees them (the repo's #844 lesson;
it already bit ``MapsGbpAuditResponse`` in #1009).
"""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

ProfileField = Literal[
    "description", "hours", "services",
    # Phase 3a — Tier A fields (same locations.patch endpoint).
    "website", "labels", "special_hours", "more_hours", "service_area", "open_info",
]
EditSource = Literal["manual", "ai", "strategist"]


# ── shared value shapes (hours / services) ──────────────────────────────────
class HoursPeriod(BaseModel):
    open: str   # 'HH:MM'
    close: str  # 'HH:MM'


class HoursRow(BaseModel):
    day: int = Field(ge=0, le=6)  # 0 = Monday … 6 = Sunday
    open_24: bool = False
    periods: list[HoursPeriod] = []


class DateInput(BaseModel):
    year: int
    month: int
    day: int


class SpecialHoursRow(BaseModel):
    start: DateInput
    end: Optional[DateInput] = None
    closed: bool = False
    open: Optional[str] = None
    close: Optional[str] = None


class HoursValue(BaseModel):
    regular: list[HoursRow] = []
    # None leaves special hours untouched; [] clears them.
    special: Optional[list[SpecialHoursRow]] = None


# ── Phase 3a value shapes (more hours / service area / open info) ────────────
class MoreHoursEntry(BaseModel):
    """One additional-hours type + its weekly hours (kitchen / delivery / …)."""

    hours_type_id: str
    regular: list[HoursRow] = []


class ServiceAreaPlace(BaseModel):
    name: str = ""
    place_id: str = ""  # the Google place id a v1 serviceArea write requires


class ServiceAreaValue(BaseModel):
    business_type: str = ""  # CUSTOMER_AND_BUSINESS_LOCATION | CUSTOMER_LOCATION_ONLY
    places: list[ServiceAreaPlace] = []
    region_code: Optional[str] = None


class OpenInfoValue(BaseModel):
    status: str  # OPEN | CLOSED_TEMPORARILY | CLOSED_PERMANENTLY
    opening_date: Optional[DateInput] = None


class ServiceItemInput(BaseModel):
    kind: Literal["free_form", "structured"] = "free_form"
    label: str = ""
    description: Optional[str] = None
    category_id: Optional[str] = None        # a listing category's gcid
    service_type_id: Optional[str] = None    # a Google-defined structured service type
    raw: Optional[dict[str, Any]] = None     # structured passthrough (keeps description)


class Category(BaseModel):
    id: str    # the gcid the services editor attaches to
    name: str  # display name


class ServiceType(BaseModel):
    service_type_id: str
    display_name: str


class ServiceTypeCategory(BaseModel):
    id: str    # the listing category's gcid
    name: str  # display name
    service_types: list[ServiceType] = []


class ServiceTypesResponse(BaseModel):
    """The Google-defined service types the operator can pick, grouped by the
    listing's categories (categories.batchGet, view=FULL)."""

    categories: list[ServiceTypeCategory] = []


# ── requests ────────────────────────────────────────────────────────────────
class ProfileEditCreateRequest(BaseModel):
    """Create a manual draft edit for one field. Exactly one value key must be
    supplied, matching ``field``."""

    location_row_id: UUID
    field: ProfileField
    description: Optional[str] = None
    hours: Optional[HoursValue] = None
    services: Optional[list[ServiceItemInput]] = None
    # Phase 3a fields.
    website: Optional[str] = None
    labels: Optional[list[str]] = None
    special_hours: Optional[list[SpecialHoursRow]] = None
    more_hours: Optional[list[MoreHoursEntry]] = None
    service_area: Optional[ServiceAreaValue] = None
    open_info: Optional[OpenInfoValue] = None


class ProfileEditPatchRequest(BaseModel):
    """Edit an existing draft's proposed value (before applying)."""

    description: Optional[str] = None
    hours: Optional[HoursValue] = None
    services: Optional[list[ServiceItemInput]] = None
    website: Optional[str] = None
    labels: Optional[list[str]] = None
    special_hours: Optional[list[SpecialHoursRow]] = None
    more_hours: Optional[list[MoreHoursEntry]] = None
    service_area: Optional[ServiceAreaValue] = None
    open_info: Optional[OpenInfoValue] = None


class ProfileDraftRequest(BaseModel):
    """Ask the AI to draft one field (async job). Hours is never AI-drafted."""

    location_row_id: UUID
    field: Literal["description", "services"]


class ResolvePlacesRequest(BaseModel):
    """Resolve typed service-area place names → Google place ids."""

    names: list[str] = []


# ── responses ───────────────────────────────────────────────────────────────
class ProfileMetadata(BaseModel):
    has_pending_edits: bool = False
    can_modify_service_list: Optional[bool] = None
    can_operate_local_post: Optional[bool] = None
    place_id: Optional[str] = None
    maps_uri: Optional[str] = None


class GbpProfileEdit(BaseModel):
    id: UUID
    client_id: UUID
    location_row_id: UUID
    field: str
    source: str
    current_value: Optional[Any] = None
    proposed_value: Optional[Any] = None
    status: str
    google_pending: bool = False
    sync_attempts: int = 0
    next_sync_at: Optional[str] = None
    error: Optional[str] = None
    applied_at: Optional[str] = None
    created_by: Optional[UUID] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class GbpProfileResponse(BaseModel):
    """Live current values for one location + the open/recent edits for it."""

    location_row_id: UUID
    location_id: str
    title: Optional[str] = None
    description: str = ""
    hours: HoursValue
    services: list[ServiceItemInput] = []
    categories: list[Category] = []
    metadata: ProfileMetadata
    # Phase 3a — Tier A current values.
    website: str = ""
    labels: list[str] = []
    special_hours: list[SpecialHoursRow] = []
    more_hours: list[MoreHoursEntry] = []
    service_area: ServiceAreaValue = Field(default_factory=ServiceAreaValue)
    open_info: Optional[OpenInfoValue] = None
    edits: list[GbpProfileEdit] = []


class MoreHoursType(BaseModel):
    hours_type_id: str
    display_name: str


class MoreHoursTypeCategory(BaseModel):
    id: str
    name: str
    more_hours_types: list[MoreHoursType] = []


class MoreHoursTypesResponse(BaseModel):
    """The additional-hours types the operator can add, grouped by the listing's
    categories (categories.batchGet, view=FULL — the same call as service types)."""

    categories: list[MoreHoursTypeCategory] = []


class ResolvedPlace(BaseModel):
    query: str
    name: str
    place_id: str = ""
    matched: bool = False


class ResolvePlacesResponse(BaseModel):
    places: list[ResolvedPlace] = []


class GbpProfileJob(BaseModel):
    job_id: UUID


class GbpProfileJobStatus(BaseModel):
    job_id: UUID
    status: str
    edit_id: Optional[UUID] = None
    error: Optional[str] = None


class GbpProfileJobsStatusRequest(BaseModel):
    job_ids: list[UUID]


class ProfileLintResponse(BaseModel):
    """Advisory description linter — warnings only, never a gate."""

    warnings: list[dict[str, str]] = []


class GbpAuditCheck(BaseModel):
    key: str
    label: str
    ok: bool
    detail: str = ""


class GbpAuditRecommendation(BaseModel):
    key: str
    severity: str  # critical | high | medium | low
    title: str
    detail: str
    target: Optional[str] = None  # profile | dashboard | reviews


class GbpReviewGap(BaseModel):
    client: int
    competitor_median: int
    deficit: int


class GbpDescriptionQuality(BaseModel):
    ok: bool = False
    length: int = 0
    issues: list[str] = []


class GbpAuditResponse(BaseModel):
    """Profile-health audit of the live listing + competitor context."""

    access_status: Optional[str] = None  # ok | suspended | no_access
    score: Optional[int] = None
    band: Optional[str] = None           # strong | fair | needs_work
    checks: list[GbpAuditCheck] = []
    recommendations: list[GbpAuditRecommendation] = []
    category_gaps: list[str] = []
    review_gap: Optional[GbpReviewGap] = None
    description_quality: Optional[GbpDescriptionQuality] = None
    competitor_count: int = 0


class GbpChangeEvent(BaseModel):
    at: Optional[str] = None
    source: str                    # team | external
    kind: str                      # edit | outside_change | suspended | access_lost | restored
    field: Optional[str] = None
    detail: str = ""
    who: Optional[str] = None
    edit_source: Optional[str] = None  # manual | ai | strategist (team edits)
    status: Optional[str] = None


class GbpMonitorStatus(BaseModel):
    """Profile-monitor state for one location (suspension / out-of-band change
    watch). ``monitored`` is False until the first daily check establishes a
    baseline; ``enabled`` reflects the gbp_profile_monitor flag."""

    monitored: bool = False
    enabled: bool = False
    access_status: Optional[str] = None          # ok | suspended | no_access
    checked_at: Optional[str] = None
    last_change: Optional[dict[str, Any]] = None  # {fields: [...]} of the last out-of-band change
    last_change_at: Optional[str] = None

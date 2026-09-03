"""Pydantic models for Client resources."""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator


class ClientListItem(BaseModel):
    id: UUID
    name: str
    website_url: str
    website_analysis_status: str
    archived: bool
    created_at: str
    logo_url: Optional[str] = None


class WebsiteAnalysis(BaseModel):
    services: list[str] = []
    locations: list[str] = []
    contact_info: dict[str, str] = {}


class GbpReview(BaseModel):
    reviewer: str = "Anonymous"
    rating: Optional[float] = None
    text: str = ""
    date: str = ""


class GbpProfile(BaseModel):
    business_name: Optional[str] = None
    description: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    logo: Optional[str] = None
    photo: Optional[str] = None
    gbp_category: Optional[str] = None
    gbp_categories: list[str] = Field(default_factory=list)
    gbp_rating: Optional[float] = None
    gbp_review_count: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    hours: Optional[dict[str, Any]] = None
    google_maps_uri: Optional[str] = None
    reviews: list[GbpReview] = Field(default_factory=list)
    # Service-area places Google lists for a service-area business (best-effort;
    # empty when the listing doesn't publish them). Feeds target-city discovery.
    service_area_places: list[str] = Field(default_factory=list)


class PageStructureUrls(BaseModel):
    """The reference page URLs whose structure the writing modules mirror.

    Each is optional; an empty/omitted value clears that page type. Keys match
    the `clients.page_structures` JSONB shape. `product` and `solution` are
    capture-only references for ecom sites (scraped + stored, not yet consumed
    by a writer).
    """
    local_landing: Optional[str] = None
    service: Optional[str] = None
    location: Optional[str] = None
    blog_post: Optional[str] = None
    product: Optional[str] = None
    solution: Optional[str] = None


class PageStructureGuideline(BaseModel):
    """A written page-structure spec for one page type, as an alternative to a
    reference URL — for clients with no live page to scrape (no website yet, a
    rebuild, or a layout that only exists in a design/brand document).

    `text` is the spec itself. When it came from an uploaded file the frontend
    sends the parser's extracted text here too and passes `original_filename`
    for provenance (mirroring how the brand guide handles an upload).
    """
    text: str = ""
    original_filename: Optional[str] = None


class PageStructureGuidelines(BaseModel):
    """Written page-structure specs keyed by page type. An empty/omitted value
    clears that page type; a page type set here and in `page_structure_urls` is
    a conflict (one source per page type) and is rejected at the API."""
    local_landing: Optional[PageStructureGuideline] = None
    service: Optional[PageStructureGuideline] = None
    location: Optional[PageStructureGuideline] = None
    blog_post: Optional[PageStructureGuideline] = None
    product: Optional[PageStructureGuideline] = None
    solution: Optional[PageStructureGuideline] = None


class TrustBadge(BaseModel):
    """A single accreditation / affiliation / financing-partner badge — a name
    and (optionally) a logo image URL — for the Local SEO Trust & Proof block."""
    name: str = ""
    logo_url: str = ""


class TrustSignals(BaseModel):
    """Business-supplied trust facts the Local SEO writer renders deterministically
    (docs/modules/local-landing-page-structure.md). Stored on clients.trust_signals
    (JSONB). Media assets (photos/video) are the separate client_assets table."""
    certifications: list[TrustBadge] = Field(default_factory=list)
    affiliations: list[TrustBadge] = Field(default_factory=list)
    financing_partners: list[TrustBadge] = Field(default_factory=list)
    license_number: Optional[str] = None
    years_founded: Optional[int] = None
    founding_date: Optional[str] = None


class ClientAsset(BaseModel):
    """A media-gallery asset row (client_assets table)."""
    id: UUID
    kind: Literal["team_photo", "owner_photo", "vehicle", "before_after", "video_embed", "other"]
    url: str
    caption: Optional[str] = None
    sort_order: int = 0


class ClientAssetCreateRequest(BaseModel):
    kind: Literal["team_photo", "owner_photo", "vehicle", "before_after", "video_embed", "other"]
    url: str = Field(..., min_length=1)
    caption: Optional[str] = None
    sort_order: int = 0


class ClientDetail(BaseModel):
    id: UUID
    name: str
    website_url: str
    website_analysis: Optional[dict[str, Any]] = None
    website_analysis_status: str
    website_analysis_error: Optional[str] = None
    brand_guide_source_type: str
    brand_guide_text: str
    brand_guide_original_filename: Optional[str] = None
    icp_source_type: str
    icp_text: str
    icp_original_filename: Optional[str] = None
    archived: bool
    created_at: str
    updated_at: str
    google_drive_folder_id: Optional[str] = None
    # Per-content-type Drive folders (content_type slug → folder ID). The
    # type-specific folder wins; google_drive_folder_id is the fallback.
    drive_folders: dict[str, str] = Field(default_factory=dict)
    # Publish-target scaffold (#3): GitHub repo the Fanout/Blog content can be
    # committed to (resolved per-client when publishing). Wired, used later.
    github_repo: Optional[str] = None
    github_branch: Optional[str] = None
    github_content_path: Optional[str] = None
    # Per-content-type repo content paths (content_type slug → path). The
    # type-specific path wins; github_content_path is the single fallback.
    github_content_paths: dict[str, str] = Field(default_factory=dict)
    # Inferred conventions of the client's EXISTING site (system-populated by the
    # pattern discovery job); SOP "site always wins" — read at publish time.
    # Nested dict, so NOT run through the flat {str:str} folder sanitizer.
    github_inferred_patterns: dict[str, Any] = Field(default_factory=dict)
    # WordPress direct-publish target (#3). The site URL + username are safe to
    # surface; the Application Password is a secret and is NEVER returned — only
    # `wordpress_app_password_set` indicates whether one is stored.
    wordpress_site_url: Optional[str] = None
    wordpress_username: Optional[str] = None
    wordpress_app_password_set: bool = False
    # Per-client gate for the WheelHouse IT location/service page poster module.
    wheelhouse_cpt_enabled: bool = False
    logo_url: Optional[str] = None
    gsc_property: Optional[str] = None
    business_location: Optional[str] = None
    gbp_place_id: Optional[str] = None
    gbp: Optional[GbpProfile] = None
    local_seo_page_template_url: Optional[str] = None
    # Reference page structures the writing modules mirror (#page-structures).
    # JSONB keyed by page type: {local_landing|service|location|blog_post|product|solution:
    #   {url, status, error, analysis, analyzed_at}}.
    page_structures: dict[str, Any] = Field(default_factory=dict)
    # Cities the team explicitly wants location pages for, beyond the primary —
    # one source feeding the silo planner's target-city discovery.
    target_cities: list[str] = Field(default_factory=list)
    # Recipe Engine budget inputs (docs/sops/Link_Building_Recipe_Engine.md §1–§2).
    retainer_monthly: Optional[float] = None
    is_sab: bool = False
    illustrate_content: bool = False
    client_type: Literal["local", "enterprise"] = "local"
    # Content-compliance guardrail (services/content_compliance.py): 'off' for
    # normal clients; 'peptide' for regulated (research-chemical) vendors, which
    # blocks human-dosing / branded-equivalence / guaranteed-results / advocacy
    # content at every publish choke point.
    content_compliance_mode: Literal["off", "peptide"] = "off"
    # Per-client strategist review day (0=Mon..6=Sun). None → the global
    # `strategist_weekly_weekday` default, so reviews can be staggered across
    # the week instead of all landing on one day.
    strategist_weekday: Optional[int] = None
    # Slack channel PACE posts this client's PM notifications to (channel id like
    # C0... or #name). None → the single master PACE channel.
    slack_channel_id: Optional[str] = None
    # Everhour project this client's time is logged against (opaque id like
    # "ev:123"/"as:123", not numeric). None → not yet onboarded to Everhour.
    everhour_project_id: Optional[str] = None
    # Trust & Proof facts the Local SEO writer renders deterministically
    # (docs/modules/local-landing-page-structure.md). Media assets are the
    # separate client_assets table, surfaced via the assets endpoints.
    trust_signals: Optional[TrustSignals] = None

    @field_validator("drive_folders", "github_content_paths", mode="before")
    @classmethod
    def _sanitize_drive_folders(cls, v: Any) -> dict[str, str]:
        """Coerce the stored JSONB into a clean {str: str} map so a malformed or
        legacy value (null, non-dict, non-string/blank entries) can't 500 a GET.
        Drops empty/whitespace entries; stringifies keys and values."""
        if not isinstance(v, dict):
            return {}
        return {
            str(k): str(val).strip()
            for k, val in v.items()
            if val is not None and str(val).strip()
        }

    @field_validator("trust_signals", mode="before")
    @classmethod
    def _sanitize_trust_signals(cls, v: Any) -> Optional[dict]:
        """Coerce a malformed/legacy stored value into a shape TrustSignals
        accepts so a bad row can't 500 a GET (the write path validates at the
        request model, so this only ever repairs reads). A non-dict → None
        (unset); each badge list is normalised to [{name, logo_url}] (a bare
        string or partial dict is repaired, junk dropped); years_founded → int
        or None. Mirrors the drive_folders sanitizer's defensive intent."""
        if not isinstance(v, dict):
            return None

        def _badges(x: Any) -> list[dict]:
            out: list[dict] = []
            if isinstance(x, list):
                for it in x:
                    if isinstance(it, str) and it.strip():
                        out.append({"name": it.strip(), "logo_url": ""})
                    elif isinstance(it, dict):
                        name = str(it.get("name") or "").strip()
                        logo = str(it.get("logo_url") or it.get("logo") or "").strip()
                        if name or logo:
                            out.append({"name": name, "logo_url": logo})
            return out

        years = v.get("years_founded")
        try:
            years = int(years) if years not in (None, "") else None
        except (TypeError, ValueError):
            years = None
        return {
            "certifications": _badges(v.get("certifications")),
            "affiliations": _badges(v.get("affiliations")),
            "financing_partners": _badges(v.get("financing_partners")),
            "license_number": (str(v.get("license_number")).strip() or None) if v.get("license_number") else None,
            "years_founded": years,
            "founding_date": (str(v.get("founding_date")).strip() or None) if v.get("founding_date") else None,
        }


class ClientCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    # Empty = no website yet (a pre-client market pick from LeadOff). Every
    # website consumer already truthiness-guards, and setting a real URL later
    # via update re-enqueues the scrape.
    website_url: str = ""
    brand_guide_source_type: Literal["text", "file"]
    brand_guide_text: str = ""
    brand_guide_file_id: Optional[UUID] = None
    icp_source_type: Literal["text", "file"]
    icp_text: str = ""
    icp_file_id: Optional[UUID] = None
    google_drive_folder_id: Optional[str] = None
    drive_folders: Optional[dict[str, str]] = None
    # Publish-target scaffold (#3): GitHub repo the Fanout/Blog content can be
    # committed to (resolved per-client when publishing). Wired, used later.
    github_repo: Optional[str] = None
    github_branch: Optional[str] = None
    github_content_path: Optional[str] = None
    # Per-content-type repo content paths (content_type slug → path).
    github_content_paths: Optional[dict[str, str]] = None
    # WordPress direct-publish target (#3). app_password is write-only.
    wordpress_site_url: Optional[str] = None
    wordpress_username: Optional[str] = None
    wordpress_app_password: Optional[str] = None
    # Per-client gate for the WheelHouse IT page poster (admin-toggled).
    wheelhouse_cpt_enabled: Optional[bool] = None
    logo_url: Optional[str] = None
    gsc_property: Optional[str] = None
    business_location: Optional[str] = None
    gbp_place_id: Optional[str] = None
    gbp: Optional[GbpProfile] = None
    target_cities: Optional[list[str]] = None
    # Recipe Engine budget inputs.
    retainer_monthly: Optional[float] = None
    is_sab: Optional[bool] = None
    illustrate_content: Optional[bool] = None
    client_type: Optional[Literal["local", "enterprise"]] = None
    content_compliance_mode: Optional[Literal["off", "peptide"]] = None
    # Per-client strategist review day (0=Mon..6=Sun); None → global default.
    strategist_weekday: Optional[int] = Field(None, ge=0, le=6)
    # Slack channel PACE posts this client's PM notifications to; None → master.
    slack_channel_id: Optional[str] = None
    # Everhour project this client's time is logged against; None → unmapped.
    everhour_project_id: Optional[str] = None
    # Trust & Proof facts (docs/modules/local-landing-page-structure.md).
    trust_signals: Optional[TrustSignals] = None
    # Reference page URLs to scrape + analyze for structure mirroring.
    page_structure_urls: Optional[PageStructureUrls] = None
    # Written page-structure specs — the no-website alternative to the URLs above.
    page_structure_guidelines: Optional[PageStructureGuidelines] = None


class ClientUpdateRequest(BaseModel):
    page_structure_urls: Optional[PageStructureUrls] = None
    page_structure_guidelines: Optional[PageStructureGuidelines] = None
    target_cities: Optional[list[str]] = None
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    website_url: Optional[str] = None
    brand_guide_source_type: Optional[Literal["text", "file"]] = None
    brand_guide_text: Optional[str] = None
    brand_guide_file_id: Optional[UUID] = None
    icp_source_type: Optional[Literal["text", "file"]] = None
    icp_text: Optional[str] = None
    icp_file_id: Optional[UUID] = None
    google_drive_folder_id: Optional[str] = None
    drive_folders: Optional[dict[str, str]] = None
    # Publish-target scaffold (#3): GitHub repo the Fanout/Blog content can be
    # committed to (resolved per-client when publishing). Wired, used later.
    github_repo: Optional[str] = None
    github_branch: Optional[str] = None
    github_content_path: Optional[str] = None
    # Per-content-type repo content paths (content_type slug → path).
    github_content_paths: Optional[dict[str, str]] = None
    # WordPress direct-publish target (#3). app_password is write-only; pass an
    # empty string to clear a stored password, or omit the field to leave it.
    wordpress_site_url: Optional[str] = None
    wordpress_username: Optional[str] = None
    wordpress_app_password: Optional[str] = None
    # Per-client gate for the WheelHouse IT page poster (admin-toggled).
    wheelhouse_cpt_enabled: Optional[bool] = None
    logo_url: Optional[str] = None
    gsc_property: Optional[str] = None
    business_location: Optional[str] = None
    gbp_place_id: Optional[str] = None
    gbp: Optional[GbpProfile] = None
    # Recipe Engine budget inputs.
    retainer_monthly: Optional[float] = None
    is_sab: Optional[bool] = None
    illustrate_content: Optional[bool] = None
    client_type: Optional[Literal["local", "enterprise"]] = None
    content_compliance_mode: Optional[Literal["off", "peptide"]] = None
    # Per-client strategist review day (0=Mon..6=Sun); None → global default.
    strategist_weekday: Optional[int] = Field(None, ge=0, le=6)
    # Slack channel PACE posts this client's PM notifications to; pass an empty
    # string to clear it back to the master PACE channel.
    slack_channel_id: Optional[str] = None
    # Everhour project this client's time is logged against; pass an empty string
    # to clear the mapping.
    everhour_project_id: Optional[str] = None
    # Trust & Proof facts (docs/modules/local-landing-page-structure.md). Send the
    # full object to replace what's stored; omit to leave unchanged.
    trust_signals: Optional[TrustSignals] = None

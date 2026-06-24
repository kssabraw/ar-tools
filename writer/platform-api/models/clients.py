"""Pydantic models for Client resources."""

from __future__ import annotations

from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


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


class PageStructureUrls(BaseModel):
    """The four reference page URLs whose structure the writing modules mirror.

    Each is optional; an empty/omitted value clears that page type. Keys match
    the `clients.page_structures` JSONB shape.
    """
    local_landing: Optional[str] = None
    service: Optional[str] = None
    location: Optional[str] = None
    blog_post: Optional[str] = None


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
    # Publish-target scaffold (#3): GitHub repo the Fanout/Blog content can be
    # committed to (resolved per-client when publishing). Wired, used later.
    github_repo: Optional[str] = None
    github_branch: Optional[str] = None
    github_content_path: Optional[str] = None
    logo_url: Optional[str] = None
    gsc_property: Optional[str] = None
    business_location: Optional[str] = None
    gbp_place_id: Optional[str] = None
    gbp: Optional[GbpProfile] = None
    local_seo_page_template_url: Optional[str] = None
    # Reference page structures the writing modules mirror (#page-structures).
    # JSONB keyed by page type: {local_landing|service|location|blog_post:
    #   {url, status, error, analysis, analyzed_at}}.
    page_structures: dict[str, Any] = Field(default_factory=dict)


class ClientCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    website_url: str = Field(..., min_length=1)
    brand_guide_source_type: Literal["text", "file"]
    brand_guide_text: str = ""
    brand_guide_file_id: Optional[UUID] = None
    icp_source_type: Literal["text", "file"]
    icp_text: str = ""
    icp_file_id: Optional[UUID] = None
    google_drive_folder_id: Optional[str] = None
    # Publish-target scaffold (#3): GitHub repo the Fanout/Blog content can be
    # committed to (resolved per-client when publishing). Wired, used later.
    github_repo: Optional[str] = None
    github_branch: Optional[str] = None
    github_content_path: Optional[str] = None
    logo_url: Optional[str] = None
    gsc_property: Optional[str] = None
    business_location: Optional[str] = None
    gbp_place_id: Optional[str] = None
    gbp: Optional[GbpProfile] = None
    # Reference page URLs to scrape + analyze for structure mirroring.
    page_structure_urls: Optional[PageStructureUrls] = None


class ClientUpdateRequest(BaseModel):
    page_structure_urls: Optional[PageStructureUrls] = None
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    website_url: Optional[str] = None
    brand_guide_source_type: Optional[Literal["text", "file"]] = None
    brand_guide_text: Optional[str] = None
    brand_guide_file_id: Optional[UUID] = None
    icp_source_type: Optional[Literal["text", "file"]] = None
    icp_text: Optional[str] = None
    icp_file_id: Optional[UUID] = None
    google_drive_folder_id: Optional[str] = None
    # Publish-target scaffold (#3): GitHub repo the Fanout/Blog content can be
    # committed to (resolved per-client when publishing). Wired, used later.
    github_repo: Optional[str] = None
    github_branch: Optional[str] = None
    github_content_path: Optional[str] = None
    logo_url: Optional[str] = None
    gsc_property: Optional[str] = None
    business_location: Optional[str] = None
    gbp_place_id: Optional[str] = None
    gbp: Optional[GbpProfile] = None

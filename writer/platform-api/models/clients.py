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


class WebsiteAnalysis(BaseModel):
    services: list[str] = []
    locations: list[str] = []
    contact_info: dict[str, str] = {}


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


class ClientCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    website_url: str = Field(..., min_length=1)
    brand_guide_source_type: Literal["text", "file"]
    brand_guide_text: str = ""
    brand_guide_file_id: Optional[UUID] = None
    icp_source_type: Literal["text", "file"]
    icp_text: str = ""
    icp_file_id: Optional[UUID] = None


class ClientUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    website_url: Optional[str] = None
    brand_guide_source_type: Optional[Literal["text", "file"]] = None
    brand_guide_text: Optional[str] = None
    brand_guide_file_id: Optional[UUID] = None
    icp_source_type: Optional[Literal["text", "file"]] = None
    icp_text: Optional[str] = None
    icp_file_id: Optional[UUID] = None

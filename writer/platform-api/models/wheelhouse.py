"""Pydantic request/response models for the WheelHouse IT page poster."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


PageType = Literal["service", "city"]


class WheelhouseMassRequest(BaseModel):
    """Mass Create. For page_type='city' the items are CITIES (one city page each,
    `city` ignored); for page_type='service' the items are SERVICES under `city`."""
    page_type: PageType = "service"
    state: str
    city: str = ""
    items: list[str] = Field(default_factory=list)


class WheelhouseMassJob(BaseModel):
    job_ids: list[str]


class WheelhouseGenerateJobResult(BaseModel):
    status: str
    page_id: Optional[str] = None
    error: Optional[str] = None


class WheelhouseJobStatus(BaseModel):
    job_id: str
    status: str
    page_id: Optional[str] = None
    error: Optional[str] = None


class WheelhouseJobsStatusRequest(BaseModel):
    job_ids: list[str] = Field(default_factory=list)


class WheelhouseGenerateOneRequest(BaseModel):
    """One-off: generate all missing fields for a single page; any `supplied`
    fields are kept verbatim. `persist=False` returns the fields WITHOUT creating a
    Saved row (the form's live 'Draft all' preview). For page_type='city' the
    service is fixed and may be omitted."""
    page_type: PageType = "service"
    state: str
    city: str
    service: str = ""
    supplied: Optional[dict] = None
    persist: bool = True


class WheelhouseOneOffSaveRequest(BaseModel):
    """Save a fully user-authored/edited ACF object as a draft (no generation)."""
    page_type: PageType = "service"
    state: str
    city: str
    service: str = ""
    acf: dict = Field(default_factory=dict)


class WheelhouseDraftFieldRequest(BaseModel):
    """Per-field 'Draft with AI' in the one-off form."""
    page_type: PageType = "service"
    state: str
    city: str
    service: str = ""
    field_name: str


class WheelhouseDraftFieldResult(BaseModel):
    field_name: str
    value: str


class WheelhousePublishRequest(BaseModel):
    status: Literal["draft", "publish"] = "draft"

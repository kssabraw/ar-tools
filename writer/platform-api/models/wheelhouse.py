"""Pydantic request/response models for the WheelHouse IT page poster."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class WheelhouseMassRequest(BaseModel):
    """Mass Create: one city + a list of services → one leaf page per city×service."""
    state: str
    city: str
    services: list[str] = Field(default_factory=list)


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
    """One-off: generate all missing fields for a single city×service; any
    `supplied` fields are kept verbatim. `persist=False` returns the fields
    WITHOUT creating a Saved row (the form's live 'Draft all' preview)."""
    state: str
    city: str
    service: str
    supplied: Optional[dict] = None
    persist: bool = True


class WheelhouseOneOffSaveRequest(BaseModel):
    """Save a fully user-authored/edited ACF object as a draft (no generation)."""
    state: str
    city: str
    service: str
    acf: dict = Field(default_factory=dict)


class WheelhouseDraftFieldRequest(BaseModel):
    """Per-field 'Draft with AI' in the one-off form."""
    state: str
    city: str
    service: str
    field_name: str


class WheelhouseDraftFieldResult(BaseModel):
    field_name: str
    value: str


class WheelhousePublishRequest(BaseModel):
    status: Literal["draft", "publish"] = "draft"

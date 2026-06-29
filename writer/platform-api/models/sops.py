"""Pydantic schemas for the SOP / playbook store."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class Sop(BaseModel):
    id: UUID
    client_id: Optional[UUID] = None     # null = agency-wide
    title: str
    content: str
    category: str = "general"
    source: str = "paste"
    enabled: bool = True
    created_at: str
    updated_at: Optional[str] = None


class SopCreateRequest(BaseModel):
    title: str
    content: str
    category: str = "general"
    source: str = "paste"


class SopUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    enabled: Optional[bool] = None

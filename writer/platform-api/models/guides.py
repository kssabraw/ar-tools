"""Pydantic schemas for the in-app Guides portal."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class Guide(BaseModel):
    id: UUID
    slug: str
    title: str
    category: str = "Setup"
    icon: str = "BookOpen"
    summary: str = ""
    body: str = ""
    sort_order: int = 0
    enabled: bool = True
    created_at: str
    updated_at: Optional[str] = None


class GuideCreateRequest(BaseModel):
    slug: str
    title: str
    body: str = ""
    summary: str = ""
    category: str = "Setup"
    icon: str = "BookOpen"
    sort_order: int = 0


class GuideUpdateRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    enabled: Optional[bool] = None

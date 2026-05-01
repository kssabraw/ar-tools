"""Pydantic models for file upload."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    file_id: UUID
    original_filename: str
    parsed_text: str
    truncated: bool
    format: str  # "json" | "markdown" | "text"

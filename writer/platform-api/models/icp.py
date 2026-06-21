"""Pydantic models for the ICP Creator module (client-level, converged).

detected_icp is the canonical client asset (Option A): a structured blob on
`clients`, authored by the app (`/scan`) or the user (`PUT`). Differentiators
are generated alongside it. User-authored content (source:"user") supersedes —
an auto-scan won't overwrite a structured ICP unless `force=True`.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class IcpScanRequest(BaseModel):
    """Trigger an app ICP analysis. Business identity (name / website /
    categories) is pulled server-side from the client record."""

    force: bool = Field(
        default=False,
        description="Re-analyze even when the stored ICP is user-authored "
        "structured content (source == 'user' with segments).",
    )


class IcpUpdateRequest(BaseModel):
    """Manually author / edit the ICP. Any provided field is merged into the
    stored blob; the result is marked source:'user' (supersede)."""

    raw_text: Optional[str] = Field(
        default=None,
        description="Freeform ICP write-up. Rendered verbatim into the Blog "
        "Writer snapshot; takes precedence over structured segments.",
    )
    segments: Optional[list[dict[str, Any]]] = Field(
        default=None, description="Structured ICP segments (see detected_icp.segments)."
    )
    reasoning: Optional[str] = None
    differentiators: Optional[list[dict[str, Any]]] = Field(
        default=None, description="Differentiators [ { claim, mechanism, type } ]."
    )


class IcpResponse(BaseModel):
    detected_icp: Optional[dict[str, Any]] = None
    differentiators: Optional[list[dict[str, Any]]] = None
    pages_crawled: Optional[int] = Field(
        default=None, description="Pages discovered on the last scan."
    )
    analysis_status: Optional[str] = Field(
        default=None, description="'complete' (pages found) or 'partial'."
    )

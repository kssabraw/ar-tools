"""Pydantic models for the Brand Voice module (client-level, converged).

Brand voice is a single client-level asset (Option A): a structured
`brand_voice` JSONB on `clients`, authored either by the app (`/scan`) or by
the user (`PUT`). User-authored content has `source: "user"` and supersedes —
an auto-scan won't overwrite it unless `force=True`.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class BrandVoiceScanRequest(BaseModel):
    """Trigger an app brand-voice analysis for a client.

    Business identity (name / website / category) is pulled server-side from
    the client record, so the body only carries the overwrite guard.
    """

    force: bool = Field(
        default=False,
        description="Re-scan even when the stored voice is user-authored "
        "(source == 'user'). Without this, a user-authored voice is preserved.",
    )


class BrandVoiceUpdateRequest(BaseModel):
    """Manually author / edit the brand voice. Any provided field is merged into
    the stored blob; the result is marked `source: "user"` (supersede)."""

    raw_text: Optional[str] = Field(
        default=None,
        description="Freeform brand guide passthrough. Rendered verbatim into "
        "the Blog Writer run snapshot; takes precedence over structured fields.",
    )
    current_voice: Optional[dict[str, Any]] = Field(
        default=None, description="Structured VoiceProfile to use as the active voice."
    )
    recommended_accepted: Optional[bool] = Field(
        default=None,
        description="Accept (true) / reject (false) the app's recommended voice.",
    )


class BrandVoiceResponse(BaseModel):
    """The stored brand_voice blob for a client (null until first authored)."""

    brand_voice: Optional[dict[str, Any]] = None
    pages_sampled: Optional[int] = Field(
        default=None, description="Pages that produced usable text on the last scan."
    )


class BrandVoiceScanJob(BaseModel):
    """Handle for a backgrounded brand-voice scan (enqueued async job). The scan
    runs server-side, so the UI can navigate away; poll `.../scan/{job_id}` and
    refetch the voice on completion."""

    job_id: str
    status: str


class BrandVoiceScanJobStatus(BaseModel):
    """Poll result for a backgrounded brand-voice scan."""

    status: str  # pending | running | complete | failed
    error: Optional[str] = None

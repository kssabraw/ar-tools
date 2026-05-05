"""Briefs router — cache status lookup for the run-create UX.

Frontend calls this before submitting a run so it can prompt the user:
"a cached brief exists from N days ago — reuse, or regenerate?" The
answer maps to `RunCreateRequest.brief_force_refresh`.

Brief cache is keyed on `(keyword, location_code)` and is shared across
clients (PRD §2 — the brief is client-agnostic). TTL is the
pipeline-api's `brief_cache_ttl_days` setting (7 days by default).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter()


# Mirror of pipeline-api's brief_cache_ttl_days. Hardcoded here to
# avoid a cross-service config import; if the pipeline-api ever
# diverges, update both. The actual cache write enforces the same TTL
# on the pipeline-api side, so this is purely the dashboard's view of
# what counts as "fresh enough to offer reuse."
BRIEF_CACHE_TTL_DAYS = 7


class BriefCacheStatusResponse(BaseModel):
    """Response shape for `GET /briefs/cache-status`.

    `exists=True` only when a row inside the TTL window is present. The
    frontend should ALSO trust the response when `exists=False` — that
    means the next run will regenerate either way and no prompt is
    needed.
    """

    exists: bool
    cached_at: Optional[str] = None
    age_days: Optional[float] = None
    schema_version: Optional[str] = None


def _normalize_keyword(keyword: str) -> str:
    """Mirror the pipeline-api cache key normalization (lower + strip)
    so dashboard lookups match what was actually stored."""
    return keyword.strip().lower()


@router.get("/briefs/cache-status", response_model=BriefCacheStatusResponse)
async def cache_status(
    keyword: str = Query(..., min_length=1, max_length=150),
    location_code: int = Query(2840, ge=1),
    auth: dict = Depends(require_auth),
) -> BriefCacheStatusResponse:
    """Return whether a fresh cached brief exists for (keyword, location_code).

    Used by the frontend's "Run brief" / "Rerun" UX to prompt the user
    when they're about to silently get a cached result. The user can
    then choose to set `brief_force_refresh=true` on the run create
    request to regenerate.
    """
    supabase = get_supabase()
    threshold = datetime.now(timezone.utc) - timedelta(days=BRIEF_CACHE_TTL_DAYS)

    result = (
        supabase.table("briefs_cache")
        .select("created_at, schema_version")
        .eq("keyword", _normalize_keyword(keyword))
        .eq("location_code", location_code)
        .gte("created_at", threshold.isoformat())
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    rows = result.data or []
    if not rows:
        return BriefCacheStatusResponse(exists=False)

    row = rows[0]
    created_at_str = row.get("created_at")
    age_days: Optional[float] = None
    if isinstance(created_at_str, str):
        try:
            created_at = datetime.fromisoformat(
                created_at_str.replace("Z", "+00:00")
            )
            age_days = round(
                (datetime.now(timezone.utc) - created_at).total_seconds() / 86400.0,
                2,
            )
        except ValueError:
            age_days = None

    return BriefCacheStatusResponse(
        exists=True,
        cached_at=created_at_str,
        age_days=age_days,
        schema_version=row.get("schema_version"),
    )

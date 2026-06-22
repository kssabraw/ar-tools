"""Cache for the expensive SERP analysis (DataForSEO + ScrapeOwl + TextRazor).

The analysis depends only on (keyword, location), not the client, so a cached
`AnalysisResponse` is shared across all clients. Entries older than the configured
TTL are treated as misses and overwritten on the next compute. The platform-api
service-role key bypasses RLS, so this internal cache is never client-readable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_TABLE = "keyword_analyses"


def _norm(text: str) -> str:
    """Collapse whitespace + lowercase, for stable cache keys."""
    return " ".join((text or "").split()).lower()


def cache_key(keyword: str, location_code: Optional[int], location_name: str) -> str:
    """Shared key: prefer the canonical DataForSEO location_code, else the name."""
    loc = str(location_code) if location_code else _norm(location_name)
    return f"{_norm(keyword)}::{loc}"


def get(keyword: str, location_code: Optional[int], location_name: str) -> Optional[dict]:
    """Return the cached analysis dict if a fresh entry exists, else None."""
    if settings.analysis_cache_ttl_days <= 0:
        return None
    key = cache_key(keyword, location_code, location_name)
    try:
        res = (
            get_supabase()
            .table(_TABLE)
            .select("analysis, created_at")
            .eq("cache_key", key)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # cache is best-effort — never block on a read error
        logger.warning("analysis_cache.read_failed", extra={"error": str(exc)})
        return None

    rows = res.data or []
    if not rows:
        return None
    created = _parse_ts(rows[0].get("created_at"))
    if created is None:
        return None
    age = datetime.now(timezone.utc) - created
    if age > timedelta(days=settings.analysis_cache_ttl_days):
        logger.info("analysis_cache.stale", extra={"cache_key": key, "age_days": age.days})
        return None
    logger.info("analysis_cache.hit", extra={"cache_key": key, "age_days": age.days})
    analysis = rows[0].get("analysis")
    if isinstance(analysis, dict):
        # Served from cache → this request incurred no provider cost. Mark it and
        # zero the cost subtotal so the UI/cost tracking doesn't double-count the
        # original (already-paid) scrape.
        analysis = {**analysis, "from_cache": True, "analysis_cost": {"cached": True, "subtotal": 0.0}}
    return analysis


def store(keyword: str, location_code: Optional[int], location_name: str, analysis: dict) -> None:
    """Upsert the analysis under the shared key (refreshes created_at)."""
    if settings.analysis_cache_ttl_days <= 0:
        return
    key = cache_key(keyword, location_code, location_name)
    row = {
        "cache_key": key,
        "keyword": _norm(keyword),
        "location_code": location_code,
        "location_name": location_name,
        "analysis": analysis,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        get_supabase().table(_TABLE).upsert(row, on_conflict="cache_key").execute()
        logger.info("analysis_cache.store", extra={"cache_key": key})
    except Exception as exc:  # never fail the request because caching failed
        logger.warning("analysis_cache.write_failed", extra={"error": str(exc)})


def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

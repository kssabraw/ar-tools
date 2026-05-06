"""Brief Generator 7-day Supabase cache (PRD §2 - client-agnostic).

Lookup is keyed on (keyword, location_code). The freshest row inside the
TTL window wins. Writes are append-only - historical rows survive so we
can compare runs across threshold-tuning iterations.

Per PRD §2 the brief is client-agnostic: two clients running the same
keyword share the cached output. `triggered_by_client_id` is captured
on write for audit only and never enters the cache key.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def _normalize_keyword(keyword: str) -> str:
    """Lowercase + strip - keeps the cache key resilient to surface variation."""
    return keyword.strip().lower()


async def get_cached(
    keyword: str,
    location_code: int,
) -> Optional[dict]:
    """Return cached output_payload dict if a fresh row exists, else None.

    "Fresh" means created_at within `settings.brief_cache_ttl_days` of now.
    Errors during lookup degrade silently - the pipeline will simply
    regenerate the brief.
    """
    threshold = datetime.now(timezone.utc) - timedelta(days=settings.brief_cache_ttl_days)

    def _query():
        client = get_supabase()
        return (
            client.table("briefs_cache")
            .select("output_payload, created_at")
            .eq("keyword", _normalize_keyword(keyword))
            .eq("location_code", location_code)
            .gte("created_at", threshold.isoformat())
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

    try:
        result = await asyncio.to_thread(_query)
    except Exception as exc:
        logger.warning(
            "brief.cache.lookup_failed",
            extra={"keyword": keyword, "error": str(exc)},
        )
        return None

    rows = result.data or []
    if not rows:
        logger.info(
            "brief.cache.miss",
            extra={"keyword": keyword, "location_code": location_code},
        )
        return None
    payload = rows[0].get("output_payload")
    if not isinstance(payload, dict):
        return None
    logger.info(
        "brief.cache.hit",
        extra={
            "keyword": keyword,
            "location_code": location_code,
            "cached_at": rows[0].get("created_at"),
        },
    )
    return payload


async def write_cache(
    *,
    keyword: str,
    location_code: int,
    schema_version: str,
    output_payload: dict,
    triggered_by_client_id: Optional[str] = None,
    cost_usd: Optional[float] = None,
    duration_ms: Optional[int] = None,
) -> None:
    """Append a row to briefs_cache. Errors are logged but not raised.

    The orchestrator passes `triggered_by_client_id` for audit; leave None
    when the run came from an internal admin task without a client context.
    """
    row: dict = {
        "keyword": _normalize_keyword(keyword),
        "location_code": location_code,
        "schema_version": schema_version,
        "output_payload": output_payload,
    }
    if triggered_by_client_id is not None:
        row["triggered_by_client_id"] = triggered_by_client_id
    if cost_usd is not None:
        row["cost_usd"] = cost_usd
    if duration_ms is not None:
        row["duration_ms"] = duration_ms

    def _insert():
        client = get_supabase()
        return client.table("briefs_cache").insert(row).execute()

    try:
        await asyncio.to_thread(_insert)
    except Exception as exc:
        logger.warning(
            "brief.cache.write_failed",
            extra={"keyword": keyword, "error": str(exc)},
        )

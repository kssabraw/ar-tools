"""SIE Supabase 7-day cache.

Lookup is keyed on (keyword, location_code, outlier_mode). The freshest row
within the TTL window wins. Writes are append-only — historical rows are
preserved for trend analysis (per SIE PRD §6 Output Storage).
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
    return keyword.strip().lower()


async def get_cached(
    keyword: str,
    location_code: int,
    outlier_mode: str,
) -> Optional[dict]:
    """Return cached output_payload dict if a fresh row exists, else None."""
    threshold = datetime.now(timezone.utc) - timedelta(days=settings.sie_cache_ttl_days)

    def _query():
        client = get_supabase()
        return (
            client.table("sie_cache")
            .select("output_payload, created_at")
            .eq("keyword", _normalize_keyword(keyword))
            .eq("location_code", location_code)
            .eq("outlier_mode", outlier_mode)
            .gte("created_at", threshold.isoformat())
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

    try:
        result = await asyncio.to_thread(_query)
    except Exception as exc:
        logger.warning("sie_cache lookup failed: %s", exc)
        return None

    rows = result.data or []
    if not rows:
        return None
    payload = rows[0].get("output_payload")
    if not isinstance(payload, dict):
        return None
    payload["cache_date"] = rows[0].get("created_at")
    return payload


async def write_cache(
    keyword: str,
    location_code: int,
    outlier_mode: str,
    schema_version: str,
    output_payload: dict,
    cost_usd: Optional[float] = None,
    duration_ms: Optional[int] = None,
) -> None:
    """Append a fresh row to sie_cache. Errors are logged but not raised."""
    row = {
        "keyword": _normalize_keyword(keyword),
        "location_code": location_code,
        "outlier_mode": outlier_mode,
        "schema_version": schema_version,
        "output_payload": output_payload,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
    }

    def _insert():
        client = get_supabase()
        return client.table("sie_cache").insert(row).execute()

    try:
        await asyncio.to_thread(_insert)
    except Exception as exc:
        logger.warning("sie_cache write failed: %s", exc)

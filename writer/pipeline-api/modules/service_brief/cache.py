"""Service Page Brief research cache (PRD §7).

Caches the **research_bundle** (not the final brief) keyed on
`(keyword, location_code)` with a TTL. The research bundle is client-agnostic
— competitor SERPs for a service don't move much week-to-week — while synthesis
stays per-client, so two clients targeting the same query share the cached
research but still get differentiated briefs. A repeat run within the TTL does
not re-fetch the SERP (PRD §8.6).

Mirrors `modules/brief/cache.py`: append-only writes, freshest-row-wins lookup,
schema_version embedded in the payload, and silent degradation on DB errors so
a cache miss/failure just regenerates the research.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_TABLE = "service_brief_cache"


def _normalize_keyword(keyword: str, page_type: str = "service") -> str:
    """Lowercase + strip — keeps the cache key resilient to surface variation.

    Location pages namespace the key (`location::<anchor>`) so a multi-service
    location hub never collides with a single-service page that happens to share
    the anchor query; service pages keep the bare keyword for backward compat
    with existing cache rows.
    """
    norm = keyword.strip().lower()
    return f"location::{norm}" if page_type == "location" else norm


async def get_cached(
    keyword: str, location_code: int, page_type: str = "service"
) -> Optional[dict]:
    """Return the cached research_bundle payload if a fresh row exists, else None."""
    threshold = datetime.now(timezone.utc) - timedelta(
        days=settings.service_brief_cache_ttl_days
    )

    def _query():
        client = get_supabase()
        return (
            client.table(_TABLE)
            .select("output_payload, created_at")
            .eq("keyword", _normalize_keyword(keyword, page_type))
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
            "service_brief.cache.lookup_failed",
            extra={"keyword": keyword, "error": str(exc)},
        )
        return None

    rows = result.data or []
    if not rows:
        logger.info(
            "service_brief.cache.miss",
            extra={"keyword": keyword, "location_code": location_code},
        )
        return None
    payload = rows[0].get("output_payload")
    if not isinstance(payload, dict):
        return None
    logger.info(
        "service_brief.cache.hit",
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
    page_type: str = "service",
    cost_usd: Optional[float] = None,
    duration_ms: Optional[int] = None,
) -> None:
    """Append a research_bundle row. Errors are logged but never raised.

    Only the always-present columns are written unconditionally; optional
    columns are skipped when None so the insert still succeeds if a later
    migration hasn't been applied. `schema_version` is also embedded inside
    `output_payload` by the caller for the same robustness reason.
    """
    row: dict = {
        "keyword": _normalize_keyword(keyword, page_type),
        "location_code": location_code,
        "schema_version": schema_version,
        "output_payload": output_payload,
    }
    if cost_usd is not None:
        row["cost_usd"] = cost_usd
    if duration_ms is not None:
        row["duration_ms"] = duration_ms

    def _insert():
        client = get_supabase()
        return client.table(_TABLE).insert(row).execute()

    try:
        await asyncio.to_thread(_insert)
    except Exception as exc:
        logger.warning(
            "service_brief.cache.write_failed",
            extra={"keyword": keyword, "error": str(exc)},
        )

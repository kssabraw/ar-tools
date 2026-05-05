"""SIE Supabase 7-day cache.

Lookup is keyed on (keyword, location_code, outlier_mode). The freshest row
within the TTL window wins. Writes are append-only — historical rows are
preserved for trend analysis (per SIE PRD §6 Output Storage).

Defensive against DB schema drift: the cache deliberately operates on a
minimal column set (keyword, location_code, outlier_mode, output_payload,
created_at). Schema-version validation happens IN PYTHON against the
payload's own `schema_version` field so that adding/removing the
optional `schema_version` / `cost_usd` / `duration_ms` columns at the
DB layer doesn't break reads or writes. Older deploys had those columns
in their migration but never applied them in production — keeping the
code resilient avoids hard failures when DB and code versions drift.
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
    schema_version: Optional[str] = None,
) -> Optional[dict]:
    """Return cached output_payload dict if a fresh row exists, else None.

    `schema_version` is validated against the payload's own
    `schema_version` field (which lives inside output_payload) AFTER
    fetch, rather than via a SQL filter on a `schema_version` column.
    This makes the lookup robust against DB column drift — the live
    `sie_cache` table may or may not carry that column depending on
    whether the migration was applied. Stale-shape rows still get
    treated as misses and trigger a rebuild.
    """
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

    # Schema-version gate — payload-level so DB column presence is
    # irrelevant. Older payloads with a different schema_version fail
    # Pydantic Literal validation downstream; treat them as misses.
    if schema_version:
        payload_version = payload.get("schema_version")
        if payload_version and payload_version != schema_version:
            logger.info(
                "sie_cache.schema_version_mismatch_skipped",
                extra={
                    "expected": schema_version,
                    "found": payload_version,
                },
            )
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
    """Append a fresh row to sie_cache. Errors are logged but not raised.

    Writes only the columns guaranteed to exist (keyword, location_code,
    outlier_mode, output_payload). The optional `schema_version`,
    `cost_usd`, `duration_ms` columns aren't included in the INSERT
    because they may not be present on every deploy's `sie_cache`
    table — the migration that adds them hasn't necessarily been
    applied. Schema_version is preserved INSIDE output_payload (every
    SIEResponse carries it) so retrieval-time validation still works.
    `cost_usd` and `duration_ms` are diagnostics-only and acceptable
    to drop here.
    """
    # `schema_version` and `cost_usd`/`duration_ms` are intentionally
    # NOT in this dict — see docstring.
    row = {
        "keyword": _normalize_keyword(keyword),
        "location_code": location_code,
        "outlier_mode": outlier_mode,
        "output_payload": output_payload,
    }

    def _insert():
        client = get_supabase()
        return client.table("sie_cache").insert(row).execute()

    try:
        await asyncio.to_thread(_insert)
    except Exception as exc:
        logger.warning("sie_cache write failed: %s", exc)

"""SIE 7-day cache (`fanout.keyword_analyses`). Cross-session by keyword+location;
the pipeline lookup runs as the service role (bypasses RLS), so reuse never depends
on the RLS policy (which only gates direct report reads)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fanout.storage.supabase_client import get_service_client

MAX_AGE_DAYS = 7


def get_fresh_analysis(
    keyword: str, location_code: int, *, max_age_days: int = MAX_AGE_DAYS
) -> dict | None:
    """Latest `keyword_analyses` row for (keyword, location) with run_date within
    `max_age_days`, else None (cache miss / stale)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    res = (
        get_service_client()
        .table("keyword_analyses")
        .select("*")
        .eq("keyword", keyword)
        .eq("location_code", location_code)
        .gte("run_date", cutoff)
        .order("run_date", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def save_analysis(
    *, keyword: str, location_code: int, language_code: str, outlier_mode: str,
    output_json: dict, cost_usd: float | None, session_id: str | None,
    cluster_id: str | None,
) -> dict:
    """Insert a new analysis row (history is never overwritten; a `force_refresh`
    just writes another row that becomes the freshest)."""
    res = (
        get_service_client()
        .table("keyword_analyses")
        .insert({
            "keyword": keyword, "location_code": location_code,
            "language_code": language_code, "outlier_mode": outlier_mode,
            "output_json": output_json, "cost_usd": cost_usd,
            "session_id": session_id, "cluster_id": cluster_id,
        })
        .execute()
    )
    return res.data[0]

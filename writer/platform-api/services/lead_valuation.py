"""Lead valuation engine — headless (no UI surface).

The volume × CPC × visibility-gap valuation originally built for the AI
Visibility tracker: for each tracked brand keyword, what the AI answers the
brand does NOT appear in would cost per month in equivalent paid clicks. The
dashboard card and the client-report "Monthly Growth Opportunity" section were
removed 2026-07-10 (owner request) — the ENGINE is deliberately kept here,
UI-less, for a future tool to consume.

Pure pieces (`keyword_visibility_stats`, `build_lead_valuation`) are unit-
tested with no I/O; `compute_lead_valuation` is the impure assembler that reads
brand_mention_history + the shared keyword_market cache (cache-only — the paid
DataForSEO fill runs as the shared `keyword_market` async job with
scope='brand', auto-enqueued when keywords are missing/stale).

Visibility stats honor `feature_present` — a Google AI answer that never fired
is not a miss, matching the tracker's scoring.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_DAYS = 30


# ── pure ─────────────────────────────────────────────────────────────────────
def keyword_visibility_stats(rows: list[dict], keyword_labels: dict[str, str]) -> list[dict]:
    """Fold completed brand-mention rows into per-keyword {keyword, scans,
    mentions}. Excludes cells where the Google AI feature didn't fire
    (feature_present is False) — same semantics as the visibility score. Pure."""
    stats: dict[str, dict] = {}
    for r in rows:
        if r.get("status") != "completed":
            continue
        if r.get("feature_present") is False:
            continue
        label = keyword_labels.get(r.get("keyword_id"))
        if not label:
            continue
        s = stats.setdefault(label, {"keyword": label, "scans": 0, "mentions": 0})
        s["scans"] += 1
        if r.get("mention_found"):
            s["mentions"] += 1
    return sorted(stats.values(), key=lambda s: s["keyword"])


def build_lead_valuation(keyword_stats: list[dict], market_by_kw: dict[str, dict]) -> Optional[dict]:
    """Per keyword: volume x CPC x visibility gap (share of scanned cells where
    the brand wasn't found). None when no keyword has market data. Pure."""
    rows = []
    for k in keyword_stats:
        m = market_by_kw.get(k["keyword"].lower()) or {}
        vol, cpc = m.get("search_volume"), m.get("cpc")
        if vol is None or cpc is None or not k["scans"]:
            continue
        gap = 1 - k["mentions"] / k["scans"]
        rows.append({"keyword": k["keyword"], "volume": vol, "cpc": float(cpc), "gap": gap,
                     "cost": float(vol) * float(cpc) * gap})
    if not rows:
        return None
    total = sum(r["cost"] for r in rows)
    return {
        "total": round(total),
        "avg_cpc": round(sum(r["cpc"] for r in rows) / len(rows), 2),
        "monthly_searches": sum(r["volume"] for r in rows),
        "gap_pct": round(100 * sum(r["gap"] for r in rows) / len(rows)),
        "rows": sorted(rows, key=lambda r: -r["cost"]),
    }


# ── impure assembler ─────────────────────────────────────────────────────────
def compute_lead_valuation(
    client_id: str, *, days: int = _DEFAULT_WINDOW_DAYS, auto_refresh_market: bool = True,
) -> dict:
    """Assemble the valuation for a client over the trailing `days` window.

    Returns {valuation, keyword_count, window_days, market_refreshing}.
    `valuation` is None when there are no scans or no market data yet.
    Cache-only market read; when keywords are missing/stale (and DataForSEO is
    configured) the shared scope='brand' fill job is enqueued best-effort and
    `market_refreshing` is True — call again once it lands."""
    from services.dataforseo_rank import location_code_for
    from services.keyword_market import (
        enqueue_keyword_market, fetch_cached_market, market_job_pending, stale_keywords,
    )

    supabase = get_supabase()
    client_res = (
        supabase.table("clients").select("id, website_url, gbp, rank_tracking_location_code")
        .eq("id", client_id).limit(1).execute()
    ).data
    if not client_res:
        raise ValueError("client_not_found")
    location_code = location_code_for(client_res[0])

    keywords = (
        supabase.table("brand_tracked_keywords")
        .select("id, keyword")
        .eq("client_id", client_id).eq("is_active", True).execute()
    ).data or []
    labels = {k["id"]: k["keyword"] for k in keywords}
    kw_list = [k["keyword"] for k in keywords]
    if not kw_list:
        return {"valuation": None, "keyword_count": 0, "window_days": days, "market_refreshing": False}

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = (
        supabase.table("brand_mention_history")
        .select("keyword_id, status, mention_found, feature_present")
        .eq("client_id", client_id)
        .eq("is_competitor_scan", False)
        .eq("status", "completed")
        .gte("created_at", since)
        .limit(20000)
        .execute()
    ).data or []
    stats = keyword_visibility_stats(rows, labels)

    cached = fetch_cached_market(supabase, kw_list, location_code)
    refreshing = False
    if auto_refresh_market and settings.dataforseo_login and settings.dataforseo_password:
        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.keyword_market_refresh_days)
        try:
            if stale_keywords(kw_list, cached, stale_cutoff) and not market_job_pending(supabase, client_id, "brand"):
                enqueue_keyword_market(client_id, scope="brand")
                refreshing = True
            else:
                refreshing = market_job_pending(supabase, client_id, "brand")
        except Exception as exc:  # noqa: BLE001 — fill is best-effort
            logger.warning("lead_valuation_market_enqueue_failed", extra={"error": str(exc)})

    return {
        "valuation": build_lead_valuation(stats, cached),
        "keyword_count": len(kw_list),
        "window_days": days,
        "market_refreshing": refreshing,
    }

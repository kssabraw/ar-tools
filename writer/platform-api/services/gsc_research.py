"""GSC Research — on-demand opportunity analysis off ingested GSC data.

Ported from the "GSC Research" n8n workflow. One run does a LIVE Search Console
pull (query×page dimensions over a lookback window, like the n8n flow's
"last 3 months") for the client's verified property and produces three
opportunity sets:

  1. Keyword cannibalization — a query split across >1 URL where every URL
     ranks well (≤ pos 30) AND their impressions are clustered (within 50% of
     each other). That clustering is the tell: Google is alternating between
     competing pages instead of favoring one.
  2. Quick wins — query×page sitting at position 6–10. A small push lands it
     on page 1.
  3. Hidden wins — query×page at position 11–30. Real demand stuck on page 2–3.

All three bands share a minimum-impressions floor (`_MIN_IMPRESSIONS`) over the
LOOKBACK_DAYS window so the long tail of near-zero-impression queries doesn't
drown out real opportunities on large properties.

Quick/hidden wins are enriched with DataForSEO market data (CPC / search volume
/ competition) by reusing the keyword_market service + its cross-client cache.

The analysis helpers are pure (no I/O) so they're unit-tested directly. The
job runner pulls data, computes, enriches, and writes the run row.

Position bands encode the source workflow's heuristics; see the constants below.
Note the small gap at position (10, 11] between the quick- and hidden-win bands
— replicated from the source workflow intentionally for fidelity.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from db.supabase_client import get_supabase
from services import gsc_service, keyword_market, rank_materialize
from services.dataforseo_rank import location_code_for

logger = logging.getLogger(__name__)

# Lookback window analyzed (the n8n flow used GSC's "last 3 months").
LOOKBACK_DAYS = 90

# Cannibalization thresholds.
_RANK_HIGH_MAX = 30.0          # every competing URL must rank at/above this
_IMPRESSIONS_CLOSE_RATIO = 0.5  # (max-min)/max ≤ this → impressions "clustered"

# Quick-win band: position in (5, 10].
_QUICK_MIN_EXCL = 5.0
_QUICK_MAX_INCL = 10.0

# Hidden-win band: position in (11, 30].
_HIDDEN_MIN_EXCL = 11.0
_HIDDEN_MAX_INCL = 30.0

# Shared impressions floor across all three bands: a query must have pulled at
# least this many impressions over the LOOKBACK_DAYS window to surface as an
# opportunity — per query×page for quick/hidden wins, and the query's total
# across its competing pages for cannibalization. Filters out the long tail of
# 1–2 impression flukes that otherwise dominate large properties.
_MIN_IMPRESSIONS = 500

# Cap on keywords sent to DataForSEO per run (cost guard); the top opportunities
# by impressions are enriched first.
_MARKET_KEYWORD_CAP = 200


# ----------------------------------------------------------------------------
# Pure aggregation + analysis (no I/O) — unit-tested directly.
# ----------------------------------------------------------------------------
def aggregate_query_pages(rows: list[dict]) -> list[dict]:
    """Collapse dated query×page rows into one row per (query, page).

    Sums clicks + impressions and computes the impression-weighted average
    position (matching GSC's single-period totals). Input rows are
    gsc_query_page_daily records: {query, page, clicks, impressions, position}.
    """
    by_key: dict[tuple[str, str], dict] = {}
    for row in rows:
        query = str(row.get("query") or "")
        page = str(row.get("page") or "")
        if not query or not page:
            continue
        key = (query, page)
        agg = by_key.setdefault(
            key, {"query": query, "page": page, "clicks": 0, "impressions": 0, "_pos_num": 0.0, "_pos_den": 0}
        )
        clicks = int(row.get("clicks") or 0)
        impressions = int(row.get("impressions") or 0)
        agg["clicks"] += clicks
        agg["impressions"] += impressions
        pos = row.get("position")
        if pos is not None and impressions:
            agg["_pos_num"] += float(pos) * impressions
            agg["_pos_den"] += impressions

    out = []
    for agg in by_key.values():
        position = round(agg["_pos_num"] / agg["_pos_den"], 1) if agg["_pos_den"] else None
        out.append(
            {
                "query": agg["query"],
                "page": agg["page"],
                "clicks": agg["clicks"],
                "impressions": agg["impressions"],
                "position": position,
            }
        )
    return out


def find_cannibalization(aggregated: list[dict]) -> list[dict]:
    """Queries split across >1 URL, all ranking ≤30, impressions clustered.

    Returns CannibalizationRow-shaped dicts ordered by total impressions desc.
    """
    by_query: dict[str, list[dict]] = defaultdict(list)
    for row in aggregated:
        by_query[row["query"]].append(row)

    out = []
    for query, pages in by_query.items():
        if len(pages) <= 1:
            continue

        # Every competing URL must rank well. A missing position (no
        # impression-weighted rank) fails the test.
        all_high = all(p["position"] is not None and p["position"] <= _RANK_HIGH_MAX for p in pages)
        if not all_high:
            continue

        impressions = [p["impressions"] for p in pages]
        max_impr, min_impr = max(impressions), min(impressions)
        if max_impr <= 0:
            continue
        impressions_close = (max_impr - min_impr) / max_impr <= _IMPRESSIONS_CLOSE_RATIO
        if not impressions_close:
            continue

        # Impressions floor: the query (summed across its competing pages) must
        # clear _MIN_IMPRESSIONS over the window.
        total_impressions = sum(p["impressions"] for p in pages)
        if total_impressions < _MIN_IMPRESSIONS:
            continue

        ordered_pages = sorted(pages, key=lambda p: p["impressions"], reverse=True)
        out.append(
            {
                "query": query,
                "page_count": len(pages),
                "total_clicks": sum(p["clicks"] for p in pages),
                "total_impressions": total_impressions,
                "pages": [
                    {
                        "page": p["page"],
                        "clicks": p["clicks"],
                        "impressions": p["impressions"],
                        "position": p["position"],
                    }
                    for p in ordered_pages
                ],
            }
        )
    out.sort(key=lambda r: r["total_impressions"], reverse=True)
    return out


def _opportunity_row(agg: dict) -> dict:
    return {
        "keyword": agg["query"],
        "page": agg["page"],
        "position": agg["position"],
        "impressions": agg["impressions"],
        "clicks": agg["clicks"],
        "search_volume": None,
        "cpc": None,
        "competition": None,
    }


def find_quick_wins(aggregated: list[dict]) -> list[dict]:
    """query×page rows at position (5, 10] with ≥_MIN_IMPRESSIONS, by impressions desc."""
    out = [
        _opportunity_row(a)
        for a in aggregated
        if a["position"] is not None
        and _QUICK_MIN_EXCL < a["position"] <= _QUICK_MAX_INCL
        and a["impressions"] >= _MIN_IMPRESSIONS
    ]
    out.sort(key=lambda r: r["impressions"], reverse=True)
    return out


def find_hidden_wins(aggregated: list[dict]) -> list[dict]:
    """query×page rows at position (11, 30] with ≥_MIN_IMPRESSIONS, by impressions desc."""
    out = [
        _opportunity_row(a)
        for a in aggregated
        if a["position"] is not None
        and _HIDDEN_MIN_EXCL < a["position"] <= _HIDDEN_MAX_INCL
        and a["impressions"] >= _MIN_IMPRESSIONS
    ]
    out.sort(key=lambda r: r["impressions"], reverse=True)
    return out


def enrich_with_market(rows: list[dict], market: dict[str, dict]) -> None:
    """Attach cpc / search_volume / competition to opportunity rows in place,
    matching on lowercased keyword."""
    for row in rows:
        m = market.get(row["keyword"].lower())
        if not m:
            continue
        row["search_volume"] = m.get("search_volume")
        row["cpc"] = m.get("cpc")
        row["competition"] = m.get("competition")


# ----------------------------------------------------------------------------
# Data access
# ----------------------------------------------------------------------------
def parse_live_page_rows(raw: list[dict]) -> list[dict]:
    """Map raw GSC query×page rows (keys = [query, page], no date dimension —
    already aggregated for the period) to analysis rows."""
    out = []
    for row in raw or []:
        keys = row.get("keys") or []
        if len(keys) < 2 or not keys[0] or not keys[1]:
            continue
        out.append(
            {
                "query": keys[0],
                "page": keys[1],
                "clicks": int(row.get("clicks") or 0),
                "impressions": int(row.get("impressions") or 0),
                "position": row.get("position"),
            }
        )
    return out


def _fetch_live_page_rows(site_url: str, date_from: date, date_to: date) -> list[dict]:
    """Live Search Console pull of query×page rows for a property + window.

    Blocking (googleapiclient) — run via asyncio.to_thread from the async job so
    it doesn't stall the event loop. Raises on API error (e.g. 403) so the caller
    can fail the run with a real cause.
    """
    raw = gsc_service.fetch_search_analytics(
        site_url, ["query", "page"], date_from.isoformat(), date_to.isoformat()
    )
    return parse_live_page_rows(raw)


async def _fetch_market_for(supabase, keywords: list[str], location_code: int) -> dict[str, dict]:
    """Cached-first market data for keywords; fetches + caches any misses."""
    if not keywords:
        return {}
    cached = keyword_market.fetch_cached_market(supabase, keywords, location_code)
    missing = [kw for kw in keywords if kw.lower() not in cached]
    if missing:
        try:
            fetched = await keyword_market.fetch_market(missing, location_code)
        except Exception as exc:
            logger.warning("gsc_research.market_failed", extra={"error": str(exc)})
            fetched = {}
        if fetched:
            from datetime import datetime, timezone

            now_iso = datetime.now(timezone.utc).isoformat()
            records = [
                {
                    "keyword": kw,
                    "location_code": location_code,
                    "search_volume": fetched.get(kw.lower(), {}).get("search_volume"),
                    "cpc": fetched.get(kw.lower(), {}).get("cpc"),
                    "competition": fetched.get(kw.lower(), {}).get("competition"),
                    "monthly_searches": fetched.get(kw.lower(), {}).get("monthly_searches"),
                    "refreshed_at": now_iso,
                }
                for kw in missing
                if kw.lower() in fetched
            ]
            if records:
                supabase.table("keyword_market").upsert(
                    records, on_conflict="keyword,location_code"
                ).execute()
            for kw in missing:
                m = fetched.get(kw.lower())
                if m:
                    cached[kw.lower()] = m
    return cached


def is_gsc_research_due(last_run_date: Optional[date], today: date, interval_days: int) -> bool:
    """Whether a scheduled GSC Research run is due: never run before (first-entry),
    or the last completed run is at least `interval_days` old (monthly). Pure."""
    if last_run_date is None:
        return True
    return (today.toordinal() - last_run_date.toordinal()) >= interval_days


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def enqueue_gsc_research(client_id: str, trigger: str = "manual") -> Optional[str]:
    """Create a pending run + enqueue its job. Returns the run id, or None if a
    run is already in flight for this client (dedupe)."""
    supabase = get_supabase()
    in_flight = (
        supabase.table("gsc_research_runs")
        .select("id")
        .eq("client_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    ).data
    if in_flight:
        return in_flight[0]["id"]

    run = (
        supabase.table("gsc_research_runs")
        .insert({"client_id": client_id, "status": "pending", "trigger": trigger})
        .execute()
    ).data[0]
    run_id = run["id"]
    supabase.table("async_jobs").insert(
        {"job_type": "gsc_research", "entity_id": client_id, "payload": {"run_id": run_id, "client_id": client_id}}
    ).execute()
    return run_id


async def run_gsc_research_job(job: dict) -> None:
    payload = job.get("payload") or {}
    run_id = payload.get("run_id")
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()

    if not run_id or not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing run_id/client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    supabase.table("gsc_research_runs").update({"status": "running"}).eq("id", run_id).execute()

    try:
        result = await _compute_research(supabase, client_id)
        supabase.table("gsc_research_runs").update(
            {
                "status": "complete",
                "gsc_connected": result["gsc_connected"],
                "date_from": result["date_from"],
                "date_to": result["date_to"],
                "cannibalization": result["cannibalization"],
                "quick_wins": result["quick_wins"],
                "hidden_wins": result["hidden_wins"],
                "cannibalization_count": len(result["cannibalization"]),
                "quick_wins_count": len(result["quick_wins"]),
                "hidden_wins_count": len(result["hidden_wins"]),
                "error": None,
                "completed_at": "now()",
            }
        ).eq("id", run_id).execute()
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"run_id": run_id}, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info(
            "gsc_research_complete",
            extra={
                "run_id": run_id,
                "client_id": client_id,
                "cannibalization": len(result["cannibalization"]),
                "quick_wins": len(result["quick_wins"]),
                "hidden_wins": len(result["hidden_wins"]),
            },
        )
    except Exception as exc:
        logger.warning("gsc_research_failed", extra={"run_id": run_id, "client_id": client_id, "error": str(exc)})
        supabase.table("gsc_research_runs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", run_id).execute()
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()


async def _compute_research(supabase, client_id: str) -> dict:
    """Pull data, run the three analyses, enrich. Pure-ish orchestration —
    returns a dict ready to persist to the run row."""
    today = date.today()
    date_from = today - timedelta(days=LOOKBACK_DAYS)
    empty = {
        "gsc_connected": False,
        "date_from": date_from.isoformat(),
        "date_to": today.isoformat(),
        "cannibalization": [],
        "quick_wins": [],
        "hidden_wins": [],
    }

    # Live GSC fetch needs both a verified property AND the agency service-account
    # key. Missing either → complete with gsc_connected=false + empty results (the
    # UI shows a "connect Search Console" state rather than erroring).
    property = rank_materialize._verified_property(supabase, client_id)
    if not property or not gsc_service.is_configured():
        return empty

    rows = await asyncio.to_thread(_fetch_live_page_rows, property["site_url"], date_from, today)
    aggregated = aggregate_query_pages(rows)

    cannibalization = find_cannibalization(aggregated)
    quick_wins = find_quick_wins(aggregated)
    hidden_wins = find_hidden_wins(aggregated)

    # Enrich the opportunity rows with market data (top-by-impressions first,
    # under the per-run cap). Both bands share the cache lookup.
    client = (
        supabase.table("clients").select("id, website_url, gbp, rank_tracking_location_code")
        .eq("id", client_id).limit(1).execute()
    ).data
    location_code = location_code_for(client[0]) if client else 2840
    unique_keywords: list[str] = []
    seen: set[str] = set()
    for row in quick_wins + hidden_wins:
        kw = row["keyword"]
        if kw.lower() in seen:
            continue
        seen.add(kw.lower())
        unique_keywords.append(kw)
        if len(unique_keywords) >= _MARKET_KEYWORD_CAP:
            break
    market = await _fetch_market_for(supabase, unique_keywords, location_code)
    enrich_with_market(quick_wins, market)
    enrich_with_market(hidden_wins, market)

    return {
        "gsc_connected": True,
        "date_from": date_from.isoformat(),
        "date_to": today.isoformat(),
        "cannibalization": cannibalization,
        "quick_wins": quick_wins,
        "hidden_wins": hidden_wins,
    }

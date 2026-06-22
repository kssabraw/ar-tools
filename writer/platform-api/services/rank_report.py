"""Scheduled rank reports — snapshot builder, schedule logic, archive.

Organic Rank Tracker (Module #4). Builds a point-in-time report snapshot (the
same numbers the live Overview/Keywords views show) and stores it in
``rank_reports`` so the team has a dated, printable archive. The shared
scheduler enqueues a ``rank_report`` job when a client's schedule is due.

See docs/modules/organic-rank-tracker-prd-v1_0.md.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import dataforseo_rank, keyword_market, rank_status

logger = logging.getLogger(__name__)

_READ_DAYS = 95


# ----------------------------------------------------------------------------
# Schedule due-logic (pure) — unit-tested.
# ----------------------------------------------------------------------------
def is_report_due(config: dict, today: date) -> bool:
    """Whether a client's scheduled report should generate today.

    `config` is a rank_report_config row. 'as_needed' never auto-generates.
    Never generates twice on the same day.
    """
    mode = config.get("mode", "as_needed")
    if mode == "as_needed":
        return False

    last_raw = config.get("last_generated_at")
    last_date = date.fromisoformat(last_raw[:10]) if last_raw else None
    if last_date == today:
        return False

    if mode == "weekly":
        return today.weekday() == (config.get("day_of_week") or 0)
    if mode == "monthly":
        dom = config.get("day_of_month") or 1
        last_day = calendar.monthrange(today.year, today.month)[1]
        return today.day == min(dom, last_day)  # clamp e.g. 31 → month end
    if mode == "interval":
        n = config.get("interval_days") or 7
        return last_date is None or (today.toordinal() - last_date.toordinal()) >= n
    return False


# ----------------------------------------------------------------------------
# Snapshot builder
# ----------------------------------------------------------------------------
def build_report_snapshot(supabase, client_id: str, today: Optional[date] = None) -> Optional[dict]:
    """Assemble the full report data (overview + per-keyword) for a client."""
    today = today or date.today()
    client_res = supabase.table("clients").select(
        "id, name, logo_url, website_url, gbp, rank_tracking_location, rank_tracking_location_code"
    ).eq("id", client_id).limit(1).execute()
    if not client_res.data:
        return None
    client = client_res.data[0]

    gsc_connected = bool(
        supabase.table("gsc_properties").select("id")
        .eq("client_id", client_id).eq("access_status", "ok").limit(1).execute().data
    )
    location_code = dataforseo_rank.location_code_for(client)

    kw_rows = (
        supabase.table("tracked_keywords").select("*")
        .eq("client_id", client_id).eq("active", True).order("keyword").execute()
    ).data or []

    cutoff = date.fromordinal(today.toordinal() - _READ_DAYS).isoformat()
    metric_rows = (
        supabase.table("rank_keyword_metrics")
        .select("keyword_id, date, clicks, impressions, ctr, gsc_position, tracked_rank")
        .in_("keyword_id", [k["id"] for k in kw_rows]).gte("date", cutoff).execute()
    ).data or [] if kw_rows else []
    by_keyword: dict[str, list[dict]] = {}
    for r in metric_rows:
        by_keyword.setdefault(r["keyword_id"], []).append(r)

    market = keyword_market.fetch_cached_market(supabase, [k["keyword"] for k in kw_rows], location_code)

    keywords: list[dict] = []
    for k in kw_rows:
        s = rank_status.compute_keyword_summary(
            by_keyword.get(k["id"], []), today, settings.rank_gsc_coverage_days
        )
        m = market.get(k["keyword"].lower(), {})
        position = s["today_rank"] if s["primary_source"] == "dataforseo" else s["avg_30"]
        keywords.append({
            "id": k["id"],
            "keyword": k["keyword"],
            "status": k["status"],
            "cpc": m.get("cpc"),
            "search_volume": m.get("search_volume"),
            "est_monthly_value": keyword_market.estimate_monthly_value(
                m.get("search_volume"), position, m.get("cpc")
            ),
            **s,
        })

    all_rows = [r for group in by_keyword.values() for r in group]
    status_counts: dict[str, int] = {}
    for k in kw_rows:
        status_counts[k["status"]] = status_counts.get(k["status"], 0) + 1
    overview = {
        "keyword_count": len(kw_rows),
        "gsc_connected": gsc_connected,
        "status_counts": status_counts,
        "clicks_30d": rank_status._window_sum(all_rows, 30, today, "clicks"),
        "impressions_30d": rank_status._window_sum(all_rows, 30, today, "impressions"),
        "avg_position_30d": rank_status.rolling_average(
            [(r["date"], r.get("gsc_position")) for r in all_rows], 30, today
        ),
        "at_risk": status_counts.get("deindex_risk", 0) + status_counts.get("dropping", 0),
        "hero": rank_status.aggregate_hero(all_rows, today, 90),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "client": {"name": client.get("name"), "logo_url": client.get("logo_url")},
        "location": client.get("rank_tracking_location"),
        "gsc_connected": gsc_connected,
        "overview": overview,
        "keywords": keywords,
    }


def generate_and_store(supabase, client_id: str, today: Optional[date] = None, created_by: Optional[str] = None) -> Optional[dict]:
    """Build a snapshot, store it in the archive, and stamp last_generated_at."""
    today = today or date.today()
    snapshot = build_report_snapshot(supabase, client_id, today)
    if snapshot is None:
        return None
    title = f"Organic Rankings — {today.strftime('%b %d, %Y')}"
    inserted = supabase.table("rank_reports").insert(
        {"client_id": client_id, "title": title, "snapshot": snapshot, "created_by": created_by}
    ).execute()

    now_iso = datetime.now(timezone.utc).isoformat()
    supabase.table("rank_report_config").upsert(
        {"client_id": client_id, "last_generated_at": now_iso, "updated_at": now_iso},
        on_conflict="client_id",
    ).execute()
    return inserted.data[0] if inserted.data else None


def enqueue_rank_report(client_id: str) -> None:
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "rank_report").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "rank_report", "entity_id": client_id, "payload": {"client_id": client_id}}
    ).execute()


async def run_rank_report_job(job: dict) -> None:
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    try:
        report = generate_and_store(supabase, client_id)
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"report_id": report["id"] if report else None}, "completed_at": "now()"}
        ).eq("id", job_id).execute()
    except Exception as exc:
        logger.error("rank_report_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

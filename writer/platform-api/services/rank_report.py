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

import httpx

from config import settings
from db.supabase_client import get_supabase
from services import dataforseo_rank, keyword_market, rank_status

logger = logging.getLogger(__name__)

_READ_DAYS = 95

_STATUS_LABELS = {
    "climbing": "Climbing", "stable": "Stable", "volatile": "Volatile",
    "dropping": "Dropping", "deindex_risk": "At risk", "no_data": "No data yet",
}
_STATUS_ORDER = ["deindex_risk", "dropping", "volatile", "climbing", "stable", "no_data"]


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


def _fmt_pos(v) -> str:
    return f"{v:.1f}" if isinstance(v, (int, float)) else "—"


def _best_position(k: dict):
    return k.get("today_rank") if k.get("primary_source") == "dataforseo" else k.get("avg_30")


def render_report_markdown(snapshot: dict) -> str:
    """Render a report snapshot to Markdown for the Google-Doc publish webhook."""
    client = (snapshot.get("client") or {}).get("name") or "Client"
    ov = snapshot.get("overview") or {}
    gsc = bool(snapshot.get("gsc_connected"))
    kws = snapshot.get("keywords") or []
    when = (snapshot.get("generated_at") or "")[:10]
    loc = snapshot.get("location")

    total_value = round(sum(k.get("est_monthly_value") or 0 for k in kws))
    lines: list[str] = [f"# Organic Rankings Report — {client}", ""]
    meta = f"{when} · {'Search Console + DataForSEO' if gsc else 'DataForSEO'}"
    if loc:
        meta += f" · {loc}"
    lines += [f"_{meta}_", "", "## Summary", ""]
    lines.append(f"- **Keywords tracked:** {ov.get('keyword_count', 0):,}")
    lines.append(f"- **At risk:** {ov.get('at_risk', 0):,}")
    if gsc:
        lines.append(f"- **Avg. position (30d):** {_fmt_pos(ov.get('avg_position_30d'))}")
        lines.append(f"- **Clicks (30d):** {ov.get('clicks_30d', 0):,}")
        lines.append(f"- **Impressions (30d):** {ov.get('impressions_30d', 0):,}")
    lines.append(f"- **Estimated monthly value:** ${total_value:,}")
    lines.append("")

    counts = ov.get("status_counts") or {}
    rollup = " · ".join(f"{_STATUS_LABELS.get(s, s)} {counts[s]}" for s in _STATUS_ORDER if counts.get(s))
    if rollup:
        lines += [f"**Status:** {rollup}", ""]

    by_value = sorted([k for k in kws if k.get("est_monthly_value")], key=lambda k: k["est_monthly_value"], reverse=True)[:10]
    if by_value:
        lines += ["## Top opportunities by estimated value", "",
                  "| Keyword | Best position | Volume | CPC | Est. value |",
                  "|---|---|---|---|---|"]
        for k in by_value:
            vol = f"{k['search_volume']:,}" if k.get("search_volume") is not None else "—"
            cpc = f"${k['cpc']:.2f}" if k.get("cpc") is not None else "—"
            lines.append(f"| {k['keyword']} | {_fmt_pos(_best_position(k))} | {vol} | {cpc} | ${round(k['est_monthly_value']):,} |")
        lines.append("")

    improving = [k for k in kws if k.get("direction") == "up" or k.get("status") == "climbing"][:8]
    declining = sorted([k for k in kws if k.get("status") in ("dropping", "deindex_risk") or k.get("direction") == "down"],
                       key=lambda k: _STATUS_ORDER.index(k.get("status", "no_data")))[:8]
    if improving:
        lines += ["## Improving", ""] + [f"- {k['keyword']} ({_STATUS_LABELS.get(k['status'], k['status'])})" for k in improving] + [""]
    if declining:
        lines += ["## Needs attention", ""] + [f"- {k['keyword']} ({_STATUS_LABELS.get(k['status'], k['status'])})" for k in declining] + [""]

    lines += ["## All tracked keywords", ""]
    if gsc:
        lines += ["| Keyword | Status | Today | 30d | 90d | Clicks |", "|---|---|---|---|---|---|"]
    else:
        lines += ["| Keyword | Status | Today |", "|---|---|---|"]
    for k in sorted(kws, key=lambda k: _STATUS_ORDER.index(k.get("status", "no_data"))):
        label = _STATUS_LABELS.get(k.get("status"), k.get("status"))
        today_rank = k.get("today_rank") if k.get("today_rank") is not None else "—"
        if gsc:
            lines.append(f"| {k['keyword']} | {label} | {today_rank} | {_fmt_pos(k.get('avg_30'))} | {_fmt_pos(k.get('avg_90'))} | {k.get('clicks_30d', 0):,} |")
        else:
            lines.append(f"| {k['keyword']} | {label} | {today_rank} |")
    return "\n".join(lines)


async def publish_report_doc(supabase, report: dict) -> dict:
    """Publish an archived report as a Google Doc in the client's Drive folder."""
    if not settings.google_apps_script_url:
        raise RuntimeError("publish_not_configured")
    client_res = (
        supabase.table("clients").select("name, google_drive_folder_id")
        .eq("id", report["client_id"]).single().execute()
    )
    folder_id = (client_res.data or {}).get("google_drive_folder_id")
    if not folder_id:
        raise RuntimeError("missing_google_drive_folder_id")

    markdown = render_report_markdown(report["snapshot"])
    body = {"folder_id": folder_id, "title": report["title"], "content": markdown}
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
        resp = await http.post(settings.google_apps_script_url, json=body)
        resp.raise_for_status()
        result = resp.json()
    if not result.get("success"):
        raise RuntimeError(f"apps_script_error: {result.get('error', 'unknown')}")

    doc_id, doc_url = result.get("doc_id"), result.get("doc_url")
    supabase.table("rank_reports").update(
        {"doc_id": doc_id, "doc_url": doc_url, "delivered_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", report["id"]).execute()
    return {"doc_id": doc_id, "doc_url": doc_url}


def deliver_enabled(supabase, client_id: str) -> bool:
    cfg = supabase.table("rank_report_config").select("deliver_google_doc").eq("client_id", client_id).limit(1).execute()
    return bool(cfg.data and cfg.data[0].get("deliver_google_doc"))


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
        # Auto-deliver to Google Doc when the client opted in (best-effort).
        if report and deliver_enabled(supabase, client_id):
            try:
                await publish_report_doc(supabase, report)
            except Exception as exc:
                logger.warning("rank_report_delivery_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "complete", "result": {"report_id": report["id"] if report else None}, "completed_at": "now()"}
        ).eq("id", job_id).execute()
    except Exception as exc:
        logger.error("rank_report_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

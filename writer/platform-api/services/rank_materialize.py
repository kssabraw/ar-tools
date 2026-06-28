"""Materialize the per-keyword-per-day date axis + recompute status/source.

Organic Rank Tracker (Module #4). Reads the raw GSC query×date dump
(gsc_query_daily) for the client's verified property — if any — and writes one
rank_keyword_metrics row per active keyword per day over a trailing window,
leaving gsc_position NULL on days GSC returned nothing (the stored gap). Then
recomputes each keyword's status + source, blending in DataForSEO tracked_rank
that the weekly fallback job wrote (without ever overwriting it).

Keywords are CLIENT-anchored (GSC property optional), so this runs per client.
Runs as a `gsc_materialize` job (chained after ingest / DataForSEO refresh, and
on keyword add) and on demand. See PRD §2, §6, §7.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import rank_alerts, rank_status

logger = logging.getLogger(__name__)


@dataclass
class MaterializeResult:
    status: str  # 'ok' | 'failed'
    keywords: int
    rows: int
    error: Optional[str] = None


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def date_range(start: date, end: date) -> list[date]:
    if end < start:
        return []
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def index_gsc_rows(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Index raw gsc_query_daily rows by (lowercased query, date iso)."""
    index: dict[tuple[str, str], dict] = {}
    for row in rows:
        index[(str(row["query"]).lower(), str(row["date"]))] = row
    return index


def build_keyword_axis(
    keyword_id: str,
    keyword: str,
    dates: list[date],
    gsc_index: dict[tuple[str, str], dict],
) -> list[dict]:
    """One rank_keyword_metrics record per date; absent days carry NULL position.

    tracked_rank is intentionally omitted so the upsert never clobbers the
    DataForSEO value (different job, different column — PRD §5).
    """
    kw = keyword.lower()
    records: list[dict] = []
    for d in dates:
        hit = gsc_index.get((kw, d.isoformat()))
        records.append(
            {
                "keyword_id": keyword_id,
                "date": d.isoformat(),
                "clicks": int(hit.get("clicks", 0) or 0) if hit else 0,
                "impressions": int(hit.get("impressions", 0) or 0) if hit else 0,
                "ctr": float(hit.get("ctr", 0) or 0) if hit else 0.0,
                "gsc_position": hit.get("position") if hit else None,
            }
        )
    return records


def resolve_canonical_pages(page_rows: list[dict]) -> dict[str, str]:
    """Best landing page per query: most clicks, tie-broken by most impressions.

    `page_rows` are gsc_query_page_daily records (query, page, clicks,
    impressions). Returns {lowercased query: page}. This is the heuristic the
    `canonical_url_locked` flag overrides when a client pins a target URL.
    """
    totals: dict[str, dict[str, tuple[int, int]]] = {}
    for row in page_rows:
        q = str(row["query"]).lower()
        page = row["page"]
        clicks = int(row.get("clicks", 0) or 0)
        impressions = int(row.get("impressions", 0) or 0)
        bucket = totals.setdefault(q, {})
        prev = bucket.get(page, (0, 0))
        bucket[page] = (prev[0] + clicks, prev[1] + impressions)
    out: dict[str, str] = {}
    for q, pages in totals.items():
        best = max(pages.items(), key=lambda kv: (kv[1][0], kv[1][1]))
        out[q] = best[0]
    return out


def needs_index_check(
    status: str, canonical_url: Optional[str], last_checked: Optional[str], today: date, recheck_days: int
) -> bool:
    """Only inspect a keyword's page when it's flagged deindex_risk, has a
    canonical URL, and hasn't been checked within the recheck window (quota)."""
    if status != "deindex_risk" or not canonical_url:
        return False
    if not last_checked:
        return True
    checked = date.fromisoformat(last_checked[:10])
    return (today.toordinal() - checked.toordinal()) >= recheck_days


def classify_source(merged_rows: list[dict]) -> str:
    """tracked_keywords.source from what data the keyword actually has."""
    has_gsc = any(r.get("gsc_position") is not None for r in merged_rows)
    has_df = any(r.get("tracked_rank") is not None for r in merged_rows)
    if has_gsc and has_df:
        return "both"
    if has_df:
        return "dataforseo"
    return "gsc"  # GSC-only or no-data-yet (the default)


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
def _verified_property(supabase, client_id: str) -> Optional[dict]:
    res = (
        supabase.table("gsc_properties")
        .select("id, site_url, property_type")
        .eq("client_id", client_id)
        .eq("access_status", "ok")
        .order("created_at")
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def _verified_property_id(supabase, client_id: str) -> Optional[str]:
    prop = _verified_property(supabase, client_id)
    return prop["id"] if prop else None


def materialize_client(client_id: str, today: Optional[date] = None) -> MaterializeResult:
    """Rebuild the date axis + status/source for every active keyword of a client."""
    supabase = get_supabase()
    today = today or date.today()
    start = today - timedelta(days=settings.rank_materialize_days)
    dates = date_range(start, today)
    coverage = settings.rank_gsc_coverage_days

    keywords = (
        supabase.table("tracked_keywords")
        .select("id, keyword, canonical_url, canonical_url_locked, index_checked_at")
        .eq("client_id", client_id)
        .eq("active", True)
        .execute()
    )
    if not keywords.data:
        return MaterializeResult(status="ok", keywords=0, rows=0)
    keyword_ids = [k["id"] for k in keywords.data]

    # GSC data (only if the client has a verified property).
    prop_row = _verified_property(supabase, client_id)
    property_id = prop_row["id"] if prop_row else None
    gsc_index: dict[tuple[str, str], dict] = {}
    canonical_by_query: dict[str, str] = {}
    to_inspect: list[tuple[str, str]] = []  # (keyword_id, canonical_url)
    if property_id:
        raw = (
            supabase.table("gsc_query_daily")
            .select("query, date, clicks, impressions, ctr, position")
            .eq("property_id", property_id)
            .gte("date", start.isoformat())
            .lte("date", today.isoformat())
            .execute()
        )
        gsc_index = index_gsc_rows(raw.data or [])
        # Canonical landing page per query, from the weekly query×page data.
        page_rows = (
            supabase.table("gsc_query_page_daily")
            .select("query, page, clicks, impressions")
            .eq("property_id", property_id)
            .execute()
        )
        canonical_by_query = resolve_canonical_pages(page_rows.data or [])

    # Existing DataForSEO ranks (weekly fallback wrote these); blend for status.
    df_rows = (
        supabase.table("rank_keyword_metrics")
        .select("keyword_id, date, tracked_rank")
        .in_("keyword_id", keyword_ids)
        .gte("date", start.isoformat())
        .execute()
    ).data or []
    df_by_kw: dict[str, dict[str, int]] = {}
    for r in df_rows:
        if r.get("tracked_rank") is not None:
            df_by_kw.setdefault(r["keyword_id"], {})[str(r["date"])] = r["tracked_rank"]

    total_rows = 0
    now_iso = "now()"
    alert_inputs: list[tuple[str, str, list]] = []  # (keyword_id, keyword, signals)
    try:
        for kw in keywords.data:
            records = build_keyword_axis(kw["id"], kw["keyword"], dates, gsc_index)
            if records:
                supabase.table("rank_keyword_metrics").upsert(
                    records, on_conflict="keyword_id,date"
                ).execute()
                total_rows += len(records)

            # Merge in DataForSEO ranks to pick the source + status.
            kw_df = df_by_kw.get(kw["id"], {})
            merged = [{**r, "tracked_rank": kw_df.get(r["date"])} for r in records]
            source = classify_source(merged)
            primary = rank_status.determine_primary_source(merged, today, coverage)
            if primary == "dataforseo":
                series = [(r["date"], r.get("tracked_rank")) for r in merged]
            else:
                series = [(r["date"], r.get("gsc_position")) for r in merged]
            status = rank_status.compute_status(series)

            # Collect rank-drop alert signals for this keyword (reconciled below).
            alert_inputs.append(
                (kw["id"], kw["keyword"], rank_alerts.detect_alerts(kw["keyword"], merged, primary, status, today))
            )

            update = {
                "status": status, "source": source,
                "status_updated_at": now_iso, "updated_at": now_iso,
            }
            # Resolve canonical URL unless the client pinned it.
            canonical = kw.get("canonical_url")
            if not kw.get("canonical_url_locked"):
                resolved = canonical_by_query.get(kw["keyword"].lower())
                if resolved and resolved != kw.get("canonical_url"):
                    update["canonical_url"] = resolved
                    canonical = resolved

            supabase.table("tracked_keywords").update(update).eq("id", kw["id"]).execute()

            # Queue a URL-Inspection confirmation for newly/again deindex-risk pages.
            if property_id and needs_index_check(
                status, canonical, kw.get("index_checked_at"), today, settings.url_inspection_recheck_days
            ):
                to_inspect.append((kw["id"], canonical))
    except Exception as exc:
        logger.error("rank_materialize_failed", extra={"client_id": client_id, "error": str(exc)})
        return MaterializeResult(status="failed", keywords=len(keywords.data), rows=total_rows, error=str(exc))

    if to_inspect and prop_row:
        _confirm_deindex(supabase, prop_row, to_inspect)

    # Open/resolve in-app rank-drop alerts from this run's signals, then trigger a
    # rate-limited rankability snapshot for any keyword that newly dropped.
    try:
        result = rank_alerts.reconcile_alerts(supabase, client_id, alert_inputs, today)
        opened_ids = result.get("opened_keyword_ids") or []
        if opened_ids:
            from services import serp_snapshot

            serp_snapshot.enqueue_drop_triggered_snapshots(client_id, opened_ids, today)
        opened_alerts = result.get("opened_alerts") or []
        if opened_alerts:
            from services import notifications

            digest = rank_alerts.summarize_drop_alerts(opened_alerts)
            notifications.emit(
                client_id=client_id,
                kind="rank_drop",
                title=digest["title"],
                summary=digest["summary"],
                severity=digest["severity"],
                payload={"link": f"clients/{client_id}/rankings", "alerts": opened_alerts},
            )
    except Exception as exc:
        logger.warning("rank_alerts_reconcile_failed", extra={"client_id": client_id, "error": str(exc)})

    logger.info(
        "rank_materialize_complete",
        extra={"client_id": client_id, "keywords": len(keywords.data), "rows": total_rows},
    )
    return MaterializeResult(status="ok", keywords=len(keywords.data), rows=total_rows)


_MAX_INSPECTIONS_PER_RUN = 10  # stay well under the daily per-property quota


def _confirm_deindex(supabase, prop_row: dict, to_inspect: list[tuple[str, str]]) -> None:
    """Run URL Inspection on flagged keywords' canonical pages and store results."""
    from services import gsc_service

    try:
        site_url = gsc_service.normalize_site_url(prop_row["site_url"], prop_row["property_type"])
    except ValueError:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    for keyword_id, url in to_inspect[:_MAX_INSPECTIONS_PER_RUN]:
        try:
            result = gsc_service.inspect_url(site_url, url)
        except Exception as exc:
            logger.warning("url_inspection_failed", extra={"keyword_id": keyword_id, "error": str(exc)})
            continue
        supabase.table("tracked_keywords").update(
            {
                "index_status": result["index_status"],
                "index_coverage": result.get("coverage_state"),
                "index_checked_at": now_iso,
            }
        ).eq("id", keyword_id).execute()


def enqueue_materialize(client_id: str) -> None:
    """Enqueue a gsc_materialize job (deduped against pending ones)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "gsc_materialize")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "gsc_materialize", "entity_id": client_id, "payload": {"client_id": client_id}}
    ).execute()


async def run_gsc_materialize_job(job: dict) -> None:
    """async_jobs handler for job_type='gsc_materialize'."""
    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()

    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    result = materialize_client(client_id)
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.status == "ok" else "failed",
            "result": {"keywords": result.keywords, "rows": result.rows},
            "error": result.error,
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()

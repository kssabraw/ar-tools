"""Organic Rank Tracker keyword + metrics router.

Keywords are CLIENT-anchored (a GSC property is optional). When the client has
a verified GSC property the views show GSC clicks/impressions/average-position;
otherwise — or for keywords the site doesn't rank for — they fall back to the
weekly DataForSEO live rank, dropping the GSC-only metrics.

Authorization follows the suite model (any authenticated user reads; admins
manage); all DB access uses the service-role client.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_auth
from models.rank import (
    DataForSeoRefreshResponse,
    FetchSchedule,
    KeywordSummary,
    KeywordTrendline,
    KeywordPagesResponse,
    KeywordPageRow,
    MaterializeResponse,
    OverviewResponse,
    GeneratedReport,
    PagesResponse,
    RankAlert,
    RankAlertsResponse,
    RankLocation,
    ReportListItem,
    ReportPublishResponse,
    ReportSchedule,
    SerpSnapshotCaptureResponse,
    SerpSnapshotDetail,
    SerpSnapshotDomainRow,
    SerpSnapshotListItem,
    SerpSnapshotResultRow,
    SerpChangeItem,
    SerpTimelinePoint,
    SerpTimelineResponse,
    SerpTrendSeries,
    SerpTrendsResponse,
    StrikingDistanceResponse,
    TrackedKeywordCreateRequest,
    TrackedKeywordUpdateRequest,
    TrendPoint,
)
from services import (
    dataforseo_rank,
    gsc_service,
    keyword_market,
    rank_location,
    rank_materialize,
    rank_report,
    rank_status,
    serp_snapshot,
    serp_trends,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rank"])

# Read window: rolling averages need up to 90 days; pull a little more for the
# 7d-vs-90d direction to be meaningful.
_READ_DAYS = 95


def _fetch_metrics(supabase, keyword_ids: list[str]) -> dict[str, list[dict]]:
    if not keyword_ids:
        return {}
    cutoff = date.fromordinal(date.today().toordinal() - _READ_DAYS).isoformat()
    result = (
        supabase.table("rank_keyword_metrics")
        .select("keyword_id, date, clicks, impressions, ctr, gsc_position, tracked_rank")
        .in_("keyword_id", keyword_ids)
        .gte("date", cutoff)
        .execute()
    )
    grouped: dict[str, list[dict]] = {}
    for row in result.data or []:
        grouped.setdefault(row["keyword_id"], []).append(row)
    return grouped


def _gsc_connected(supabase, client_id: str) -> bool:
    return bool(
        supabase.table("gsc_properties")
        .select("id")
        .eq("client_id", client_id)
        .eq("access_status", "ok")
        .limit(1)
        .execute()
        .data
    )


def _client_location_code(supabase, client_id: str) -> int:
    res = supabase.table("clients").select(
        "id, website_url, gbp, rank_tracking_location_code"
    ).eq("id", client_id).limit(1).execute()
    return dataforseo_rank.location_code_for(res.data[0]) if res.data else settings.dataforseo_default_location_code


def _page_counts(supabase, client_id: str, keywords: list[str]) -> dict[str, int]:
    """Distinct landing-page count per keyword (lowercased), from query×page data."""
    property_id = rank_materialize._verified_property_id(supabase, client_id)
    if not property_id or not keywords:
        return {}
    rows = (
        supabase.table("gsc_query_page_daily")
        .select("query, page")
        .eq("property_id", property_id)
        .in_("query", [k.lower() for k in keywords])
        .execute()
    ).data or []
    pages_by_query: dict[str, set] = {}
    for r in rows:
        pages_by_query.setdefault(str(r["query"]).lower(), set()).add(r["page"])
    return {q: len(pages) for q, pages in pages_by_query.items()}


def _build_summaries(supabase, client_id: str, keyword_rows: list[dict], today: date) -> list[KeywordSummary]:
    metrics = _fetch_metrics(supabase, [k["id"] for k in keyword_rows])
    location_code = _client_location_code(supabase, client_id)
    market = keyword_market.fetch_cached_market(
        supabase, [k["keyword"] for k in keyword_rows], location_code
    )
    page_counts = _page_counts(supabase, client_id, [k["keyword"] for k in keyword_rows])

    out: list[KeywordSummary] = []
    for k in keyword_rows:
        s = rank_status.compute_keyword_summary(
            metrics.get(k["id"], []), today, settings.rank_gsc_coverage_days
        )
        m = market.get(k["keyword"].lower(), {})
        # Best current-position estimate for the ROI figure: live rank for a
        # DataForSEO keyword, else the 30d GSC average.
        position = s["today_rank"] if s["primary_source"] == "dataforseo" else s["avg_30"]
        out.append(
            KeywordSummary(
                id=k["id"],
                keyword=k["keyword"],
                source=k["source"],
                canonical_url=k.get("canonical_url"),
                canonical_url_locked=k["canonical_url_locked"],
                status=k["status"],
                status_updated_at=k.get("status_updated_at"),
                cpc=m.get("cpc"),
                search_volume=m.get("search_volume"),
                competition=m.get("competition"),
                est_monthly_value=keyword_market.estimate_monthly_value(
                    m.get("search_volume"), position, m.get("cpc")
                ),
                index_status=k.get("index_status"),
                index_checked_at=k.get("index_checked_at"),
                page_count=page_counts.get(k["keyword"].lower(), 0),
                **s,
            )
        )
    return out


@router.get("/clients/{client_id}/rank/keywords", response_model=list[KeywordSummary])
async def list_keywords(client_id: UUID, auth: dict = Depends(require_auth)) -> list[KeywordSummary]:
    supabase = get_supabase()
    kws = (
        supabase.table("tracked_keywords")
        .select("*")
        .eq("client_id", str(client_id))
        .eq("active", True)
        .order("keyword")
        .execute()
    )
    rows = kws.data or []
    return _build_summaries(supabase, str(client_id), rows, date.today())


def _split_keywords(raw: list[str]) -> list[str]:
    """Split a bulk-add payload on newlines/commas, trim, dedupe, drop blanks."""
    seen: dict[str, None] = {}
    for chunk in raw:
        for part in re.split(r"[\n,]+", chunk):
            kw = part.strip()
            if kw:
                seen.setdefault(kw, None)
    return list(seen)


@router.post("/clients/{client_id}/rank/keywords", response_model=list[KeywordSummary])
async def add_keywords(
    client_id: UUID,
    body: TrackedKeywordCreateRequest,
    auth: dict = Depends(require_auth),  # adding keywords is open to any team member
) -> list[KeywordSummary]:
    keywords = _split_keywords(body.keywords)
    if not keywords:
        raise HTTPException(status_code=422, detail="validation_error: no keywords provided")

    supabase = get_supabase()
    payload = [
        {"client_id": str(client_id), "keyword": kw, "source": "gsc", "created_by": auth["user_id"]}
        for kw in keywords
    ]
    supabase.table("tracked_keywords").upsert(
        payload, on_conflict="client_id,keyword", ignore_duplicates=True
    ).execute()

    # Backfill GSC axis + status now; the weekly job (or manual refresh) fills in
    # DataForSEO for any keyword GSC doesn't cover; market data for CPC/volume.
    rank_materialize.enqueue_materialize(str(client_id))
    keyword_market.enqueue_keyword_market(str(client_id))
    return await list_keywords(client_id, auth)


@router.patch("/tracked-keywords/{keyword_id}", response_model=KeywordSummary)
async def update_keyword(
    keyword_id: UUID,
    body: TrackedKeywordUpdateRequest,
    auth: dict = Depends(require_auth),
) -> KeywordSummary:
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="validation_error: no fields to update")
    updates["updated_at"] = "now()"

    supabase = get_supabase()
    result = supabase.table("tracked_keywords").update(updates).eq("id", str(keyword_id)).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="not_found")
    k = result.data[0]
    return _build_summaries(supabase, k["client_id"], [k], date.today())[0]


@router.delete("/tracked-keywords/{keyword_id}", status_code=204, response_class=Response)
async def delete_keyword(keyword_id: UUID, auth: dict = Depends(require_auth)) -> Response:
    get_supabase().table("tracked_keywords").delete().eq("id", str(keyword_id)).execute()
    return Response(status_code=204)


@router.get("/tracked-keywords/{keyword_id}/trendline", response_model=KeywordTrendline)
async def get_trendline(keyword_id: UUID, auth: dict = Depends(require_auth)) -> KeywordTrendline:
    supabase = get_supabase()
    found = supabase.table("tracked_keywords").select("*").eq("id", str(keyword_id)).limit(1).execute()
    if not found.data:
        raise HTTPException(status_code=404, detail="not_found")
    k = found.data[0]

    metrics = (
        supabase.table("rank_keyword_metrics")
        .select("date, gsc_position, tracked_rank, clicks, impressions, ctr")
        .eq("keyword_id", str(keyword_id))
        .order("date")
        .execute()
    )
    points = [
        TrendPoint(
            date=r["date"],
            gsc_position=r.get("gsc_position"),
            tracked_rank=r.get("tracked_rank"),
            clicks=r.get("clicks", 0),
            impressions=r.get("impressions", 0),
            ctr=r.get("ctr", 0.0),
        )
        for r in (metrics.data or [])
    ]
    return KeywordTrendline(
        id=k["id"], keyword=k["keyword"], status=k["status"],
        canonical_url=k.get("canonical_url"), points=points,
    )


@router.get("/tracked-keywords/{keyword_id}/pages", response_model=KeywordPagesResponse)
async def get_keyword_pages(keyword_id: UUID, auth: dict = Depends(require_auth)) -> KeywordPagesResponse:
    """The landing pages a keyword surfaces for (query×page breakdown)."""
    supabase = get_supabase()
    found = (
        supabase.table("tracked_keywords")
        .select("keyword, client_id, canonical_url")
        .eq("id", str(keyword_id)).limit(1).execute()
    )
    if not found.data:
        raise HTTPException(status_code=404, detail="not_found")
    k = found.data[0]
    property_id = rank_materialize._verified_property_id(supabase, k["client_id"])
    if not property_id:
        return KeywordPagesResponse(keyword=k["keyword"], canonical_url=k.get("canonical_url"), pages=[])

    rows = (
        supabase.table("gsc_query_page_daily")
        .select("query, page, clicks, impressions, position")
        .eq("property_id", property_id)
        .ilike("query", k["keyword"])
        .execute()
    )
    pages = [
        KeywordPageRow(
            page=p["page"], clicks=p["clicks"], impressions=p["impressions"],
            avg_position=p["avg_position"], is_canonical=(p["page"] == k.get("canonical_url")),
        )
        for p in rank_status.aggregate_pages(rows.data or [])
    ]
    return KeywordPagesResponse(keyword=k["keyword"], canonical_url=k.get("canonical_url"), pages=pages)


@router.get("/clients/{client_id}/rank/overview", response_model=OverviewResponse)
async def get_overview(client_id: UUID, auth: dict = Depends(require_auth)) -> OverviewResponse:
    supabase = get_supabase()
    kws = (
        supabase.table("tracked_keywords")
        .select("id, status")
        .eq("client_id", str(client_id))
        .eq("active", True)
        .execute()
    )
    rows = kws.data or []
    status_counts: dict[str, int] = {}
    for k in rows:
        status_counts[k["status"]] = status_counts.get(k["status"], 0) + 1

    metrics = _fetch_metrics(supabase, [k["id"] for k in rows])
    all_rows = [r for group in metrics.values() for r in group]
    today = date.today()

    clicks_30 = rank_status._window_sum(all_rows, 30, today, "clicks")
    impressions_30 = rank_status._window_sum(all_rows, 30, today, "impressions")
    positions_30 = rank_status.rolling_average(
        [(r["date"], r.get("gsc_position")) for r in all_rows], 30, today
    )
    hero = rank_status.aggregate_hero(all_rows, today, 90)
    at_risk = status_counts.get("deindex_risk", 0) + status_counts.get("dropping", 0)

    unread_alerts = (
        supabase.table("rank_alerts")
        .select("id", count="exact")
        .eq("client_id", str(client_id))
        .eq("status", "unread")
        .execute()
    )

    return OverviewResponse(
        keyword_count=len(rows),
        gsc_connected=_gsc_connected(supabase, str(client_id)),
        status_counts=status_counts,
        clicks_30d=clicks_30,
        impressions_30d=impressions_30,
        avg_position_30d=positions_30,
        at_risk=at_risk,
        hero=hero,
        unread_alert_count=unread_alerts.count or 0,
    )


@router.get("/clients/{client_id}/rank/striking-distance", response_model=StrikingDistanceResponse)
async def get_striking_distance(client_id: UUID, auth: dict = Depends(require_auth)) -> StrikingDistanceResponse:
    """Untracked GSC queries in the page-2 position band (opportunities)."""
    supabase = get_supabase()
    property_id = rank_materialize._verified_property_id(supabase, str(client_id))
    if not property_id:
        return StrikingDistanceResponse(gsc_connected=False, keywords=[])

    tracked = (
        supabase.table("tracked_keywords").select("keyword").eq("client_id", str(client_id)).execute()
    ).data or []
    tracked_lower = {t["keyword"].lower() for t in tracked}

    cutoff = date.fromordinal(date.today().toordinal() - settings.gsc_page_window_days).isoformat()
    rows = (
        supabase.table("gsc_query_daily")
        .select("query, clicks, impressions, position")
        .eq("property_id", property_id)
        .gte("date", cutoff)
        .execute()
    )
    opportunities = rank_status.aggregate_striking_distance(
        rows.data or [], tracked_lower, settings.striking_distance_min, settings.striking_distance_max
    )[:50]
    return StrikingDistanceResponse(gsc_connected=True, keywords=opportunities)


@router.post("/tracked-keywords/{keyword_id}/check-index", response_model=KeywordSummary)
async def check_index(keyword_id: UUID, auth: dict = Depends(require_auth)) -> KeywordSummary:
    """Run URL Inspection now on a keyword's canonical page (admin)."""
    supabase = get_supabase()
    found = supabase.table("tracked_keywords").select("*").eq("id", str(keyword_id)).limit(1).execute()
    if not found.data:
        raise HTTPException(status_code=404, detail="not_found")
    k = found.data[0]
    prop = rank_materialize._verified_property(supabase, k["client_id"])
    if not prop or not k.get("canonical_url"):
        raise HTTPException(status_code=422, detail="needs_gsc_property_and_canonical_url")
    try:
        site_url = gsc_service.normalize_site_url(prop["site_url"], prop["property_type"])
        result = gsc_service.inspect_url(site_url, k["canonical_url"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"url_inspection_failed: {exc}")
    updated = supabase.table("tracked_keywords").update(
        {
            "index_status": result["index_status"],
            "index_coverage": result.get("coverage_state"),
            "index_checked_at": "now()",
        }
    ).eq("id", str(keyword_id)).execute()
    return _build_summaries(supabase, k["client_id"], [updated.data[0]], date.today())[0]


@router.get("/clients/{client_id}/rank/pages", response_model=PagesResponse)
async def get_pages(client_id: UUID, auth: dict = Depends(require_auth)) -> PagesResponse:
    """GSC performance pivoted by landing page (requires a verified property)."""
    supabase = get_supabase()
    property_id = rank_materialize._verified_property_id(supabase, str(client_id))
    if not property_id:
        return PagesResponse(gsc_connected=False, pages=[])
    rows = (
        supabase.table("gsc_query_page_daily")
        .select("query, page, clicks, impressions, position")
        .eq("property_id", property_id)
        .execute()
    )
    pages = rank_status.aggregate_pages(rows.data or [])[:100]
    return PagesResponse(gsc_connected=True, pages=pages)


@router.post("/clients/{client_id}/rank/materialize", response_model=MaterializeResponse)
async def trigger_materialize(client_id: UUID, auth: dict = Depends(require_auth)) -> MaterializeResponse:
    result = rank_materialize.materialize_client(str(client_id))
    return MaterializeResponse(
        client_id=client_id, status=result.status, keywords=result.keywords,
        rows=result.rows, error=result.error,
    )


@router.get("/clients/{client_id}/rank/location", response_model=RankLocation)
async def get_tracking_location(client_id: UUID, auth: dict = Depends(require_auth)) -> RankLocation:
    res = (
        get_supabase().table("clients")
        .select("rank_tracking_location, rank_tracking_location_code, rank_tracking_location_source")
        .eq("id", str(client_id)).limit(1).execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="not_found")
    row = res.data[0]
    return RankLocation(
        location=row.get("rank_tracking_location"),
        location_code=row.get("rank_tracking_location_code"),
        source=row.get("rank_tracking_location_source"),
    )


@router.put("/clients/{client_id}/rank/location", response_model=RankLocation)
async def set_tracking_location(
    client_id: UUID, body: RankLocation, auth: dict = Depends(require_auth)
) -> RankLocation:
    """Set (or clear, with both fields null) the client's DataForSEO tracking
    location. Setting one marks it 'manual' so GBP auto-derivation won't overwrite
    it; clearing reverts to GBP-auto (re-derived in the background). Fresh ranks +
    market data for the new area are fetched in the background."""
    supabase = get_supabase()
    location = (body.location or "").strip() or None
    code = body.location_code if location else None
    source = "manual" if location else None
    supabase.table("clients").update(
        {
            "rank_tracking_location": location,
            "rank_tracking_location_code": code,
            "rank_tracking_location_source": source,
            "updated_at": "now()",
        }
    ).eq("id", str(client_id)).execute()

    if location is not None:
        # Manual pin — refresh ranks + market data for the chosen area now.
        dataforseo_rank.enqueue_dataforseo_rank(str(client_id))
        keyword_market.enqueue_keyword_market(str(client_id))
    else:
        # Cleared → revert to GBP-auto. The derive job does the single refresh at
        # the resolved (or national) area, so there's no separate pull here.
        rank_location.enqueue_location_derive(str(client_id), refresh_always=True)
    return RankLocation(location=location, location_code=code, source=source)


@router.post("/clients/{client_id}/rank/refresh-dataforseo", response_model=DataForSeoRefreshResponse)
async def trigger_dataforseo(client_id: UUID, auth: dict = Depends(require_auth)) -> DataForSeoRefreshResponse:
    """Fetch DataForSEO ranks now for keywords GSC can't cover (admin)."""
    result = await dataforseo_rank.refresh_client_ranks(str(client_id))
    if result.get("status") == "ok" and result.get("fetched"):
        rank_materialize.materialize_client(str(client_id))
    return DataForSeoRefreshResponse(client_id=client_id, **result)


# ---- Per-client rank-data refresh schedule -----------------------------------
@router.get("/clients/{client_id}/rank/fetch-schedule", response_model=FetchSchedule)
async def get_fetch_schedule(client_id: UUID, auth: dict = Depends(require_auth)) -> FetchSchedule:
    """The client's DataForSEO rank-pull cadence. No row = the legacy default
    (weekly on the global weekday), surfaced so the UI reflects what runs today."""
    default_weekday = settings.dataforseo_rank_weekday
    res = (
        get_supabase().table("rank_fetch_config").select("*").eq("client_id", str(client_id)).limit(1).execute()
    )
    if not res.data:
        return FetchSchedule(mode="weekly", day_of_week=default_weekday)
    r = res.data[0]
    day_of_week = r.get("day_of_week")
    # A weekly row with no explicit day falls back to the global weekday at
    # scheduling time; surface that effective day so the UI matches what runs.
    if r["mode"] == "weekly" and day_of_week is None:
        day_of_week = default_weekday
    return FetchSchedule(
        mode=r["mode"], day_of_week=day_of_week, day_of_month=r.get("day_of_month"),
        interval_days=r.get("interval_days"), last_fetched_at=r.get("last_fetched_at"),
    )


@router.put("/clients/{client_id}/rank/fetch-schedule", response_model=FetchSchedule)
async def set_fetch_schedule(
    client_id: UUID, body: FetchSchedule, auth: dict = Depends(require_auth)
) -> FetchSchedule:
    """Set the client's rank-pull cadence. Only the field for the chosen mode is
    kept; last_fetched_at is owned by the fetch path and never set here."""
    supabase = get_supabase()
    row = {
        "client_id": str(client_id),
        "mode": body.mode,
        "day_of_week": body.day_of_week if body.mode == "weekly" else None,
        "day_of_month": body.day_of_month if body.mode == "monthly" else None,
        "interval_days": body.interval_days if body.mode == "interval" else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    supabase.table("rank_fetch_config").upsert(row, on_conflict="client_id").execute()
    return await get_fetch_schedule(client_id, auth)


# ---- Scheduled reports + in-app archive --------------------------------------
@router.get("/clients/{client_id}/rank/report-schedule", response_model=ReportSchedule)
async def get_report_schedule(client_id: UUID, auth: dict = Depends(require_auth)) -> ReportSchedule:
    res = (
        get_supabase().table("rank_report_config").select("*").eq("client_id", str(client_id)).limit(1).execute()
    )
    if not res.data:
        return ReportSchedule()  # default: as_needed
    r = res.data[0]
    return ReportSchedule(
        mode=r["mode"], day_of_week=r.get("day_of_week"), day_of_month=r.get("day_of_month"),
        interval_days=r.get("interval_days"), deliver_google_doc=r.get("deliver_google_doc", False),
        last_generated_at=r.get("last_generated_at"),
    )


@router.put("/clients/{client_id}/rank/report-schedule", response_model=ReportSchedule)
async def set_report_schedule(
    client_id: UUID, body: ReportSchedule, auth: dict = Depends(require_auth)
) -> ReportSchedule:
    """Set the client's report schedule. Only the field for the chosen mode is kept."""
    supabase = get_supabase()
    row = {
        "client_id": str(client_id),
        "mode": body.mode,
        "day_of_week": body.day_of_week if body.mode == "weekly" else None,
        "day_of_month": body.day_of_month if body.mode == "monthly" else None,
        "interval_days": body.interval_days if body.mode == "interval" else None,
        "deliver_google_doc": body.deliver_google_doc,
        "updated_at": "now()",
    }
    supabase.table("rank_report_config").upsert(row, on_conflict="client_id").execute()
    return await get_report_schedule(client_id, auth)


@router.get("/clients/{client_id}/rank/reports", response_model=list[ReportListItem])
async def list_reports(client_id: UUID, auth: dict = Depends(require_auth)) -> list[ReportListItem]:
    res = (
        get_supabase().table("rank_reports").select("id, title, created_at, doc_url")
        .eq("client_id", str(client_id)).order("created_at", desc=True).limit(60).execute()
    )
    return [ReportListItem(**r) for r in (res.data or [])]


@router.post("/clients/{client_id}/rank/reports", response_model=GeneratedReport)
async def generate_report(client_id: UUID, auth: dict = Depends(require_auth)) -> GeneratedReport:
    """Generate a report now (the 'as needed' path) and store it in the archive.
    Also delivers a Google Doc if the client has opted into delivery."""
    supabase = get_supabase()
    report = rank_report.generate_and_store(supabase, str(client_id), created_by=auth["user_id"])
    if report is None:
        raise HTTPException(status_code=404, detail="client_not_found")
    if rank_report.deliver_enabled(supabase, str(client_id)):
        try:
            result = await rank_report.publish_report_doc(supabase, report)
            report["doc_url"] = result.get("doc_url")
        except Exception as exc:
            logger.warning("report_delivery_failed", extra={"client_id": str(client_id), "error": str(exc)})
    return GeneratedReport(**report)


@router.post("/rank-reports/{report_id}/publish", response_model=ReportPublishResponse)
async def publish_report(report_id: UUID, auth: dict = Depends(require_auth)) -> ReportPublishResponse:
    """Publish an archived report to a Google Doc in the client's Drive folder."""
    supabase = get_supabase()
    res = supabase.table("rank_reports").select("*").eq("id", str(report_id)).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="not_found")
    try:
        result = await rank_report.publish_report_doc(supabase, res.data[0])
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"publish_failed: {exc}")
    return ReportPublishResponse(**result)


@router.get("/rank-reports/{report_id}", response_model=GeneratedReport)
async def get_report(report_id: UUID, auth: dict = Depends(require_auth)) -> GeneratedReport:
    res = get_supabase().table("rank_reports").select("*").eq("id", str(report_id)).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="not_found")
    return GeneratedReport(**res.data[0])


@router.delete("/rank-reports/{report_id}", status_code=204, response_class=Response)
async def delete_report(report_id: UUID, auth: dict = Depends(require_auth)) -> Response:
    get_supabase().table("rank_reports").delete().eq("id", str(report_id)).execute()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Competitive SERP Snapshot — diagnostic store. Captured weekly alongside the
# DataForSEO rank refresh; not a user-facing feature, retrieved here on request
# to diagnose a ranking drop.
# ---------------------------------------------------------------------------
@router.get(
    "/tracked-keywords/{keyword_id}/serp-snapshots",
    response_model=list[SerpSnapshotListItem],
)
async def list_serp_snapshots(
    keyword_id: UUID, auth: dict = Depends(require_auth)
) -> list[SerpSnapshotListItem]:
    """Dated SERP snapshots stored for a keyword (newest first)."""
    supabase = get_supabase()
    snaps = (
        supabase.table("serp_snapshots")
        .select("id, captured_at, status, query_intent, aio_present, client_rank")
        .eq("keyword_id", str(keyword_id))
        .order("captured_at", desc=True)
        .execute()
    ).data or []
    if not snaps:
        return []
    counts = (
        supabase.table("serp_snapshot_results")
        .select("snapshot_id")
        .in_("snapshot_id", [s["id"] for s in snaps])
        .execute()
    ).data or []
    count_by_snapshot: dict[str, int] = {}
    for row in counts:
        count_by_snapshot[row["snapshot_id"]] = count_by_snapshot.get(row["snapshot_id"], 0) + 1
    return [
        SerpSnapshotListItem(
            id=s["id"],
            captured_at=s["captured_at"],
            status=s["status"],
            query_intent=s.get("query_intent"),
            aio_present=s.get("aio_present", False),
            client_rank=s.get("client_rank"),
            result_count=count_by_snapshot.get(s["id"], 0),
        )
        for s in snaps
    ]


@router.get("/serp-snapshots/{snapshot_id}", response_model=SerpSnapshotDetail)
async def get_serp_snapshot(
    snapshot_id: UUID, auth: dict = Depends(require_auth)
) -> SerpSnapshotDetail:
    """A full stored snapshot: AIO + sources, intent, SERP features, and the
    ranking pages with referring domains + URL Rating."""
    supabase = get_supabase()
    found = (
        supabase.table("serp_snapshots").select("*").eq("id", str(snapshot_id)).limit(1).execute()
    )
    if not found.data:
        raise HTTPException(status_code=404, detail="not_found")
    snap = found.data[0]
    results = (
        supabase.table("serp_snapshot_results")
        .select("*")
        .eq("snapshot_id", str(snapshot_id))
        .order("position")
        .execute()
    ).data or []
    domains = (
        supabase.table("serp_snapshot_domains")
        .select("*")
        .eq("snapshot_id", str(snapshot_id))
        .execute()
    ).data or []
    # Strongest domains first, with unrated (null DR — e.g. a failed lookup on a
    # 'partial' snapshot) sorted LAST. Done in Python because Postgres orders
    # NULLS FIRST on DESC, which would float failed rows to the top.
    domains.sort(key=lambda d: (d.get("domain_rating") is None, -(d.get("domain_rating") or 0)))
    return SerpSnapshotDetail(
        **{k: snap.get(k) for k in (
            "id", "keyword_id", "client_id", "keyword", "captured_at", "status",
            "location_code", "language_code", "query_intent", "intent_probabilities",
            "local_intent", "intent_signals", "aio_present", "aio_text", "aio_sources",
            "serp_features", "client_rank", "client_url", "error",
        )},
        results=[SerpSnapshotResultRow(**{k: r.get(k) for k in (
            "position", "url", "domain", "title", "description", "is_client",
            "referring_domains", "url_rating", "backlinks", "backlinks_status",
        )}) for r in results],
        domains=[SerpSnapshotDomainRow(**{k: d.get(k) for k in (
            "domain", "is_client", "domain_rating", "referring_domains",
            "backlinks", "backlinks_status",
        )}) for d in domains],
    )


@router.post(
    "/tracked-keywords/{keyword_id}/serp-snapshot",
    response_model=SerpSnapshotCaptureResponse,
)
async def capture_serp_snapshot(
    keyword_id: UUID, auth: dict = Depends(require_auth)
) -> SerpSnapshotCaptureResponse:
    """On-demand capture for one keyword (the weekly pass captures all). Enqueues
    an async job — the capture is ~24 DataForSEO calls (1 SERP + 1 intent + ~11
    per-URL backlinks + ~11 per-domain backlinks)."""
    supabase = get_supabase()
    found = (
        supabase.table("tracked_keywords")
        .select("id, client_id")
        .eq("id", str(keyword_id))
        .limit(1)
        .execute()
    )
    if not found.data:
        raise HTTPException(status_code=404, detail="not_found")
    serp_snapshot.enqueue_serp_snapshot(found.data[0]["client_id"], keyword_id=str(keyword_id))
    return SerpSnapshotCaptureResponse(keyword_id=keyword_id, status="enqueued")


# ---------------------------------------------------------------------------
# SERP Landscape Trends — over-time + cross-keyword views over the snapshots.
# ---------------------------------------------------------------------------
@router.get("/tracked-keywords/{keyword_id}/serp-timeline", response_model=SerpTimelineResponse)
async def get_serp_timeline(
    keyword_id: UUID, auth: dict = Depends(require_auth)
) -> SerpTimelineResponse:
    """Dated snapshots for a keyword with the signal set, the client's rank/UR/DR,
    and the delta vs the previous capture — "how Google changed for this query"."""
    data = serp_trends.get_keyword_timeline(str(keyword_id))
    if data is None:
        raise HTTPException(status_code=404, detail="not_found")
    return SerpTimelineResponse(
        keyword_id=data["keyword_id"],
        keyword=data["keyword"],
        points=[SerpTimelinePoint(**p) for p in data["points"]],
    )


@router.get("/clients/{client_id}/serp-trends", response_model=SerpTrendsResponse)
async def get_serp_trends(
    client_id: UUID, weeks: int = 12, auth: dict = Depends(require_auth)
) -> SerpTrendsResponse:
    """Client-level SERP-landscape rollup: per-signal prevalence over an as-of
    weekly series, plus a "what changed since last capture" digest."""
    weeks = max(2, min(weeks, 52))
    data = serp_trends.get_client_trends(str(client_id), weeks=weeks)
    return SerpTrendsResponse(
        week_ends=data["week_ends"],
        keyword_counts=data["keyword_counts"],
        series=[SerpTrendSeries(**s) for s in data["series"]],
        changes=[SerpChangeItem(**c) for c in data["changes"]],
    )


# ---------------------------------------------------------------------------
# In-app rank-drop alerts (per-client Rankings "Alerts" tab).
# ---------------------------------------------------------------------------
def _alert_row(r: dict) -> RankAlert:
    return RankAlert(
        id=r["id"], keyword_id=r["keyword_id"], keyword=r["keyword"],
        alert_type=r["alert_type"], source=r.get("source"),
        from_position=r.get("from_position"), to_position=r.get("to_position"),
        delta=r.get("delta"), message=r["message"], status=r["status"],
        triggered_on=r.get("triggered_on"), resolved_at=r.get("resolved_at"),
        created_at=r["created_at"],
    )


@router.get("/clients/{client_id}/rank/alerts", response_model=RankAlertsResponse)
async def list_alerts(
    client_id: UUID, include_dismissed: bool = False, auth: dict = Depends(require_auth)
) -> RankAlertsResponse:
    """Rank-drop alerts for a client, newest first. Dismissed are hidden by default."""
    supabase = get_supabase()
    query = (
        supabase.table("rank_alerts")
        .select("*")
        .eq("client_id", str(client_id))
        .order("created_at", desc=True)
    )
    if not include_dismissed:
        query = query.neq("status", "dismissed")
    rows = (query.execute()).data or []
    unread = sum(1 for r in rows if r["status"] == "unread")
    return RankAlertsResponse(alerts=[_alert_row(r) for r in rows], unread_count=unread)


@router.post("/rank-alerts/{alert_id}/read", response_model=RankAlert)
async def mark_alert_read(alert_id: UUID, auth: dict = Depends(require_auth)) -> RankAlert:
    supabase = get_supabase()
    res = (
        supabase.table("rank_alerts")
        .update({"status": "read", "read_at": "now()"})
        .eq("id", str(alert_id))
        .eq("status", "unread")  # don't clobber a dismissed alert
        .execute()
    )
    row = res.data[0] if res.data else _get_alert_or_404(supabase, alert_id)
    return _alert_row(row)


@router.post("/rank-alerts/{alert_id}/dismiss", response_model=RankAlert)
async def dismiss_alert(alert_id: UUID, auth: dict = Depends(require_auth)) -> RankAlert:
    supabase = get_supabase()
    res = (
        supabase.table("rank_alerts")
        .update({"status": "dismissed", "dismissed_at": "now()"})
        .eq("id", str(alert_id))
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="not_found")
    return _alert_row(res.data[0])


@router.post("/clients/{client_id}/rank/alerts/read-all", response_model=RankAlertsResponse)
async def mark_all_alerts_read(client_id: UUID, auth: dict = Depends(require_auth)) -> RankAlertsResponse:
    supabase = get_supabase()
    supabase.table("rank_alerts").update({"status": "read", "read_at": "now()"}).eq(
        "client_id", str(client_id)
    ).eq("status", "unread").execute()
    return await list_alerts(client_id, include_dismissed=False, auth=auth)


def _get_alert_or_404(supabase, alert_id: UUID) -> dict:
    res = supabase.table("rank_alerts").select("*").eq("id", str(alert_id)).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="not_found")
    return res.data[0]

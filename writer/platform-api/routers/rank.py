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
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from config import settings
from db.supabase_client import get_supabase
from middleware.auth import require_admin, require_auth
from models.rank import (
    DataForSeoRefreshResponse,
    KeywordSummary,
    KeywordTrendline,
    KeywordPagesResponse,
    KeywordPageRow,
    MaterializeResponse,
    OverviewResponse,
    PagesResponse,
    StrikingDistanceResponse,
    TrackedKeywordCreateRequest,
    TrackedKeywordUpdateRequest,
    TrendPoint,
)
from services import dataforseo_rank, gsc_service, keyword_market, rank_materialize, rank_status

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
    res = supabase.table("clients").select("id, website_url, gbp").eq("id", client_id).limit(1).execute()
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
    auth: dict = Depends(require_admin),
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


@router.delete("/tracked-keywords/{keyword_id}", status_code=204)
async def delete_keyword(keyword_id: UUID, auth: dict = Depends(require_admin)) -> None:
    get_supabase().table("tracked_keywords").delete().eq("id", str(keyword_id)).execute()


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

    return OverviewResponse(
        keyword_count=len(rows),
        gsc_connected=_gsc_connected(supabase, str(client_id)),
        status_counts=status_counts,
        clicks_30d=clicks_30,
        impressions_30d=impressions_30,
        avg_position_30d=positions_30,
        at_risk=at_risk,
        hero=hero,
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
async def check_index(keyword_id: UUID, auth: dict = Depends(require_admin)) -> KeywordSummary:
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
async def trigger_materialize(client_id: UUID, auth: dict = Depends(require_admin)) -> MaterializeResponse:
    result = rank_materialize.materialize_client(str(client_id))
    return MaterializeResponse(
        client_id=client_id, status=result.status, keywords=result.keywords,
        rows=result.rows, error=result.error,
    )


@router.post("/clients/{client_id}/rank/refresh-dataforseo", response_model=DataForSeoRefreshResponse)
async def trigger_dataforseo(client_id: UUID, auth: dict = Depends(require_admin)) -> DataForSeoRefreshResponse:
    """Fetch DataForSEO ranks now for keywords GSC can't cover (admin)."""
    result = await dataforseo_rank.refresh_client_ranks(str(client_id))
    if result.get("status") == "ok" and result.get("fetched"):
        rank_materialize.materialize_client(str(client_id))
    return DataForSeoRefreshResponse(client_id=client_id, **result)

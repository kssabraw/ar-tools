"""Organic Rank Tracker keyword + metrics router (M3).

Keyword CRUD over tracked_keywords, the merged Keywords table read (rolling GSC
averages + sparkline + computed status), the per-keyword trendline, and the
account-level Overview. Authorization follows the suite model (any authenticated
user reads; admins manage); all DB access uses the service-role client.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from db.supabase_client import get_supabase
from middleware.auth import require_admin, require_auth
from models.rank import (
    KeywordSummary,
    KeywordTrendline,
    MaterializeResponse,
    OverviewResponse,
    TrackedKeywordCreateRequest,
    TrackedKeywordUpdateRequest,
    TrendPoint,
)
from services import rank_materialize, rank_status

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rank"])

# Read window: rolling averages need up to 90 days; pull a little more for the
# 7d-vs-90d direction to be meaningful.
_READ_DAYS = 95


def _fetch_metrics(supabase, keyword_ids: list[str]) -> dict[str, list[dict]]:
    """Fetch recent rank_keyword_metrics for the given keywords, grouped by id."""
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


@router.get("/gsc-properties/{property_id}/keywords", response_model=list[KeywordSummary])
async def list_keywords(
    property_id: UUID, auth: dict = Depends(require_auth)
) -> list[KeywordSummary]:
    supabase = get_supabase()
    kws = (
        supabase.table("tracked_keywords")
        .select("*")
        .eq("property_id", str(property_id))
        .eq("active", True)
        .order("keyword")
        .execute()
    )
    rows = kws.data or []
    metrics = _fetch_metrics(supabase, [k["id"] for k in rows])
    today = date.today()

    out: list[KeywordSummary] = []
    for k in rows:
        summary = rank_status.compute_keyword_summary(metrics.get(k["id"], []), today)
        out.append(
            KeywordSummary(
                id=k["id"],
                keyword=k["keyword"],
                source=k["source"],
                canonical_url=k.get("canonical_url"),
                canonical_url_locked=k["canonical_url_locked"],
                status=k["status"],
                status_updated_at=k.get("status_updated_at"),
                **summary,
            )
        )
    return out


def _split_keywords(raw: list[str]) -> list[str]:
    """Split a bulk-add payload on newlines/commas, trim, dedupe, drop blanks."""
    seen: dict[str, None] = {}
    for chunk in raw:
        for part in re.split(r"[\n,]+", chunk):
            kw = part.strip()
            if kw:
                seen.setdefault(kw, None)
    return list(seen)


@router.post("/gsc-properties/{property_id}/keywords", response_model=list[KeywordSummary])
async def add_keywords(
    property_id: UUID,
    body: TrackedKeywordCreateRequest,
    auth: dict = Depends(require_admin),
) -> list[KeywordSummary]:
    keywords = _split_keywords(body.keywords)
    if not keywords:
        raise HTTPException(status_code=422, detail="validation_error: no keywords provided")

    supabase = get_supabase()
    payload = [
        {
            "property_id": str(property_id),
            "keyword": kw,
            "source": "gsc",
            "created_by": auth["user_id"],
        }
        for kw in keywords
    ]
    # Idempotent: ignore keywords already tracked for this property.
    supabase.table("tracked_keywords").upsert(
        payload, on_conflict="property_id,keyword", ignore_duplicates=True
    ).execute()

    # Backfill metrics + status for the new keywords right away.
    rank_materialize.enqueue_materialize(str(property_id))

    return await list_keywords(property_id, auth)


@router.patch("/tracked-keywords/{keyword_id}", response_model=KeywordSummary)
async def update_keyword(
    keyword_id: UUID,
    body: TrackedKeywordUpdateRequest,
    auth: dict = Depends(require_admin),
) -> KeywordSummary:
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if not updates:
        raise HTTPException(status_code=422, detail="validation_error: no fields to update")
    updates["updated_at"] = "now()"

    supabase = get_supabase()
    result = (
        supabase.table("tracked_keywords")
        .update(updates)
        .eq("id", str(keyword_id))
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="not_found")
    k = result.data[0]
    metrics = _fetch_metrics(supabase, [k["id"]])
    summary = rank_status.compute_keyword_summary(metrics.get(k["id"], []), date.today())
    return KeywordSummary(
        id=k["id"],
        keyword=k["keyword"],
        source=k["source"],
        canonical_url=k.get("canonical_url"),
        canonical_url_locked=k["canonical_url_locked"],
        status=k["status"],
        status_updated_at=k.get("status_updated_at"),
        **summary,
    )


@router.delete("/tracked-keywords/{keyword_id}", status_code=204)
async def delete_keyword(keyword_id: UUID, auth: dict = Depends(require_admin)) -> None:
    get_supabase().table("tracked_keywords").delete().eq("id", str(keyword_id)).execute()


@router.get("/tracked-keywords/{keyword_id}/trendline", response_model=KeywordTrendline)
async def get_trendline(
    keyword_id: UUID, auth: dict = Depends(require_auth)
) -> KeywordTrendline:
    supabase = get_supabase()
    found = (
        supabase.table("tracked_keywords").select("*").eq("id", str(keyword_id)).limit(1).execute()
    )
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
        id=k["id"],
        keyword=k["keyword"],
        status=k["status"],
        canonical_url=k.get("canonical_url"),
        points=points,
    )


@router.get("/gsc-properties/{property_id}/overview", response_model=OverviewResponse)
async def get_overview(
    property_id: UUID, auth: dict = Depends(require_auth)
) -> OverviewResponse:
    supabase = get_supabase()
    kws = (
        supabase.table("tracked_keywords")
        .select("id, status")
        .eq("property_id", str(property_id))
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
        status_counts=status_counts,
        clicks_30d=clicks_30,
        impressions_30d=impressions_30,
        avg_position_30d=positions_30,
        at_risk=at_risk,
        hero=hero,
    )


@router.post("/gsc-properties/{property_id}/materialize", response_model=MaterializeResponse)
async def trigger_materialize(
    property_id: UUID, auth: dict = Depends(require_admin)
) -> MaterializeResponse:
    result = rank_materialize.materialize_property(str(property_id))
    return MaterializeResponse(
        property_id=property_id,
        status=result.status,
        keywords=result.keywords,
        rows=result.rows,
        error=result.error,
    )

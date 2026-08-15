"""Google Business Profile performance-metrics connection + ingest router.

GBP metrics ingestion. Lets the team register a client's GBP location, surface
the service-account email to add as a Manager, resolve the ``locations/{id}``
the Performance API needs, verify access, and trigger/observe ingests.

Mirrors routers/gsc.py. Authorization follows the suite model: any authenticated
user reads/manages (like clients). All DB access uses the service-role client.
The whole surface no-ops with clear errors while ``gbp_metrics_enabled`` is off.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from config import settings
from fastapi import APIRouter, Depends, HTTPException, Response

from db.supabase_client import get_supabase
from middleware.auth import require_admin, require_auth
from models.gbp_metrics import (
    GbpActionsSummary,
    GbpBackfillResponse,
    GbpBreakdown,
    GbpDashboardResponse,
    GbpIngestResponse,
    GbpLocation,
    GbpLocationCreateRequest,
    GbpMetricGrowth,
    GbpPerformanceDiagnostic,
    GbpPeriodReviews,
    GbpReviews,
    GbpSearchKeywordsResponse,
    GbpSeriesPoint,
    GbpServiceAccountInfo,
    GbpSyncRun,
    GbpVerifyResponse,
    ResolvedLocation,
    ResolveLocationsResponse,
)
from services import gbp_metrics_ingest, gbp_metrics_read
from services import gbp_performance_service as gbp

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gbp-metrics"])


@router.get("/gbp/service-account-email", response_model=GbpServiceAccountInfo)
async def get_service_account_email(auth: dict = Depends(require_auth)) -> GbpServiceAccountInfo:
    """The email the client adds as a Manager on their Business Profile."""
    try:
        return GbpServiceAccountInfo(email=gbp.get_service_account_email())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/gbp/diagnose-performance", response_model=GbpPerformanceDiagnostic)
async def diagnose_performance(
    auth: dict = Depends(require_admin),
) -> GbpPerformanceDiagnostic:
    """Admin-only: prove (or diagnose) live Business Profile Performance API access.

    Runs OUTSIDE the ``gbp_metrics_enabled`` gate on purpose — it's the check you
    run to decide whether that flag can be turned on. Uses the OAuth-preferred
    credential path the reporting tool will use, then walks accounts → locations →
    a 1-day metric fetch, classifying any failure (API not enabled / quota 0 / not
    a Manager) into per-step detail. No data is written."""
    return GbpPerformanceDiagnostic(**gbp.diagnose_performance())


@router.get("/gbp/resolve-locations", response_model=ResolveLocationsResponse)
async def resolve_locations(auth: dict = Depends(require_auth)) -> ResolveLocationsResponse:
    """List the GBP locations the service account can see, to register one.

    The Performance API keys on ``locations/{id}`` (not the Place ID we store),
    and only returns locations the service account manages — so this is how the
    team finds the right id after adding the SA as a Manager."""
    result = gbp.resolve_locations()
    return ResolveLocationsResponse(
        locations=[
            ResolvedLocation(
                location_id=loc.location_id,
                account_id=loc.account_id,
                title=loc.title,
                address=loc.address,
                place_id=loc.place_id,
            )
            for loc in result.locations
        ],
        detail=result.detail,
    )


@router.post("/gbp/onboard")
async def onboard_all_clients(auth: dict = Depends(require_admin)) -> dict:
    """Admin: bulk-onboard every client with a captured GBP but no registered
    location. Enqueues a single ``gbp_onboard`` job (resolve the connected
    account's listings once → auto-match each client → register + backfill).
    Idempotent: reuses an in-flight job instead of queuing a second."""
    supabase = get_supabase()
    pending = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "gbp_onboard")
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    ).data or []
    if pending:
        return {"status": "already_running", "job_id": pending[0]["id"]}
    res = (
        supabase.table("async_jobs")
        .insert({"job_type": "gbp_onboard", "payload": {"user_id": auth["user_id"]}})
        .execute()
    )
    return {"status": "queued", "job_id": res.data[0]["id"]}


@router.get("/gbp/onboard/status")
async def onboard_status(auth: dict = Depends(require_admin)) -> dict:
    """Admin: the latest bulk-onboard job's status + result (for the button poll)."""
    supabase = get_supabase()
    rows = (
        supabase.table("async_jobs")
        .select("id, status, result, error, created_at, completed_at")
        .eq("job_type", "gbp_onboard")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data or []
    return rows[0] if rows else {"status": "none"}


def _latest_metric_date(supabase, loc_ids: list[str]) -> Optional[date]:
    """The most recent date any of the locations has metric data for (a single
    indexed ``max(date)`` read). This anchors the comparison windows exactly, so
    staleness of any size is handled — the read is scoped to two full windows
    ending here rather than guessing a lag buffer back from today."""
    res = (
        supabase.table("gbp_metric_daily")
        .select("date")
        .in_("location_row_id", loc_ids)
        .order("date", desc=True)
        .limit(1)
        .execute()
    ).data or []
    if not res:
        return None
    d = res[0].get("date")
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(d) if d else None
    except ValueError:
        return None


def _latest_timestamp(values: list[Optional[str]]) -> Optional[str]:
    """The latest ISO timestamp among values, chosen by parsed instant rather
    than a lexicographic string max (which would misorder mixed offset/precision
    forms). Returns the original string so the response keeps the DB format."""
    best: Optional[str] = None
    best_dt: Optional[datetime] = None
    for v in values:
        if not v:
            continue
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if best_dt is None or dt > best_dt:
            best_dt, best = dt, v
    return best


def _fetch_metric_rows(supabase, loc_ids: list[str], start: date, end: date) -> list[dict]:
    """Read every gbp_metric_daily row for the locations over [start, end].

    Paginated in 1000-row pages: a 365-day window across 8 metrics is ~2,920 rows
    for one location, past PostgREST's default cap — an unpaged read would silently
    truncate the oldest days and skew the growth math. Ordered on the full primary
    key (date, metric, location_row_id) so the ordering is *total*: ordering on
    ``date`` alone leaves a single day's ~8 metric rows in an arbitrary,
    run-to-run-unstable order, which offset pagination can split across a page
    boundary and duplicate or drop."""
    rows: list[dict] = []
    page = 1000
    offset = 0
    while True:
        batch = (
            supabase.table("gbp_metric_daily")
            .select("date, metric, value")
            .in_("location_row_id", loc_ids)
            .gte("date", start.isoformat())
            .lte("date", end.isoformat())
            .order("date")
            .order("metric")
            .order("location_row_id")
            .range(offset, offset + page - 1)
            .execute()
        ).data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows


_MAX_CUSTOM_RANGE_DAYS = 366


def _parse_custom_range(start: str, end: str) -> tuple[date, date]:
    """Validate a custom [start, end] date range → (start, end). Raises 422."""
    try:
        cur_start = date.fromisoformat(start)
        cur_end = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_date: use YYYY-MM-DD")
    if cur_end < cur_start:
        raise HTTPException(status_code=422, detail="invalid_range: end before start")
    if (cur_end - cur_start).days + 1 > _MAX_CUSTOM_RANGE_DAYS:
        raise HTTPException(status_code=422, detail="range_too_large: max 366 days")
    return cur_start, cur_end


@router.get("/clients/{client_id}/gbp-metrics/dashboard", response_model=GbpDashboardResponse)
async def gbp_dashboard(
    client_id: UUID,
    window: int = 30,
    start: str | None = None,
    end: str | None = None,
    auth: dict = Depends(require_auth),
) -> GbpDashboardResponse:
    """The GBP Insights read: connection state + registered locations + growth
    KPI tiles + a daily series, aggregated across the client's verified (``ok``)
    locations. Mirrors the client PDF report's GBP-metrics gathering.

    Two ways to pick the period, both compared against the equal-length window
    immediately before it:
      * ``window`` — a trailing preset (days), clamped [7, 365]; the period ends
        at the last day with data (so GBP's reporting lag doesn't skew growth).
      * ``start`` + ``end`` (YYYY-MM-DD, both required) — an explicit range,
        honored as given; max 366 days.
    """
    custom = bool(start or end)
    if custom and not (start and end):
        raise HTTPException(status_code=422, detail="start and end are both required")

    if custom:
        cs, ce = _parse_custom_range(start, end)  # type: ignore[arg-type]
        cur_end_fixed: Optional[date] = ce
        window_days = (ce - cs).days + 1
    else:
        window_days = max(7, min(int(window), 365))
        cur_end_fixed = None

    supabase = get_supabase()
    try:
        locs = (
            supabase.table("gbp_locations")
            .select("*")
            .eq("client_id", str(client_id))
            .order("created_at")
            .execute()
        ).data or []
    except Exception as exc:  # DB read failure → clean 500, not a stack trace
        logger.error("gbp_dashboard_locations_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error")

    location_models = [GbpLocation(**row) for row in locs]
    ok_ids = [row["id"] for row in locs if row.get("access_status") == "ok"]

    today = date.today()
    rows: list[dict] = []
    try:
        # Custom range: honor the given end. Preset: anchor at the last day that
        # actually has data (a max(date) pre-query) — anchoring at today would
        # compare a current window still missing its not-yet-arrived days
        # against a complete prior window, reading as a spurious decline.
        if cur_end_fixed is not None:
            cur_end = cur_end_fixed
        elif ok_ids:
            cur_end = _latest_metric_date(supabase, ok_ids) or today
        else:
            cur_end = today
        cur_start = cur_end - timedelta(days=window_days - 1)
        prev_end = cur_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=window_days - 1)
        if ok_ids:
            rows = _fetch_metric_rows(supabase, ok_ids, prev_start, cur_end)
    except Exception as exc:
        logger.error("gbp_dashboard_metrics_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error")

    cards = gbp_metrics_read.build_growth_cards(rows, cur_end, window_days)
    breakdown = gbp_metrics_read.build_breakdown(rows, cur_end, window_days)
    actions = gbp_metrics_read.build_actions_summary(rows, cur_end, window_days)
    insights = gbp_metrics_read.build_insights(cards, breakdown, actions)

    cur_lo = cur_start.isoformat()
    window_rows = [r for r in rows if (r.get("date") or "") >= cur_lo]
    series = gbp_metrics_read.build_series(window_rows, cur_start, cur_end)
    prev_lo, prev_hi = prev_start.isoformat(), prev_end.isoformat()
    prev_rows = [r for r in rows if prev_lo <= (r.get("date") or "") <= prev_hi]
    compare_series = gbp_metrics_read.build_series(prev_rows, prev_start, prev_end)

    last_synced_at = _latest_timestamp([row.get("last_synced_at") for row in locs])

    reviews = {"rating": None, "review_count": 0, "items": []}
    try:  # profile-health review summary — best-effort, never blocks the dashboard
        crow = (
            supabase.table("clients").select("gbp").eq("id", str(client_id)).limit(1).execute()
        ).data or []
        if crow:
            reviews = gbp_metrics_read.build_reviews(crow[0].get("gbp"))
    except Exception as exc:
        logger.info("gbp_dashboard_reviews_failed", extra={"client_id": str(client_id), "error": str(exc)})

    return GbpDashboardResponse(
        enabled=settings.gbp_metrics_enabled,
        connected=bool(ok_ids),
        locations=location_models,
        window_days=window_days,
        date_start=cur_start.isoformat(),
        date_end=cur_end.isoformat(),
        compare_start=prev_start.isoformat(),
        compare_end=prev_end.isoformat(),
        last_synced_at=last_synced_at,
        metrics=[GbpMetricGrowth(**c) for c in cards],
        breakdown=GbpBreakdown(**breakdown),
        actions=GbpActionsSummary(**actions),
        insights=insights,
        reviews=GbpReviews(**reviews),
        series=[GbpSeriesPoint(**p) for p in series],
        compare_series=[GbpSeriesPoint(**p) for p in compare_series],
    )


@router.get("/clients/{client_id}/gbp-metrics/export")
async def gbp_metrics_export(
    client_id: UUID,
    window: int = 30,
    start: str | None = None,
    end: str | None = None,
    auth: dict = Depends(require_auth),
) -> Response:
    """Download the client's GBP daily metrics as CSV over the same period the
    dashboard shows (preset ``window`` or explicit ``start``/``end``)."""
    custom = bool(start or end)
    if custom and not (start and end):
        raise HTTPException(status_code=422, detail="start and end are both required")
    if custom:
        cs, ce = _parse_custom_range(start, end)  # type: ignore[arg-type]
        cur_end, window_days = ce, (ce - cs).days + 1
    else:
        window_days = max(7, min(int(window), 365))
        cur_end = None  # resolved below

    supabase = get_supabase()
    try:
        ok = (
            supabase.table("gbp_locations").select("id")
            .eq("client_id", str(client_id)).eq("access_status", "ok").execute()
        ).data or []
        ok_ids = [r["id"] for r in ok]
        if cur_end is None:
            cur_end = (_latest_metric_date(supabase, ok_ids) if ok_ids else None) or date.today()
        cur_start = cur_end - timedelta(days=window_days - 1)
        rows = _fetch_metric_rows(supabase, ok_ids, cur_start, cur_end) if ok_ids else []
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("gbp_export_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error")

    series = gbp_metrics_read.build_series(rows, cur_start, cur_end)
    buf = io.StringIO()
    csv.writer(buf).writerows(gbp_metrics_read.csv_rows(series))
    filename = f"gbp-metrics-{cur_start.isoformat()}-to-{cur_end.isoformat()}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/clients/{client_id}/gbp-metrics/search-keywords", response_model=GbpSearchKeywordsResponse)
async def gbp_search_keywords_read(
    client_id: UUID, month: str | None = None, limit: int = 25, auth: dict = Depends(require_auth)
) -> GbpSearchKeywordsResponse:
    """Top search terms that drove impressions for the client's verified
    locations. Defaults to the latest month with data; ``month`` (YYYY-MM-01)
    picks a specific one. Monthly data — low-volume terms are privacy-floored."""
    from services import gbp_search_keywords as skw

    try:
        data = skw.read_keywords(str(client_id), month=month, limit=max(1, min(int(limit), 500)))
    except Exception as exc:
        logger.error("gbp_search_keywords_read_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error")
    return GbpSearchKeywordsResponse(**data)


@router.get("/clients/{client_id}/gbp-metrics/reviews", response_model=GbpPeriodReviews)
async def gbp_period_reviews(
    client_id: UUID, start: str, end: str, limit: int = 50, auth: dict = Depends(require_auth)
) -> GbpPeriodReviews:
    """Reviews posted within ``[start, end]`` (YYYY-MM-DD, inclusive) across the
    client's verified locations, from the first-party v4 reviews store. The
    frontend passes the dashboard's resolved ``date_start`` / ``date_end`` so the
    panel matches the shown period."""
    cs, ce = _parse_custom_range(start, end)  # validates YYYY-MM-DD + ordering
    from services import gbp_reviews_ingest

    try:
        data = gbp_reviews_ingest.read_period_reviews(
            str(client_id), cs.isoformat(), ce.isoformat(), limit=max(1, min(int(limit), 200))
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("gbp_period_reviews_failed", extra={"client_id": str(client_id), "error": str(exc)})
        raise HTTPException(status_code=500, detail="internal_error")
    return GbpPeriodReviews(**data, start=cs.isoformat(), end=ce.isoformat())


@router.get("/clients/{client_id}/gbp-locations", response_model=list[GbpLocation])
async def list_locations(
    client_id: UUID, auth: dict = Depends(require_auth)
) -> list[GbpLocation]:
    supabase = get_supabase()
    result = (
        supabase.table("gbp_locations")
        .select("*")
        .eq("client_id", str(client_id))
        .order("created_at")
        .execute()
    )
    return [GbpLocation(**row) for row in (result.data or [])]


@router.post("/clients/{client_id}/gbp-locations", response_model=GbpLocation)
async def create_location(
    client_id: UUID,
    body: GbpLocationCreateRequest,
    auth: dict = Depends(require_auth),
) -> GbpLocation:
    try:
        location_id = gbp.normalize_location_id(body.location_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"validation_error: {exc}")

    supabase = get_supabase()
    try:
        result = (
            supabase.table("gbp_locations")
            .insert(
                {
                    "client_id": str(client_id),
                    "location_id": location_id,
                    "account_id": body.account_id,
                    "place_id": body.place_id,
                    "title": body.title,
                    "access_status": "pending",
                    "created_by": auth["user_id"],
                }
            )
            .execute()
        )
    except Exception as exc:
        logger.error("gbp_location_create_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=409, detail="conflict: location already registered for this client"
        )
    return GbpLocation(**result.data[0])


@router.delete("/gbp-locations/{location_row_id}", status_code=204, response_class=Response)
async def delete_location(location_row_id: UUID, auth: dict = Depends(require_auth)) -> Response:
    supabase = get_supabase()
    supabase.table("gbp_locations").delete().eq("id", str(location_row_id)).execute()
    return Response(status_code=204)


@router.post("/gbp-locations/{location_row_id}/verify", response_model=GbpVerifyResponse)
async def verify_location(
    location_row_id: UUID, auth: dict = Depends(require_auth)
) -> GbpVerifyResponse:
    """Run a live 1-day fetch and update the location's access_status."""
    supabase = get_supabase()
    found = (
        supabase.table("gbp_locations").select("*").eq("id", str(location_row_id)).limit(1).execute()
    )
    if not found.data:
        raise HTTPException(status_code=404, detail="not_found")
    loc = found.data[0]

    result = gbp.verify_location_access(loc["location_id"])

    # Persist only definitive ok/no_access; a transient 'error' (key/quota)
    # leaves the stored status unchanged and is surfaced via `detail`.
    if result.status in ("ok", "no_access"):
        now = datetime.now(timezone.utc).isoformat()
        updated = (
            supabase.table("gbp_locations")
            .update({"access_status": result.status, "last_verified_at": now, "updated_at": now})
            .eq("id", str(location_row_id))
            .execute()
        )
        row = updated.data[0]
        return GbpVerifyResponse(
            location_row_id=location_row_id,
            access_status=row["access_status"],
            detail=result.detail,
            last_verified_at=row["last_verified_at"],
        )

    return GbpVerifyResponse(
        location_row_id=location_row_id,
        access_status=loc["access_status"],
        detail=result.detail,
        last_verified_at=loc.get("last_verified_at"),
    )


@router.post("/gbp-locations/{location_row_id}/ingest", response_model=GbpIngestResponse)
async def trigger_ingest(
    location_row_id: UUID,
    start_date: str | None = None,
    end_date: str | None = None,
    auth: dict = Depends(require_auth),
) -> GbpIngestResponse:
    """Run a GBP metrics ingest now. Omit dates for the default trailing window."""
    result = gbp_metrics_ingest.ingest_location(str(location_row_id), start_date, end_date)
    return GbpIngestResponse(
        location_row_id=location_row_id,
        status=result.status,
        rows=result.rows,
        error=result.error,
    )


@router.post("/gbp-locations/{location_row_id}/backfill", response_model=GbpBackfillResponse)
async def trigger_backfill(
    location_row_id: UUID, auth: dict = Depends(require_auth)
) -> GbpBackfillResponse:
    """Queue a one-time historical pull (~18 months) via the job worker."""
    supabase = get_supabase()
    found = (
        supabase.table("gbp_locations")
        .select("id, access_status")
        .eq("id", str(location_row_id))
        .limit(1)
        .execute()
    )
    if not found.data:
        raise HTTPException(status_code=404, detail="not_found")
    if found.data[0]["access_status"] != "ok":
        raise HTTPException(status_code=422, detail="location_not_verified")

    end = date.today()
    start = end - timedelta(days=settings.gbp_metrics_backfill_days)
    pending = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "gbp_metrics_ingest")
        .eq("entity_id", str(location_row_id))
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if not pending.data:
        supabase.table("async_jobs").insert(
            {
                "job_type": "gbp_metrics_ingest",
                "entity_id": str(location_row_id),
                "payload": {
                    "location_row_id": str(location_row_id),
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                },
            }
        ).execute()
    return GbpBackfillResponse(
        location_row_id=location_row_id,
        status="queued",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )


@router.get("/gbp-locations/{location_row_id}/sync-runs", response_model=list[GbpSyncRun])
async def list_sync_runs(
    location_row_id: UUID, auth: dict = Depends(require_auth)
) -> list[GbpSyncRun]:
    supabase = get_supabase()
    result = (
        supabase.table("gbp_sync_runs")
        .select("*")
        .eq("location_row_id", str(location_row_id))
        .order("run_at", desc=True)
        .limit(20)
        .execute()
    )
    return [GbpSyncRun(**row) for row in (result.data or [])]

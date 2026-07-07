"""Google Business Profile performance-metrics access (service account).

GBP metrics ingestion — the "Connection" layer. Reuses the agency-owned service
account already used for GSC (``settings.google_service_account_key``); GBP just
needs the wider ``business.manage`` scope and the service account added as a
**Manager** on each client's Business Profile (the per-client onboarding
equivalent of adding it as a user on a GSC property).

Three Google APIs are involved:
  * **Account Management API** (``mybusinessaccountmanagement``) — list the
    accounts the service account can see.
  * **Business Information API** (``mybusinessbusinessinformation``) — list each
    account's locations, whose resource name (``locations/{id}``) is the key the
    Performance API needs (this is NOT the Place ID we already store).
  * **Business Profile Performance API** (``businessprofileperformance``) — the
    daily metric time-series itself.

Google client libraries are imported lazily so this module (and its unit tests)
import cleanly where the libraries aren't installed. The pure parse/classify
helpers have no Google dependency and are independently unit-tested.

⚠️ This path is dormant until Google approves Business Profile API quota for the
GCP project (0 QPM by default) — nothing here returns data before that.

See: docs/modules/client-reporting-prd-v1_0.md (Phase 2 — GBP Performance).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

from config import settings
from services import gsc_service

logger = logging.getLogger(__name__)

# GBP metrics need the broad business.manage scope (there is no read-only GBP
# scope). Distinct from GSC's webmasters.readonly — same key, wider grant.
SCOPES = ["https://www.googleapis.com/auth/business.manage"]

AccessStatus = Literal["ok", "no_access", "pending", "error"]

# The daily metrics the Performance API exposes. We pull the engagement +
# impression set relevant to local SEO reporting; food/booking metrics are
# omitted (irrelevant to our client base) but can be appended without a schema
# change — gbp_metric_daily is metric-as-row.
DEFAULT_METRICS: list[str] = [
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
    "BUSINESS_CONVERSATIONS",
    "BUSINESS_DIRECTION_REQUESTS",
    "CALL_CLICKS",
    "WEBSITE_CLICKS",
]


@dataclass
class VerifyResult:
    """Outcome of a location access check."""

    status: AccessStatus
    detail: Optional[str] = None


@dataclass
class ResolvedLocation:
    location_id: str
    account_id: Optional[str] = None
    title: Optional[str] = None
    address: Optional[str] = None
    place_id: Optional[str] = None


@dataclass
class ResolveResult:
    locations: list[ResolvedLocation] = field(default_factory=list)
    detail: Optional[str] = None


# ----------------------------------------------------------------------------
# Pure helpers (no Google dependency) — independently unit-tested.
# ----------------------------------------------------------------------------
def is_configured() -> bool:
    """Whether the agency service-account key is present AND GBP metrics are
    enabled. GBP calls no-op until both hold."""
    raw = settings.google_service_account_key
    return bool(settings.gbp_metrics_enabled and raw and raw.strip())


def normalize_location_id(value: str) -> str:
    """Canonicalize a location resource name to ``locations/{id}``.

    Accepts a bare id, ``locations/{id}``, or an ``accounts/x/locations/{id}``
    form and normalizes to the ``locations/{id}`` the Performance API wants.
    Raises ValueError on empty input.
    """
    v = (value or "").strip()
    if not v:
        raise ValueError("location_id is required")
    # Pull the trailing 'locations/{id}' if a longer resource path was pasted.
    if "locations/" in v:
        tail = v.split("locations/", 1)[1].strip().strip("/")
        if not tail or "/" in tail:
            raise ValueError("location_id must be 'locations/{id}'")
        return f"locations/{tail}"
    if "/" in v or " " in v:
        raise ValueError("location_id must be 'locations/{id}' or a bare id")
    return f"locations/{v}"


def _date_str(d: dict) -> Optional[str]:
    """Format a google.type.Date dict {year,month,day} as YYYY-MM-DD."""
    if not isinstance(d, dict):
        return None
    y, m, day = d.get("year"), d.get("month"), d.get("day")
    if not (y and m and day):
        return None
    return f"{int(y):04d}-{int(m):02d}-{int(day):02d}"


def _to_int(value) -> int:
    """Performance API serializes int64 values as strings (and omits zeros)."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_time_series(payload: dict) -> list[dict]:
    """Map a ``fetchMultiDailyMetricsTimeSeries`` response to flat records.

    Response shape::

        {"multiDailyMetricTimeSeries": [
           {"dailyMetricTimeSeries": [
              {"dailyMetric": "CALL_CLICKS",
               "timeSeries": {"datedValues": [
                  {"date": {"year": 2026, "month": 7, "day": 1}, "value": "12"}, ...]}}]}]}

    Returns ``[{"metric", "date", "value"}, ...]`` — one per dated value with a
    resolvable date. A missing ``value`` means 0.
    """
    out: list[dict] = []
    for multi in payload.get("multiDailyMetricTimeSeries", []) or []:
        for series in multi.get("dailyMetricTimeSeries", []) or []:
            metric = series.get("dailyMetric")
            if not metric:
                continue
            dated = (series.get("timeSeries") or {}).get("datedValues") or []
            for dv in dated:
                dstr = _date_str(dv.get("date") or {})
                if not dstr:
                    continue
                out.append({"metric": metric, "date": dstr, "value": _to_int(dv.get("value"))})
    return out


def classify_access_error(status_code: Optional[int]) -> VerifyResult:
    """Map an HTTP status from a live call into an access state."""
    if status_code in (401, 403):
        return VerifyResult(
            status="no_access",
            detail="service_account_not_a_manager_or_insufficient_permission",
        )
    if status_code == 429:
        # Quota not yet granted (0 QPM default) or rate-limited.
        return VerifyResult(status="error", detail="quota_exceeded_or_not_granted")
    if status_code in (400, 404):
        return VerifyResult(status="no_access", detail="location_not_recognized")
    return VerifyResult(
        status="error", detail=f"http_{status_code}" if status_code else "unknown_error"
    )


# ----------------------------------------------------------------------------
# Service-account identity + clients (lazy Google imports)
# ----------------------------------------------------------------------------
def get_service_account_email() -> str:
    """The email clients add as a Manager on their Business Profile."""
    return gsc_service.get_service_account_email()


def _credentials():
    from google.oauth2 import service_account  # noqa: PLC0415

    return service_account.Credentials.from_service_account_info(
        gsc_service._load_key(), scopes=SCOPES
    )


def _build(service_name: str, version: str = "v1"):
    from googleapiclient.discovery import build  # noqa: PLC0415

    return build(service_name, version, credentials=_credentials(), cache_discovery=False)


def build_performance_client():
    """Authenticated Business Profile Performance API client."""
    return _build("businessprofileperformance", "v1")


def build_account_client():
    return _build("mybusinessaccountmanagement", "v1")


def build_business_info_client():
    return _build("mybusinessbusinessinformation", "v1")


# ----------------------------------------------------------------------------
# Live operations
# ----------------------------------------------------------------------------
def resolve_locations() -> ResolveResult:
    """List every location the service account can see, across all accounts.

    Used at connection time to offer the user the ``locations/{id}`` to register
    (they can't get it from the Place ID we store). Best-effort: on any API
    error returns an empty list + a detail string rather than raising.
    """
    if not is_configured():
        return ResolveResult(detail="gbp_metrics_not_configured")
    try:
        accounts_client = build_account_client()
        info_client = build_business_info_client()
    except Exception as exc:  # pragma: no cover - client build failure
        logger.error("gbp_client_build_failed", extra={"error": str(exc)})
        return ResolveResult(detail="client_build_failed")

    try:
        acct_resp = accounts_client.accounts().list().execute()
    except Exception as exc:
        code = gsc_service._extract_status_code(exc)
        logger.info("gbp_accounts_list_failed", extra={"status_code": code})
        return ResolveResult(detail=classify_access_error(code).detail or "accounts_list_failed")

    resolved: list[ResolvedLocation] = []
    for acct in acct_resp.get("accounts", []) or []:
        account_id = acct.get("name")  # 'accounts/{id}'
        if not account_id:
            continue
        try:
            loc_resp = (
                info_client.accounts()
                .locations()
                .list(
                    parent=account_id,
                    readMask="name,title,storefrontAddress,metadata",
                )
                .execute()
            )
        except Exception as exc:
            logger.info(
                "gbp_locations_list_failed",
                extra={"account_id": account_id, "status_code": gsc_service._extract_status_code(exc)},
            )
            continue
        for loc in loc_resp.get("locations", []) or []:
            name = loc.get("name")  # 'locations/{id}'
            if not name:
                continue
            addr = loc.get("storefrontAddress") or {}
            lines = addr.get("addressLines") or []
            locality = addr.get("locality")
            address = ", ".join([*lines, locality] if locality else lines) or None
            resolved.append(
                ResolvedLocation(
                    location_id=name,
                    account_id=account_id,
                    title=loc.get("title"),
                    address=address,
                    place_id=(loc.get("metadata") or {}).get("placeId"),
                )
            )
    return ResolveResult(locations=resolved)


def _google_date(d: date) -> dict:
    return {"year": d.year, "month": d.month, "day": d.day}


def fetch_daily_metrics(
    location_id: str, start: date, end: date, metrics: Optional[list[str]] = None
) -> list[dict]:
    """Fetch a daily metric time-series window for one location.

    ``location_id`` must be normalized (``locations/{id}``). Returns the flat
    parsed records (see ``parse_time_series``). Raises on API error so the
    caller can classify it (e.g. a 403 → no_access).
    """
    client = build_performance_client()
    metrics = metrics or DEFAULT_METRICS
    request = (
        client.locations().fetchMultiDailyMetricsTimeSeries(
            location=location_id,
            dailyMetrics=metrics,
            **{
                "dailyRange_startDate_year": start.year,
                "dailyRange_startDate_month": start.month,
                "dailyRange_startDate_day": start.day,
                "dailyRange_endDate_year": end.year,
                "dailyRange_endDate_month": end.month,
                "dailyRange_endDate_day": end.day,
            },
        )
    )
    resp = request.execute()
    return parse_time_series(resp)


def verify_location_access(location_id: str) -> VerifyResult:
    """Prove read access by fetching a tiny 1-day window. Classifies the result."""
    if not settings.gbp_metrics_enabled:
        return VerifyResult(status="error", detail="gbp_metrics_disabled")
    try:
        normalized = normalize_location_id(location_id)
    except ValueError as exc:
        return VerifyResult(status="error", detail=str(exc))
    try:
        # A single recent day is enough to prove access; data lag makes an old
        # date safest (guaranteed to exist for an active listing).
        from datetime import timedelta

        end = date.today() - timedelta(days=5)
        fetch_daily_metrics(normalized, end, end, metrics=["CALL_CLICKS"])
        return VerifyResult(status="ok")
    except RuntimeError as exc:
        # Missing/invalid key.
        logger.error("gbp_service_account_unavailable", extra={"error": str(exc)})
        return VerifyResult(status="error", detail=str(exc))
    except Exception as exc:
        code = gsc_service._extract_status_code(exc)
        logger.info("gbp_verify_failed", extra={"location_id": normalized, "status_code": code})
        return classify_access_error(code)

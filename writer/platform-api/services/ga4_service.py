"""Google Analytics (GA4) service-account access.

Client Reporting Phase 2 (docs/modules/client-reporting-prd-v1_0.md §Phase 2 —
"GA4 connector: sessions/users/conversions/channels"). Mirrors gsc_service.py:
the agency-owned service-account identity + the property "verify access" check +
the read calls the report gatherer and daily ingest use.

The service-account key lives once at the app level in
``settings.google_service_account_key`` (the same key GSC/GBP already use),
never per-client and never in the database. Clients grant access by adding the
service account's email (``client_email`` in the key) as a **Viewer** on their
GA4 property; after that the app reads their data as the service account.

Unlike GSC (which uses the discovery client), GA4 is read over plain REST with a
token minted from the same service-account key — so there is **no new
dependency** (google-auth + httpx are already required) and the transport matches
``scripts/verify_ga4_api_access.py``. Google imports stay lazy so this module and
its unit tests import cleanly where the libraries are not installed.

See: docs/modules/client-reporting-prd-v1_0.md; the preflight
``scripts/verify_ga4_api_access.py`` proves access layer by layer.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Read-only analytics data is all the reporting connector needs.
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

DATA_API = "https://analyticsdata.googleapis.com/v1beta"
ADMIN_API = "https://analyticsadmin.googleapis.com/v1beta"
_TIMEOUT = 60

AccessStatus = str  # 'ok' | 'no_access' | 'pending' | 'error'

# The metrics the daily ingest pulls at the date level. Kept as a module
# constant (not inlined) so the set is tunable from one place once we've
# confirmed the exact metric names a live property accepts — GA4 renamed
# ``conversions`` to ``keyEvents`` in 2024, so conversions is fetched
# best-effort separately and never fails the core pull (see ``run_report``).
CORE_METRICS = ["sessions", "totalUsers", "screenPageViews"]
# GA4 renamed the conversions metric to ``keyEvents`` in 2024. Try the new name
# first, fall back to the legacy one, and only then drop conversions — so a
# property on either naming still reports conversions (fetch_daily_metrics).
CONVERSION_METRIC = "keyEvents"
CONVERSION_METRIC_LEGACY = "conversions"
# The dimension the channel-breakdown report groups sessions by.
CHANNEL_DIMENSION = "sessionDefaultChannelGroup"
# Page size for runReport pagination. The Data API caps a request at 250k rows;
# we page at 100k and loop on rowCount so a large window never silently truncates.
_PAGE_SIZE = 100000


@dataclass
class VerifyResult:
    """Outcome of a property access check (mirrors gsc_service.VerifyResult)."""

    status: AccessStatus
    detail: Optional[str] = None


@dataclass
class PropertySummary:
    """A GA4 property the service account can see (from the Admin API)."""

    property_id: str  # "properties/123456789"
    display_name: str
    account_name: str = ""


# ----------------------------------------------------------------------------
# Pure helpers (no Google/network dependency) — independently unit-tested.
# ----------------------------------------------------------------------------
_PROPERTY_RE = re.compile(r"^properties/\d+$")


def normalize_property_id(value: str) -> str:
    """Accept ``properties/123`` or a bare ``123`` → ``properties/123``; else raise.

    The GA4 Data API addresses a property as ``properties/<numeric id>``. A
    display name or a URL is not valid, so we validate up front — mirroring
    gsc_service.normalize_site_url — so a bad value fails at create time rather
    than as an opaque 400 at read time.
    """
    v = (value or "").strip()
    if not v:
        raise ValueError("property_id is required")
    if v.startswith("properties/"):
        candidate = v
    elif v.isdigit():
        candidate = f"properties/{v}"
    else:
        raise ValueError("property_id must be 'properties/123456789' or a numeric id")
    if not _PROPERTY_RE.match(candidate):
        raise ValueError("property_id must be 'properties/123456789' or a numeric id")
    return candidate


def parse_report_rows(resp: dict) -> list[dict]:
    """Map a runReport response to flat rows keyed by its own dimension + metric
    header names — e.g. ``{"date": "20260814", "sessions": 120.0, ...}``.

    Reads the header names straight from the response (not the request), so a
    single- or multi-dimension report parses the same way. GA4 returns every
    metric value as a string, so we coerce to float. Pure — no network."""
    dim_headers = [h.get("name") for h in resp.get("dimensionHeaders", []) or []]
    metric_headers = [h.get("name") for h in resp.get("metricHeaders", []) or []]
    rows: list[dict] = []
    for raw in resp.get("rows", []) or []:
        record: dict = {}
        dim_values = raw.get("dimensionValues", []) or []
        for name, dv in zip(dim_headers, dim_values):
            record[name] = dv.get("value")
        metric_values = raw.get("metricValues", []) or []
        for name, mv in zip(metric_headers, metric_values):
            record[name] = _to_float(mv.get("value"))
        rows.append(record)
    return rows


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def classify_access_error(status_code: Optional[int], message: str = "") -> VerifyResult:
    """Map an HTTP status from a GA4 call into an access state (mirrors GSC)."""
    lowered = (message or "").lower()
    if status_code == 403 and ("has not been used" in lowered or "disabled" in lowered):
        # The API itself is not enabled — a setup problem, not a per-property one.
        return VerifyResult(status="error", detail="ga4_api_not_enabled")
    if status_code in (401, 403):
        return VerifyResult(
            status="no_access",
            detail="service_account_not_added_or_insufficient_permission",
        )
    if status_code in (400, 404):
        return VerifyResult(status="no_access", detail="property_not_recognized")
    if status_code == 429:
        return VerifyResult(status="error", detail="rate_limited")
    return VerifyResult(
        status="error", detail=f"http_{status_code}" if status_code else "unknown_error"
    )


# ----------------------------------------------------------------------------
# Service-account identity + auth
# ----------------------------------------------------------------------------
def is_configured() -> bool:
    """Whether the agency service-account key is present (live GA4 calls work)."""
    raw = settings.google_service_account_key
    return bool(raw and raw.strip())


def _load_key() -> dict:
    raw = settings.google_service_account_key
    if not raw or not raw.strip():
        raise RuntimeError("google_service_account_key_not_configured")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("google_service_account_key_invalid_json") from exc


def get_service_account_email() -> str:
    """The ``client_email`` clients must add as a Viewer on their GA4 property."""
    email = _load_key().get("client_email")
    if not email:
        raise RuntimeError("google_service_account_key_missing_client_email")
    return email


def _mint_token() -> str:
    """Mint an OAuth token for the analytics.readonly scope (lazy Google imports).

    Uses the same transport-fallback dance as scripts/verify_ga4_api_access.py so
    it works whether or not ``requests`` is installed alongside google-auth."""
    from google.oauth2 import service_account  # noqa: PLC0415

    creds = service_account.Credentials.from_service_account_info(
        _load_key(), scopes=SCOPES
    )
    try:
        from google.auth.transport.requests import Request  # noqa: PLC0415

        creds.refresh(Request())
    except ImportError:  # pragma: no cover - depends on installed transport
        import google_auth_httplib2  # noqa: PLC0415
        import httplib2  # noqa: PLC0415

        creds.refresh(google_auth_httplib2.Request(httplib2.Http()))
    return creds.token


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_mint_token()}"}


class Ga4ApiError(Exception):
    """A GA4 REST call returned a non-2xx status. Carries the HTTP code so the
    caller can classify it (mirrors how gsc_service uses HttpError.resp.status)."""

    def __init__(self, status_code: Optional[int], message: str = ""):
        self.status_code = status_code
        self.message = message
        super().__init__(f"ga4_api_error http_{status_code}: {message[:200]}")


def _post(url: str, body: dict) -> dict:
    with httpx.Client(timeout=_TIMEOUT) as http:
        resp = http.post(url, headers=_auth_headers(), json=body)
    if resp.status_code != 200:
        raise Ga4ApiError(resp.status_code, _error_message(resp))
    return resp.json()


def _get(url: str) -> dict:
    with httpx.Client(timeout=_TIMEOUT) as http:
        resp = http.get(url, headers=_auth_headers())
    if resp.status_code != 200:
        raise Ga4ApiError(resp.status_code, _error_message(resp))
    return resp.json()


def _error_message(resp: httpx.Response) -> str:
    try:
        return resp.json().get("error", {}).get("message", "") or resp.text[:300]
    except Exception:  # noqa: BLE001
        return resp.text[:300]


# ----------------------------------------------------------------------------
# Read calls
# ----------------------------------------------------------------------------
def list_property_summaries() -> list[PropertySummary]:
    """Every GA4 property the service account can see, via the Admin API.

    Powers property discovery in the connect UI (so the team doesn't hand-type
    numeric ids). Raises Ga4ApiError so the caller can classify (Admin API not
    enabled vs SA added nowhere yet)."""
    resp = _get(f"{ADMIN_API}/accountSummaries")
    summaries: list[PropertySummary] = []
    for acct in resp.get("accountSummaries", []) or []:
        account_name = acct.get("displayName", "")
        for prop in acct.get("propertySummaries", []) or []:
            res = prop.get("property")
            if res:
                summaries.append(
                    PropertySummary(
                        property_id=res,
                        display_name=prop.get("displayName", ""),
                        account_name=account_name,
                    )
                )
    return summaries


def run_report(
    property_id: str,
    start_date: str,
    end_date: str,
    metrics: list[str],
    dimensions: Optional[list[str]] = None,
) -> list[dict]:
    """Run a GA4 report and return all flat parsed rows, paginating on rowCount
    so a window larger than one page is never silently truncated. ``property_id``
    must be normalized. Raises Ga4ApiError on a non-200 so the caller can
    classify."""
    body: dict = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "metrics": [{"name": m} for m in metrics],
    }
    if dimensions:
        body["dimensions"] = [{"name": d} for d in dimensions]

    rows: list[dict] = []
    offset = 0
    while True:
        body["limit"] = _PAGE_SIZE
        body["offset"] = offset
        resp = _post(f"{DATA_API}/{property_id}:runReport", body)
        page = parse_report_rows(resp)
        rows.extend(page)
        row_count = int(resp.get("rowCount", 0) or 0)
        # Stop on a short page (last page) or once we've covered rowCount. The
        # short-page check also guarantees termination if rowCount is missing.
        if len(page) < _PAGE_SIZE or offset + _PAGE_SIZE >= row_count:
            break
        offset += _PAGE_SIZE
    return rows


def _fetch_date_rows(
    property_id: str, start_date: str, end_date: str, metrics: list[str]
) -> tuple[list[dict], Optional[str]]:
    """Date-level report + the conversion metric name that worked.

    Tries ``keyEvents`` then the legacy ``conversions``; if both 400 (unknown
    metric), pulls the core metrics only and returns ``None`` for the conversion
    field. A non-400 error propagates so the ingest marks the pull failed."""
    for candidate in (CONVERSION_METRIC, CONVERSION_METRIC_LEGACY):
        try:
            rows = run_report(
                property_id, start_date, end_date, metrics + [candidate], ["date"]
            )
            return rows, candidate
        except Ga4ApiError as exc:
            if exc.status_code == 400:
                continue  # unknown metric name — try the next candidate
            raise
    # Neither conversion name is accepted — core metrics only.
    return run_report(property_id, start_date, end_date, metrics, ["date"]), None


def fetch_daily_metrics(
    property_id: str, start_date: str, end_date: str
) -> list[dict]:
    """Per-day core metrics + a channel breakdown for the window.

    Returns one dict per date: ``{date, sessions, total_users,
    screen_page_views, conversions, channels}`` where ``channels`` maps the
    default channel group to its session count. Two reports (date-level totals +
    date×channel) so the daily rows carry the channel split the report renders.

    Conversions are fetched best-effort: the modern ``keyEvents`` metric first,
    then the legacy ``conversions`` name, and only if BOTH are rejected (400) is
    conversions dropped (stored null) — so a property on either naming still
    reports conversions and a rename never fails the whole ingest."""
    metrics = list(CORE_METRICS)
    date_rows, conversion_field = _fetch_date_rows(property_id, start_date, end_date, metrics)

    by_date: dict[str, dict] = {}
    for row in date_rows:
        ga_date = row.get("date")  # GA4 "date" dimension = "YYYYMMDD"
        iso = _iso_date(ga_date)
        if not iso:
            continue
        by_date[iso] = {
            "date": iso,
            "sessions": int(row.get("sessions", 0) or 0),
            "total_users": int(row.get("totalUsers", 0) or 0),
            "screen_page_views": int(row.get("screenPageViews", 0) or 0),
            "conversions": (
                int(row.get(conversion_field, 0) or 0) if conversion_field else None
            ),
            "channels": {},
        }

    # Channel breakdown (date × channel → sessions), folded onto each date.
    try:
        channel_rows = run_report(
            property_id, start_date, end_date, ["sessions"], ["date", CHANNEL_DIMENSION]
        )
        for row in channel_rows:
            iso = _iso_date(row.get("date"))
            channel = row.get(CHANNEL_DIMENSION) or "Unassigned"
            if iso and iso in by_date:
                by_date[iso]["channels"][channel] = int(row.get("sessions", 0) or 0)
    except Ga4ApiError as exc:  # pragma: no cover - channel split is best-effort
        logger.warning(
            "ga4_channel_report_failed",
            extra={"property_id": property_id, "error": str(exc)},
        )

    return list(by_date.values())


def _iso_date(ga_date: Optional[str]) -> Optional[str]:
    """GA4 returns the ``date`` dimension as ``YYYYMMDD``; convert to ISO."""
    if not ga_date or len(ga_date) != 8 or not ga_date.isdigit():
        return None
    return f"{ga_date[0:4]}-{ga_date[4:6]}-{ga_date[6:8]}"


def verify_property_access(property_id: str) -> VerifyResult:
    """Run a tiny report against a property and classify the result.

    Returns ``ok`` when the service account can read the property, ``no_access``
    when it can't (typically not yet added as a Viewer), or ``error`` for
    configuration problems (missing/invalid key, API not enabled, network)."""
    try:
        normalized = normalize_property_id(property_id)
    except ValueError as exc:
        return VerifyResult(status="error", detail=str(exc))

    try:
        run_report(normalized, "7daysAgo", "today", ["sessions"])
        return VerifyResult(status="ok")
    except Ga4ApiError as exc:
        logger.info(
            "ga4_verify_failed",
            extra={"property_id": normalized, "status_code": exc.status_code},
        )
        return classify_access_error(exc.status_code, exc.message)
    except RuntimeError as exc:
        # Key missing/invalid — a setup problem, not the property's fault.
        logger.error("ga4_service_account_unavailable", extra={"error": str(exc)})
        return VerifyResult(status="error", detail=str(exc))
    except Exception as exc:  # pragma: no cover - unexpected transport failure
        logger.error("ga4_verify_unexpected", extra={"error": str(exc)})
        return VerifyResult(status="error", detail="verify_failed")

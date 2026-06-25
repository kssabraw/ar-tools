"""Google Search Console service-account access.

Organic Rank Tracker (Module #4), M1 "Connection". This module owns the
agency-owned service-account identity and the property "verify access" check.

The service-account key lives once at the app level in
``settings.google_service_account_key`` (the full key-file JSON as a string),
never per-client and never in the database. Clients grant access by adding the
service account's email (``client_email`` in the key) as a user on their Search
Console property; after that the app reads their data as the service account.

Google client libraries are imported lazily inside the functions that need them
so this module (and its unit tests) import cleanly even where the libraries are
not installed.

See: docs/modules/organic-rank-tracker-prd-v1_0.md §4, §11.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal, Optional

from config import settings

logger = logging.getLogger(__name__)

# Read-only performance data is all M1 needs. URL Inspection (M4) uses the same
# scope set; widen here when that lands.
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

PropertyType = Literal["url_prefix", "domain"]
AccessStatus = Literal["ok", "no_access", "pending", "error"]


@dataclass
class VerifyResult:
    """Outcome of a property access check."""

    status: AccessStatus
    detail: Optional[str] = None


# ----------------------------------------------------------------------------
# Pure helpers (no Google dependency) — independently unit-tested.
# ----------------------------------------------------------------------------
def infer_property_type(site_url: str) -> PropertyType:
    """A ``sc-domain:`` prefix means a domain property; otherwise url-prefix."""
    return "domain" if site_url.strip().startswith("sc-domain:") else "url_prefix"


def normalize_site_url(site_url: str, property_type: PropertyType) -> str:
    """Canonicalize a site_url for the given property type, or raise ValueError.

    GSC requires the siteUrl to match the property type *exactly*: a domain
    property is ``sc-domain:host`` and a url-prefix property is a full URL with a
    trailing slash. A mismatch returns a 403 that masquerades as a permissions
    error (PRD §4), so we validate/normalize up front and reject the mismatch
    here — that way a 403 at verify time means "service account not added,"
    not "wrong format."
    """
    value = site_url.strip()
    if not value:
        raise ValueError("site_url is required")

    if property_type == "domain":
        if not value.startswith("sc-domain:"):
            raise ValueError("domain property must start with 'sc-domain:'")
        host = value.removeprefix("sc-domain:").strip()
        if not host or "/" in host or " " in host:
            raise ValueError("domain property must be 'sc-domain:example.com'")
        return f"sc-domain:{host}"

    # url_prefix
    if value.startswith("sc-domain:"):
        raise ValueError("url-prefix property must be a full https:// URL")
    if not value.startswith("http://") and not value.startswith("https://"):
        raise ValueError("url-prefix property must start with http:// or https://")
    return value if value.endswith("/") else value + "/"


def _extract_status_code(exc: Exception) -> Optional[int]:
    """Pull an HTTP status code out of a Google ``HttpError`` or similar.

    ``googleapiclient.errors.HttpError`` carries it on ``exc.resp.status``; we
    also accept a plain ``status_code`` so callers/tests don't need the Google
    library to exercise the classification logic.
    """
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None) if resp is not None else None
    if status is None:
        status = getattr(exc, "status_code", None)
    if status is None:
        return None
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def classify_access_error(status_code: Optional[int]) -> VerifyResult:
    """Map an HTTP status from a test query into an access state."""
    if status_code in (401, 403):
        # The service account can't read the property. Most often it hasn't been
        # added as a user yet; surface that as the actionable cause.
        return VerifyResult(
            status="no_access",
            detail="service_account_not_added_or_insufficient_permission",
        )
    if status_code in (400, 404):
        # Shouldn't happen now that we normalize site_url, but keep it distinct.
        return VerifyResult(status="no_access", detail="site_url_not_recognized")
    return VerifyResult(status="error", detail=f"http_{status_code}" if status_code else "unknown_error")


# ----------------------------------------------------------------------------
# Service-account identity
# ----------------------------------------------------------------------------
def is_configured() -> bool:
    """Whether the agency service-account key is present (live GSC calls work)."""
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
    """The ``client_email`` clients must add to their Search Console property."""
    email = _load_key().get("client_email")
    if not email:
        raise RuntimeError("google_service_account_key_missing_client_email")
    return email


def build_search_console_client():
    """Build an authenticated Search Console API client (lazy Google imports)."""
    from google.oauth2 import service_account  # noqa: PLC0415
    from googleapiclient.discovery import build  # noqa: PLC0415

    creds = service_account.Credentials.from_service_account_info(
        _load_key(), scopes=SCOPES
    )
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _run_test_query(client, site_url: str) -> None:
    """Issue a tiny searchanalytics.query to prove read access. Raises on error."""
    client.searchanalytics().query(
        siteUrl=site_url,
        body={
            "startDate": "2020-01-01",
            "endDate": "2020-01-01",
            "dimensions": ["query"],
            "rowLimit": 1,
        },
    ).execute()


# Google caps a single Search Analytics request at 25k rows; paginate startRow.
GSC_ROW_LIMIT = 25000


def fetch_search_analytics(
    site_url: str,
    dimensions: list[str],
    start_date: str,
    end_date: str,
    row_limit: int = GSC_ROW_LIMIT,
) -> list[dict]:
    """Fetch all Search Analytics rows for a window, paginating ``startRow``.

    ``site_url`` must already be normalized for its property type. Raises on API
    error so the caller can classify it (e.g. a 403 → property no_access).
    Returns the raw GSC rows (each has ``keys`` matching ``dimensions`` order
    plus clicks/impressions/ctr/position).
    """
    client = build_search_console_client()
    rows: list[dict] = []
    start_row = 0
    while True:
        resp = client.searchanalytics().query(
            siteUrl=site_url,
            body={
                "startDate": start_date,
                "endDate": end_date,
                "dimensions": dimensions,
                "rowLimit": row_limit,
                "startRow": start_row,
            },
        ).execute()
        page = resp.get("rows", []) or []
        rows.extend(page)
        # A short page (fewer than row_limit) is the last page.
        if len(page) < row_limit:
            break
        start_row += row_limit
    return rows


def classify_index_status(verdict: Optional[str]) -> str:
    """Map a URL Inspection verdict to our index_status enum."""
    if verdict == "PASS":
        return "indexed"
    if verdict in ("FAIL", "NEUTRAL"):
        return "not_indexed"
    return "unknown"


def inspect_url(site_url: str, inspection_url: str) -> dict:
    """Run GSC URL Inspection for a page; return index status + coverage state.

    `site_url` must be the property the page belongs to (same format rules as
    elsewhere). Raises on API error so the caller can skip/record it.
    """
    client = build_search_console_client()
    resp = (
        client.urlInspection()
        .index()
        .inspect(body={"inspectionUrl": inspection_url, "siteUrl": site_url})
        .execute()
    )
    result = (resp.get("inspectionResult") or {}).get("indexStatusResult") or {}
    verdict = result.get("verdict")
    return {
        "index_status": classify_index_status(verdict),
        "coverage_state": result.get("coverageState"),
        "verdict": verdict,
    }


def verify_property_access(site_url: str, property_type: PropertyType) -> VerifyResult:
    """Run a test query against a property and classify the result.

    Returns ``ok`` when the service account can read the property, ``no_access``
    when it can't (typically not yet added as a user), or ``error`` for
    configuration problems (missing/invalid key, network, etc.).
    """
    try:
        normalized = normalize_site_url(site_url, property_type)
    except ValueError as exc:
        return VerifyResult(status="error", detail=str(exc))

    try:
        client = build_search_console_client()
    except RuntimeError as exc:
        logger.error("gsc_service_account_unavailable", extra={"error": str(exc)})
        return VerifyResult(status="error", detail=str(exc))
    except Exception as exc:  # pragma: no cover - unexpected client build failure
        logger.error("gsc_client_build_failed", extra={"error": str(exc)})
        return VerifyResult(status="error", detail="client_build_failed")

    try:
        _run_test_query(client, normalized)
        return VerifyResult(status="ok")
    except Exception as exc:
        code = _extract_status_code(exc)
        logger.info("gsc_verify_failed", extra={"site_url": normalized, "status_code": code})
        return classify_access_error(code)

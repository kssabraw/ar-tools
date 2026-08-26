"""Google Business Profile **Reviews** API — the v4 ``reviews`` surface.

Reviews (like Posts) live only on the legacy-but-active **Google My Business
API (v4)** (``mybusiness.googleapis.com/v4``) — the v1 split APIs (Account
Management / Business Information / Performance) never got a reviews resource.
v4 is NOT in Google's discovery service, so this is plain REST (httpx + a
bearer token from ``gbp_auth``), mirroring ``services/gbp_posts_api.py``.

Each review carries an absolute ``createTime`` (ISO-8601), a ``starRating`` enum
(ONE…FIVE), the reviewer's display name, the comment text, and whether the
business has replied — everything the reporting dashboard needs to show the
reviews *posted during a period*. Auth reuses the same agency credential (OAuth
account, service-account fallback) already proven by the metrics ingest.

This is the first-party alternative to the Outscraper feed in
``services.gbp_reviews`` (which powers the client PDF report): free + complete,
but the v4 API can need per-project allowlisting. Read-only; ``list_reviews``
raises on a non-2xx so the caller can classify (403 → not enabled/allowlisted).
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import HTTPException

from services.gbp_posts_api import v4_parent  # pure helper; reuse the parent builder

logger = logging.getLogger(__name__)

_V4_BASE = "https://mybusiness.googleapis.com/v4"
_TIMEOUT = 45
_PAGE_SIZE = 50  # v4 reviews.list max
_MAX_PAGES = 40  # runaway guard: up to 2,000 reviews/location per pull

# v4 starRating enum → integer stars. STAR_RATING_UNSPECIFIED / unknown → None.
_STAR_MAP = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


def star_to_int(value) -> Optional[int]:
    """Map a v4 ``starRating`` enum string to 1–5 (None when unspecified). Pure."""
    return _STAR_MAP.get(value) if isinstance(value, str) else None


def parse_review(item: dict) -> dict:
    """Map one v4 ``Review`` to our flat shape. Pure.

    ``review_id`` prefers the short ``reviewId``, falling back to the tail of the
    resource ``name`` (``…/reviews/{id}``) so it's always populated for a PK."""
    reviewer = (item.get("reviewer") or {}).get("displayName") or ""
    review_id = item.get("reviewId") or ""
    if not review_id:
        name = item.get("name") or ""
        review_id = name.split("/reviews/")[-1] if "/reviews/" in name else name
    return {
        "review_id": review_id,
        "reviewer": reviewer,
        "rating": star_to_int(item.get("starRating")),
        "text": item.get("comment") or "",
        "create_time": item.get("createTime") or "",
        "update_time": item.get("updateTime") or "",
        "has_reply": bool(item.get("reviewReply")),
    }


def parse_reviews(payload: dict) -> list[dict]:
    """Map a v4 ``reviews.list`` page to flat records (dropping any with no id). Pure."""
    return [r for r in (parse_review(i) for i in (payload.get("reviews") or [])) if r["review_id"]]


def classify_review_error(status_code: Optional[int], message: str = "") -> str:
    """Map an HTTP status + error message from a v4 reviews call to a code. Pure."""
    msg = (message or "").lower()
    if status_code == 403 and ("has not been used" in msg or "is disabled" in msg):
        return "gbp_api_not_enabled"
    if status_code == 429 or "resource_exhausted" in msg or "quota" in msg:
        return "gbp_quota_not_granted"
    if status_code in (401, 403):
        return "account_not_a_manager_or_forbidden"
    if status_code == 404:
        return "location_not_found"
    return f"http_{status_code}" if status_code else "unknown_error"


def _headers() -> dict:
    from services import gbp_auth  # lazy: no google import at module load

    return {"Authorization": f"Bearer {gbp_auth.access_token()}", "Content-Type": "application/json"}


def _raise_for(resp: httpx.Response) -> None:
    """Raise HTTPException(502, classified-detail) on a non-2xx response."""
    if resp.status_code < 400:
        return
    try:
        message = (resp.json().get("error") or {}).get("message", "")
    except Exception:  # noqa: BLE001 — body may not be JSON
        message = resp.text[:300]
    code = classify_review_error(resp.status_code, message)
    logger.info("gbp_reviews_api.error", extra={"status": resp.status_code, "code": code})
    raise HTTPException(status_code=502, detail=code)


def list_reviews(account_id: str, location_id: str, client: Optional[httpx.Client] = None) -> dict:
    """Fetch all reviews for one location (paginated, capped at ``_MAX_PAGES``).

    Returns ``{reviews:[…parsed], average_rating, total_count, truncated}``.
    Raises on a non-2xx so the caller can classify (allowlisting / manager access).
    """
    parent = v4_parent(account_id, location_id)
    reviews: list[dict] = []
    average_rating = None
    total_count = None
    token: Optional[str] = None
    pages = 0
    owns = client is None
    client = client or httpx.Client(timeout=_TIMEOUT)
    # Mint the bearer once per call (each _headers() does a token-endpoint refresh);
    # an OAuth token easily outlives a multi-page fetch, so reuse it across pages.
    headers = _headers()
    try:
        while True:
            params: dict = {"pageSize": _PAGE_SIZE}
            if token:
                params["pageToken"] = token
            resp = client.get(f"{_V4_BASE}/{parent}/reviews", headers=headers, params=params)
            _raise_for(resp)
            data = resp.json()
            reviews.extend(parse_reviews(data))
            if average_rating is None:
                average_rating = data.get("averageRating")
            if total_count is None:
                total_count = data.get("totalReviewCount")
            token = data.get("nextPageToken")
            pages += 1
            if not token or pages >= _MAX_PAGES:
                break
    finally:
        if owns:
            client.close()
    return {
        "reviews": reviews,
        "average_rating": average_rating,
        "total_count": total_count,
        "truncated": bool(token),  # more pages existed than _MAX_PAGES allowed
    }

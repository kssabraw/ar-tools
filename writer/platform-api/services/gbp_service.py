"""Google Business Profile (GBP) auto-fetch via the Outscraper API."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from config import settings

logger = logging.getLogger(__name__)

_OUTSCRAPER_BASE_URL = "https://api.app.outscraper.com"
_SEARCH_ENDPOINT = f"{_OUTSCRAPER_BASE_URL}/maps/search-v3"
_DATAFORSEO_REVIEWS_ENDPOINT = (
    "https://api.dataforseo.com/v3/business_data/google/reviews/live"
)
_TIMEOUT = 45
# Only surface strong reviews with actual text, capped to a handful.
_REVIEW_MIN_RATING = 4
_REVIEW_LIMIT = 5

# Hosts used by Google Maps "share" / short links that 302-redirect to the
# full place URL. We expand these server-side before querying Outscraper,
# because the provider does not reliably follow shorteners.
_SHORT_LINK_HOSTS = ("maps.app.goo.gl", "goo.gl", "g.co")
# A bare place_id (Google "ChIJ…" style) or feature/Google ID ("0x…:0x…").
_PLACE_ID_RE = re.compile(r"^ChI[\w-]+$")
_FEATURE_ID_RE = re.compile(r"^0x[0-9a-fA-F]+:0x[0-9a-fA-F]+$")
# Identifiers embedded in a full Maps URL.
_URL_PLACE_ID_RE = re.compile(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")
_URL_CID_RE = re.compile(r"[?&]cid=(\d+)")


def _headers() -> dict[str, str]:
    return {"X-API-KEY": settings.outscraper_api_key}


def _places_from_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Outscraper returns data.data as an array-of-arrays; places are at index 0."""
    outer = data.get("data") or []
    if not outer:
        return []
    first = outer[0]
    return first if isinstance(first, list) else []


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _reviews_from_dataforseo(data: dict[str, Any]) -> list[dict]:
    """Map a DataForSEO reviews/live response to our review shape."""
    tasks = data.get("tasks") or []
    if not tasks:
        return []
    result = (tasks[0] or {}).get("result") or []
    if not result:
        return []
    items = (result[0] or {}).get("items") or []

    reviews: list[dict] = []
    for r in items:
        if not isinstance(r, dict):
            continue
        text = r.get("review_text")
        rating_raw = r.get("review_rating")
        rating = None
        if isinstance(rating_raw, dict):
            rating = _to_float(rating_raw.get("value"))
        if rating is None:
            rating = _to_float(r.get("rating"))
        if not text or (rating or 0) < _REVIEW_MIN_RATING:
            continue
        timestamp = r.get("timestamp") or ""
        datetime_utc = r.get("review_datetime_utc") or ""
        if timestamp:
            date = timestamp.split("T")[0]
        elif datetime_utc:
            date = datetime_utc.split(" ")[0]
        else:
            date = ""
        reviews.append(
            {
                "reviewer": r.get("profile_name") or r.get("author_title") or "Anonymous",
                "rating": rating if rating is not None else 5.0,
                "text": text,
                "date": date,
            }
        )
        if len(reviews) >= _REVIEW_LIMIT:
            break
    return reviews


def _reviews_from_outscraper(place: dict[str, Any]) -> list[dict]:
    """Fallback: map Outscraper's inline reviews_data to our review shape."""
    raw = place.get("reviews_data")
    if not isinstance(raw, list):
        return []

    reviews: list[dict] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        text = r.get("review_text")
        rating = _to_float(r.get("review_rating"))
        if not text or (rating or 0) < _REVIEW_MIN_RATING:
            continue
        datetime_utc = r.get("review_datetime_utc") or ""
        reviews.append(
            {
                "reviewer": r.get("author_title") or "Anonymous",
                "rating": rating,
                "text": text,
                "date": datetime_utc.split(" ")[0] if datetime_utc else "",
            }
        )
        if len(reviews) >= _REVIEW_LIMIT:
            break
    return reviews


async def _fetch_reviews(place_id: str) -> list[dict]:
    """Fetch top reviews for a place via DataForSEO. Best-effort: any failure
    or missing credentials returns [] so it never breaks the details call."""
    if not place_id or not settings.dataforseo_login or not settings.dataforseo_password:
        return []
    body = [
        {
            "place_id": place_id,
            "depth": 10,
            "sort_by": "most_relevant",
            "language_name": "English",
        }
    ]
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                _DATAFORSEO_REVIEWS_ENDPOINT,
                json=body,
                auth=(settings.dataforseo_login, settings.dataforseo_password),
            )
            response.raise_for_status()
            return _reviews_from_dataforseo(response.json())
    except httpx.HTTPError:
        logger.warning("gbp_service.reviews_fetch_failed", extra={"place_id": place_id})
        return []


async def search_businesses(query: str) -> list[dict]:
    """Search GBP listings by free-text query, returning lightweight suggestions."""
    if not query or len(query.strip()) < 2:
        return []

    params = {
        "query": query,
        "organizationsPerQueryLimit": 5,
        "language": "en",
        "async": "false",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(_SEARCH_ENDPOINT, params=params, headers=_headers())
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "gbp_service.search_http_error",
            extra={"status_code": exc.response.status_code},
        )
        raise HTTPException(status_code=502, detail="gbp_provider_error") from exc
    except httpx.HTTPError as exc:
        logger.warning("gbp_service.search_request_error")
        raise HTTPException(status_code=502, detail="gbp_provider_error") from exc

    suggestions: list[dict] = []
    for p in _places_from_response(data):
        if not isinstance(p, dict):
            continue
        name = p.get("name") or ""
        address = (
            p.get("full_address")
            or p.get("address")
            or ", ".join([v for v in [p.get("city"), p.get("state")] if v])
        )
        suggestions.append(
            {
                "place_id": p.get("place_id") or p.get("google_id") or "",
                "name": name,
                "address": address,
                "description": f"{name}, {address}",
            }
        )
    return suggestions


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _is_short_link(value: str) -> bool:
    return _is_url(value) and any(host in value for host in _SHORT_LINK_HOSTS)


def _identifier_from_url(url: str) -> Optional[str]:
    """Extract a queryable identifier from a full Google Maps URL.

    Prefers the embedded feature/Google ID (`!1s0x…:0x…`), then a `cid=`
    param. Returns None if neither is present, in which case the caller
    passes the full URL to Outscraper as-is (it accepts Maps URLs).
    """
    m = _URL_PLACE_ID_RE.search(url)
    if m:
        return m.group(1)
    m = _URL_CID_RE.search(url)
    if m:
        return m.group(1)
    return None


async def _expand_short_link(url: str) -> str:
    """Follow a Maps short link to its canonical URL. Best-effort: on any
    failure we return the original input so the caller can still try it."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url)
            return str(response.url) or url
    except httpx.HTTPError:
        logger.warning("gbp_service.short_link_expand_failed")
        return url


async def resolve_query(raw: str) -> str:
    """Normalize whatever the user pasted (free text, place_id, feature/Google
    ID, full Maps URL, or short share link) into a single string suitable for
    Outscraper's `query` parameter."""
    value = (raw or "").strip()
    if not value:
        raise HTTPException(status_code=422, detail="gbp_input_required")

    # Bare identifiers — pass straight through.
    if _PLACE_ID_RE.match(value) or _FEATURE_ID_RE.match(value):
        return value

    if _is_url(value):
        if _is_short_link(value):
            value = await _expand_short_link(value)
        # If we can pull a clean identifier from the (expanded) URL, prefer it;
        # otherwise hand Outscraper the URL itself.
        return _identifier_from_url(value) or value

    # Free text (business name + city, etc.) — pass through unchanged.
    return value


async def resolve_business(raw_input: str) -> dict:
    """Resolve any supported GBP input (URL / share link / place_id / CID /
    free text) to a full profile. Thin wrapper over get_business_details."""
    query = await resolve_query(raw_input)
    return await get_business_details(query)


async def get_business_details(query: str) -> dict:
    """Fetch a full GBP profile for an Outscraper query (place_id, CID,
    feature/Google ID, Maps URL, or free text) and map it to our shape."""
    params = {
        "query": query,
        "organizationsPerQueryLimit": 1,
        "language": "en",
        "async": "false",
        "reviewsLimit": 5,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(_SEARCH_ENDPOINT, params=params, headers=_headers())
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "gbp_service.details_http_error",
            extra={"status_code": exc.response.status_code},
        )
        raise HTTPException(status_code=502, detail="gbp_provider_error") from exc
    except httpx.HTTPError as exc:
        logger.warning("gbp_service.details_request_error")
        raise HTTPException(status_code=502, detail="gbp_provider_error") from exc

    places = _places_from_response(data)
    if not places or not isinstance(places[0], dict):
        raise HTTPException(status_code=404, detail="gbp_place_not_found")
    p = places[0]

    description = p.get("description") or ""
    if not description:
        about = p.get("about")
        if isinstance(about, dict):
            description = about.get("summary") or ""

    categories = p.get("categories")
    if isinstance(categories, list):
        gbp_categories = [c for c in categories if c]
    elif p.get("subtypes"):
        gbp_categories = [c.strip() for c in str(p["subtypes"]).split(",") if c.strip()]
    else:
        gbp_categories = []

    gbp: dict[str, Any] = {
        "business_name": p.get("name") or "",
        "description": description,
        "address": p.get("full_address") or p.get("address") or "",
        "phone": p.get("phone") or "",
        "website": p.get("site") or p.get("website") or "",
        "logo": p.get("logo") or "",
        "photo": p.get("photo") or "",
        "gbp_category": p.get("category") or p.get("type") or "",
        "gbp_categories": gbp_categories,
        "gbp_rating": _to_float(p.get("rating")),
        "gbp_review_count": _to_int(p.get("reviews")),
        "latitude": _to_float(p.get("latitude") if p.get("latitude") is not None else p.get("lat")),
        "longitude": _to_float(
            p.get("longitude") if p.get("longitude") is not None else p.get("lng")
        ),
        "hours": p.get("working_hours") or p.get("hours") or None,
        "google_maps_uri": p.get("location_link") or p.get("google_maps_url") or "",
    }

    resolved_place_id = p.get("place_id") or p.get("google_id") or query

    # Review enrichment: DataForSEO is preferred; fall back to whatever
    # Outscraper returned inline. Both are best-effort — never fatal.
    reviews = await _fetch_reviews(resolved_place_id)
    if not reviews:
        reviews = _reviews_from_outscraper(p)
    gbp["reviews"] = reviews

    return {
        "place_id": resolved_place_id,
        "gbp": gbp,
    }

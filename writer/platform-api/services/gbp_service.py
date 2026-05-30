"""Google Business Profile (GBP) auto-fetch via the Outscraper API."""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from config import settings

logger = logging.getLogger(__name__)

_OUTSCRAPER_BASE_URL = "https://api.app.outscraper.com"
_SEARCH_ENDPOINT = f"{_OUTSCRAPER_BASE_URL}/maps/search-v3"
_TIMEOUT = 45


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


async def get_business_details(place_id: str) -> dict:
    """Fetch a full GBP profile for a place_id and map it to our GbpProfile shape."""
    params = {
        "query": place_id,
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

    return {
        "place_id": p.get("place_id") or p.get("google_id") or place_id,
        "gbp": gbp,
    }

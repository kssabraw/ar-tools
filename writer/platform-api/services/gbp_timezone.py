"""Client timezone derivation for GBP scheduling.

GBP post scheduling is expressed in the **client's local time** (the timezone of
their Business Profile), converted to UTC underneath. This module owns resolving
and caching that timezone.

The IANA timezone name (e.g. ``America/Los_Angeles``) is derived from the GBP
listing's lat/lng — which the suite already captures on ``clients.gbp``
(latitude/longitude, from Outscraper) — via Google's Time Zone API, reusing the
server-side ``GOOGLE_MAPS_API_KEY`` (same key the Maps geocode path uses). Once
resolved it is cached on ``clients.timezone`` so later reads are a cheap column
lookup, not another paid call.

Everything is best-effort: no key / no coordinates / an API error yields ``None``,
and callers fall back to UTC — a missing timezone degrades scheduling to UTC, it
never breaks it. The pure parser (``parse_timezone_id``) is unit-tested.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_TIMEZONE_URL = "https://maps.googleapis.com/maps/api/timezone/json"
_TIMEOUT = 15


def parse_timezone_id(payload: dict) -> Optional[str]:
    """Pull the IANA ``timeZoneId`` from a Time Zone API response, or None.

    Pure (unit-tested). Only a ``status == "OK"`` response with a non-empty
    ``timeZoneId`` counts; ZERO_RESULTS / errors / malformed payloads → None.
    """
    if not isinstance(payload, dict) or payload.get("status") != "OK":
        return None
    tz = payload.get("timeZoneId")
    return tz or None


def resolve_timezone(
    lat: Optional[float], lng: Optional[float], api_key: Optional[str] = None
) -> Optional[str]:
    """Look up the IANA timezone for a coordinate via Google's Time Zone API.

    Best-effort: returns None when the key or coordinates are missing, or on any
    API/network error. The ``timeZoneId`` is stable regardless of the timestamp
    we pass (that only affects the dst/raw offset fields, which we ignore)."""
    key = settings.google_maps_api_key if api_key is None else api_key
    if not key or lat is None or lng is None:
        return None
    try:
        resp = httpx.get(
            _TIMEZONE_URL,
            params={"location": f"{lat},{lng}", "timestamp": 0, "key": key},
            timeout=_TIMEOUT,
        )
        return parse_timezone_id(resp.json())
    except Exception as exc:  # noqa: BLE001 — derivation is best-effort
        logger.warning("gbp_timezone.resolve_failed", extra={"error": str(exc)})
        return None


def ensure_client_timezone(client: dict) -> Optional[str]:
    """Return the client's timezone, deriving + persisting it on first need.

    ``client`` must carry ``id``, ``timezone`` and ``gbp``. If ``timezone`` is
    already set it's returned as-is; otherwise it's derived from the GBP lat/lng
    and cached onto ``clients.timezone``. Best-effort — None when it can't be
    resolved (no coordinates / no key / API error)."""
    tz = client.get("timezone")
    if tz:
        return tz
    gbp = client.get("gbp") or {}
    tz = resolve_timezone(gbp.get("latitude"), gbp.get("longitude"))
    if tz and client.get("id"):
        try:
            get_supabase().table("clients").update({"timezone": tz}).eq(
                "id", client["id"]
            ).execute()
        except Exception as exc:  # noqa: BLE001 — caching failure must not break scheduling
            logger.warning("gbp_timezone.cache_failed", extra={"error": str(exc)})
    return tz


def resolve_client_timezone(client_id: str) -> Optional[str]:
    """Fetch the client and return its timezone (deriving + caching if needed).

    The convenience entry point for the scheduling code, which usually holds only
    a client_id. Best-effort — None on any failure or when the client is gone."""
    try:
        rows = (
            get_supabase()
            .table("clients")
            .select("id, timezone, gbp")
            .eq("id", client_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("gbp_timezone.client_fetch_failed", extra={"error": str(exc)})
        return None
    if not rows:
        return None
    return ensure_client_timezone(rows[0])

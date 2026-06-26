"""Auto-derive a client's rank-tracking location from its Google Business Profile.

Organic Rank Tracker (Module #4). DataForSEO live-rank + market-data calls are
localized by a per-client ``rank_tracking_location_code``. Rather than make the
team pick one by hand for every client, we derive it from the client's GBP — the
business's real location — and resolve it to the **most specific DataForSEO
location available** (city → region → none).

Resolution chain (best-effort; any step may no-op and we fall back):
  1. Reverse-geocode the GBP's lat/lng (Google) → ``{city, admin_area}``.
  2. Failing that, parse the GBP's free-text ``address``.
  3. Resolve the city first, then the region/state, against DataForSEO's
     location list (the same list the location typeahead uses).

A location a user picked by hand is marked ``rank_tracking_location_source =
'manual'`` (see routers/rank.py) and is never overwritten here.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from db.supabase_client import get_supabase
from services import locations_service, maps_geocode

logger = logging.getLogger(__name__)

_POSTCODE = re.compile(r"\d{4,6}")        # AU/US/etc. postcode or ZIP
_STATE_CODE = re.compile(r"[A-Z]{2,3}")   # state/territory abbrev, e.g. "VIC", "AZ"


def address_location_candidates(address: Optional[str]) -> list[str]:
    """Ordered (most specific first) place candidates from a GBP free-text address.

    A fallback for when the GBP has no coordinates to reverse-geocode. GBP/
    Outscraper addresses look like ``"117 Newry St, Carlton North VIC 3054,
    Australia"`` (suburb+state+postcode in one segment) or ``"123 Main St,
    Phoenix, AZ 85001, USA"`` (city and state in separate segments). We drop the
    street (first) and country (last when present), then from each remaining
    segment emit the place words and any state code separately — e.g.
    ``["Carlton North", "VIC"]`` / ``["Phoenix", "AZ"]`` — so the resolver can try
    the most specific first and fall back to the state.
    """
    if not address:
        return []
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) < 2:
        return []
    middle = parts[1:-1] if len(parts) >= 3 else parts[1:]
    candidates: list[str] = []
    for seg in middle:
        words, codes = [], []
        for tok in seg.split():
            if _POSTCODE.fullmatch(tok):
                continue
            (codes if _STATE_CODE.fullmatch(tok) else words).append(tok)
        if words:
            candidates.append(" ".join(words))
        candidates.extend(codes)
    # De-dup, preserving order.
    seen: set[str] = set()
    return [c for c in candidates if not (c.lower() in seen or seen.add(c.lower()))]


async def derive_location_from_gbp(client: dict) -> tuple[Optional[str], Optional[int]]:
    """Resolve the most specific DataForSEO location for a client's GBP.

    Returns ``(canonical_location_name, location_code)``, or ``(None, None)`` when
    the GBP yields nothing resolvable — the caller then leaves the client on its
    national fallback. Never raises: every external call is best-effort.
    """
    gbp = client.get("gbp") or {}
    iso = locations_service.infer_country_iso(client)

    # Most specific first: the GBP's city, then its region/state.
    candidates: list[str] = []
    lat, lng = gbp.get("latitude"), gbp.get("longitude")
    if lat is not None and lng is not None:
        try:
            enriched = await maps_geocode.reverse_geocode_points(
                [{"lat": float(lat), "lng": float(lng)}], supabase=get_supabase()
            )
            if enriched:
                candidates += [c for c in (enriched[0].get("city"), enriched[0].get("admin_area")) if c]
        except Exception as exc:  # geocoding is best-effort
            logger.warning("rank_location.reverse_geocode_failed", extra={"error": str(exc)})

    if not candidates:
        candidates = address_location_candidates(gbp.get("address"))

    for candidate in candidates:
        try:
            matches = await locations_service.search_locations(client, candidate, country=iso, limit=5)
        except Exception as exc:
            logger.warning("rank_location.search_failed", extra={"candidate": candidate, "error": str(exc)})
            continue
        if matches:
            best = matches[0]
            logger.info(
                "rank_location.derived",
                extra={
                    "candidate": candidate,
                    "location_name": best["location_name"],
                    "location_code": best["location_code"],
                    "location_type": best.get("location_type"),
                },
            )
            return best["location_name"], best["location_code"]

    logger.info("rank_location.unresolved", extra={"candidates": candidates, "iso": iso})
    return None, None


def enqueue_location_derive(client_id: str) -> None:
    """Enqueue a best-effort GBP→location derivation for a client (deduped)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "rank_location_derive")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "rank_location_derive", "entity_id": client_id, "payload": {"client_id": client_id}}
    ).execute()


async def run_rank_location_derive_job(job: dict) -> None:
    """async_jobs handler for job_type='rank_location_derive'.

    Skips clients whose location is user-set ('manual'). Applies a derived
    location only when it differs from the current one, then re-fetches ranks +
    market data for the new area (mirrors the manual set_tracking_location path).
    """
    from services import dataforseo_rank, keyword_market

    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    try:
        res = (
            supabase.table("clients")
            .select(
                "id, website_url, gbp, rank_tracking_location_code, rank_tracking_location_source"
            )
            .eq("id", client_id)
            .limit(1)
            .execute()
        )
        client = res.data[0] if res.data else None
        if not client:
            raise RuntimeError("client_not_found")

        # Never override a manually-set location.
        if client.get("rank_tracking_location_source") == "manual":
            supabase.table("async_jobs").update(
                {"status": "complete", "result": {"applied": False, "reason": "manual"}, "completed_at": "now()"}
            ).eq("id", job_id).execute()
            return

        name, code = await derive_location_from_gbp(client)
        applied = bool(code and code != client.get("rank_tracking_location_code"))
        if applied:
            supabase.table("clients").update(
                {
                    "rank_tracking_location": name,
                    "rank_tracking_location_code": code,
                    "rank_tracking_location_source": "auto",
                    "updated_at": "now()",
                }
            ).eq("id", client_id).execute()
            # Re-fetch ranks + market data for the new area.
            dataforseo_rank.enqueue_dataforseo_rank(client_id)
            keyword_market.enqueue_keyword_market(client_id)

        supabase.table("async_jobs").update(
            {
                "status": "complete",
                "result": {"applied": applied, "location": name, "location_code": code},
                "completed_at": "now()",
            }
        ).eq("id", job_id).execute()
    except Exception as exc:
        logger.error("rank_location_derive_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

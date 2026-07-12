"""LeadOff proximity — competitor geocoding (app-side, no re-pull, no desktop).

Spec: docs/modules/leadoff-proximity-plan-v1_0.md §5/§5c. A one-time desktop
uploader pushes competitor addresses into public.competitor_locations
(reference: docs/reference/leadoff-scanner/upload_competitor_addresses.py);
this job — on the deployed worker, which reaches census.gov (proven by the
permits BPS pull) — turns those addresses into coordinates:

  * addressed rows (~88%) → free US Census batch geocoder ($0, keyless).
    Street-centroid, not the exact GBP pin — a feasibility-grade coordinate
    (see plan §5 tradeoffs).
  * service-area businesses (~12%, blank address) → optional Outscraper
    lookup by name+city (the raw place object carries lat/lng even when the
    address is hidden — gbp_service already reads it). PAID, so gated behind
    `leadoff_geocode_sab_outscraper` (default off); Google's exact pin.

The $137 full DataForSEO re-pull (exact pins for everyone) is declined by the
owner (2026-07-12) — this recovers the coordinates from data already owned.

No scoring here; proximity computation (octant clustering / underserved
zones) is a later phase gated on these coordinates validating on the test
markets.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
_CENSUS_BENCHMARK = "Public_AR_Current"
# The batch cap is 10k/request, but the endpoint 502s under load at large
# sizes — 1k batches are the reliable sweet spot (and each commits before the
# next, so a mid-run blip loses at most one batch of progress).
_CENSUS_CHUNK = 1000
_CENSUS_RETRY_WAITS = [5, 15, 30, 60]   # transient-502/timeout backoff (seconds)
# The two known test markets — every run reports them so the coordinate
# quality can be eyeballed before proximity is built on top (working agreement).
VALIDATE = [("La Jolla", "CA"), ("Kansas City", "MO")]


# ── Pure helpers (unit-tested) ────────────────────────────────────────────────

def one_line_address(address: Optional[str], city: Optional[str],
                     state: Optional[str]) -> Optional[str]:
    """Reconstruct a geocodable one-line address from the street `address`
    (all the CSV kept) plus the city/state from the scanner's cities map.
    None when there's no street address (a service-area business)."""
    a = (address or "").strip()
    if not a:
        return None
    parts = [a]
    if city:
        parts.append(city.strip())
    if state:
        parts.append(state.strip())
    return ", ".join(parts)


def build_census_payload(rows: list[tuple[str, str]]) -> bytes:
    """Multipart body for the Census batch endpoint from (id, one_line_addr)
    pairs. The batch CSV is id,street,city,state,zip — but the one-line form
    goes wholly in the street field and the geocoder parses it."""
    buf = io.StringIO()
    w = csv.writer(buf)
    for rid, addr in rows:
        w.writerow([rid, addr, "", "", ""])
    body = buf.getvalue().encode()
    boundary = "----leadoffgeocode"
    return (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="benchmark"\r\n\r\n'
        f"{_CENSUS_BENCHMARK}\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="addressFile"; '
        'filename="a.csv"\r\nContent-Type: text/csv\r\n\r\n'
    ).encode() + body + f"\r\n--{boundary}--\r\n".encode(), boundary


def parse_census_response(text: str) -> dict[str, tuple[float, float]]:
    """{row_id: (lat, lng)} for the 'Match' rows of a Census batch response.
    The coordinate column is 'lon,lat' (X,Y) — we return (lat, lng)."""
    out: dict[str, tuple[float, float]] = {}
    for row in csv.reader(io.StringIO(text)):
        # id, input, match_indicator, match_type, matched_addr, coord, tiger...
        if len(row) >= 6 and row[2].strip().lower() == "match":
            try:
                lon, lat = (float(x) for x in row[5].split(","))
                out[row[0]] = (lat, lon)
            except (ValueError, IndexError):
                continue
    return out


def chunked(seq: list, size: int) -> list[list]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def coverage_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Post-geocode coverage report. Pure."""
    total = len(rows)
    addressed = sum(1 for r in rows if (r.get("address") or "").strip())
    geocoded = sum(1 for r in rows if r.get("lat") is not None)
    by_source: dict[str, int] = {}
    for r in rows:
        s = r.get("geo_source")
        if s:
            by_source[s] = by_source.get(s, 0) + 1
    return {
        "competitors": total,
        "addressed": addressed,
        "geocoded": geocoded,
        "geocoded_pct": round(geocoded / total, 3) if total else 0,
        "by_source": by_source,
        "service_area_no_address": total - addressed,
    }


# ── Data access ───────────────────────────────────────────────────────────────

def _city_index() -> dict[int, tuple[str, str]]:
    from services.leadoff_db import get_leadoff_client

    client = get_leadoff_client()
    idx: dict[int, tuple[str, str]] = {}
    page = 0
    while True:
        chunk = (client.table("cities").select("city_id, name, state_code")
                 .range(page * 1000, page * 1000 + 999).execute().data or [])
        for c in chunk:
            idx[c["city_id"]] = (c.get("name"), c.get("state_code"))
        if len(chunk) < 1000:
            return idx
        page += 1


# A competitor is "pending" until it has a coordinate OR a geo_source stamp —
# the stamp is how a no-match leaves the work queue (so the job terminates
# instead of re-selecting the same unmatched rows forever).
def _pending_addressed(supabase, limit: int) -> list[dict[str, Any]]:
    """Next batch of addressed rows not yet attempted (the NOT NULL columns
    come along so the bulk upsert's insert-arm is satisfied)."""
    return (supabase.table("competitor_locations")
            .select("id, city_id, category_id, rank_position, business_name, address")
            .is_("lat", "null").not_.is_("address", "null").is_("geo_source", "null")
            .limit(limit).execute().data or [])


def _pending_sab(supabase, limit: int) -> list[dict[str, Any]]:
    """Service-area rows (no address) not yet attempted — Outscraper path."""
    return (supabase.table("competitor_locations")
            .select("id, city_id, business_name")
            .is_("address", "null").is_("lat", "null").is_("geo_source", "null")
            .limit(limit).execute().data or [])


def _bulk_write(supabase, rows: list[dict[str, Any]]) -> None:
    """Upsert coordinate results in chunks (on the id PK) — 500/call instead of
    one call per row, so a full-board geocode commits in ~hundreds of calls,
    not ~130k, and each chunk persists before the next (reaper-safe)."""
    for i in range(0, len(rows), 500):
        supabase.table("competitor_locations").upsert(rows[i:i + 500]).execute()


def _count(supabase, **filters) -> int:
    q = supabase.table("competitor_locations").select("id", count="exact")
    for col, val in filters.items():
        q = q.is_(col, "null") if val is None else q.eq(col, val)
    return q.limit(1).execute().count or 0


# ── Census geocode (free, addressed rows) ─────────────────────────────────────

async def _census_post(client: httpx.AsyncClient,
                       chunk: list[tuple[str, str]]) -> str:
    """POST one batch, retrying transient failures (502/503/504, timeouts,
    transport errors) with backoff. The Census batch endpoint is load-flaky;
    a single blip should not fail a 149k-row job."""
    payload, boundary = build_census_payload(chunk)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    last_exc: Exception | None = None
    for attempt in range(len(_CENSUS_RETRY_WAITS) + 1):
        try:
            resp = await client.post(_CENSUS_BATCH_URL, content=payload,
                                     headers=headers, timeout=300.0)
            if resp.status_code in (502, 503, 504):
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.text
        except (httpx.HTTPStatusError, httpx.TransportError,
                httpx.TimeoutException) as exc:
            # 4xx (other than the retryable 5xx above) is not transient — abort
            if isinstance(exc, httpx.HTTPStatusError) and \
                    exc.response.status_code not in (502, 503, 504):
                raise
            last_exc = exc
            if attempt < len(_CENSUS_RETRY_WAITS):
                wait = _CENSUS_RETRY_WAITS[attempt]
                logger.warning("leadoff_geocode.census_retry",
                               extra={"attempt": attempt + 1, "wait": wait,
                                      "error": str(exc)[:200]})
                await asyncio.sleep(wait)
    raise last_exc  # type: ignore[misc]


async def _census_geocode(client: httpx.AsyncClient,
                          rows: list[tuple[str, str]]) -> dict[str, tuple[float, float]]:
    coords: dict[str, tuple[float, float]] = {}
    for chunk in chunked(rows, _CENSUS_CHUNK):
        coords.update(parse_census_response(await _census_post(client, chunk)))
    return coords


# ── Outscraper SAB fill (paid, flag-gated) ────────────────────────────────────

async def _outscraper_coord(client: httpx.AsyncClient,
                            name: str, city: str, state: str) -> Optional[tuple[float, float]]:
    """Google's pin for a service-area business by name+city — the raw
    Outscraper place object carries lat/lng even with the address hidden."""
    from services.gbp_service import (
        _SEARCH_ENDPOINT, _headers, _places_from_response, _to_float,
    )
    try:
        resp = await client.get(_SEARCH_ENDPOINT, headers=_headers(), timeout=60.0,
                                params={"query": f"{name} {city} {state}",
                                        "organizationsPerQueryLimit": 1,
                                        "language": "en", "async": "false"})
        resp.raise_for_status()
        places = _places_from_response(resp.json())
    except Exception as exc:
        logger.warning("leadoff_geocode.outscraper_failed",
                       extra={"name": name, "error": str(exc)})
        return None
    if not places or not isinstance(places[0], dict):
        return None
    p = places[0]
    lat = _to_float(p.get("latitude") if p.get("latitude") is not None else p.get("lat"))
    lng = _to_float(p.get("longitude") if p.get("longitude") is not None else p.get("lng"))
    return (lat, lng) if lat is not None and lng is not None else None


# ── Job ───────────────────────────────────────────────────────────────────────

async def run_geocode_job(job: dict) -> None:
    supabase = get_supabase()
    job_id = job["id"]
    try:
        cities = _city_index()
        now = datetime.now(timezone.utc).isoformat()
        matched = missed = sab_filled = 0

        async with httpx.AsyncClient(follow_redirects=True) as client:
            # 1) addressed rows → free Census batch, chunk-and-commit so each
            #    batch's coordinates persist before the next (reaper-safe).
            while True:
                batch = _pending_addressed(supabase, _CENSUS_CHUNK)
                if not batch:
                    break
                inputs = []
                for r in batch:
                    city, state = cities.get(r["city_id"], (None, None))
                    ol = one_line_address(r.get("address"), city, state)
                    if ol:
                        inputs.append((r["id"], ol))
                coords = await _census_geocode(client, inputs) if inputs else {}
                writes = []
                for r in batch:
                    base = {k: r[k] for k in ("id", "city_id", "category_id",
                                              "rank_position", "business_name")}
                    ll = coords.get(r["id"])
                    if ll:
                        writes.append({**base, "lat": ll[0], "lng": ll[1],
                                       "geo_source": "census", "geocoded_at": now})
                        matched += 1
                    else:
                        # stamp 'none' so an unmatched/city-less row leaves the
                        # queue instead of being re-selected forever
                        writes.append({**base, "geo_source": "none"})
                        missed += 1
                _bulk_write(supabase, writes)

            # 2) SAB fill via Outscraper (paid — off by default; per-business
            #    lookups, so update-by-id, also chunk-committed)
            if settings.leadoff_geocode_sab_outscraper:
                while True:
                    sab = _pending_sab(supabase, 200)
                    if not sab:
                        break
                    for r in sab:
                        city, state = cities.get(r["city_id"], (None, None))
                        ll = (await _outscraper_coord(client, r["business_name"],
                                                      city, state or "")
                              if city else None)
                        patch = ({"lat": ll[0], "lng": ll[1],
                                  "geo_source": "outscraper", "geocoded_at": now}
                                 if ll else {"geo_source": "none"})
                        supabase.table("competitor_locations").update(patch) \
                            .eq("id", r["id"]).execute()
                        if ll:
                            sab_filled += 1

        # coverage via count queries (no 200k-row fetch)
        total = _count(supabase)
        geocoded = total - _count(supabase, lat=None)
        summary = {
            "competitors": total,
            "geocoded": geocoded,
            "geocoded_pct": round(geocoded / total, 3) if total else 0,
            "by_source": {s: _count(supabase, geo_source=s)
                          for s in ("census", "outscraper")},
            "this_run": {"census_matched": matched, "census_missed": missed,
                         "sab_filled": sab_filled},
        }
        validation: dict[str, Any] = {}
        for name, state in VALIDATE:
            cid = next((k for k, (n, s) in cities.items()
                        if (n or "").lower() == name.lower() and s == state), None)
            if cid is not None:
                pins = (supabase.table("competitor_locations")
                        .select("category_id, business_name, lat, lng, geo_source")
                        .eq("city_id", cid).not_.is_("lat", "null")
                        .execute().data or [])
                validation[f"{name}, {state}"] = {"geocoded_pins": len(pins),
                                                  "sample": pins[:8]}

        result = {**summary,
                  "sab_outscraper_enabled": settings.leadoff_geocode_sab_outscraper,
                  "validation": validation,
                  "note": ("Census = street-centroid (feasibility grade); "
                           "proximity computation is the next phase, gated on "
                           "these coordinates validating on the test markets.")}
        supabase.table("async_jobs").update({
            "status": "complete", "result": result, "completed_at": "now()",
        }).eq("id", job_id).execute()
        logger.info("leadoff_geocode.complete", extra={
            "geocoded": geocoded, "geocoded_pct": summary["geocoded_pct"]})
    except Exception as exc:
        logger.error("leadoff_geocode.failed", extra={"job_id": job_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

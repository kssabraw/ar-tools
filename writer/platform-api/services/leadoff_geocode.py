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
_CENSUS_CHUNK = 5000            # census batch cap is 10k/request; stay conservative
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


def _ungeocoded_rows(supabase) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page = 0
    while True:
        chunk = (supabase.table("competitor_locations")
                 .select("id, city_id, category_id, business_name, address")
                 .is_("lat", "null")
                 .range(page * 1000, page * 1000 + 999).execute().data or [])
        out.extend(chunk)
        if len(chunk) < 1000:
            return out
        page += 1


# ── Census geocode (free, addressed rows) ─────────────────────────────────────

async def _census_geocode(client: httpx.AsyncClient,
                          rows: list[tuple[str, str]]) -> dict[str, tuple[float, float]]:
    coords: dict[str, tuple[float, float]] = {}
    for chunk in chunked(rows, _CENSUS_CHUNK):
        payload, boundary = build_census_payload(chunk)
        resp = await client.post(
            _CENSUS_BATCH_URL, content=payload,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            timeout=300.0)
        resp.raise_for_status()
        coords.update(parse_census_response(resp.text))
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
        pending = _ungeocoded_rows(supabase)
        now = datetime.now(timezone.utc).isoformat()

        # 1) addressed rows → Census batch (free)
        census_inputs: list[tuple[str, str]] = []
        sab_rows: list[dict[str, Any]] = []
        for r in pending:
            city, state = cities.get(r["city_id"], (None, None))
            one_line = one_line_address(r.get("address"), city, state)
            if one_line:
                census_inputs.append((r["id"], one_line))
            elif city:
                sab_rows.append({**r, "_city": city, "_state": state})

        updates: dict[str, dict[str, Any]] = {}
        async with httpx.AsyncClient(follow_redirects=True) as client:
            if census_inputs:
                coords = await _census_geocode(client, census_inputs)
                for rid, (lat, lng) in coords.items():
                    updates[rid] = {"lat": lat, "lng": lng,
                                    "geo_source": "census", "geocoded_at": now}

            # 2) SAB fill via Outscraper (paid — off by default)
            sab_filled = 0
            if settings.leadoff_geocode_sab_outscraper and sab_rows:
                for r in sab_rows:
                    ll = await _outscraper_coord(client, r["business_name"],
                                                 r["_city"], r["_state"] or "")
                    if ll:
                        updates[r["id"]] = {"lat": ll[0], "lng": ll[1],
                                            "geo_source": "outscraper",
                                            "geocoded_at": now}
                        sab_filled += 1

        for rid, patch in updates.items():
            supabase.table("competitor_locations").update(patch) \
                .eq("id", rid).execute()

        # coverage report + the test-market validation
        sample_ids = list(cities.keys())
        all_rows = (supabase.table("competitor_locations")
                    .select("address, lat, geo_source").limit(200000)
                    .execute().data or [])
        summary = coverage_summary(all_rows)
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

        result = {**summary, "newly_geocoded": len(updates),
                  "sab_outscraper_enabled": settings.leadoff_geocode_sab_outscraper,
                  "validation": validation,
                  "note": ("Census = street-centroid (feasibility grade); "
                           "proximity computation is the next phase, gated on "
                           "these coordinates validating on the test markets.")}
        supabase.table("async_jobs").update({
            "status": "complete", "result": result, "completed_at": "now()",
        }).eq("id", job_id).execute()
        logger.info("leadoff_geocode.complete", extra={
            "newly_geocoded": len(updates), "geocoded_pct": summary["geocoded_pct"]})
    except Exception as exc:
        logger.error("leadoff_geocode.failed", extra={"job_id": job_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

"""LeadOff — per-city county backfill + county resolution.

The scanner's board carries no county, but every city has a stored lat/lng, so
this job reverse-geocodes each city to its county via the free, keyless US
Census "geographies/coordinates" endpoint (census.gov is reachable from the
deployed worker — proven by the permits/geocode/income jobs) and stores one row
per city in the app-owned public.city_counties. That powers a county filter on
the board ("every scanned market in Hudson County, NJ").

Per-coordinate (not name-matched): we own exact coordinates, so this avoids the
duplicate-place-name ambiguity that a name lookup would hit. Best-effort,
idempotent (city_id PK), self-continuing if the endpoint throttles — same shape
as services/leadoff_geocode.py.

httpx / config / db are imported lazily inside the impure functions so the pure
parse/normalize helpers stay importable (and unit-testable) without the service
deps installed.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CENSUS_COORD_URL = (
    "https://geocoding.geo.census.gov/geocoder/geographies/coordinates")
_CENSUS_BENCHMARK = "Public_AR_Current"
_CENSUS_VINTAGE = "Current_Current"
# Census coordinates endpoint is burst-sensitive: an early run at ~26 req/s
# tripped its rate limiter and then throttled everything into backoff. So keep
# this GENTLE — low concurrency + a per-request pace — and bound each run small
# so it self-continues across rate windows instead of hogging the worker lane.
_RETRY_WAITS = [8, 30]             # transient-failure backoff (seconds); short — pacing avoids the wall
_CONCURRENCY = 3                   # gentle concurrency on the endpoint
_REQUEST_PAUSE = 0.35              # per-request pace inside the semaphore (~8 req/s ceiling)
_PAGE = 1000                       # city pages / commit chunks
# Each run resolves at most this many cities, then self-continues with a fresh
# job — bounds wall-clock per run (deploy-interruption + reaper safety) and
# spreads load across Census rate windows.
_MAX_PER_RUN = 1200
# Safety cap on the self-continue chain (payload 'run' counter) so a persistent
# failure can't spawn jobs forever. 4,682 cities / 1,200 ≈ 4 runs; 15 is slack.
_MAX_CONTINUATIONS = 15


# ── Pure helpers (unit-tested) ────────────────────────────────────────────────

def parse_county(resp_json: dict[str, Any]) -> Optional[tuple[str, str]]:
    """(county_name, county_fips) from a Census geographies/coordinates
    response, or None when no county layer matched (a coordinate in water/
    offshore). The county layer key is 'Counties'; each entry carries NAME
    ('Hudson County' / 'Orleans Parish'), BASENAME ('Hudson') and GEOID
    (5-digit state+county FIPS)."""
    try:
        geos = (resp_json.get("result") or {}).get("geographies") or {}
    except AttributeError:
        return None
    # be tolerant of the layer label ("Counties")
    counties = None
    for key, val in geos.items():
        if "count" in key.lower():
            counties = val
            break
    if not counties:
        return None
    c = counties[0]
    name = (c.get("NAME") or c.get("BASENAME") or "").strip()
    fips = (c.get("GEOID") or "").strip()
    if not name or not fips:
        return None
    return name, fips


def bare_county(name: str) -> str:
    """'Hudson County' → 'Hudson'; 'Orleans Parish' → 'Orleans'. Used only for
    lenient user-typed matching — the stored county_name keeps the full form."""
    n = (name or "").strip()
    for suffix in (" County", " Parish", " Borough", " Census Area",
                   " Municipality", " City and Borough", " Municipio"):
        if n.lower().endswith(suffix.lower()):
            return n[: -len(suffix)].strip()
    return n


def county_matches(stored_name: str, query: str) -> bool:
    """Does a user-typed county query match a stored county name? Matches on the
    full name or the bare form, case-insensitively ('hudson' or 'hudson
    county')."""
    if not stored_name or not query:
        return False
    q = query.strip().lower()
    full = stored_name.strip().lower()
    return q in (full, bare_county(full)) or bare_county(q) == bare_county(full)


# ── Data access ───────────────────────────────────────────────────────────────

def _existing_city_ids(supabase) -> set[int]:
    ids: set[int] = set()
    page = 0
    while True:
        chunk = (supabase.table("city_counties").select("city_id")
                 .range(page * _PAGE, page * _PAGE + _PAGE - 1).execute().data or [])
        ids.update(c["city_id"] for c in chunk)
        if len(chunk) < _PAGE:
            return ids
        page += 1


def _all_cities() -> list[dict[str, Any]]:
    """Every board city with coordinates (city_id, name, state_code, lat, lng)."""
    from services.leadoff_db import get_leadoff_client
    client = get_leadoff_client()
    out: list[dict[str, Any]] = []
    page = 0
    while True:
        chunk = (client.table("cities")
                 .select("city_id, name, state_code, latitude, longitude")
                 .range(page * _PAGE, page * _PAGE + _PAGE - 1).execute().data or [])
        out.extend(chunk)
        if len(chunk) < _PAGE:
            return out
        page += 1


def _bulk_upsert(supabase, rows: list[dict[str, Any]]) -> None:
    for i in range(0, len(rows), 500):
        supabase.table("city_counties").upsert(rows[i:i + 500]).execute()


# ── County resolution (for the board filter + picker) ─────────────────────────

def city_ids_for_county(county: str, state: Optional[str] = None) -> list[int]:
    """City ids in a (fuzzily-matched) county, optionally scoped to a state.
    Reads public.city_counties. Empty when the county isn't recognized."""
    from db.supabase_client import get_supabase
    supabase = get_supabase()
    q = supabase.table("city_counties").select("city_id, county_name, state_code")
    if state:
        q = q.eq("state_code", state.upper())
    rows = q.execute().data or []
    return [r["city_id"] for r in rows
            if county_matches(r.get("county_name") or "", county)]


def list_counties(state: Optional[str] = None) -> list[dict[str, Any]]:
    """Distinct counties (name + state), optionally filtered to a state, for the
    board's county picker. Sorted by state then county."""
    from db.supabase_client import get_supabase
    supabase = get_supabase()
    q = supabase.table("city_counties").select("county_name, state_code")
    if state:
        q = q.eq("state_code", state.upper())
    rows = q.execute().data or []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        name, st = r.get("county_name"), r.get("state_code")
        if name and st:
            seen[(st, name)] = {"county_name": name, "state_code": st}
    return sorted(seen.values(), key=lambda x: (x["state_code"], x["county_name"]))


# ── Census reverse geocode ────────────────────────────────────────────────────

async def _county_for_coord(client, lat: float, lng: float) -> Optional[tuple[str, str]]:
    """One coordinate → (county_name, fips). Retries transient failures; returns
    None on a hard failure so one bad point can't fail the run."""
    import httpx
    params = {"x": lng, "y": lat, "benchmark": _CENSUS_BENCHMARK,
              "vintage": _CENSUS_VINTAGE, "format": "json"}
    headers = {"User-Agent": ("Mozilla/5.0 (compatible; AR-Tools-LeadOff/1.0; "
                              "+https://amazingrankings.com)"),
               "Accept": "application/json"}
    for attempt in range(len(_RETRY_WAITS) + 1):
        try:
            resp = await client.get(_CENSUS_COORD_URL, params=params,
                                    headers=headers, timeout=60.0)
            if resp.status_code in (429, 500, 502, 503, 504):
                resp.raise_for_status()
            resp.raise_for_status()
            return parse_county(resp.json())
        except (httpx.HTTPStatusError, httpx.TransportError,
                httpx.TimeoutException) as exc:
            transient = not (isinstance(exc, httpx.HTTPStatusError)
                             and exc.response.status_code not in
                             (429, 500, 502, 503, 504))
            if transient and attempt < len(_RETRY_WAITS):
                await asyncio.sleep(_RETRY_WAITS[attempt])
                continue
            raise
        except ValueError:   # non-JSON body (edge block page) — not this point's fault
            return None
    return None


# ── Scheduling (self-gating: run when cities lack a county row) ────────────────

def enqueue_due_county_backfill() -> int:
    """Enqueue the county backfill when cities exist without a county row and
    none is already queued. Cheap daily check; cities are static, so this runs
    once to fill and then only tops up genuinely new cities. Never raises into
    the scheduler loop."""
    from config import settings
    from db.supabase_client import get_supabase
    if not settings.leadoff_counties_enabled:
        return 0
    try:
        supabase = get_supabase()
        active = (supabase.table("async_jobs").select("id", count="exact")
                  .eq("job_type", "leadoff_county_backfill")
                  .in_("status", ["pending", "running"]).limit(1)
                  .execute().count or 0)
        if active:
            return 0
        have = (supabase.table("city_counties").select("city_id", count="exact")
                .limit(1).execute().count or 0)
        from services.leadoff_db import get_leadoff_client
        total = (get_leadoff_client().table("cities").select("city_id", count="exact")
                 .limit(1).execute().count or 0)
        if total and have >= total:
            return 0
        supabase.table("async_jobs").insert({
            "job_type": "leadoff_county_backfill", "entity_id": str(uuid.uuid4()),
            "payload": {}, "max_attempts": 5}).execute()
        return 1
    except Exception:
        logger.warning("leadoff_counties.enqueue_failed", exc_info=True)
        return 0


# ── Job ───────────────────────────────────────────────────────────────────────

async def run_county_backfill_job(job: dict) -> None:
    import httpx
    from db.supabase_client import get_supabase
    supabase = get_supabase()
    job_id = job["id"]
    payload = job.get("payload") or {}
    run_n = int(payload.get("run", 0)) if isinstance(payload, dict) else 0
    try:
        done = _existing_city_ids(supabase)
        pending = [c for c in _all_cities()
                   if c["city_id"] not in done
                   and c.get("latitude") is not None
                   and c.get("longitude") is not None]
        total_pending = len(pending)
        batch = pending[:_MAX_PER_RUN]
        now = datetime.now(timezone.utc).isoformat()
        matched = missed = 0
        sem = asyncio.Semaphore(_CONCURRENCY)
        writes: list[dict[str, Any]] = []

        async with httpx.AsyncClient(follow_redirects=True) as client:
            async def one(c: dict[str, Any]) -> dict[str, Any]:
                async with sem:
                    res = await _county_for_coord(
                        client, float(c["latitude"]), float(c["longitude"]))
                    # pace inside the slot so the endpoint's burst limiter isn't
                    # tripped (a fast run once throttled the whole continuation)
                    await asyncio.sleep(_REQUEST_PAUSE)
                row = {"city_id": c["city_id"], "city_name": c.get("name"),
                       "state_code": c.get("state_code"), "source": "census",
                       "updated_at": now}
                if res:
                    row["county_name"], row["county_fips"] = res
                return row

            # process in commit-sized chunks so progress persists (reaper-safe)
            for i in range(0, len(batch), 500):
                sub = batch[i:i + 500]
                results = await asyncio.gather(*(one(c) for c in sub),
                                               return_exceptions=True)
                good = [r for r in results if isinstance(r, dict)]
                for r in good:
                    if r.get("county_fips"):
                        matched += 1
                    else:
                        missed += 1
                if good:
                    _bulk_upsert(supabase, good)

        remaining = total_pending - len(batch)
        continued = False
        # Self-continue with a fresh job (bounded chain) so each run stays short
        # and load spreads across Census rate windows. Progress-gated: only chain
        # when this run actually wrote something, so a persistent failure fails
        # instead of spawning no-op jobs forever.
        if remaining > 0 and (matched + missed) > 0 and run_n + 1 <= _MAX_CONTINUATIONS:
            supabase.table("async_jobs").insert({
                "job_type": "leadoff_county_backfill",
                "entity_id": str(uuid.uuid4()), "payload": {"run": run_n + 1},
                "max_attempts": 5,
            }).execute()
            continued = True

        have = (supabase.table("city_counties").select("city_id", count="exact")
                .limit(1).execute().count or 0)
        result = {
            "run": run_n, "processed_this_run": len(batch),
            "county_matched": matched, "no_county": missed,
            "remaining": remaining, "continuation_enqueued": continued,
            "total_with_county": have,
        }
        supabase.table("async_jobs").update({
            "status": "complete", "result": result, "completed_at": "now()",
        }).eq("id", job_id).execute()
        logger.info("leadoff_counties.complete", extra=result)
    except Exception as exc:
        logger.error("leadoff_counties.failed",
                     extra={"job_id": job_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

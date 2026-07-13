"""LeadOff household-income backfill — per-city median household income from the
free, keyless US Census ACS 5-year API (table B19013), the demographic input to
the peer-cohort field-strength signal (services/leadoff_peer_cohort.py).

No income lived anywhere in the board; this job fetches it once (annually) and
stores one value per city we have on file. The Census API returns every place
in a state in a single call, so the whole country is ~51 requests — one per
state FIPS — matched to our cities by normalized place name + state. Cheap and
$0, same source the proximity geocoder already uses (census.gov is reachable
from the deployed worker).

Best-effort per state: a failing state is logged and skipped, never aborting
the run. Idempotent (city_id PK upsert); a re-run refreshes in place.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# httpx / config / db are imported lazily inside the impure functions so the
# pure parse/normalize/match helpers stay importable (and unit-testable) in a
# sandbox without the service deps installed.

logger = logging.getLogger(__name__)

_ACS_BASE = "https://api.census.gov/data"
_RETRY_WAITS = [10, 30, 90]
_STATE_PAUSE = 0.5

# FIPS → USPS state code (50 states + DC — the places the board covers).
STATE_FIPS: dict[str, str] = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY",
}

# Census place-name suffixes to strip so "Cheyenne city" matches our "Cheyenne".
_SUFFIXES = (
    "city", "town", "village", "borough", "municipality", "cdp",
    "township", "plantation", "gore", "grant", "location",
)
_SUFFIX_RE = re.compile(
    r"\s+(?:" + "|".join(_SUFFIXES) + r")\b\.?$", re.IGNORECASE)
_BALANCE_RE = re.compile(r"\s*\(balance\)\s*$", re.IGNORECASE)


# ── Pure helpers (unit-tested) ────────────────────────────────────────────────

def normalize_place_name(name: str) -> str:
    """Bare, comparable place name from a Census NAME field.

    "Cheyenne city, Wyoming" → "cheyenne"; "St. Louis city, Missouri" →
    "st. louis"; "Lake Havasu City city, Arizona" → "lake havasu city" (only
    the trailing government-type suffix is stripped, not a real 'City' in the
    name). Drops the ", State" tail and the '(balance)' marker."""
    base = name.split(",")[0].strip()
    base = _BALANCE_RE.sub("", base)
    # strip at most one trailing government-type suffix (never a real word)
    stripped = _SUFFIX_RE.sub("", base).strip()
    if stripped:
        base = stripped
    return base.lower()


def coerce_income(raw: Any) -> Optional[int]:
    """ACS median household income → int, or None for the no-data sentinels
    (negative jam values like -666666666, empty, or nulls)."""
    try:
        v = int(float(raw))
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


def coerce_pop(raw: Any) -> int:
    try:
        v = int(float(raw))
    except (TypeError, ValueError):
        return 0
    return max(v, 0)


def parse_acs_rows(data: list[list[Any]]) -> list[dict[str, Any]]:
    """Parse the ACS JSON matrix (first row is the header) into place dicts
    {name, norm, income, population}. Rows with an unusable income are kept out
    (no point matching a place we have no income for)."""
    if not data or len(data) < 2:
        return []
    header = [h.lower() for h in data[0]]
    try:
        i_name = header.index("name")
        i_inc = header.index("b19013_001e")
    except ValueError:
        return []
    i_pop = header.index("b01003_001e") if "b01003_001e" in header else None
    out: list[dict[str, Any]] = []
    for row in data[1:]:
        income = coerce_income(row[i_inc])
        if income is None:
            continue
        name = str(row[i_name])
        out.append({
            "name": name,
            "norm": normalize_place_name(name),
            "income": income,
            "population": coerce_pop(row[i_pop]) if i_pop is not None else 0,
        })
    return out


def best_by_norm(places: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse places sharing a normalized name (e.g. a 'city' and a 'CDP' of
    the same name) to the most-populous one — the best match to our board city,
    which is a ≥10k-pop incorporated place."""
    best: dict[str, dict[str, Any]] = {}
    for p in places:
        cur = best.get(p["norm"])
        if cur is None or p["population"] > cur["population"]:
            best[p["norm"]] = p
    return best


def match_places(places: list[dict[str, Any]],
                 city_index: dict[str, int]) -> dict[int, dict[str, Any]]:
    """{city_id: {income, matched_name}} for the state's places matched against
    our {normalized_name: city_id} index for that state."""
    collapsed = best_by_norm(places)
    out: dict[int, dict[str, Any]] = {}
    for norm, p in collapsed.items():
        city_id = city_index.get(norm)
        if city_id is not None:
            out[city_id] = {"income": p["income"], "matched_name": p["name"]}
    return out


# ── Data access ───────────────────────────────────────────────────────────────

def _city_index_by_state() -> dict[str, dict[str, int]]:
    """{state_code: {normalized_city_name: city_id}} for every board city."""
    from services.leadoff_db import get_leadoff_client

    client = get_leadoff_client()
    idx: dict[str, dict[str, int]] = {}
    page = 0
    while True:
        chunk = (client.table("cities").select("city_id, name, state_code")
                 .range(page * 1000, page * 1000 + 999).execute().data or [])
        for c in chunk:
            st = (c.get("state_code") or "").strip().upper()
            nm = (c.get("name") or "").strip()
            if st and nm:
                idx.setdefault(st, {})[normalize_place_name(nm)] = c["city_id"]
        if len(chunk) < 1000:
            return idx
        page += 1


def _upsert_income(supabase, rows: list[dict[str, Any]], now: str) -> None:
    for i in range(0, len(rows), 500):
        supabase.table("city_household_income").upsert(
            [{**r, "source": "census_acs5", "pulled_at": now}
             for r in rows[i:i + 500]]).execute()


async def _fetch_state(client, fips: str) -> list[list[Any]]:
    """One state's places with income + population. Retries transient failures;
    returns [] on a hard/parse failure so one bad state doesn't fail the run."""
    import httpx

    from config import settings
    params = {
        "get": "NAME,B19013_001E,B01003_001E",
        "for": "place:*",
        "in": f"state:{fips}",
    }
    url = f"{_ACS_BASE}/{settings.leadoff_income_acs_year}/acs/acs5"
    for attempt in range(len(_RETRY_WAITS) + 1):
        try:
            resp = await client.get(url, params=params, timeout=120.0)
            if resp.status_code in (429, 500, 502, 503, 504):
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.TransportError,
                httpx.TimeoutException) as exc:
            transient = not (isinstance(exc, httpx.HTTPStatusError)
                             and exc.response.status_code not in
                             (429, 500, 502, 503, 504))
            if transient and attempt < len(_RETRY_WAITS):
                await asyncio.sleep(_RETRY_WAITS[attempt])
                continue
            logger.warning("leadoff_income.state_failed",
                           extra={"fips": fips, "error": str(exc)[:200]})
            return []
        except ValueError:  # non-JSON body
            logger.warning("leadoff_income.state_bad_json", extra={"fips": fips})
            return []
    return []


# ── Scheduling (self-gating: run once if empty, else annually) ────────────────

def enqueue_due_income_backfill() -> int:
    """Enqueue the income backfill when the store is empty or older than
    `leadoff_income_refresh_days`, and none is already queued. Cheap daily
    check; best-effort — never raises into the scheduler loop."""
    from config import settings
    from db.supabase_client import get_supabase
    if not settings.leadoff_income_enabled:
        return 0
    try:
        supabase = get_supabase()
        active = (supabase.table("async_jobs").select("id", count="exact")
                  .eq("job_type", "leadoff_income_backfill")
                  .in_("status", ["pending", "running"]).limit(1)
                  .execute().count or 0)
        if active:
            return 0
        newest = (supabase.table("city_household_income")
                  .select("pulled_at").order("pulled_at", desc=True)
                  .limit(1).execute().data or [])
        if newest:
            age_cut = (datetime.now(timezone.utc)
                       - timedelta(days=settings.leadoff_income_refresh_days))
            ts = datetime.fromisoformat(str(newest[0]["pulled_at"]))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts > age_cut:
                return 0
        supabase.table("async_jobs").insert({
            "job_type": "leadoff_income_backfill", "entity_id": str(uuid.uuid4()),
            "payload": {}, "max_attempts": 3}).execute()
        return 1
    except Exception:
        logger.warning("leadoff_income.enqueue_failed", exc_info=True)
        return 0


# ── Job ───────────────────────────────────────────────────────────────────────

async def run_income_backfill_job(job: dict) -> None:
    import httpx

    from config import settings
    from db.supabase_client import get_supabase
    supabase = get_supabase()
    job_id = job["id"]
    try:
        city_index = _city_index_by_state()
        now = datetime.now(timezone.utc).isoformat()
        matched_total = places_total = states_ok = 0
        writes: list[dict[str, Any]] = []

        async with httpx.AsyncClient(follow_redirects=True) as client:
            for fips, state_code in STATE_FIPS.items():
                data = await _fetch_state(client, fips)
                if not data:
                    continue
                states_ok += 1
                places = parse_acs_rows(data)
                places_total += len(places)
                state_matches = match_places(places, city_index.get(state_code, {}))
                for city_id, m in state_matches.items():
                    writes.append({"city_id": city_id,
                                   "state_code": state_code,
                                   "median_household_income": m["income"],
                                   "matched_name": m["matched_name"]})
                matched_total += len(state_matches)
                if len(writes) >= 500:
                    _upsert_income(supabase, writes, now)
                    writes = []
                await asyncio.sleep(_STATE_PAUSE)
        if writes:
            _upsert_income(supabase, writes, now)

        cities_total = sum(len(v) for v in city_index.values())
        result = {
            "acs_year": settings.leadoff_income_acs_year,
            "states_fetched": states_ok, "states_total": len(STATE_FIPS),
            "places_with_income": places_total,
            "cities_matched": matched_total, "cities_total": cities_total,
            "match_pct": round(matched_total / cities_total, 3) if cities_total else 0,
        }
        supabase.table("async_jobs").update({
            "status": "complete", "result": result, "completed_at": "now()",
        }).eq("id", job_id).execute()
        logger.info("leadoff_income.complete", extra=result)
    except Exception as exc:
        logger.error("leadoff_income.failed",
                     extra={"job_id": job_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

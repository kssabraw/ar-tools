"""LeadOff GBP Placement Advisor — Phase 0b feasibility probe (plan §4.3.2/§9).

The opt-in paid ZIP demand layer (Phase 3) re-weights the free Census demand
surface by real per-ZIP Google Ads search volume — BUT Google thresholds volume
at small geos, so niche categories read null in most ZIPs and the layer would
add nothing. Before building the layer past this point, one ~$0.05 probe must
confirm DataForSEO actually returns non-null postal-code volumes on a known
high-volume market (plan §4.3.2). If >`null_share` of ZIPs come back null, the
layer is `inconclusive` and Phase 3 is dropped from v1 — this module is then the
record of why.

The probe: resolve a handful of real postal-code location_codes in a dense metro
from DataForSEO's Google-Ads locations DB, then run one `search_volume/live`
task per ZIP for a high-volume keyword, and measure the null share. Reuses the
existing DataForSEO auth/endpoint pattern (services/keyword_market.py). $0.05-ish
one-off — deliberately NOT wired to any user-facing button until it passes.

httpx / config / db imported lazily inside the impure functions so the pure
helpers stay importable (and unit-testable) without the service deps.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dataforseo.com"
_VOLUME_PATH = "/v3/keywords_data/google_ads/search_volume/live"
_LOCATIONS_PATH = "/v3/keywords_data/google_ads/locations/US"
_TIMEOUT = 120.0
_POSTAL_TYPE = "Postal Code"


# ── Pure helpers (unit-tested) ────────────────────────────────────────────────

def pick_probe_zips(locations: list[dict[str, Any]], prefix: str,
                    n: int) -> list[dict[str, Any]]:
    """Up to `n` postal-code locations whose name starts with `prefix` (a ZIP
    prefix, e.g. '606' → Chicago). DataForSEO postal-code names are
    '60601,Illinois,United States'. Returns {location_code, location_name}."""
    out: list[dict[str, Any]] = []
    for loc in locations:
        if (loc.get("location_type") == _POSTAL_TYPE
                and str(loc.get("location_name") or "").startswith(prefix)
                and loc.get("location_code") is not None):
            out.append({"location_code": loc["location_code"],
                        "location_name": loc["location_name"]})
            if len(out) >= n:
                break
    return out


def probe_verdict(results: list[dict[str, Any]],
                  null_share_bar: float) -> dict[str, Any]:
    """Judge the probe (pure). `results` = [{location_name, volume, error}].
    A ZIP is "queried" when the task didn't error; among queried ZIPs, null =
    volume is None (Google thresholded it). Verdict: `pass` when the null share
    is at/below the bar, `inconclusive` above it, `error` when nothing queried."""
    queried = [r for r in results if not r.get("error")]
    if not queried:
        return {"verdict": "error", "tested": len(results), "queried": 0,
                "non_null": 0, "null_share": None,
                "reason": "no ZIP returned a task (check location resolution / creds)"}
    non_null = [r for r in queried if r.get("volume") is not None]
    null_share = round(1 - len(non_null) / len(queried), 3)
    verdict = "pass" if null_share <= null_share_bar else "inconclusive"
    return {"verdict": verdict, "tested": len(results), "queried": len(queried),
            "non_null": len(non_null), "null_share": null_share,
            "null_share_bar": null_share_bar}


# ── DataForSEO access ─────────────────────────────────────────────────────────

def _auth_header() -> dict[str, str]:
    from config import settings
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    return {"Authorization": f"Basic {base64.b64encode(creds.encode()).decode()}",
            "Content-Type": "application/json"}


async def _fetch_us_locations(client) -> list[dict[str, Any]]:
    """The Google-Ads locations DB for the US (postal codes + cities + regions).
    One large GET; free/cheap. Returns the flat result list."""
    resp = await client.get(f"{_BASE_URL}{_LOCATIONS_PATH}", headers=_auth_header())
    resp.raise_for_status()
    body = resp.json()
    tasks = body.get("tasks") or []
    if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
        raise RuntimeError(f"dataforseo_locations_error: "
                           f"{tasks[0].get('status_message') if tasks else 'no tasks'}")
    return tasks[0].get("result") or []


async def _zip_volume(client, keyword: str, location_code: int,
                      location_name: str) -> dict[str, Any]:
    """One search_volume/live task for a keyword at a postal-code location.
    Returns {location_code, location_name, volume, error}."""
    from config import settings
    payload = [{"keywords": [keyword], "location_code": location_code,
                "language_code": settings.dataforseo_default_language_code}]
    row: dict[str, Any] = {"location_code": location_code,
                           "location_name": location_name,
                           "volume": None, "error": None}
    try:
        resp = await client.post(f"{_BASE_URL}{_VOLUME_PATH}",
                                 headers=_auth_header(), json=payload)
        resp.raise_for_status()
        tasks = (resp.json().get("tasks") or [])
        if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
            row["error"] = (tasks[0].get("status_message") if tasks else "no task")
            return row
        items = tasks[0].get("result") or []
        if items:
            row["volume"] = items[0].get("search_volume")
    except Exception as exc:  # transport / HTTP error for this ZIP
        row["error"] = str(exc)[:200]
    return row


# ── Job ───────────────────────────────────────────────────────────────────────

async def run_zip_demand_probe_job(job: dict) -> None:
    """Phase 0b: run the feasibility probe and persist the verdict on the job
    row. Reads config for the test metro/keyword; best-effort per ZIP."""
    import httpx

    from config import settings
    from db.supabase_client import get_supabase
    supabase = get_supabase()
    job_id = job["id"]
    try:
        if not (settings.dataforseo_login and settings.dataforseo_password):
            raise RuntimeError("dataforseo credentials not configured")
        keyword = settings.leadoff_zip_probe_keyword
        prefix = settings.leadoff_zip_probe_zip_prefix
        count = settings.leadoff_zip_probe_count
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            locations = await _fetch_us_locations(client)
            zips = pick_probe_zips(locations, prefix, count)
            if not zips:
                raise RuntimeError(f"no postal codes matched prefix {prefix!r} "
                                   f"({len(locations)} US locations scanned)")
            results = []
            for z in zips:
                results.append(await _zip_volume(
                    client, keyword, z["location_code"], z["location_name"]))

        verdict = probe_verdict(
            results, settings.placement_zip_null_share_inconclusive)
        result = {
            "phase": "0b_probe", "keyword": keyword, "zip_prefix": prefix,
            **verdict,
            "sample": [{"zip": r["location_name"], "volume": r["volume"],
                        "error": r["error"]} for r in results],
            "note": ("Phase 0b feasibility probe (plan §4.3.2). verdict=pass → "
                     "DataForSEO returns per-ZIP volumes; build Phase 3. "
                     "verdict=inconclusive → Google thresholds this geo/category; "
                     "the paid ZIP layer would add no signal → dropped from v1."),
        }
        supabase.table("async_jobs").update({
            "status": "complete", "result": result, "completed_at": "now()",
        }).eq("id", job_id).execute()
        logger.info("leadoff_zip_demand.probe_complete",
                    extra={"verdict": verdict.get("verdict"),
                           "null_share": verdict.get("null_share")})
    except Exception as exc:
        logger.error("leadoff_zip_demand.probe_failed",
                     extra={"job_id": job_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

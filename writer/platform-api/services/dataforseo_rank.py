"""DataForSEO live organic rank — the fallback rank source.

Organic Rank Tracker (Module #4). Used when GSC can't cover a keyword: either
the site has no accessible GSC property, or the site doesn't rank for the
keyword (so GSC returns nothing). Fetches a point-in-time Google organic SERP
and finds the client's domain position, writing it to
rank_keyword_metrics.tracked_rank. Refreshed weekly to bound cost.

DataForSEO writes only tracked_rank; the GSC materialize writes only
gsc_position — the two columns are never reconciled (PRD §2/§5).
"""

from __future__ import annotations

import base64
import calendar
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

from config import settings
from db.supabase_client import get_supabase
from services.locations_service import infer_country_iso

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dataforseo.com"
_SERP_PATH = "/v3/serp/google/organic/live/advanced"
_TIMEOUT = 60.0

# A small ISO→DataForSEO country location_code map for the countries the suite's
# location helper already recognizes; falls back to the configured default.
_COUNTRY_LOCATION_CODES = {
    "US": 2840, "GB": 2826, "CA": 2124, "AU": 2036, "NZ": 2554, "IE": 2372,
    "ZA": 2710, "IN": 2356, "SG": 2702, "PH": 2608, "MY": 2458, "DE": 2276,
    "FR": 2250, "ES": 2724, "IT": 2380, "NL": 2528, "SE": 2752, "BR": 2076,
    "MX": 2484, "AE": 2784,
}


def _auth_header() -> dict[str, str]:
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    encoded = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def extract_domain(website_url: str) -> str:
    """Registrable host for SERP matching: strip scheme, path, and leading www."""
    if not website_url:
        return ""
    raw = website_url if "//" in website_url else f"//{website_url}"
    host = (urlparse(raw).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def location_code_for(client: dict) -> int:
    """DataForSEO location for a client's rank/market checks.

    Prefers an explicit per-client tracking location (city/region/country picked
    in the UI); otherwise falls back to the country auto-detected from the
    website TLD.
    """
    code = client.get("rank_tracking_location_code")
    if code:
        return int(code)
    iso = infer_country_iso(client)
    return _COUNTRY_LOCATION_CODES.get(iso, settings.dataforseo_default_location_code)


def find_rank_in_items(items: list[dict], domain: str) -> Optional[int]:
    """First organic result whose domain matches `domain`, by rank_absolute.

    Returns None when the domain isn't in the fetched results (= not ranking in
    the top N) — a real, stored fact, not an error.
    """
    if not domain:
        return None
    for item in items:
        if item.get("type") != "organic":
            continue
        item_domain = (item.get("domain") or "").lower()
        if item_domain == domain or item_domain.endswith("." + domain):
            rank = item.get("rank_absolute") or item.get("rank_group")
            return int(rank) if rank is not None else None
    return None


def is_gsc_covered(rows: list[dict], today: date, days: int) -> bool:
    """True if the keyword has a non-null GSC position within the last `days`."""
    cutoff = today.toordinal() - days + 1
    for row in rows:
        if row.get("gsc_position") is None:
            continue
        d = row["date"]
        d_ord = (d if isinstance(d, date) else date.fromisoformat(d)).toordinal()
        if d_ord >= cutoff:
            return True
    return False


def is_fetch_due(config: dict, today: date, default_weekday: int) -> bool:
    """Whether a client's scheduled DataForSEO rank pull should fire today.

    `config` is a rank_fetch_config row (or {} for a client with no explicit
    schedule, which defaults to the legacy weekly-on-`default_weekday` cadence).
    Mirrors rank_report.is_report_due; 'off' never auto-fires, and a fetch never
    fires twice on the same day. `default_weekday` is config.dataforseo_rank_weekday.
    """
    mode = config.get("mode", "weekly")
    if mode == "off":
        return False

    last_raw = config.get("last_fetched_at")
    last_date = date.fromisoformat(last_raw[:10]) if last_raw else None
    if last_date == today:
        return False

    if mode == "weekly":
        dow = config.get("day_of_week")
        if dow is None:
            dow = default_weekday
        return today.weekday() == dow
    if mode == "monthly":
        dom = config.get("day_of_month") or 1
        last_day = calendar.monthrange(today.year, today.month)[1]
        return today.day == min(dom, last_day)  # clamp e.g. 31 → month end
    if mode == "interval":
        n = config.get("interval_days") or 7
        return last_date is None or (today.toordinal() - last_date.toordinal()) >= n
    return False


# ----------------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------------
async def fetch_serp_rank(keyword: str, domain: str, location_code: int) -> Optional[int]:
    """Live organic SERP rank of `domain` for `keyword`, or None if not found."""
    payload = [
        {
            "keyword": keyword,
            "language_code": settings.dataforseo_default_language_code,
            "location_code": location_code,
            "depth": settings.dataforseo_serp_depth,
            "calculate_rectangles": False,
        }
    ]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(f"{_BASE_URL}{_SERP_PATH}", headers=_auth_header(), json=payload)
        resp.raise_for_status()
        body = resp.json()

    tasks = body.get("tasks") or []
    if not tasks or (tasks[0].get("status_code") or 0) >= 40000:
        raise RuntimeError(f"dataforseo_serp_error: {tasks[0].get('status_message') if tasks else 'no tasks'}")
    items = (tasks[0].get("result") or [{}])[0].get("items") or []
    return find_rank_in_items(items, domain)


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------
async def refresh_client_ranks(client_id: str, today: Optional[date] = None) -> dict:
    """Fetch DataForSEO ranks for every keyword GSC can't cover, for one client.

    Skips keywords already covered by a verified GSC property; for the rest,
    writes today's tracked_rank into rank_keyword_metrics. Returns a small
    summary. Designed not to raise for a single keyword's failure.
    """
    supabase = get_supabase()
    today = today or date.today()

    client_res = supabase.table("clients").select(
        "id, name, website_url, gbp, rank_tracking_location_code"
    ).eq("id", client_id).limit(1).execute()
    if not client_res.data:
        return {"status": "failed", "error": "client_not_found", "fetched": 0}
    client = client_res.data[0]
    domain = extract_domain(client.get("website_url") or "")
    if not domain:
        return {"status": "failed", "error": "client_has_no_website", "fetched": 0}
    location_code = location_code_for(client)

    gsc_available = bool(
        supabase.table("gsc_properties")
        .select("id")
        .eq("client_id", client_id)
        .eq("access_status", "ok")
        .limit(1)
        .execute()
        .data
    )

    keywords = (
        supabase.table("tracked_keywords")
        .select("id, keyword")
        .eq("client_id", client_id)
        .eq("active", True)
        .execute()
    ).data or []
    if not keywords:
        return {"status": "ok", "fetched": 0, "skipped": 0}

    # Pull recent metrics once to decide GSC coverage per keyword.
    cutoff = (today - timedelta(days=settings.rank_gsc_coverage_days)).isoformat()
    metrics = (
        supabase.table("rank_keyword_metrics")
        .select("keyword_id, date, gsc_position")
        .in_("keyword_id", [k["id"] for k in keywords])
        .gte("date", cutoff)
        .execute()
    ).data or []
    by_keyword: dict[str, list[dict]] = {}
    for row in metrics:
        by_keyword.setdefault(row["keyword_id"], []).append(row)

    fetched = skipped = failed = 0
    for kw in keywords:
        covered = gsc_available and is_gsc_covered(
            by_keyword.get(kw["id"], []), today, settings.rank_gsc_coverage_days
        )
        if covered:
            skipped += 1
            continue
        try:
            rank = await fetch_serp_rank(kw["keyword"], domain, location_code)
        except Exception as exc:
            failed += 1
            logger.warning("dataforseo_rank_failed", extra={"keyword": kw["keyword"], "error": str(exc)})
            continue
        supabase.table("rank_keyword_metrics").upsert(
            {"keyword_id": kw["id"], "date": today.isoformat(), "tracked_rank": rank},
            on_conflict="keyword_id,date",
        ).execute()
        fetched += 1

    # Advance the per-client fetch clock so interval schedules measure "days
    # since the last real pull" and a weekly/monthly fetch can't double-fire the
    # same day — whether triggered by the scheduler or a manual refresh. Skip the
    # stamp when EVERY attempt errored (transient DataForSEO outage — nothing
    # fetched): leaving last_fetched_at unchanged lets the next interval tick
    # retry instead of waiting a full cycle on a bad day. (fetched>0, or a pull
    # with nothing to do because all keywords are GSC-covered, both stamp.)
    if not (fetched == 0 and failed > 0):
        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table("rank_fetch_config").upsert(
            {"client_id": client_id, "last_fetched_at": now_iso, "updated_at": now_iso},
            on_conflict="client_id",
        ).execute()

    logger.info(
        "dataforseo_rank_complete",
        extra={"client_id": client_id, "fetched": fetched, "skipped": skipped, "failed": failed},
    )
    return {"status": "ok", "fetched": fetched, "skipped": skipped, "failed": failed}


def enqueue_dataforseo_rank(client_id: str) -> None:
    """Enqueue a weekly DataForSEO rank job (deduped against pending ones)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs")
        .select("id")
        .eq("job_type", "dataforseo_rank")
        .eq("entity_id", client_id)
        .in_("status", ["pending", "running"])
        .limit(1)
        .execute()
    )
    if existing.data:
        return
    supabase.table("async_jobs").insert(
        {"job_type": "dataforseo_rank", "entity_id": client_id, "payload": {"client_id": client_id}}
    ).execute()


async def run_dataforseo_rank_job(job: dict) -> None:
    """async_jobs handler for job_type='dataforseo_rank'."""
    from services.rank_materialize import enqueue_materialize

    payload = job.get("payload") or {}
    client_id = payload.get("client_id")
    job_id = job["id"]
    supabase = get_supabase()
    if not client_id:
        supabase.table("async_jobs").update(
            {"status": "failed", "error": "missing client_id", "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return

    result = await refresh_client_ranks(client_id)
    supabase.table("async_jobs").update(
        {
            "status": "complete" if result.get("status") == "ok" else "failed",
            "result": result,
            "error": result.get("error"),
            "completed_at": "now()",
        }
    ).eq("id", job_id).execute()

    # Recompute status/source now that fresh DataForSEO ranks have landed.
    if result.get("status") == "ok" and result.get("fetched"):
        enqueue_materialize(client_id)

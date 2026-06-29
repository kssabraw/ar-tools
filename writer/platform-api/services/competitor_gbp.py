"""Competitor GBP intelligence (Maps strategy PRD, Tier B / B1).

For the top local-pack competitors a client's geo-grid scans surface, fetch a
full Google Business Profile (via gbp_service / Outscraper) and store it as a
time-series in `competitor_gbp_profiles`. This answers *why* a competitor wins a
zone — categories, review count/velocity, photos, hours — and is the foundation
for the GBP profile audit (B2).

Each fetch is one Outscraper call, so the competitor set is capped
(`competitor_gbp_max`). Best-effort throughout: a competitor whose GBP can't be
fetched is skipped, never aborting the run.
"""

from __future__ import annotations

import logging

from config import settings
from db.supabase_client import get_supabase
from services import gbp_service

logger = logging.getLogger(__name__)


def select_competitors(results: list[dict], max_n: int) -> list[dict]:
    """Aggregate the latest scan's per-keyword `competitors` leaderboards into a
    single client-wide ranking (by Top-3 then overall local-pack presence) and
    return the top max_n. Pure (unit-tested)."""
    agg: dict[str, dict] = {}
    for r in results:
        for c in r.get("competitors") or []:
            pid = c.get("place_id")
            if not pid:
                continue
            slot = agg.setdefault(
                pid,
                {"place_id": pid, "name": c.get("name"), "primary_category": c.get("primary_category"),
                 "rating": c.get("rating"), "reviews": c.get("reviews"), "website": c.get("website"),
                 "found_pins": 0, "top3_pins": 0},
            )
            slot["found_pins"] += c.get("found_pins") or 0
            slot["top3_pins"] += c.get("top3_pins") or 0
            # Keep the richest name/category/rating we see.
            for k in ("name", "primary_category", "website"):
                if c.get(k) and not slot.get(k):
                    slot[k] = c[k]
            if c.get("rating") is not None:
                slot["rating"] = c["rating"]
            if c.get("reviews") is not None:
                slot["reviews"] = c["reviews"]
    ranked = sorted(agg.values(), key=lambda c: (-(c["top3_pins"]), -(c["found_pins"]), (c["name"] or "")))
    return ranked[:max_n]


def profile_row(client_id: str, comp: dict, details: dict) -> dict:
    """Map a fetched GBP `details` payload (+ the leaderboard `comp` context) to a
    competitor_gbp_profiles insert row. Pure (unit-tested)."""
    gbp = (details or {}).get("gbp") or {}
    return {
        "client_id": client_id,
        "place_id": (details or {}).get("place_id") or comp.get("place_id"),
        "name": gbp.get("business_name") or comp.get("name"),
        "primary_category": gbp.get("gbp_category") or comp.get("primary_category"),
        "business_type": gbp_service.classify_business_type(gbp),
        "gbp_categories": gbp.get("gbp_categories") or [],
        "rating": gbp.get("gbp_rating") if gbp.get("gbp_rating") is not None else comp.get("rating"),
        "review_count": gbp.get("gbp_review_count") if gbp.get("gbp_review_count") is not None else comp.get("reviews"),
        "website": gbp.get("website") or comp.get("website"),
        "phone": gbp.get("phone"),
        "address": gbp.get("address"),
        "photo": gbp.get("photo"),
        "has_hours": bool(gbp.get("hours")),
        "found_pins": comp.get("found_pins"),
        "top3_pins": comp.get("top3_pins"),
        "profile": gbp,
    }


def _latest_completed_scan_results(supabase, client_id: str) -> list[dict]:
    scan = (
        supabase.table("maps_scans").select("id")
        .eq("client_id", client_id).eq("status", "complete")
        .order("completed_at", desc=True).limit(1).execute()
    ).data
    if not scan:
        return []
    return (
        supabase.table("maps_scan_results").select("competitors")
        .eq("scan_id", scan[0]["id"]).execute()
    ).data or []


async def fetch_and_store(client_id: str) -> dict:
    """Select the client's top local-pack competitors from the latest scan and
    store a fresh GBP capture for each. Returns {fetched, skipped, competitors}."""
    supabase = get_supabase()
    results = _latest_completed_scan_results(supabase, client_id)
    competitors = select_competitors(results, settings.competitor_gbp_max)
    if not competitors:
        return {"fetched": 0, "skipped": 0, "competitors": 0}

    rows: list[dict] = []
    skipped = 0
    for comp in competitors:
        try:
            details = await gbp_service.get_business_details(comp["place_id"])
            rows.append(profile_row(client_id, comp, details))
        except Exception as exc:  # one bad competitor must not abort the run
            skipped += 1
            logger.warning(
                "competitor_gbp_fetch_failed",
                extra={"client_id": client_id, "place_id": comp.get("place_id"), "error": str(exc)},
            )
    if rows:
        try:
            supabase.table("competitor_gbp_profiles").insert(rows).execute()
        except Exception as exc:
            logger.error("competitor_gbp_store_failed", extra={"client_id": client_id, "error": str(exc)})
            raise
    return {"fetched": len(rows), "skipped": skipped, "competitors": len(competitors)}


def latest_profiles(client_id: str) -> list[dict]:
    """The most recent capture per competitor, ordered by local-pack presence."""
    supabase = get_supabase()
    rows = (
        supabase.table("competitor_gbp_profiles")
        .select("place_id, name, primary_category, gbp_categories, rating, review_count, "
                "website, phone, address, photo, has_hours, business_type, found_pins, top3_pins, captured_at")
        .eq("client_id", client_id)
        .order("captured_at", desc=True)
        .limit(500)
        .execute()
    ).data or []
    seen: set[str] = set()
    latest: list[dict] = []
    for r in rows:  # rows are newest-first → first occurrence per place_id is latest
        pid = r.get("place_id")
        if pid in seen:
            continue
        seen.add(pid)
        latest.append(r)
    latest.sort(key=lambda r: (-(r.get("top3_pins") or 0), -(r.get("found_pins") or 0)))
    return latest


def enqueue_competitor_gbp(client_id: str) -> bool:
    """Enqueue a competitor_gbp job (deduped against any in-flight one)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "competitor_gbp").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return False
    supabase.table("async_jobs").insert(
        {"job_type": "competitor_gbp", "entity_id": client_id, "payload": {"client_id": client_id}}
    ).execute()
    return True


async def run_competitor_gbp_job(job: dict) -> None:
    """async_jobs handler for job_type='competitor_gbp'."""
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
        result = await fetch_and_store(client_id)
    except Exception as exc:
        logger.warning("competitor_gbp_job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()

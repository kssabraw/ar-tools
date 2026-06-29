"""Review analytics (Maps strategy PRD, Tier B / B3).

Compares Google review volume, velocity (reviews/month), rating distribution and
recent negatives for the client vs its top local-pack competitors. Reviews are
fetched via DataForSEO (all ratings, newest-first — unlike gbp_service's
4★-only "strong reviews" marketing pull) and stored in `reviews`; analytics are
deterministic and computed on read.

LLM sentiment/theme extraction is a deliberate follow-up (the `reviews.sentiment`
column is reserved); v1 surfaces volume/velocity/rating/recent-negatives, which
are reliable without an LLM.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta

import httpx

from config import settings
from db.supabase_client import get_supabase
from services import competitor_gbp
from services.gbp_service import _DATAFORSEO_REVIEWS_ENDPOINT, _to_float

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0
_NEGATIVE_MAX_RATING = 2.0
_RECENT_DAYS = 90
_VELOCITY_DAYS = 365


def _review_key(place_id: str, reviewer: str, d: str, text: str) -> str:
    return hashlib.md5(f"{place_id}|{reviewer}|{d}|{text}".encode("utf-8")).hexdigest()


def _parse_reviews_all(data: dict) -> list[dict]:
    """Map a DataForSEO reviews/live response to our shape — ALL ratings (so the
    distribution + negatives are real), newest-first preserved from the request."""
    tasks = data.get("tasks") or []
    if not tasks:
        return []
    result = (tasks[0] or {}).get("result") or []
    if not result:
        return []
    items = (result[0] or {}).get("items") or []
    out: list[dict] = []
    for r in items:
        if not isinstance(r, dict):
            continue
        rating_raw = r.get("review_rating")
        rating = _to_float(rating_raw.get("value")) if isinstance(rating_raw, dict) else _to_float(r.get("rating"))
        ts = r.get("timestamp") or ""
        dt = r.get("review_datetime_utc") or ""
        d = ts.split("T")[0] if ts else (dt.split(" ")[0] if dt else "")
        out.append(
            {
                "reviewer": r.get("profile_name") or r.get("author_title") or "Anonymous",
                "rating": rating,
                "text": r.get("review_text") or "",
                "date": d,
            }
        )
    return out


async def fetch_reviews_full(place_id: str, depth: int) -> list[dict]:
    """Fetch up to `depth` newest reviews (all ratings) for a place. Best-effort."""
    if not place_id or not settings.dataforseo_login or not settings.dataforseo_password:
        return []
    body = [{"place_id": place_id, "depth": depth, "sort_by": "newest", "language_name": "English"}]
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _DATAFORSEO_REVIEWS_ENDPOINT, json=body,
                auth=(settings.dataforseo_login, settings.dataforseo_password),
            )
            resp.raise_for_status()
            return _parse_reviews_all(resp.json())
    except httpx.HTTPError:
        logger.warning("review_analytics.fetch_failed", extra={"place_id": place_id})
        return []


# --- pure analytics ---------------------------------------------------------
def analyze_reviews(reviews: list[dict], today: date) -> dict:
    """Deterministic per-entity review analytics. Pure (unit-tested).
    Returns {count, avg_rating, rating_distribution, velocity_per_month,
    recent_negatives, last_review_date}."""
    count = len(reviews)
    dist = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    rating_sum = 0.0
    rating_n = 0
    recent_neg = 0
    in_year = 0
    last_date = None
    recent_cut = today - timedelta(days=_RECENT_DAYS)
    year_cut = today - timedelta(days=_VELOCITY_DAYS)
    for r in reviews:
        rating = r.get("rating")
        if rating is not None:
            rating_sum += rating
            rating_n += 1
            bucket = min(5, max(1, round(rating)))
            dist[str(bucket)] += 1
        d = _as_date(r.get("date"))
        if d:
            if last_date is None or d > last_date:
                last_date = d
            if d >= year_cut:
                in_year += 1
            if d >= recent_cut and rating is not None and rating <= _NEGATIVE_MAX_RATING:
                recent_neg += 1
    return {
        "count": count,
        "avg_rating": round(rating_sum / rating_n, 2) if rating_n else None,
        "rating_distribution": dist,
        "velocity_per_month": round(in_year / 12, 1),
        "recent_negatives": recent_neg,
        "last_review_date": last_date.isoformat() if last_date else None,
    }


def _as_date(s) -> "date | None":
    try:
        return date.fromisoformat(s) if s else None
    except (ValueError, TypeError):
        return None


def _median(values: list[float]) -> "float | None":
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    return vals[len(vals) // 2]


def compare(client: dict, competitors: list[dict]) -> dict:
    """Client vs competitor-median velocity & rating. Pure (unit-tested)."""
    comp_velocity = _median([c.get("velocity_per_month") for c in competitors])
    comp_rating = _median([c.get("avg_rating") for c in competitors])
    cv = client.get("velocity_per_month")
    velocity_behind = (
        round(comp_velocity - cv, 1) if comp_velocity is not None and cv is not None and comp_velocity > cv else None
    )
    return {
        "competitor_median_velocity": comp_velocity,
        "competitor_median_rating": comp_rating,
        "velocity_behind": velocity_behind,   # reviews/month the client trails the median, else None
    }


def detect_review_gap(comparison: dict, client: dict, min_behind: float) -> "dict | None":
    """An Action-Plan signal: client review velocity meaningfully behind the
    competitor median, or recent negative reviews. Pure."""
    behind = comparison.get("velocity_behind")
    neg = client.get("recent_negatives") or 0
    if (behind is None or behind < min_behind) and neg == 0:
        return None
    return {
        "velocity": client.get("velocity_per_month"),
        "competitor_velocity": comparison.get("competitor_median_velocity"),
        "behind": behind,
        "recent_negatives": neg,
    }


# --- impure: fetch + store + read -------------------------------------------
def _store(client_id: str, place_id: str, is_client: bool, reviews: list[dict]) -> int:
    if not reviews:
        return 0
    rows = []
    for r in reviews:
        text = r.get("text") or ""
        reviewer = r.get("reviewer") or ""
        d = r.get("date") or ""
        rows.append(
            {
                "client_id": client_id,
                "place_id": place_id,
                "is_client": is_client,
                "reviewer": reviewer,
                "rating": r.get("rating"),
                "text": text,
                "review_date": d or None,
                "review_key": _review_key(place_id, reviewer, d, text),
            }
        )
    supabase = get_supabase()
    try:
        supabase.table("reviews").upsert(rows, on_conflict="client_id,review_key", ignore_duplicates=True).execute()
    except Exception as exc:
        logger.warning("review_analytics.store_failed", extra={"client_id": client_id, "error": str(exc)})
        return 0
    return len(rows)


async def fetch_and_store(client_id: str) -> dict:
    """Fetch + store reviews for the client's own GBP and its top local-pack
    competitors. Returns {client_reviews, competitor_reviews, competitors}."""
    supabase = get_supabase()
    depth = settings.review_intel_depth
    stored_client = 0
    stored_comp = 0

    client_rows = supabase.table("clients").select("gbp_place_id").eq("id", client_id).limit(1).execute().data
    client_place = (client_rows[0].get("gbp_place_id") if client_rows else None)
    if client_place:
        stored_client = _store(client_id, client_place, True, await fetch_reviews_full(client_place, depth))

    profiles = competitor_gbp.latest_profiles(client_id)
    for p in profiles[: settings.competitor_gbp_max]:
        pid = p.get("place_id")
        if not pid:
            continue
        stored_comp += _store(client_id, pid, False, await fetch_reviews_full(pid, depth))

    return {"client_reviews": stored_client, "competitor_reviews": stored_comp, "competitors": len(profiles)}


def get_review_intel(client_id: str, today: "date | None" = None) -> dict:
    """Read stored reviews → client analytics, per-competitor analytics, and the
    comparison. Impure read; analytics are the pure helpers above."""
    today = today or date.today()
    supabase = get_supabase()
    rows = (
        supabase.table("reviews")
        .select("place_id, is_client, rating, text, review_date, reviewer")
        .eq("client_id", client_id)
        .limit(5000)
        .execute()
    ).data or []
    client_reviews = [{"rating": r.get("rating"), "date": r.get("review_date")} for r in rows if r.get("is_client")]
    by_comp: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("is_client"):
            continue
        by_comp.setdefault(r.get("place_id"), []).append({"rating": r.get("rating"), "date": r.get("review_date")})

    client = analyze_reviews(client_reviews, today)
    names = {p.get("place_id"): p.get("name") for p in competitor_gbp.latest_profiles(client_id)}
    competitors = []
    for pid, revs in by_comp.items():
        a = analyze_reviews(revs, today)
        a["place_id"] = pid
        a["name"] = names.get(pid)
        competitors.append(a)
    competitors.sort(key=lambda c: -(c["velocity_per_month"] or 0))
    comparison = compare(client, competitors)
    return {"client": client, "competitors": competitors, "comparison": comparison}


def enqueue_review_intel(client_id: str) -> bool:
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "review_intel").eq("entity_id", client_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return False
    supabase.table("async_jobs").insert(
        {"job_type": "review_intel", "entity_id": client_id, "payload": {"client_id": client_id}}
    ).execute()
    return True


async def run_review_intel_job(job: dict) -> None:
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
        logger.warning("review_intel_job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()
        return
    supabase.table("async_jobs").update(
        {"status": "complete", "result": result, "completed_at": "now()"}
    ).eq("id", job_id).execute()

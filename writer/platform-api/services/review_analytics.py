"""Review analytics (Maps strategy PRD, Tier B / B3).

Compares Google review volume, velocity (reviews/month), rating distribution and
recent negatives for the client vs its top local-pack competitors. Reviews are
fetched via `services.dataforseo_reviews` (all ratings, newest-first — unlike
gbp_service's 4★-only "strong reviews" marketing pull) and stored in `reviews`;
analytics are deterministic and computed on read.

A failed fetch RAISES rather than returning an empty list. Every headline this
module produces — count, velocity, recent negatives — has zero as a legitimate
value, so a fetch that reports failure as emptiness does not degrade the feature,
it fabricates a result. That is what happened for months behind a 404 (outreach
ISSUES I-059), and why `fetch_and_store` now reports `failures` explicitly.

LLM sentiment/theme extraction is a deliberate follow-up (the `reviews.sentiment`
column is reserved); v1 surfaces volume/velocity/rating/recent-negatives, which
are reliable without an LLM.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta

from config import settings
from db.supabase_client import get_supabase
from services import competitor_gbp, dataforseo_reviews
from services.dataforseo_reviews import ReviewFetchError

logger = logging.getLogger(__name__)

_NEGATIVE_MAX_RATING = 2.0
_RECENT_DAYS = 90
_VELOCITY_DAYS = 365


def _review_key(place_id: str, reviewer: str, d: str, text: str) -> str:
    return hashlib.md5(f"{place_id}|{reviewer}|{d}|{text}".encode("utf-8")).hexdigest()


async def fetch_reviews_full(place_id: str, depth: int) -> list[dict]:
    """Fetch up to `depth` newest reviews (all ratings) for a place.

    Raises `ReviewFetchError` on failure. It previously returned `[]`, which this
    module's analytics cannot distinguish from a business that genuinely has no
    reviews — and because the endpoint it called had been 404ing all along
    (outreach ISSUES I-059), every client and competitor looked like it had zero
    reviews, zero velocity and zero recent negatives. Those are the module's
    headline outputs, so the failure produced confident, wrong numbers rather
    than a visible outage. Failures must reach the caller.
    """
    return await dataforseo_reviews.fetch_reviews(place_id, depth, sort_by="newest")


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
        # DO UPDATE on conflict (was DO NOTHING): a re-pull must refresh a row's
        # rating/text — the rows stored before the rating-shape fix carry null
        # ratings and would otherwise stay null forever.
        supabase.table("reviews").upsert(rows, on_conflict="client_id,review_key", ignore_duplicates=False).execute()
    except Exception as exc:
        logger.warning("review_analytics.store_failed", extra={"client_id": client_id, "error": str(exc)})
        return 0
    return len(rows)


# ── marketing reviews for the writer ────────────────────────────────────────
# `clients.gbp.reviews` is the ONLY review text the Local SEO / service writers
# are handed (the ≥4★ "strong reviews" pull captured with the GBP). When that
# list is empty — the GBP capture predates the pull, or Outscraper's inline
# reviews_data came back empty — the client's testimonials block can't be
# written honestly. The full review pull this module makes is the natural
# source to backfill it from, in the same shape and with the same policy.
_MARKETING_MIN_RATING = 4
_MARKETING_LIMIT = 10


def marketing_reviews(reviews: list[dict], limit: int = _MARKETING_LIMIT) -> list[dict]:
    """Pure: the writer-facing subset of a full review pull — ≥4★ with text,
    newest first, capped — in the `clients.gbp.reviews` shape
    ``{reviewer, rating, text, date}``."""
    keep = []
    for r in reviews or []:
        if not isinstance(r, dict):
            continue
        text = (r.get("text") or "").strip()
        rating = r.get("rating")
        if not text or not isinstance(rating, (int, float)) or rating < _MARKETING_MIN_RATING:
            continue
        keep.append({
            "reviewer": r.get("reviewer") or "Anonymous",
            "rating": float(rating),
            "text": text,
            "date": str(r.get("date") or ""),
        })
    keep.sort(key=lambda r: r["date"], reverse=True)
    return keep[:limit]


def _backfill_gbp_reviews(client_id: str, reviews: list[dict]) -> int:
    """Fill `clients.gbp.reviews` from the full pull when it is empty. Never
    overwrites reviews already on file (the GBP capture stays the owner of
    that list once it has one). Best-effort; returns the number written."""
    picked = marketing_reviews(reviews)
    if not picked:
        return 0
    supabase = get_supabase()
    try:
        row = (supabase.table("clients").select("gbp").eq("id", client_id).limit(1).execute().data or [{}])[0]
        gbp = row.get("gbp") if isinstance(row.get("gbp"), dict) else {}
        existing = gbp.get("reviews")
        if isinstance(existing, list) and any(isinstance(r, dict) and (r.get("text") or "").strip() for r in existing):
            return 0
        supabase.table("clients").update({"gbp": {**gbp, "reviews": picked}}).eq("id", client_id).execute()
        logger.info("review_analytics.gbp_reviews_backfilled", extra={"client_id": client_id, "count": len(picked)})
        return len(picked)
    except Exception as exc:  # noqa: BLE001 — a backfill must never sink the run
        logger.warning("review_analytics.gbp_reviews_backfill_failed", extra={"client_id": client_id, "error": str(exc)})
        return 0


class _ShapeUnproven(RuntimeError):
    """The first lookup of a run failed, so nothing has yet proved the provider contract holds.

    Raised to abort the run rather than keep paying to rediscover the same failure. See
    `fetch_and_store` for why this is a fail-fast rather than a per-place skip.
    """


async def _fetch_or_record(
    place_id: str, depth: int, failures: list[dict], *, proven: bool
) -> list[dict]:
    """One lookup, with the failure RECORDED rather than disguised as zero reviews.

    A failed place is skipped (no rows stored) and named in `failures`, so a run that
    could not reach the provider is distinguishable from a run that found nothing —
    the distinction this module lost when its fetch swallowed a 404 into `[]`.

    `proven` is False until some lookup in this run has succeeded. While it is False a
    failure aborts the run (`_ShapeUnproven`) instead of being skipped, because a failure
    before ANY success is almost certainly systemic — a dead endpoint, a rejected
    credential, an unparseable envelope — and those fail identically for every remaining
    place. DataForSEO bills on task acceptance, so continuing would pay N times to learn
    what the first task already established.
    """
    try:
        return await fetch_reviews_full(place_id, depth)
    except ReviewFetchError as exc:
        logger.error(
            "review_analytics.fetch_failed",
            extra={"place_id": place_id, "error": str(exc), "proven": proven},
        )
        failures.append({"place_id": place_id, "error": str(exc)})
        if not proven:
            raise _ShapeUnproven(str(exc)) from exc
        return []


async def fetch_and_store(client_id: str) -> dict:
    """Fetch + store reviews for the client's own GBP and its top local-pack
    competitors.

    Returns {client_reviews, competitor_reviews, competitors, failures, failed, aborted} —
    `failures` names every place whose lookup errored. A caller (or a human reading
    the job result) can then tell "this market has no reviews" apart from "we could
    not ask", which reporting zero for both made impossible.

    **The run aborts on a failure that precedes any success**, and `aborted` carries the
    reason. The `task_post`/`task_get` envelope is parsed tolerantly but has never been
    confirmed against a live paid task (I-059) — the probe established that the lifecycle
    exists, not what it returns. Since DataForSEO bills on task acceptance, a wrong
    envelope would otherwise cost one billed task per place, every one of them failing
    the same way. Stopping at the first means a bad contract costs a single task instead
    of a run, and the fix is verified by the next run rather than by a synthetic test that
    can only confirm the shape we already assumed.

    Once ONE lookup succeeds the contract is proved for this run, and later failures are
    per-place problems (a delisted business, a transient timeout) that correctly skip and
    continue.
    """
    supabase = get_supabase()
    depth = settings.review_intel_depth
    stored_client = 0
    stored_comp = 0
    failures: list[dict] = []
    profiles: list[dict] = []
    proven = False
    aborted: str | None = None
    backfilled = 0

    client_rows = supabase.table("clients").select("gbp_place_id").eq("id", client_id).limit(1).execute().data
    client_place = (client_rows[0].get("gbp_place_id") if client_rows else None)

    try:
        if client_place:
            reviews = await _fetch_or_record(client_place, depth, failures, proven=proven)
            proven = True
            stored_client = _store(client_id, client_place, True, reviews)
            backfilled = _backfill_gbp_reviews(client_id, reviews)

        profiles.extend(competitor_gbp.latest_profiles(client_id))
        for p in profiles[: settings.competitor_gbp_max]:
            pid = p.get("place_id")
            if not pid:
                continue
            reviews = await _fetch_or_record(pid, depth, failures, proven=proven)
            proven = True
            stored_comp += _store(client_id, pid, False, reviews)
    except _ShapeUnproven as exc:
        aborted = str(exc)
        logger.error(
            "review_analytics.run_aborted",
            extra={"client_id": client_id, "error": aborted},
        )

    return {
        "client_reviews": stored_client,
        "gbp_reviews_backfilled": backfilled,
        "competitor_reviews": stored_comp,
        "competitors": len(profiles),
        "failures": failures,
        "failed": len(failures),
        "aborted": aborted,
    }


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

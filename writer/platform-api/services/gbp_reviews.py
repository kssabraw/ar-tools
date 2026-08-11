"""GBP review time-series for client reporting.

Two capabilities, both feeding the report's "reviews this period vs last period":

  * a dated-review fetch (one paid Outscraper call) → count new reviews per
    period + surface recent highlights. Works immediately (reviews carry dates).
  * a review-count + rating snapshot series (`gbp_review_snapshots`) → the exact
    rating-over-time that individual reviews can't reconstruct; builds up over
    captures.

Pure helpers (`count_in_range`, `avg_rating_asof`, `newest_highlights`, the
query resolver, the Outscraper parser) are unit-tested; the fetch + DB writes are
the only I/O and are all best-effort (never raise into the report).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from config import settings

logger = logging.getLogger(__name__)

_OUTSCRAPER_SEARCH_URL = "https://api.app.outscraper.com/maps/search-v3"
_FETCH_TIMEOUT = 60.0


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------
def query_for(gbp: dict) -> Optional[str]:
    """Best identifier for an Outscraper review lookup: the Maps URL (carries the
    CID, unambiguous) → place_id / cid → business name. None when nothing usable."""
    if not isinstance(gbp, dict):
        return None
    for key in ("google_maps_uri", "place_id", "cid", "business_name"):
        val = gbp.get(key)
        if val:
            return str(val)
    return None


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def parse_reviews(place: dict[str, Any]) -> list[dict]:
    """Map Outscraper `reviews_data` to [{date, rating, text, reviewer}] — ALL
    ratings (this is a count/period source, not marketing copy), newest first.
    Pure."""
    raw = place.get("reviews_data") if isinstance(place, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        d = _parse_date((r.get("review_datetime_utc") or "").split(" ")[0])
        if d is None:
            continue
        try:
            rating = float(r.get("review_rating")) if r.get("review_rating") is not None else None
        except (TypeError, ValueError):
            rating = None
        out.append({
            "date": d,
            "rating": rating,
            "text": (r.get("review_text") or "").strip(),
            "reviewer": r.get("author_title") or "Anonymous",
        })
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


def count_in_range(reviews: list[dict], start: date, end: date) -> int:
    """Reviews created in (start, end]. Pure."""
    return sum(1 for r in reviews if isinstance(r.get("date"), date) and start < r["date"] <= end)


def avg_rating_asof(reviews: list[dict], asof: date) -> Optional[float]:
    """Approximate aggregate rating as of a date = mean of review ratings on/before
    it. Best-effort reconstruction when no exact snapshot exists; None when there
    are no rated reviews in range. Pure."""
    vals = [r["rating"] for r in reviews
            if isinstance(r.get("date"), date) and r["date"] <= asof and isinstance(r.get("rating"), (int, float))]
    return round(sum(vals) / len(vals), 2) if vals else None


def newest_highlights(reviews: list[dict], start: date, end: date,
                      min_rating: float = 4.0, limit: int = 2, max_len: int = 240) -> list[str]:
    """Newest positive review texts created in (start, end] (for the report's
    'recent reviews this period' highlights). Pure."""
    out: list[str] = []
    for r in reviews:  # already newest-first
        d = r.get("date")
        if not (isinstance(d, date) and start < d <= end):
            continue
        if (r.get("rating") or 0) < min_rating or not r.get("text"):
            continue
        out.append(r["text"][:max_len])
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Fetch (paid Outscraper call) + snapshot store — I/O, best-effort
# ---------------------------------------------------------------------------
def fetch_dated_reviews(gbp: dict, limit: Optional[int] = None) -> list[dict]:
    """Fetch the client's reviews (newest first, all ratings, with dates) from
    Outscraper. Best-effort — [] on any failure or missing key/identifier."""
    if not settings.outscraper_api_key:
        return []
    query = query_for(gbp)
    if not query:
        return []
    limit = limit or settings.client_report_review_fetch_limit
    try:
        import httpx  # noqa: PLC0415

        params = {
            "query": query,
            "organizationsPerQueryLimit": 1,
            "language": "en",
            "async": "false",
            "reviewsLimit": limit,
            "sort": "newest",
        }
        with httpx.Client(timeout=_FETCH_TIMEOUT) as client:
            resp = client.get(_OUTSCRAPER_SEARCH_URL, params=params,
                              headers={"X-API-KEY": settings.outscraper_api_key})
            resp.raise_for_status()
            data = resp.json()
        # Outscraper returns data.data as an array-of-arrays; the place is at [0][0].
        blocks = data.get("data") if isinstance(data, dict) else None
        place = None
        if isinstance(blocks, list) and blocks:
            first = blocks[0]
            place = first[0] if isinstance(first, list) and first else (first if isinstance(first, dict) else None)
        return parse_reviews(place) if isinstance(place, dict) else []
    except Exception as exc:  # noqa: BLE001 — a review fetch must never sink a report
        logger.warning("gbp_reviews.fetch_failed", extra={"error": str(exc)})
        return []


def record_snapshot(supabase, client_id: str, review_count: Optional[int], rating: Optional[float]) -> None:
    """Upsert today's review-count + rating snapshot for a client. Best-effort."""
    if review_count is None and rating is None:
        return
    try:
        supabase.table("gbp_review_snapshots").upsert(
            {"client_id": client_id, "captured_at": date.today().isoformat(),
             "review_count": review_count, "rating": rating},
            on_conflict="client_id,captured_at",
        ).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("gbp_reviews.snapshot_failed", extra={"client_id": client_id, "error": str(exc)})


def snapshot_on_or_before(supabase, client_id: str, on_or_before: date) -> Optional[dict]:
    """The newest review snapshot captured on/before a date (for exact period-start
    review_count / rating). None when there's no such snapshot."""
    try:
        rows = (
            supabase.table("gbp_review_snapshots")
            .select("captured_at, review_count, rating")
            .eq("client_id", client_id)
            .lte("captured_at", on_or_before.isoformat())
            .order("captured_at", desc=True).limit(1).execute()
        ).data
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("gbp_reviews.snapshot_read_failed", extra={"client_id": client_id, "error": str(exc)})
        return None

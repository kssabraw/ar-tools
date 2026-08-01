"""DataForSEO review retrieval — the corrected instrument (outreach ISSUES I-059).

**What was wrong.** Two services in this API — `gbp_service` and `review_analytics` — called
`POST /v3/business_data/google/reviews/live`. That path **does not exist**; it returns 404. Both
call sites wrapped it in `except httpx.HTTPError: return []`, and `httpx.HTTPStatusError`
subclasses `HTTPError`, so every 404 was converted into the sentence "this business has no
reviews" and returned as data. Nothing raised, nothing alerted, and the sentence is a perfectly
plausible one — so GBP review enrichment and the whole Tier-B review-analytics feature have been
returning nothing for as long as that endpoint has been gone, while reporting `count: 0`,
`velocity_per_month: 0.0` and `recent_negatives: 0` as measurements.

**How the replacement was established.** Not from vendor docs and not by reading this estate — by
a free probe against these credentials (a task DataForSEO rejects is not billed), run in the
outreach pipeline. The endpoint below EXISTS; `reviews/live` does not:

    /v3/business_data/google/reviews/live         404  gone. Do not resurrect it.
    /v3/business_data/google/reviews/task_post    200  exists — queued lifecycle
    /v3/business_data/google/my_business_info/live 200 exists — business record, NO review objects

The previous fix asserted `reviews/live` was "production-proven because platform-api calls it in
production". It is called there. It also 404s. **Being CALLED is not being WORKING** — that
mistake is the reason this module states which claims are measured and which are not.

**Shape caveat, stated plainly.** The task_post/task_get *lifecycle* is confirmed to exist; the
exact result envelope it returns for these credentials is parsed tolerantly here but has NOT been
verified against a live paid task. That is why the error semantics below matter more than the
parsing: if the shape is wrong, this raises and says so loudly on the first call, rather than
returning `[]` and quietly meaning "no reviews" for another few months.

**The rule this module exists to enforce:** a failed lookup NEVER returns "no reviews". Absence of
evidence must not be able to argue for absence of reviews — that is exactly the failure mode being
corrected. Failures raise `ReviewFetchError`; only the provider may assert zero.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dataforseo.com"

# Probe-confirmed as existing. The queued lifecycle: task_post → task_get.
REVIEWS_TASK_POST_ENDPOINT = f"{_BASE_URL}/v3/business_data/google/reviews/task_post"
REVIEWS_TASK_GET_ENDPOINT = f"{_BASE_URL}/v3/business_data/google/reviews/task_get"

# Probe-confirmed as existing. Returns a business record with its rating + vote count, and
# NEVER review objects — so it can answer "how many reviews" but not "what do they say".
MY_BUSINESS_INFO_LIVE_ENDPOINT = f"{_BASE_URL}/v3/business_data/google/my_business_info/live"

# 404s. Named, not deleted, so the next person who finds it in git history does not re-derive
# the discovery — and does not wire it up again.
REVIEWS_LIVE_ENDPOINT_DOES_NOT_EXIST = f"{_BASE_URL}/v3/business_data/google/reviews/live"

# DataForSEO reports per-task status INSIDE a 200 response — a transport-level 200 says nothing
# about whether the task succeeded. 20000 is its "Ok" code; 20100 is "task created".
_TASK_STATUS_OK = 20000
_TASK_STATUS_CREATED = 20100

_TIMEOUT = 45.0
# Queued lifecycle: how long to wait for a posted task to become collectable. Reviews are
# gathered by a background job, so a slow answer is fine — a WRONG answer is not.
_POLL_ATTEMPTS = 12
_POLL_INTERVAL_SECONDS = 5.0

_DEFAULT_LOCATION_CODE = 2840  # United States
_DEFAULT_LANGUAGE_NAME = "English"


class ReviewFetchError(RuntimeError):
    """A failed review lookup — including a task-level error returned inside a 200.

    Deliberately NOT a subclass of anything the old call sites catch. The bug being fixed was a
    failure being caught by a broad `except httpx.HTTPError` and returned as empty data; a caller
    that wants to degrade must now do so explicitly, in code that says so.
    """


def credentials_present() -> bool:
    return bool(settings.dataforseo_login and settings.dataforseo_password)


def _auth() -> tuple[str, str]:
    return (settings.dataforseo_login, settings.dataforseo_password)


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _first_task(body: dict[str, Any]) -> dict[str, Any]:
    """The first task of a response, with its task-level status checked.

    A task-level error is RAISED rather than returned as an empty result. This is the single
    most important line in the module: the old code's equivalent path returned `[]`.
    """
    tasks = body.get("tasks") or []
    if not tasks:
        raise ReviewFetchError("response carried no tasks")
    task = tasks[0] or {}
    status = task.get("status_code")
    if status is not None and status not in (_TASK_STATUS_OK, _TASK_STATUS_CREATED):
        raise ReviewFetchError(
            f"task failed: status_code={status} message={task.get('status_message')!r}"
        )
    return task


def parse_task_id(body: dict[str, Any]) -> str:
    """Read the task id out of a task_post response."""
    task = _first_task(body)
    task_id = task.get("id")
    if not task_id:
        raise ReviewFetchError("task_post returned no task id")
    return str(task_id)


def task_is_ready(body: dict[str, Any]) -> bool:
    """Whether a task_get response actually carries a result block yet.

    Kept separate from parsing so "not finished yet" and "finished and empty" stay distinguishable
    — collapsing them is how a poll loop turns an in-progress task into "no reviews".
    """
    try:
        task = _first_task(body)
    except ReviewFetchError:
        return False
    if task.get("status_code") != _TASK_STATUS_OK:
        return False
    return bool(task.get("result"))


def parse_reviews(body: dict[str, Any]) -> list[dict]:
    """Map a reviews task_get envelope to our review shape — ALL ratings, order preserved.

    No rating filtering and no truncation here: which reviews matter is the caller's policy
    (`gbp_service` wants strong reviews with text for marketing copy; `review_analytics` needs
    every rating or its distribution and negative counts are wrong). A fetch layer that quietly
    drops 1★ reviews would make the analytics feature silently incorrect rather than empty, which
    is harder to notice, not easier.
    """
    task = _first_task(body)
    result = task.get("result") or []
    if not result:
        raise ReviewFetchError("task returned no result block")

    items = (result[0] or {}).get("items") or []
    out: list[dict] = []
    for r in items:
        if not isinstance(r, dict):
            continue
        rating_raw = r.get("review_rating")
        rating = (
            _to_float(rating_raw.get("value"))
            if isinstance(rating_raw, dict)
            else _to_float(r.get("rating"))
        )
        timestamp = r.get("timestamp") or ""
        datetime_utc = r.get("review_datetime_utc") or ""
        if timestamp:
            review_date = timestamp.split("T")[0]
        elif datetime_utc:
            review_date = datetime_utc.split(" ")[0]
        else:
            review_date = ""
        out.append(
            {
                "reviewer": r.get("profile_name") or r.get("author_title") or "Anonymous",
                "rating": rating,
                "text": r.get("review_text") or "",
                "date": review_date,
            }
        )
    return out


def parse_business_rating(body: dict[str, Any]) -> tuple[Optional[float], Optional[int]]:
    """Read (rating, review_count) from a my_business_info/live response.

    **Zero and missing are kept apart.** `votes_count: 0` is a positive assertion of zero and is
    returned as int 0; an absent count returns None. Collapsing the two would let a parse failure
    vote for "this business has no reviews", which is the conclusion under investigation.
    """
    task = _first_task(body)
    result = task.get("result") or []
    if not result:
        raise ReviewFetchError("task returned no result block")

    first = result[0] or {}
    items = first.get("items")
    record = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else first

    rating_raw = record.get("rating")
    rating: Optional[float] = None
    count: Optional[int] = None
    if isinstance(rating_raw, dict):
        rating = _to_float(rating_raw.get("value"))
        for key in ("votes_count", "rating_count", "reviews_count"):
            value = rating_raw.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                count = int(value)
                break
    elif isinstance(rating_raw, (int, float)):
        rating = _to_float(rating_raw)

    if count is None:
        for key in ("reviews_count", "rating_count", "votes_count"):
            value = record.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                count = int(value)
                break

    return rating, count


async def fetch_reviews(place_id: str, depth: int, sort_by: str = "newest") -> list[dict]:
    """Fetch up to `depth` reviews for a place via the queued lifecycle.

    Raises `ReviewFetchError` on any failure — missing credentials, transport error, HTTP status,
    task-level error, or a task that never becomes collectable. It returns `[]` only when the
    provider genuinely returned an empty review list.
    """
    if not place_id:
        raise ReviewFetchError("no place_id")
    if not credentials_present():
        raise ReviewFetchError("DataForSEO credentials are not configured")

    post_body = [
        {
            "place_id": place_id,
            "depth": depth,
            "sort_by": sort_by,
            "location_code": _DEFAULT_LOCATION_CODE,
            "language_name": _DEFAULT_LANGUAGE_NAME,
        }
    ]
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            posted = await client.post(
                REVIEWS_TASK_POST_ENDPOINT, json=post_body, auth=_auth()
            )
            posted.raise_for_status()
            task_id = parse_task_id(posted.json())

            for _ in range(_POLL_ATTEMPTS):
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
                got = await client.get(
                    f"{REVIEWS_TASK_GET_ENDPOINT}/{task_id}", auth=_auth()
                )
                got.raise_for_status()
                body = got.json()
                if task_is_ready(body):
                    return parse_reviews(body)
    except httpx.HTTPStatusError as exc:
        # The 404 that started all this lands here, and now says so.
        raise ReviewFetchError(
            f"HTTP {exc.response.status_code} from {exc.request.url}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ReviewFetchError(f"transport error: {exc}") from exc

    raise ReviewFetchError(
        f"task {place_id} not collectable after "
        f"{_POLL_ATTEMPTS * _POLL_INTERVAL_SECONDS:.0f}s"
    )


async def fetch_business_rating(place_id: str) -> tuple[Optional[float], Optional[int]]:
    """Fetch (rating, review_count) for a place — one synchronous call, no queue.

    This is the instrument for "how many reviews does this listing have", including the explicit
    zero. It cannot answer "what do the reviews say" — the endpoint returns a business record and
    never review objects.
    """
    if not place_id:
        raise ReviewFetchError("no place_id")
    if not credentials_present():
        raise ReviewFetchError("DataForSEO credentials are not configured")

    body = [
        {
            "keyword": f"place_id:{place_id}",
            "location_code": _DEFAULT_LOCATION_CODE,
            "language_code": "en",
        }
    ]
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                MY_BUSINESS_INFO_LIVE_ENDPOINT, json=body, auth=_auth()
            )
            response.raise_for_status()
            return parse_business_rating(response.json())
    except httpx.HTTPStatusError as exc:
        raise ReviewFetchError(
            f"HTTP {exc.response.status_code} from {exc.request.url}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ReviewFetchError(f"transport error: {exc}") from exc

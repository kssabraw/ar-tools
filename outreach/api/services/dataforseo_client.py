"""DataForSEO client — the independent second opinion for ISSUES I-041.

**Why a second vendor at all.** The question is whether *Outscraper* encodes "no reviews" as null.
Asking Outscraper again cannot answer it: if the null comes from its parser failing on the review
block, it fails identically on the second pull and the ambiguous value comes back either way
(I-050). Only a provider that does not share that failure mode can settle it.

**Endpoint and request shape are taken from this estate, not from the vendor docs** — the I-029
lesson, learned when a newer SDK led to the wrong conclusion about a live endpoint.
`platform-api/services/gbp_service.py` has been calling
`POST /v3/business_data/google/reviews/live` with `{"place_id": ...}` and HTTP basic auth against
this same account, in production, for months.

**That endpoint is a better instrument than a count field.** It takes a `place_id` and returns the
reviews themselves plus `reviews_count`. So "does this listing have reviews" is answered by the
presence of review objects rather than by re-reading a number that might be null for the very
reason under investigation — and a DataForSEO `reviews_count` of **0** is a positive assertion of
zero, which is exactly what Outscraper never emits.

This module is read-only. It looks things up; deciding what the answers mean is `review_verify`'s
job, and acting on that decision is a human's.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dataforseo.com"
REVIEWS_LIVE_PATH = "/v3/business_data/google/reviews/live"

# DataForSEO reports per-task status inside a 200 response, the same trap Outscraper has
# (ISSUES I-009 in the provider notes): a transport-level 200 says nothing about whether the task
# succeeded. 20000 is its "Ok" code.
_TASK_STATUS_OK = 20000


class DataForSEOError(RuntimeError):
    """A failure talking to DataForSEO, including task-level errors returned inside a 200."""


@dataclass(frozen=True)
class PlaceReviews:
    """What one place lookup established.

    `reviews_count` is the provider's own total. `items_returned` is how many review objects came
    back, and the two are deliberately kept apart: `depth` bounds the second but not the first, so
    a listing with 400 reviews at depth 10 reports `reviews_count=400, items_returned=10`. Reading
    the item count as the review count would understate every busy business in the market.
    """

    place_id: str
    reviews_count: int | None
    rating: float | None
    items_returned: int


def missing_dataforseo_vars(settings: Settings) -> list[str]:
    """Which DataForSEO credentials are absent, by env-var name.

    Pure, and separate from the client for the same reason `missing_supabase_vars` is: naming only
    what is actually missing. "A and B must be set" when only B is absent sends people to check A
    first, which is set, and makes the error look wrong.
    """
    return [
        name
        for name, value in (
            ("OUTREACH_DATAFORSEO_LOGIN", settings.dataforseo_login),
            ("OUTREACH_DATAFORSEO_PASSWORD", settings.dataforseo_password),
        )
        if not value
    ]


def parse_place_reviews(body: dict[str, Any], place_id: str) -> PlaceReviews:
    """Read one reviews/live response.

    Tolerant of the envelope in the same way `outscraper_client.extract_places` is — a shape
    assumption that holds until it doesn't is how a parser silently returns nothing.

    A task-level error is RAISED rather than returned as "no reviews". Treating a failed lookup as
    a zero would let outages argue in favour of the very conclusion this is testing, which is the
    worst available failure mode here.
    """
    tasks = body.get("tasks") or []
    if not tasks:
        raise DataForSEOError("response carried no tasks")

    task = tasks[0] or {}
    status = task.get("status_code")
    if status is not None and status != _TASK_STATUS_OK:
        raise DataForSEOError(
            f"task failed: status_code={status} message={task.get('status_message')!r}"
        )

    result = task.get("result") or []
    if not result:
        # No result block at all. Not the same as a listing with zero reviews, and must not be
        # collapsed into one.
        raise DataForSEOError("task returned no result block")

    first = result[0] or {}
    raw_count = first.get("reviews_count")
    count = int(raw_count) if isinstance(raw_count, (int, float)) else None

    rating_raw = first.get("rating")
    if isinstance(rating_raw, dict):
        rating_raw = rating_raw.get("value")
    rating = float(rating_raw) if isinstance(rating_raw, (int, float)) else None

    items = first.get("items")
    return PlaceReviews(
        place_id=str(first.get("place_id") or place_id),
        reviews_count=count,
        rating=rating,
        items_returned=len(items) if isinstance(items, list) else 0,
    )


class DataForSEOClient:
    """Minimal async client. One endpoint, because one endpoint is all this needs.

    Deliberately NOT a general-purpose wrapper. The scan layer will want the queued Maps endpoints
    with `tasks_ready` collection (PRD §B2), which is a different lifecycle entirely — building a
    speculative abstraction over both now would be guessing at the shape of code nobody has
    written.
    """

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "DataForSEOClient":
        missing = missing_dataforseo_vars(self._settings)
        if missing:
            raise DataForSEOError(f"not set: {', '.join(missing)}")
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                timeout=self._settings.outscraper_request_timeout_seconds,
                auth=(self._settings.dataforseo_login, self._settings.dataforseo_password),
            )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_place_reviews(self, place_id: str, depth: int = 10) -> PlaceReviews:
        """Look up one place. `depth` bounds the review ITEMS returned, never `reviews_count`.

        Depth is kept small on purpose: the question is whether reviews exist at all, and a larger
        depth costs more while changing nothing about the answer.
        """
        if self._client is None:
            raise DataForSEOError("client used outside its context manager")

        body = [
            {
                "place_id": place_id,
                "depth": depth,
                "sort_by": "most_relevant",
                "language_name": "English",
            }
        ]
        response = await self._client.post(REVIEWS_LIVE_PATH, json=body)
        response.raise_for_status()
        return parse_place_reviews(response.json(), place_id)

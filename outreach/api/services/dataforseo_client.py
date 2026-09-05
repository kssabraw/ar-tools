"""DataForSEO client — the independent second opinion for ISSUES I-041.

**Why a second vendor at all.** The question is whether *Outscraper* encodes "no reviews" as null.
Asking Outscraper again cannot answer it: if the null comes from its parser failing on the review
block, it fails identically on the second pull and the ambiguous value comes back either way
(I-050). Only a provider that does not share that failure mode can settle it.

**Endpoint and request shape are MEASURED against this account, not inferred from anywhere** —
including not from this estate. The first version of this file asserted that
`POST /v3/business_data/google/reviews/live` was production-proven because
`platform-api/services/gbp_service.py` calls it in production. It does call it. It also gets a
**404**, and swallows the failure (`except httpx.HTTPError: return []`), so GBP review enrichment
has been silently returning nothing. Being CALLED is not being WORKING, and I checked the first
and claimed the second — the shallow version of the I-029 lesson I was citing at the time.

What the probe (`probe_endpoints`, free — every task deliberately invalid) actually established
against these credentials:

    /v3/business_data/google/reviews/live                 404  does not exist
    /v3/business_data/google/reviews/task_post            200  exists (queued lifecycle)
    /v3/business_data/google/my_business_info/live        200  exists, and told us its
                                                               required field: "Invalid Field:
                                                               'keyword'."
    /v3/serp/google/maps/live/advanced                    200  exists

`my_business_info/live` is the instrument this needs: one synchronous call per place, returning
that listing's own `rating.votes_count`. A votes_count of **0** is a positive assertion of zero,
which is exactly what Outscraper never emits, and is the whole reason a second vendor is worth
paying for.

**The `keyword` VALUE form is still unmeasured**, so it is discovered rather than assumed — see
`build_lookup_bodies`. A rejected task is not billed, so trying three forms costs nothing until
one is accepted.

This module is read-only. It looks things up; deciding what the answers mean is `review_verify`'s
job, and acting on that decision is a human's.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dataforseo.com"

# Probe-confirmed. Synchronous, one place per call.
MY_BUSINESS_INFO_LIVE_PATH = "/v3/business_data/google/my_business_info/live"

# Probe-confirmed as EXISTING but NOT used here: it is the queued lifecycle (task_post →
# tasks_ready → task_get), which is the right shape for the Phase 2 scan and the wrong shape for
# twenty one-off lookups. `parse_place_reviews` below still reads its result envelope.
REVIEWS_TASK_POST_PATH = "/v3/business_data/google/reviews/task_post"

# 404s. Kept named so the next person who finds it in gbp_service.py does not re-derive this.
REVIEWS_LIVE_PATH_DOES_NOT_EXIST = "/v3/business_data/google/reviews/live"

_DEFAULT_LOCATION_CODE = 2840  # United States
_DEFAULT_LANGUAGE_CODE = "en"

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
    # Which ladder rung produced this, for the log. A result from a NAME search is weaker evidence
    # than one from a place_id lookup and the report should be able to say which it was.
    form: str = ""
    # False when the provider answered about a DIFFERENT listing than the one asked about. Only
    # reachable via the name-search rungs, and it must never be read as evidence about our
    # prospect — a name search that lands on the wrong plumber would otherwise "confirm" a review
    # count for a business we did not ask about.
    place_id_matches: bool = True


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


def build_lookup_bodies(
    place_id: str,
    name: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """The ladder of `keyword` forms to try, strongest evidence first.

    The probe established that `my_business_info/live` requires a `keyword`. It did not establish
    what a *place* looks like inside one, and guessing is what produced the 404 this file exists
    to correct. So: try the forms, keep the one the provider accepts, and log which it was. A task
    DataForSEO rejects is not billed, so the rungs below an accepted one are free.

    Ordered by how much the answer is worth, not by how likely it is to work:

      place_id       unambiguous. Asks about exactly this listing.
      name + coords  a search. Can land on a neighbouring business with a similar name, so the
                     caller must check `place_id_matches` before believing it.
      name + country the same search with a much wider net, and correspondingly more likely to
                     match the wrong listing. Last because it is the weakest, not because it is
                     the least likely to be accepted.
    """
    forms: list[tuple[str, dict[str, Any]]] = []
    if place_id:
        forms.append(
            (
                "place_id",
                {
                    "keyword": f"place_id:{place_id}",
                    "location_code": _DEFAULT_LOCATION_CODE,
                    "language_code": _DEFAULT_LANGUAGE_CODE,
                },
            )
        )
    if name and lat is not None and lng is not None:
        forms.append(
            (
                "name_coordinate",
                {
                    "keyword": name,
                    "location_coordinate": f"{lat},{lng}",
                    "language_code": _DEFAULT_LANGUAGE_CODE,
                },
            )
        )
    if name:
        forms.append(
            (
                "name_country",
                {
                    "keyword": name,
                    "location_code": _DEFAULT_LOCATION_CODE,
                    "language_code": _DEFAULT_LANGUAGE_CODE,
                },
            )
        )
    return forms


def rating_evidence(body: dict[str, Any]) -> dict[str, Any]:
    """The review-bearing fields of a response, verbatim, for the log.

    The first run logged the first 2000 characters of the envelope instead, and `rating` sits
    after `latitude` in this item's field order — so the truncation cut off the exact field the
    whole question turns on, and the log could not distinguish "the provider said null" from "the
    provider said nothing" from "the parser missed it". Three different conclusions, one
    indistinguishable line.

    Returned rather than logged here so it stays pure and testable.
    """
    task = ((body.get("tasks") or [{}])[0]) or {}
    result = (task.get("result") or [{}])[0] or {}
    items = result.get("items")
    record = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else result
    return {
        "rating": record.get("rating"),
        "rating_distribution": record.get("rating_distribution"),
        # Present-with-null and absent are different claims, and only the key list separates them.
        "has_rating_key": "rating" in record,
        "is_claimed": record.get("is_claimed"),
    }


def _first_number(record: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
    return None


def parse_my_business_info(body: dict[str, Any], place_id: str) -> PlaceReviews:
    """Read one my_business_info/live response.

    The count lives on the rating object as `votes_count` (a rating and its vote count are the
    same measurement), with the flatter spellings checked as fallbacks because the exact envelope
    is measured from one live sample, not from a contract.

    **Zero and missing are kept apart.** `votes_count: 0` is the answer this whole exercise is
    trying to obtain and is returned as an integer 0; a votes_count that is absent entirely returns
    None and classifies as AMBIGUOUS. Collapsing the two would let a parse failure vote for the
    conclusion under test, which is precisely the failure mode being investigated.
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
        raise DataForSEOError("task returned no result block")

    first = result[0] or {}
    items = first.get("items")
    record = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else first

    rating_raw = record.get("rating")
    count: int | None = None
    rating: float | None = None
    if isinstance(rating_raw, dict):
        count = _first_number(rating_raw, "votes_count", "rating_count", "reviews_count")
        value = rating_raw.get("value")
        rating = float(value) if isinstance(value, (int, float)) else None
    elif isinstance(rating_raw, (int, float)):
        rating = float(rating_raw)

    if count is None:
        count = _first_number(record, "reviews_count", "rating_count", "votes_count")

    returned_id = str(record.get("place_id") or "")
    return PlaceReviews(
        place_id=returned_id or place_id,
        reviews_count=count,
        rating=rating,
        items_returned=0,  # this endpoint returns a business record, never review objects
        place_id_matches=(not returned_id) or (not place_id) or returned_id == place_id,
    )


def parse_place_reviews(body: dict[str, Any], place_id: str) -> PlaceReviews:
    """Read one reviews-endpoint result envelope.

    Unused by the verifier — `reviews/live` does not exist and the queued `task_get` path is the
    wrong shape for twenty one-off lookups. Kept because the Phase 2 scan collects exactly this
    envelope via `tasks_ready`, and because it is tested.

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
        # The rung that worked last time. Discovery is a property of the ACCOUNT, not of the
        # place, so once one lookup establishes which keyword form this account accepts, every
        # later lookup starts there instead of re-walking the ladder.
        self._preferred_form: str | None = None
        self._logged_sample = False

    async def __aenter__(self) -> "DataForSEOClient":
        missing = missing_dataforseo_vars(self._settings)
        if missing:
            raise DataForSEOError(f"not set: {', '.join(missing)}")
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                timeout=self._settings.dataforseo_request_timeout_seconds,
                auth=(self._settings.dataforseo_login, self._settings.dataforseo_password),
            )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_place_info(
        self,
        place_id: str,
        name: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
    ) -> PlaceReviews:
        """Look up one place, walking the keyword ladder until the provider accepts a form.

        Every rung the provider rejects is free, so the cost of discovering the right form is the
        cost of one accepted lookup — the same as if it had been guessed correctly.

        Raises with the whole ladder's verdicts attached when every rung fails. A bare "task
        failed" would send the next person back to the probe; naming what each form returned is
        the difference between a debuggable failure and a repeat of this file's history.
        """
        if self._client is None:
            raise DataForSEOError("client used outside its context manager")

        forms = build_lookup_bodies(place_id, name, lat, lng)
        if not forms:
            raise DataForSEOError("no usable lookup key for this prospect")
        if self._preferred_form:
            forms.sort(key=lambda f: f[0] != self._preferred_form)

        failures: list[str] = []
        for form_name, task in forms:
            response = await self._client.post(MY_BUSINESS_INFO_LIVE_PATH, json=[task])
            response.raise_for_status()
            body = response.json()
            try:
                parsed = parse_my_business_info(body, place_id)
            except DataForSEOError as exc:
                failures.append(f"{form_name}: {exc}")
                continue

            self._preferred_form = form_name
            # Logged for EVERY lookup, not just the first, and scoped to the review-bearing
            # fields rather than the first N characters of the envelope. "Sixteen listings
            # returned no count" is a much weaker statement than "sixteen listings returned
            # `rating: {value: None, votes_count: None}`", and only this line can tell them apart.
            logger.info(
                "dataforseo rating evidence",
                extra={"place_id": parsed.place_id, "form": form_name, **rating_evidence(body)},
            )
            if not self._logged_sample:
                # One full body, once, so an unexpected envelope is still recoverable from the
                # log rather than needing another paid run to diagnose.
                self._logged_sample = True
                logger.info("dataforseo sample response", extra={"raw": str(body)[:4000]})
            return replace(parsed, form=form_name)

        raise DataForSEOError("; ".join(failures) or "all keyword forms rejected")


# --- endpoint discovery -------------------------------------------------------------------
#
# Written because I asserted `/v3/business_data/google/reviews/live` was "production-proven
# against this account" on the strength of finding it in `platform-api/services/gbp_service.py`.
# It is called there, in production. It also returns 404, and that call site swallows the failure
# (`except httpx.HTTPError: return []`), so it has been silently returning "no reviews" — being
# CALLED is not the same as WORKING, and I checked the first and claimed the second.
#
# So: measure, don't infer. Candidate paths, all of them, with the status each returns.

CANDIDATE_REVIEW_PATHS: tuple[str, ...] = (
    # What gbp_service uses. Included to prove the 404 rather than assume it.
    "/v3/business_data/google/reviews/live",
    "/v3/business_data/google/reviews/live/advanced",
    "/v3/business_data/google/reviews/task_post",
    "/v3/business_data/google/my_business_info/live",
    "/v3/business_data/google/my_business_info/live/advanced",
    "/v3/business_data/google/my_business_info/task_post",
    # The live twin of the Maps path that IS genuinely proven — maps_dataforseo.py has used
    # /v3/serp/google/maps/task_post + task_get/advanced in production.
    "/v3/serp/google/maps/live/advanced",
    # Organic SERP — the report's "organic ranking vs competitors" signal (organic_scan.py). Added
    # here so `probe-dataforseo` confirms the endpoint FREE before the first paid capture, the
    # measure-don't-infer discipline this module exists to enforce.
    "/v3/serp/google/organic/live/advanced",
    "/v3/serp/google/organic/task_post",
    # DataForSEO Labs — the ad-spend MAGNITUDE source for paid-placement Slice B2 (the money signal).
    # Probed FREE here, but note what this probe can and cannot establish: `exists` is HTTP 200, which
    # proves the PATH is real. It does NOT prove this account is entitled to Labs — an unentitled
    # account can still answer 200 with a task-level access error, so read `task_status`/`task_message`,
    # not the `exists` list, before concluding Labs is usable (ISSUES I-098). Entitlement and yield are
    # both settled by the paid spike, not here. Not yet consumed by any producer.
    "/v3/dataforseo_labs/google/domain_rank_overview/live",
    "/v3/dataforseo_labs/google/bulk_traffic_estimation/live",
    # Google-Ads search volume — the DEMAND signal for the missed-opportunity valuation
    # (demand_fetch.SEARCH_VOLUME_PATH). Probed FREE here so the endpoint is confirmed before the
    # first paid fetch, the measure-don't-infer discipline. The suite's keyword_market uses this
    # same path, so it is very likely live — which is exactly what probing (not assuming) settles.
    "/v3/keywords_data/google_ads/search_volume/live",
)

# A task with no fields. A path that exists answers 200 and rejects the task at the task level
# (status_code 40xxx); a path that does not exist answers 404. **DataForSEO does not bill a
# rejected task**, so discovery costs nothing — which is the whole point of probing this way
# rather than sending a real request to seven candidate paths.
_EMPTY_TASK: list[dict[str, Any]] = [{}]


@dataclass(frozen=True)
class ProbeResult:
    path: str
    http_status: int | None
    task_status: int | None
    task_message: str | None
    exists: bool
    error: str | None = None


async def probe_endpoints(
    settings: Settings, paths: tuple[str, ...] = CANDIDATE_REVIEW_PATHS
) -> list[ProbeResult]:
    """Which of these paths exist? Free — every task sent is deliberately invalid.

    `exists` is HTTP 200 regardless of the task-level verdict: a 40501 "invalid field" means the
    endpoint is real and read our body, which is exactly what needs establishing. A 401 would mean
    the credentials are wrong rather than the path, and is reported as-is rather than folded into
    "does not exist".
    """
    missing = missing_dataforseo_vars(settings)
    if missing:
        raise DataForSEOError(f"not set: {', '.join(missing)}")

    results: list[ProbeResult] = []
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=settings.outscraper_request_timeout_seconds,
        auth=(settings.dataforseo_login, settings.dataforseo_password),
    ) as client:
        for path in paths:
            try:
                response = await client.post(path, json=_EMPTY_TASK)
                task_status: int | None = None
                task_message: str | None = None
                if response.status_code == 200:
                    body = response.json()
                    tasks = body.get("tasks") or []
                    if tasks:
                        task_status = (tasks[0] or {}).get("status_code")
                        task_message = (tasks[0] or {}).get("status_message")
                    else:
                        task_status = body.get("status_code")
                        task_message = body.get("status_message")
                results.append(
                    ProbeResult(
                        path=path,
                        http_status=response.status_code,
                        task_status=task_status,
                        task_message=task_message,
                        exists=response.status_code == 200,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — one dead path must not end the probe
                results.append(
                    ProbeResult(
                        path=path,
                        http_status=None,
                        task_status=None,
                        task_message=None,
                        exists=False,
                        error=str(exc),
                    )
                )
    return results


async def sample_endpoint(
    settings: Settings, path: str, place_id: str
) -> dict[str, Any]:
    """One REAL request against a discovered path, to learn the response shape.

    **This one bills** — a valid task is a charged task. Called for a single place on a single
    path, so the cost is cents, and the alternative is guessing at the response shape after
    guessing at the path, which is how this went wrong the first time.
    """
    body = [build_lookup_bodies(place_id)[0][1]]
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=settings.outscraper_request_timeout_seconds,
        auth=(settings.dataforseo_login, settings.dataforseo_password),
    ) as client:
        response = await client.post(path, json=body)
        return {
            "http_status": response.status_code,
            "body": response.json() if response.status_code == 200 else response.text[:500],
        }

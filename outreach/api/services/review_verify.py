"""Verify whether a null review count means zero — ISSUES I-041.

The LA pull returned no review count for 113 of 1,388 listings. The population evidence says most
are genuinely zero-review businesses (`review_count = 0` never occurs, while 1/2/3-5/6-9 occur
118/70/129/116 times; and 105 of the 113 also have a null rating, which is coherent because a
rating is an average of reviews). But one of the eight rating-carrying exceptions — Mejia Rooter —
was confirmed at 3 real Google reviews, which proves this provider *does* sometimes drop a count.
So the convention has to be tested, not assumed, before it is encoded.

**READ-ONLY except for the cost ledger.** This module answers a question; it does not act on the
answer. It never writes `review_count`, never sets `review_count_inferred_zero`, and never
excludes anything. Applying the flag is a human decision taken once, on evidence, and a verifier
that quietly applied its own findings would remove the step where someone looks at them.

## The limitation, stated up front because it bounds what the result is worth

Re-asking Outscraper is **not independent of the hypothesis under test.** If the null comes from
its parser failing to read the review block, it will fail identically on the second pull, and the
answer returns null either way. The ambiguous value is also the expected value.

What makes a detail pull worth the money anyway is the *sub-objects*: `reviews_per_score` (the
1-5 star histogram) and `reviews_data` (inline reviews). A listing with genuinely zero reviews has
no histogram and no review list. A listing whose count was dropped by a parse failure will often
still surface one or the other. That distinction — not the count field — is the evidence here, and
`classify_lookup` below is built around it.

A genuinely independent check means a different vendor: DataForSEO returns `rating.votes_count`
on the same item as `place_id` (`maps_dataforseo.py` in platform-api). That credential does not
exist on this service. If the results below come back ambiguous, that is the next step, not more
Outscraper pulls.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..config import Settings
from .cost import CostLimitExceeded
from .dataforseo_client import DataForSEOClient, PlaceReviews, missing_dataforseo_vars
from .outscraper_client import OutscraperClient, TileRequest, extract_places
from .paging import fetch_all

logger = logging.getLogger(__name__)

# Verdicts `classify_lookup` can return.
ZERO = "zero"  # no count, and no review evidence anywhere — consistent with a true zero
HAS_REVIEWS = "has_reviews"  # a count came back, or review evidence contradicts "zero"
AMBIGUOUS = "ambiguous"  # no count and no evidence either way — the pull settled nothing
ERROR = "error"


@dataclass
class LookupResult:
    place_id: str
    name: str
    verdict: str
    review_count: int | None = None
    rating: float | None = None
    has_histogram: bool = False
    inline_reviews: int = 0
    error: str | None = None
    # Which DataForSEO keyword form answered. Reported because a result from a name search is
    # weaker evidence than one from a place_id lookup, and the reader should not have to assume.
    form: str = ""


@dataclass
class VerifyReport:
    requested: int = 0
    results: list[LookupResult] = field(default_factory=list)

    @property
    def by_verdict(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.results:
            out[r.verdict] = out.get(r.verdict, 0) + 1
        return out

    @property
    def counts_found(self) -> list[int]:
        return sorted(r.review_count for r in self.results if r.review_count)

    def recommendation(self) -> str:
        """What the numbers support — deliberately conservative, and never auto-applied.

        A single contradicting listing is enough to withhold the rule: the flag would be written
        across every future market pull, so one false zero here is a systematic error there, not
        an isolated bad row.
        """
        v = self.by_verdict
        if v.get(ERROR):
            return "INCONCLUSIVE — lookups failed; re-run before drawing anything from this"
        if v.get(HAS_REVIEWS):
            return (
                f"DO NOT SET THE FLAG — {v[HAS_REVIEWS]} of {len(self.results)} sampled listings "
                "have reviews the provider did not report. Null does not reliably mean zero."
            )
        if v.get(AMBIGUOUS, 0) > v.get(ZERO, 0):
            return (
                "INCONCLUSIVE — most lookups returned no evidence either way, which is what "
                "re-asking the same provider was always at risk of doing. Use DataForSEO."
            )
        if v.get(ZERO):
            return (
                f"SUPPORTS THE FLAG — {v[ZERO]} of {len(self.results)} show no review evidence "
                "at all. Still a human call; the flag is applied by hand, not by this command."
            )
        return "INCONCLUSIVE — no usable results"


# --- pure helpers -----------------------------------------------------------------------------


def classify_dataforseo(reviews: PlaceReviews | None) -> LookupResult:
    """Turn one DataForSEO reviews/live lookup into a verdict.

    Simpler than the Outscraper classifier, and stronger, because this provider answers the actual
    question rather than one adjacent to it:

      reviews_count > 0   -> HAS_REVIEWS. Outscraper's null was a dropped count.
      review items present -> HAS_REVIEWS, even if the count somehow did not parse.
      reviews_count == 0  -> ZERO, and this is a POSITIVE ASSERTION of zero rather than an
                             absence to be interpreted. It is what Outscraper never emits, and
                             the whole reason a second vendor is worth paying for.
      count is None       -> AMBIGUOUS. Both providers declining to say is a real outcome and must
                             not be rounded down to "zero" — that would let a second silence
                             argue for the conclusion under test.
    """
    if reviews is None:
        return LookupResult(place_id="", name="", verdict=ERROR, error="no result")

    if not reviews.place_id_matches:
        # The provider answered about a different listing — reachable only from the name-search
        # rungs of the keyword ladder. Its review count is a true fact about the wrong business,
        # which is worse than no answer, because it looks exactly like an answer.
        return LookupResult(
            place_id=reviews.place_id,
            name="",
            verdict=AMBIGUOUS,
            rating=reviews.rating,
            error=f"{reviews.form} search matched a different place_id",
            form=reviews.form,
        )

    if reviews.items_returned > 0:
        verdict = HAS_REVIEWS
    elif reviews.reviews_count is None:
        verdict = AMBIGUOUS
    elif reviews.reviews_count > 0:
        verdict = HAS_REVIEWS
    else:
        verdict = ZERO

    return LookupResult(
        place_id=reviews.place_id,
        name="",
        verdict=verdict,
        review_count=reviews.reviews_count,
        rating=reviews.rating,
        inline_reviews=reviews.items_returned,
        form=reviews.form,
    )


def classify_lookup(place: dict[str, Any] | None) -> LookupResult:
    """Turn one detail pull into a verdict.

    The count field alone cannot settle this, so the sub-objects carry the weight:

      a numeric count > 0     -> HAS_REVIEWS. The first pull was wrong; this is a dropped count.
      a star histogram        -> HAS_REVIEWS. `reviews_per_score` cannot exist without reviews.
      inline review text      -> HAS_REVIEWS. Same argument, more directly.
      none of the above       -> ZERO, but only weakly: it is also what a second parse failure
                                 looks like, which is why the caller reports the split rather
                                 than a single number.
    """
    if not place:
        return LookupResult(place_id="", name="", verdict=ERROR, error="no place returned")

    place_id = str(place.get("place_id") or place.get("google_id") or "")
    name = str(place.get("name") or place.get("title") or "")

    raw_count = place.get("reviews")
    count = int(raw_count) if isinstance(raw_count, (int, float)) else None

    raw_rating = place.get("rating")
    rating = float(raw_rating) if isinstance(raw_rating, (int, float)) else None

    histogram = place.get("reviews_per_score")
    has_histogram = bool(histogram) and any(
        (v or 0) > 0 for v in (histogram.values() if isinstance(histogram, dict) else [])
    )

    inline = place.get("reviews_data")
    inline_n = len(inline) if isinstance(inline, list) else 0

    if count and count > 0:
        verdict = HAS_REVIEWS
    elif has_histogram or inline_n > 0:
        verdict = HAS_REVIEWS
    elif count == 0:
        # The provider said zero outright. Settles the convention question in one row: it CAN
        # emit 0, so a null elsewhere means something else.
        verdict = ZERO
    elif rating is not None:
        # A rating with no count and no review evidence is the 8-group shape: a rating cannot be
        # an average of nothing, so this is a dropped count, not a zero.
        verdict = HAS_REVIEWS
    else:
        verdict = ZERO if place else AMBIGUOUS

    return LookupResult(
        place_id=place_id,
        name=name,
        verdict=verdict,
        review_count=count,
        rating=rating,
        has_histogram=has_histogram,
        inline_reviews=inline_n,
    )


def select_candidates(rows: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Pick the sample deterministically.

    Ordered by place_id rather than by anything correlated with review activity — ordering by
    ingestion order or name would sample one tile or one alphabetic slice, and a biased sample of
    a convention question is worse than no sample.
    """
    return sorted(rows, key=lambda r: str(r.get("place_id") or ""))[:limit]


# --- the run ----------------------------------------------------------------------------------


async def verify_review_counts(
    *,
    client: Any,
    settings: Settings,
    market_id: str,
    limit: int = 20,
    group: str = "both_null",
    provider: str = "outscraper",
) -> VerifyReport:
    """Look up `limit` prospects one at a time and report what comes back.

    `group` selects which half of I-041 is being tested:
      both_null      the 105 — no count AND no rating. The convention question.
      rating_present the 8 — no count but a rating. Known gaps; here for completeness.

    `provider` selects who is asked:
      outscraper   the same vendor whose convention is under test. Bounded evidence — see I-050
                   and the module docstring.
      dataforseo   an independent vendor, queried by place_id, returning the reviews themselves.
                   This is the one that can actually settle it.

    Both are kept because the comparison IS the result. Two vendors agreeing on a null is
    evidence; one vendor repeating itself is not.
    """
    rows = fetch_all(
        lambda: client.table("prospect")
        # lat/lng are here for the DataForSEO keyword ladder's name+coordinate rung, not for
        # display. Explicit columns rather than `*`: `raw` is already the one heavy field this
        # needs, and selecting the rest of the row would multiply the payload for nothing.
        .select("id,place_id,name,review_count,lat,lng,raw")
        .eq("market_id", market_id)
        .is_("review_count", "null")
    )

    if group == "rating_present":
        rows = [r for r in rows if (r.get("raw") or {}).get("rating") is not None]
    else:
        rows = [r for r in rows if (r.get("raw") or {}).get("rating") is None]

    candidates = select_candidates(rows, limit)
    report = VerifyReport(requested=len(candidates))
    if not candidates:
        return report

    if provider not in ("outscraper", "dataforseo"):
        raise ValueError(f"unknown provider {provider!r}")
    if provider == "dataforseo":
        missing = missing_dataforseo_vars(settings)
        if missing:
            raise RuntimeError(f"not set: {', '.join(missing)}")

    # Cost gate BEFORE any client is opened — same order as the ingest, so an over-budget run
    # cannot spend a single request before aborting.
    if provider == "dataforseo":
        projected = len(candidates) * settings.dataforseo_cost_per_request_cents
    else:
        projected = round(
            len(candidates) * settings.outscraper_cost_per_1000_places_cents / 1000
        )
    if projected > settings.max_market_run_cost_cents:
        raise CostLimitExceeded(
            f"projected {projected}c exceeds max_market_run_cost_cents "
            f"{settings.max_market_run_cost_cents}c"
        )
    logger.info(
        "review verification starting",
        extra={
            "places": len(candidates),
            "projected_cents": projected,
            "group": group,
            "provider": provider,
        },
    )

    if provider == "dataforseo":
        report.results = await _run_dataforseo(settings, candidates)
    else:
        report.results = await _run_outscraper(settings, candidates)

    # Ledger the spend even on a partly-failed run. A verification that quietly costs money
    # without a row is how the reconciliation against the dashboard stops adding up (I-022).
    try:
        client.table("cost_ledger").insert(
            {
                "market_id": market_id,
                "stage": "a2_verify_reviews",
                "provider": provider,
                "units": len(candidates),
                "cost_cents": projected,
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001
        logger.error("could not write cost_ledger row", extra={"error": str(exc)})

    return report


async def _run_dataforseo(
    settings: Settings, candidates: list[dict[str, Any]]
) -> list[LookupResult]:
    """One reviews/live lookup per prospect, bounded concurrency, one bad row never ends the run."""
    async with DataForSEOClient(settings) as api:
        sem = asyncio.Semaphore(settings.outscraper_tile_concurrency)

        async def one(row: dict[str, Any]) -> LookupResult:
            async with sem:
                place_id = str(row.get("place_id"))
                try:
                    result = classify_dataforseo(
                        await api.fetch_place_info(
                            place_id,
                            name=str(row.get("name") or ""),
                            lat=row.get("lat"),
                            lng=row.get("lng"),
                        )
                    )
                    if not result.place_id:
                        result.place_id = place_id
                    result.name = str(row.get("name") or "")
                    return result
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "dataforseo lookup failed",
                        extra={"place_id": place_id, "error": str(exc)},
                    )
                    return LookupResult(
                        place_id=place_id,
                        name=str(row.get("name") or ""),
                        verdict=ERROR,
                        error=str(exc),
                    )

        return list(await asyncio.gather(*(one(r) for r in candidates)))


async def _run_outscraper(
    settings: Settings, candidates: list[dict[str, Any]]
) -> list[LookupResult]:
    async with OutscraperClient(settings) as api:
        sem = asyncio.Semaphore(settings.outscraper_tile_concurrency)

        async def one(row: dict[str, Any]) -> LookupResult:
            async with sem:
                place_id = str(row.get("place_id"))
                try:
                    # The place_id IS the query — that is how a single-business lookup is
                    # expressed against this endpoint. limit 1: we want this listing, not its
                    # neighbours, and every extra place returned is billed.
                    request_id = await api.submit_maps_search(
                        TileRequest(query=place_id, label=f"verify:{place_id}"), limit=1
                    )
                    body = await api.fetch_result(request_id)
                    places = extract_places(body)
                    result = classify_lookup(places[0] if places else None)
                    if not result.place_id:
                        result.place_id = place_id
                    if not result.name:
                        result.name = str(row.get("name") or "")
                    return result
                except Exception as exc:  # noqa: BLE001 — one bad lookup must not end the run
                    logger.warning(
                        "review lookup failed",
                        extra={"place_id": place_id, "error": str(exc)},
                    )
                    return LookupResult(
                        place_id=place_id,
                        name=str(row.get("name") or ""),
                        verdict=ERROR,
                        error=str(exc),
                    )

        return list(await asyncio.gather(*(one(r) for r in candidates)))

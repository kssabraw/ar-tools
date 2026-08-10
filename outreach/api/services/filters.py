"""Stage A2 — filter.

Two properties this module exists to guarantee, both from brief §3:

  1. EVERY rule is evaluated for EVERY prospect. Not short-circuited on first failure. Dead
     listings typically fail three gates at once, and first-match-only logging produces
     misleading tuning data — you would conclude "closed" is doing all the work when
     "no phone" and "too few reviews" would each have caught the same listing alone.

  2. A franchise match FLAGS, never excludes. This is encoded in the rule definition, not left
     to the caller, so it cannot be undone by a branch somewhere else. A false positive is a
     permanently lost prospect, plenty of independents carry chain-like names, and hard exclusion
     is also what made the -87 franchise coefficient dead on arrival in an earlier draft
     (ISSUES R-003).

The module is pure: no database, no clock, no config lookup. Everything arrives as an argument
so the rule matrix is testable without mocking anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Sequence

from .parser import CLOSED_STATUSES, ParsedPlace

# Recorded in filter_result.observed_value when a rule was not run — either because it is
# disabled in config or because the data it needs does not exist yet. `passed` is true in that
# case, because a rule that did not run cannot have failed. The sentinel is what keeps the audit
# trail honest rather than silently absent.
NOT_EVALUATED = "not_evaluated"

RULE_BUSINESS_STATUS = "business_status_open"
RULE_HAS_PHONE = "has_phone"
RULE_NOT_SUPPRESSED = "not_suppressed"
RULE_NOT_FRANCHISE = "not_franchise"
RULE_REVIEW_COUNT = "review_count_min"
RULE_REVIEW_RECENCY = "review_recency"
RULE_CATEGORY_RELEVANT = "category_relevant"
RULE_WITHIN_AREA = "within_area"

# Order is presentation only — all of them run regardless.
ALL_RULES: tuple[str, ...] = (
    RULE_BUSINESS_STATUS,
    RULE_HAS_PHONE,
    RULE_NOT_SUPPRESSED,
    RULE_NOT_FRANCHISE,
    RULE_REVIEW_COUNT,
    RULE_REVIEW_RECENCY,
    RULE_CATEGORY_RELEVANT,
    RULE_WITHIN_AREA,
)

# The one non-exclusionary rule. Failing it sets franchise_status = 'flagged' and the prospect
# proceeds. Do not add to this set without re-reading DECISIONS.md.
#
# RULE_CATEGORY_RELEVANT is deliberately NOT here. It has THREE outcomes, not two: a place whose
# primary category is off-list is EXCLUDED (a hard drop, so it must stay out of this set), but a
# place whose primary is off-list while a SECONDARY category matches is neither kept nor dropped —
# it is flagged for review. The review case is encoded as passed=True with a REVIEW-prefixed
# observed value (see `evaluate`), so it never reaches `.excluded`; only the genuine off-category
# drop fails the rule. Putting the rule name in this set would turn every off-category listing
# into a flag and defeat the whole point.
CATEGORY_REVIEW_PREFIX = "review:"

NON_EXCLUSIONARY_RULES: frozenset[str] = frozenset({RULE_NOT_FRANCHISE})


@dataclass(frozen=True)
class RuleOutcome:
    rule: str
    passed: bool
    observed_value: str | None = None

    @property
    def evaluated(self) -> bool:
        return self.observed_value != NOT_EVALUATED


@dataclass
class FilterVerdict:
    outcomes: list[RuleOutcome] = field(default_factory=list)

    @property
    def failed_rules(self) -> list[str]:
        """Every rule the prospect failed — the full list, which is the point of the stage."""
        return [o.rule for o in self.outcomes if not o.passed]

    @property
    def excluded(self) -> bool:
        return any(
            not o.passed and o.rule not in NON_EXCLUSIONARY_RULES for o in self.outcomes
        )

    @property
    def franchise_flagged(self) -> bool:
        return any(not o.passed and o.rule == RULE_NOT_FRANCHISE for o in self.outcomes)

    @property
    def franchise_status(self) -> str:
        """Never returns a 'confirmed_*' value — confirmation is a human act, not a pattern match."""
        return "flagged" if self.franchise_flagged else "unknown"

    @property
    def _category_outcome(self) -> "RuleOutcome | None":
        for outcome in self.outcomes:
            if outcome.rule == RULE_CATEGORY_RELEVANT:
                return outcome
        return None

    @property
    def category_review_flagged(self) -> bool:
        """The 'maybe' pile: primary category is off-list but a secondary category matches, so a
        human should glance before this is contacted or dropped."""
        outcome = self._category_outcome
        return bool(
            outcome
            and outcome.passed
            and outcome.observed_value
            and outcome.observed_value.startswith(CATEGORY_REVIEW_PREFIX)
        )

    @property
    def category_status(self) -> str:
        """The bucket this prospect landed in, for the `category_status` column.

        Never returns a 'confirmed_*' value — confirmation is a human act, like franchise. The DB
        guard (migration 20260810180000) additionally protects a human ruling from being reverted
        by the next routine filter run.
        """
        outcome = self._category_outcome
        if outcome is None:
            return "unknown"
        if not outcome.passed:
            return "off_category"
        if outcome.observed_value and outcome.observed_value.startswith(CATEGORY_REVIEW_PREFIX):
            return "review"
        if outcome.observed_value in (None, NOT_EVALUATED):
            # Rule disabled, vertical unconfigured, or the place carried no category at all.
            return "unknown"
        return "relevant"


class SuppressionIndex:
    """Case-insensitive membership test across all suppression scopes.

    The brief's rule is "present in `suppression` (any scope)", so scope is deliberately not
    consulted when matching. Constructing this from an empty or missing table yields an index
    that matches nothing, which is the correct Phase 1 behaviour — the table is empty by
    definition and nobody is contacted.
    """

    def __init__(self, values: Iterable[str] = ()) -> None:
        self._values = {v.strip().lower() for v in values if v and v.strip()}

    def __len__(self) -> int:
        return len(self._values)

    def matches(self, *candidates: str | None) -> str | None:
        """Return the first candidate present in the index, or None."""
        for candidate in candidates:
            if candidate and candidate.strip().lower() in self._values:
                return candidate
        return None


def matches_franchise_pattern(name: str, patterns: Sequence[str]) -> str | None:
    """Return the matching pattern, or None. Case-insensitive substring match."""
    haystack = name.lower()
    for pattern in patterns:
        needle = pattern.strip().lower()
        if needle and needle in haystack:
            return pattern
    return None


def resolve_accepted_categories(
    ingest_category: str | None, mapping: dict[str, Sequence[str]]
) -> frozenset[str] | None:
    """The allow-list of Google categories that count as this vertical, or None.

    None means "this vertical is not configured for relevance filtering" — and the rule then
    records NOT_EVALUATED rather than dropping anything, so switching the feature on for a market
    we have not curated a category list for is a no-op, not a mass exclusion. Keyed case- and
    whitespace-insensitively on the ingest category (== the typed business type).
    """
    if not ingest_category:
        return None
    wanted = ingest_category.strip().lower()
    for key, categories in mapping.items():
        if key.strip().lower() == wanted and categories:
            return frozenset(c.strip().lower() for c in categories if c and c.strip())
    return None


def category_signals(place: ParsedPlace) -> tuple[str | None, frozenset[str]]:
    """A place's PRIMARY category and the full set of ALL its categories, lowercased.

    The primary is the single best label — Outscraper's `category`/`type` — and is what the keep
    decision keys on. `subtypes` is the comma-joined list of every category Google assigns, used
    only for the 'maybe' pile: a business labelled primarily 'General contractor' that lists
    'Plumber' as one of ten subtypes is a review candidate, never an automatic keep, because an
    any-subtype match would re-admit the exact noise this rule removes (a Home Depot service desk
    lists 'Plumber' among its trades).
    """
    raw = place.raw or {}

    primary: str | None = None
    for key in ("category", "type", "main_category"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            # A single label. subtypes-as-category (a comma blob) is split on the first comma.
            primary = value.split(",")[0].strip()
            break
    if primary is None and place.category:
        primary = place.category.split(",")[0].strip()

    all_categories: set[str] = set()
    if primary:
        all_categories.add(primary)

    subtypes = raw.get("subtypes")
    if isinstance(subtypes, str):
        all_categories.update(part.strip() for part in subtypes.split(",") if part.strip())
    elif isinstance(subtypes, (list, tuple)):
        all_categories.update(str(part).strip() for part in subtypes if str(part).strip())

    for key in ("category", "type", "main_category"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            all_categories.add(value.strip())

    return (
        (primary or None),
        frozenset(c.lower() for c in all_categories if c),
    )


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles. A local copy of `tiling.haversine_miles` on purpose — this
    module is deliberately dependency-free (its docstring: no database, no clock, no config), and
    importing `tiling` would drag in the Outscraper client + httpx at import time. Six lines of
    pure trig is the cheaper price. A test pins the two implementations to agree.
    """
    import math

    earth_radius_miles = 3958.7613
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * earth_radius_miles * math.asin(math.sqrt(a))


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def evaluate(
    place: ParsedPlace,
    *,
    suppression: SuppressionIndex,
    franchise_patterns: Sequence[str],
    min_review_count: int,
    review_recency_months: int,
    today: date,
    exclude_closed: bool = True,
    require_phone: bool = True,
    check_suppression: bool = True,
    min_review_count_enabled: bool = True,
    review_recency_enabled: bool = False,
    inferred_zero: bool = False,
    review_count_override: int | None = None,
    franchise_decision: str | None = None,
    accepted_categories: frozenset[str] | None = None,
    category_relevance_enabled: bool = False,
    category_decision: str | None = None,
    anchor_lat: float | None = None,
    anchor_lng: float | None = None,
    max_distance_miles: float | None = None,
    distance_gate_enabled: bool = False,
) -> FilterVerdict:
    """Run every rule against one place and return all outcomes.

    There is no early return anywhere in this function, and that is deliberate.
    """
    outcomes: list[RuleOutcome] = []

    # -- 1. business_status: closed, permanently or temporarily ---------------------------
    if not exclude_closed:
        outcomes.append(RuleOutcome(RULE_BUSINESS_STATUS, True, NOT_EVALUATED))
    elif place.business_status is None:
        # Unrecognised or absent status is NOT treated as closed. Excluding on an unknown value
        # would drop live businesses with no way to get them back.
        outcomes.append(RuleOutcome(RULE_BUSINESS_STATUS, True, NOT_EVALUATED))
    else:
        outcomes.append(
            RuleOutcome(
                RULE_BUSINESS_STATUS,
                place.business_status not in CLOSED_STATUSES,
                place.business_status,
            )
        )

    # -- 2. no phone number ---------------------------------------------------------------
    if not require_phone:
        outcomes.append(RuleOutcome(RULE_HAS_PHONE, True, NOT_EVALUATED))
    else:
        has_phone = bool(place.phone and place.phone.strip())
        outcomes.append(RuleOutcome(RULE_HAS_PHONE, has_phone, place.phone if has_phone else None))

    # -- 3. suppression (any scope) -------------------------------------------------------
    if not check_suppression:
        outcomes.append(RuleOutcome(RULE_NOT_SUPPRESSED, True, NOT_EVALUATED))
    else:
        hit = suppression.matches(place.place_id, place.phone, place.website)
        outcomes.append(RuleOutcome(RULE_NOT_SUPPRESSED, hit is None, hit))

    # -- 4. franchise / chain pattern — FLAG ONLY, never excludes -------------------------
    #
    # A human ruling outranks the pattern match, in BOTH directions. `DEFAULT_FRANCHISE_PATTERNS`
    # is an unvalidated seed (I-020) and someone who read the listing is better evidence than a
    # substring; equally, a reviewer who confirmed a chain has said something the pattern list
    # missed. Without this the verdict would keep contradicting the stored status on every run —
    # and the status itself would have been overwritten too, before the database guard
    # (migration 20260801140000) closed that path.
    if franchise_decision == "confirmed_independent":
        outcomes.append(RuleOutcome(RULE_NOT_FRANCHISE, True, "confirmed_independent (human)"))
    elif franchise_decision == "confirmed_franchise":
        outcomes.append(RuleOutcome(RULE_NOT_FRANCHISE, False, "confirmed_franchise (human)"))
    else:
        matched = matches_franchise_pattern(place.name, franchise_patterns)
        outcomes.append(RuleOutcome(RULE_NOT_FRANCHISE, matched is None, matched))

    # -- 5. review count ------------------------------------------------------------------
    #
    # A missing count is NOT a low count, and the two must not be conflated — that is why an
    # absent value records NOT_EVALUATED rather than failing. See ISSUES I-041: the LA pull
    # returned no count for 113 of 1,388 listings, and folding those into "passed" would claim
    # every business in the market has been checked when 113 were not.
    #
    # `inferred_zero` is the one exception, and it is deliberately a SEPARATE input rather than a
    # zero written over the missing count. The inference — that this provider encodes "no reviews"
    # as null — is a claim about a provider convention, not an observation about a business, so it
    # stays visible in its own field and can be withdrawn by clearing a flag rather than by trying
    # to work out which zeroes were real. `review_count` itself stays NULL forever.
    # An override is a count obtained OUTSIDE the provider payload — a manual verification, or
    # the Phase 2 geogrid backfill (I-045). It has to win, because `place` is re-parsed from
    # stored raw on every filter run and raw will never carry a correction we made. Without this
    # the next routine `filter` silently reverts the fix and says nothing, which is the exact
    # failure mode this project keeps hitting (I-036, I-035).
    effective_count = review_count_override if review_count_override is not None else place.review_count

    if not min_review_count_enabled:
        outcomes.append(RuleOutcome(RULE_REVIEW_COUNT, True, NOT_EVALUATED))
    elif effective_count is None and inferred_zero:
        outcomes.append(RuleOutcome(RULE_REVIEW_COUNT, 0 >= min_review_count, "0 (inferred)"))
    elif effective_count is None:
        # No count returned is not the same as a low count.
        outcomes.append(RuleOutcome(RULE_REVIEW_COUNT, True, NOT_EVALUATED))
    else:
        outcomes.append(
            RuleOutcome(
                RULE_REVIEW_COUNT,
                effective_count >= min_review_count,
                str(effective_count),
            )
        )

    # -- 6. review recency ----------------------------------------------------------------
    # Deferred in Phase 1 (DECISIONS.md). Review timestamps are not in the base pull. If someone
    # enables the flag without the reviews stage in place, latest_review_at is None for every
    # prospect — so this fails open rather than excluding the entire market.
    latest_review_at = getattr(place, "latest_review_at", None)
    if not review_recency_enabled or latest_review_at is None:
        outcomes.append(RuleOutcome(RULE_REVIEW_RECENCY, True, NOT_EVALUATED))
    else:
        age_months = _months_between(latest_review_at, today)
        outcomes.append(
            RuleOutcome(
                RULE_REVIEW_RECENCY,
                age_months < review_recency_months,
                latest_review_at.isoformat(),
            )
        )

    # -- 7. category relevance — three outcomes: keep / review / drop ----------------------
    #
    # Google Maps text search for a category returns adjacent businesses too (hardware stores,
    # HVAC firms, apartment buildings), and none of the six rules above ask whether a listing is
    # actually the searched trade. This rule does, keyed on Google's own PRIMARY category:
    #
    #   * primary category ON the allow-list  -> keep (rule passes)
    #   * primary OFF, but a SECONDARY matches -> review (passes, but flagged; a human glances)
    #   * primary OFF, no secondary match      -> drop  (rule fails, hard exclude)
    #
    # Fail-open is preserved throughout, per this module's dominant fear of a false exclusion: the
    # rule is NOT_EVALUATED (keeps the prospect) when disabled, when the vertical has no configured
    # allow-list, or when the place carried no category at all. A human ruling on `category_status`
    # outranks the match in both directions, exactly like franchise (I-054) — and the DB guard
    # protects that ruling from the next routine re-filter.
    if not category_relevance_enabled or accepted_categories is None:
        outcomes.append(RuleOutcome(RULE_CATEGORY_RELEVANT, True, NOT_EVALUATED))
    elif category_decision == "confirmed_relevant":
        outcomes.append(RuleOutcome(RULE_CATEGORY_RELEVANT, True, "confirmed_relevant (human)"))
    elif category_decision == "confirmed_off":
        outcomes.append(RuleOutcome(RULE_CATEGORY_RELEVANT, False, "confirmed_off (human)"))
    else:
        primary, all_categories = category_signals(place)
        accept = {c.strip().lower() for c in accepted_categories}

        if primary is None:
            # No category signal at all is not evidence of being off-topic. Keep it.
            outcomes.append(RuleOutcome(RULE_CATEGORY_RELEVANT, True, NOT_EVALUATED))
        elif primary.strip().lower() in accept:
            outcomes.append(RuleOutcome(RULE_CATEGORY_RELEVANT, True, primary))
        elif all_categories & accept:
            matched = ", ".join(sorted(all_categories & accept))
            outcomes.append(
                RuleOutcome(
                    RULE_CATEGORY_RELEVANT,
                    True,
                    f"{CATEGORY_REVIEW_PREFIX} {primary} (secondary: {matched})",
                )
            )
        else:
            outcomes.append(RuleOutcome(RULE_CATEGORY_RELEVANT, False, primary))

    # -- 8. geographic distance — the unbounded-coordinates escape ------------------------
    #
    # Outscraper's `coordinates` biases the search CENTRE but does not bound the area (there is no
    # radius parameter — tiling.py / outscraper_client.py), so a category search can return a
    # business far outside the market: an Inglewood plumbing pull surfaced a kitchen remodeler in
    # Lompoc, ~150 miles away. This rule drops a listing whose location is further than
    # `max_distance_miles` from its assigned submarket centroid.
    #
    # Fail-open, like every other rule: NOT_EVALUATED (kept) when disabled, when no centroid/cap is
    # supplied, or when the listing itself carries no coordinates — an unknown location is not
    # evidence of a distant one. The default cap is deliberately generous (it is anchored on the
    # centroid a prospect was already assigned to as its NEAREST submarket, so an in-metro business
    # sits a few miles from it at most); the point is to catch gross drift, not to fence a service
    # area.
    if (
        not distance_gate_enabled
        or max_distance_miles is None
        or anchor_lat is None
        or anchor_lng is None
    ):
        outcomes.append(RuleOutcome(RULE_WITHIN_AREA, True, NOT_EVALUATED))
    elif place.lat is None or place.lng is None:
        outcomes.append(RuleOutcome(RULE_WITHIN_AREA, True, NOT_EVALUATED))
    else:
        distance = _haversine_miles(place.lat, place.lng, anchor_lat, anchor_lng)
        outcomes.append(
            RuleOutcome(
                RULE_WITHIN_AREA,
                distance <= max_distance_miles,
                f"{distance:.1f} mi",
            )
        )

    return FilterVerdict(outcomes=outcomes)

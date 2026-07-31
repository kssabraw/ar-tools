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

# Order is presentation only — all of them run regardless.
ALL_RULES: tuple[str, ...] = (
    RULE_BUSINESS_STATUS,
    RULE_HAS_PHONE,
    RULE_NOT_SUPPRESSED,
    RULE_NOT_FRANCHISE,
    RULE_REVIEW_COUNT,
    RULE_REVIEW_RECENCY,
)

# The one non-exclusionary rule. Failing it sets franchise_status = 'flagged' and the prospect
# proceeds. Do not add to this set without re-reading DECISIONS.md.
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
    matched = matches_franchise_pattern(place.name, franchise_patterns)
    outcomes.append(RuleOutcome(RULE_NOT_FRANCHISE, matched is None, matched))

    # -- 5. review count ------------------------------------------------------------------
    if not min_review_count_enabled:
        outcomes.append(RuleOutcome(RULE_REVIEW_COUNT, True, NOT_EVALUATED))
    elif place.review_count is None:
        # No count returned is not the same as a low count.
        outcomes.append(RuleOutcome(RULE_REVIEW_COUNT, True, NOT_EVALUATED))
    else:
        outcomes.append(
            RuleOutcome(
                RULE_REVIEW_COUNT,
                place.review_count >= min_review_count,
                str(place.review_count),
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

    return FilterVerdict(outcomes=outcomes)

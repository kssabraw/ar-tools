"""Parse an Outscraper place dict into prospect columns.

Most of these aliases are now confirmed rather than guessed. `writer/platform-api/services/
gbp_service.py` has been parsing live Outscraper maps responses against this same API key for
months, and its field handling is the evidence behind the ordering below:

    place_id / google_id · name · full_address then address · phone · site then website ·
    category then type · subtypes (comma-joined string) · rating · reviews (the COUNT) ·
    latitude/lat · longitude/lng · working_hours · location_link · reviews_data · area_service

STILL UNCONFIRMED: `business_status`. Production never reads it, so nothing in this estate has
observed whether it is returned, under what name, or with what values — and it is the field the
closed-listing gate depends on. `filters.evaluate` therefore treats an absent or unrecognised
status as "not evaluated" rather than "closed", so an unconfirmed field cannot silently exclude
live businesses.

The alias map stays regardless. The brief mandates persisting raw before parsing, so re-parsing
an entire market against corrected aliases costs nothing and needs no re-pull. See ISSUES I-018.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

# Ordered by preference — the first alias present and non-empty wins.
# Ordering follows platform-api's gbp_service, which reads live responses from this account.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "place_id": ("place_id", "google_id"),
    "name": ("name", "title", "business_name"),
    # gbp_service does `category or type`, then falls back to `subtypes` (a comma-joined string).
    "category": ("category", "type", "subtypes", "main_category"),
    "address": ("full_address", "address", "formatted_address"),
    "phone": ("phone", "phone_number", "formatted_phone_number"),
    # `site` first is confirmed, not a guess — gbp_service does `site or website`.
    "website": ("site", "website", "url"),
    "rating": ("rating", "average_rating"),
    # `reviews` is the COUNT on a place object. `reviews_data` is the inline review list and must
    # never be read here — it would parse as a count of nothing.
    "review_count": ("reviews", "reviews_count", "review_count", "user_ratings_total"),
    "lat": ("latitude", "lat"),
    "lng": ("longitude", "lng", "lon"),
    # UNCONFIRMED — no production code in this estate reads it. See the module docstring.
    "business_status": ("business_status", "status", "permanently_closed"),
}

# Normalised business_status values. Google/Outscraper report upper-snake; we keep that form so
# the stored value stays recognisable against the provider's own docs.
STATUS_OPERATIONAL = "OPERATIONAL"
STATUS_CLOSED_TEMPORARILY = "CLOSED_TEMPORARILY"
STATUS_CLOSED_PERMANENTLY = "CLOSED_PERMANENTLY"

CLOSED_STATUSES = frozenset({STATUS_CLOSED_TEMPORARILY, STATUS_CLOSED_PERMANENTLY})

_STATUS_SYNONYMS: dict[str, str] = {
    "operational": STATUS_OPERATIONAL,
    "open": STATUS_OPERATIONAL,
    "closed_temporarily": STATUS_CLOSED_TEMPORARILY,
    "temporarily_closed": STATUS_CLOSED_TEMPORARILY,
    "closed temporarily": STATUS_CLOSED_TEMPORARILY,
    "closed_permanently": STATUS_CLOSED_PERMANENTLY,
    "permanently_closed": STATUS_CLOSED_PERMANENTLY,
    "closed permanently": STATUS_CLOSED_PERMANENTLY,
}


@dataclass
class ParsedPlace:
    """A place mapped onto prospect columns. `raw` is the untouched provider dict."""

    place_id: str
    name: str
    raw: dict[str, Any]
    category: str | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    rating: float | None = None
    review_count: int | None = None
    lat: float | None = None
    lng: float | None = None
    business_status: str | None = None

    # Always 'unknown' in Phase 1 — carrier/type needs the phones_enricher_service enrichment,
    # which is Phase 5 (ISSUES I-015). The column exists; the signal does not yet.
    phone_type: str = "unknown"

    # Never populated in Phase 1. Review timestamps need a separately billed /maps/reviews-v3
    # call; the recency rule is deferred (DECISIONS.md).
    latest_review_at: None = None


def _first_present(raw: dict[str, Any], aliases: Iterable[str]) -> Any:
    for alias in aliases:
        value = raw.get(alias)
        if value not in (None, "", [], {}):
            return value
    return None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    parsed = _as_float(value)
    return None if parsed is None else int(parsed)


def _as_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (list, tuple)):
        # `type`/`subtypes` sometimes arrive as a list; the first entry is the primary category.
        for item in value:
            text = _as_text(item)
            if text:
                return text
        return None
    text = str(value).strip()
    return text or None


def normalize_business_status(value: Any) -> str | None:
    """Map whatever the provider sent onto one of the three known statuses.

    Returns None for an unrecognised value rather than guessing. An unknown status must not be
    read as "closed" — that would exclude a live business permanently, and a false exclusion is
    the one filter error with no recovery path.
    """
    if value is None:
        return None

    # Some responses express this as a boolean `permanently_closed` rather than a status string.
    if isinstance(value, bool):
        return STATUS_CLOSED_PERMANENTLY if value else STATUS_OPERATIONAL

    text = str(value).strip()
    if not text:
        return None

    return _STATUS_SYNONYMS.get(text.lower().replace("-", "_"))


def parse_place(raw: dict[str, Any]) -> ParsedPlace | None:
    """Map one provider dict onto prospect columns.

    Returns None when the place has no id or no name — both are NOT NULL on `prospect`, and a
    fabricated place_id is the single most expensive mistake available here: grid results join on
    it, so an invented one silently matches nothing and leaves a prospect that can never be
    scored or audited (CLAUDE.md invariants).
    """
    place_id = _as_text(_first_present(raw, FIELD_ALIASES["place_id"]))
    name = _as_text(_first_present(raw, FIELD_ALIASES["name"]))

    if not place_id or not name:
        return None

    return ParsedPlace(
        place_id=place_id,
        name=name,
        raw=raw,
        category=_as_text(_first_present(raw, FIELD_ALIASES["category"])),
        address=_as_text(_first_present(raw, FIELD_ALIASES["address"])),
        phone=_as_text(_first_present(raw, FIELD_ALIASES["phone"])),
        website=_as_text(_first_present(raw, FIELD_ALIASES["website"])),
        rating=_as_float(_first_present(raw, FIELD_ALIASES["rating"])),
        review_count=_as_int(_first_present(raw, FIELD_ALIASES["review_count"])),
        lat=_as_float(_first_present(raw, FIELD_ALIASES["lat"])),
        lng=_as_float(_first_present(raw, FIELD_ALIASES["lng"])),
        business_status=normalize_business_status(
            _first_present(raw, FIELD_ALIASES["business_status"])
        ),
    )


def unmapped_fields(raw: dict[str, Any]) -> list[str]:
    """Provider keys no alias claims. Logged after the first real pull to tune FIELD_ALIASES."""
    claimed = {alias for aliases in FIELD_ALIASES.values() for alias in aliases}
    return sorted(key for key in raw if key not in claimed)

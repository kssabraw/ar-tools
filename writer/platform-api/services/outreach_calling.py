"""Pure helpers for the cold-caller CRM surface — the disposition vocabulary, the
disposition → next-action hints, callback-time resolution, and the local-time /
business-hours indicator.

No network, no database (mirrors `outreach_emit.py`). The service layer does the I/O and
hands these functions plain values, so the vocabulary, the wall-time → instant conversion,
and the business-hours computation are all deterministic and testable from hand-built inputs.

Two rules this module encodes:

- **The disposition set is app-level, not a DB CHECK** (crm-layer-spec.md §5, and the
  `touch.disposition` column comment: the vocabulary "is still forming and a CHECK would
  need a migration to grow"). So the enum lives here and is validated in the application —
  a new value is a one-line change and a deploy, never a migration. The database column
  stays free text; this is the friendlier, structured front door, the same posture the
  other outreach vocabularies take.

- **A callback time is a wall-clock time in the prospect's timezone** ("Tuesday 2pm THEIR
  time"). `next_action_at` stores the resolved absolute instant (timestamptz); `next_action_tz`
  stores the IANA zone so the instant can be redisplayed as their local time and so the
  business-hours indicator knows what "now" means where they are. The wall-time → instant
  conversion is DST-correct because it goes through `zoneinfo`, not a fixed offset.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# --- Disposition vocabulary (T1.2) ------------------------------------------------------------
#
# Phone is the primary channel (crm-layer-spec.md §7 — the phone track has no ESP at all). Email
# dispositions are carried too so the same picker structure serves an email touch. Values are the
# owner-confirmed set (2026-09-17); they mirror the `lost_reason` treatment — a fixed vocabulary
# captured on a field generated dozens of times a day, so it can be counted (connect rate, the
# caller scoreboard) instead of drowning in free text.

PHONE_DISPOSITIONS: tuple[str, ...] = (
    "no_answer",
    "voicemail",
    "busy",
    "wrong_number",
    "gatekeeper",
    "connected",
    "decision_maker",
    "callback_requested",
    "not_interested",
    "do_not_call",
)

EMAIL_DISPOSITIONS: tuple[str, ...] = (
    "sent",
    "bounced",
    "replied",
    "auto_reply",
    "unsubscribe",
)

DISPOSITIONS: frozenset[str] = frozenset(PHONE_DISPOSITIONS) | frozenset(EMAIL_DISPOSITIONS)

# What each disposition suggests the caller do next. These are SUGGESTIONS the UI prefills, never
# actions taken automatically — logging a call never silently marks a lead lost or suppresses a
# number. The fields:
#   reveal_callback        the disposition implies a scheduled callback → show the date+time picker
#   default_next_action    prefilled next-action text
#   offset_days            prefilled due date = today + this many days (day-level; overridden by a
#                          precise callback time when one is picked)
#   suggest_lost_reason    offer to move the lead to Lost with this reason (crm-layer-spec §5)
#   suggest_suppress       offer a one-click do-not-contact write (crm-layer-spec §4)
#   suppress_scope         the scope to offer ('all' covers phone AND email; 'email' email-only)
#
# A disposition absent from this map carries no hint — a bare log, nothing prefilled.
DISPOSITION_HINTS: dict[str, dict[str, Any]] = {
    "no_answer": {"default_next_action": "Try again", "offset_days": 1},
    "voicemail": {"default_next_action": "Follow up after voicemail", "offset_days": 2},
    "busy": {"default_next_action": "Try again", "offset_days": 1},
    "wrong_number": {"suggest_lost_reason": "unreachable"},
    "gatekeeper": {"default_next_action": "Reach the decision maker", "offset_days": 1},
    "connected": {"default_next_action": "Follow up", "offset_days": 2},
    "decision_maker": {
        "reveal_callback": True,
        "default_next_action": "Follow up with decision maker",
        "offset_days": 2,
    },
    "callback_requested": {"reveal_callback": True, "default_next_action": "Callback"},
    "not_interested": {"suggest_lost_reason": "not_interested"},
    "do_not_call": {"suggest_suppress": True, "suppress_scope": "all", "suggest_lost_reason": "opted_out"},
    "sent": {"default_next_action": "Follow up on email", "offset_days": 3},
    "bounced": {"suggest_lost_reason": "unreachable"},
    "replied": {"default_next_action": "Respond to their reply", "offset_days": 0},
    "auto_reply": {"default_next_action": "Follow up on email", "offset_days": 3},
    "unsubscribe": {"suggest_suppress": True, "suppress_scope": "email", "suggest_lost_reason": "opted_out"},
}


def label(value: str) -> str:
    """Human label for a disposition value ('no_answer' -> 'No answer')."""
    return (value or "").replace("_", " ").strip().capitalize()


def disposition_catalog() -> dict[str, list[dict[str, Any]]]:
    """The pickable disposition set, per channel, with each value's next-action hints.

    Served by `GET /outreach/dispositions` so the caller UI renders the select and applies the
    hints from ONE source of truth — the same pattern the board uses for `GET /outreach/lead-stages`,
    which keeps the frontend and this module from drifting.
    """
    def rows(values: tuple[str, ...]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for v in values:
            hint = DISPOSITION_HINTS.get(v, {})
            out.append({"value": v, "label": label(v), **hint})
        return out

    return {"phone": rows(PHONE_DISPOSITIONS), "email": rows(EMAIL_DISPOSITIONS)}


def validate_disposition(channel: str, value: Optional[str]) -> Optional[str]:
    """Validate a disposition against the channel's vocabulary.

    None/blank is allowed — a touch may be logged with no disposition (a bare dial). A value must
    belong to the given channel's set: a phone touch cannot carry 'bounced', an email one cannot
    carry 'voicemail'. Raises ValueError (the service maps it to a named 422) so a bad value names
    the legal ones instead of surfacing a raw column write.
    """
    chosen = (value or "").strip()
    if not chosen:
        return None
    allowed = PHONE_DISPOSITIONS if channel == "phone" else EMAIL_DISPOSITIONS
    if chosen not in allowed:
        raise ValueError(
            f"disposition for a {channel} touch must be one of {', '.join(allowed)}"
        )
    return chosen


# --- Timezone + business hours (T1.4) ---------------------------------------------------------
#
# There is no lat/lng -> timezone library in platform-api (checked: only tzdata/zoneinfo), so the
# prospect's zone is either STORED on the lead (`next_action_tz`, the caller's picked/confirmed
# value) or DERIVED from its longitude with the coarse continental-US band below. The derivation is
# deliberately approximate — a business-hours HINT, not a claim — and the caller can always override
# it by picking the zone when they book a callback. A missing longitude falls back to the configured
# default zone. This pipeline targets US local businesses (LA, KC, ...), which is the case the bands
# are honest for; a non-US prospect just shows the default until someone sets it.

# West edges of each continental-US zone band, degrees longitude. Order matters: first band whose
# right edge the point is west of wins. These are rough meridian splits, not the real jagged
# boundaries — good enough to answer "is it the middle of their night right now".
_US_LNG_BANDS: tuple[tuple[float, str], ...] = (
    (-67.0, "America/New_York"),    # east of ~67W -> Eastern (also catches Atlantic drift)
    (-87.5, "America/New_York"),    # ~67..87.5W -> Eastern
    (-102.0, "America/Chicago"),    # ~87.5..102W -> Central
    (-115.0, "America/Denver"),     # ~102..115W -> Mountain
    (-140.0, "America/Los_Angeles"),  # ~115..140W -> Pacific
    (-150.0, "America/Anchorage"),  # ~140..150W -> Alaska (Anchorage ~-149.9)
)
# West of the last band edge falls through to Hawaii — longitude alone cannot split Hawaii from the
# western Aleutians (they overlap), and both keep Hawaii-Aleutian time, so Honolulu is the honest
# fallback for a point out there.


def guess_timezone(lng: Optional[float]) -> Optional[str]:
    """Best-effort IANA zone from a longitude, continental-US bands. None when unknowable.

    Approximate by construction (meridian splits, not real boundaries); it exists so a prospect
    that has never had a callback booked still shows a plausible local-time hint. Hawaii sits west
    of the Alaska band's edge.
    """
    if lng is None:
        return None
    try:
        lo = float(lng)
    except (TypeError, ValueError):
        return None
    for edge, zone in _US_LNG_BANDS:
        if lo >= edge:
            return zone
    return "Pacific/Honolulu"


def resolve_timezone(stored_tz: Optional[str], lng: Optional[float], default_tz: str) -> str:
    """The zone to use for a lead: the stored one, else a longitude guess, else the configured
    default. A stored zone always wins — it is the human's confirmed answer."""
    for candidate in (stored_tz, guess_timezone(lng), default_tz):
        if candidate and _valid_zone(candidate):
            return candidate
    return "UTC"


def _valid_zone(tz_name: str) -> bool:
    try:
        ZoneInfo(tz_name)
        return True
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False


def business_hours_status(
    tz_name: Optional[str],
    now: datetime,
    *,
    open_hour: int = 8,
    close_hour: int = 18,
) -> dict[str, Any]:
    """Where the prospect's clock is right now, and whether it is inside calling hours.

    `now` must be timezone-aware (pass `datetime.now(timezone.utc)`). Weekends are outside business
    hours. An unknown/invalid zone returns `in_business_hours: None` (unknown, never a false 'go
    ahead and dial'), matching the unknown-≡-absent posture the rest of the module takes.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if not tz_name or not _valid_zone(tz_name):
        return {"tz": None, "local_time": None, "local_hour": None, "in_business_hours": None}
    local = now.astimezone(ZoneInfo(tz_name))
    weekday = local.weekday()  # Mon=0 .. Sun=6
    in_hours = weekday < 5 and open_hour <= local.hour < close_hour
    return {
        "tz": tz_name,
        "local_time": local.isoformat(),
        "local_hour": local.hour,
        "weekday": weekday,
        "in_business_hours": in_hours,
    }


# --- Callback resolution (T1.3 / T1.4) --------------------------------------------------------


def resolve_callback(local_wall: str, tz_name: str) -> dict[str, str]:
    """Turn a wall-clock callback ("2026-09-22T14:00" in America/Los_Angeles) into the fields the
    lead stores: the absolute instant, the day it falls on locally, and the zone.

    Returns `{next_action_at, next_action_due, next_action_tz}`:
      next_action_at   the resolved UTC instant (ISO8601) — DST-correct via zoneinfo
      next_action_due  the LOCAL date it falls on, so the day-level queue/overdue logic (which
                       compares against current_date) keeps working unchanged when a precise time
                       is booked
      next_action_tz   the zone, echoed back so redisplay and the business-hours indicator agree

    Raises ValueError on an unparseable time or unknown zone (the service maps it to a named 422).
    """
    zone = (tz_name or "").strip()
    if not _valid_zone(zone):
        raise ValueError(f"unknown timezone: {tz_name!r}")
    raw = (local_wall or "").strip()
    if not raw:
        raise ValueError("a callback needs a date and time")
    # Accept "YYYY-MM-DDTHH:MM" (the datetime-local input) and a bare date (defaults to open hour).
    try:
        if "T" in raw or " " in raw:
            naive = datetime.fromisoformat(raw.replace(" ", "T"))
        else:
            naive = datetime.combine(datetime.fromisoformat(raw).date(), time(9, 0))
    except ValueError as exc:
        raise ValueError(f"could not read callback time {local_wall!r}: {exc}") from exc
    if naive.tzinfo is not None:
        # A client that already resolved the offset — trust it, but still record the zone.
        instant = naive.astimezone(timezone.utc)
        local = naive.astimezone(ZoneInfo(zone))
    else:
        local = naive.replace(tzinfo=ZoneInfo(zone))
        instant = local.astimezone(timezone.utc)
    return {
        "next_action_at": instant.isoformat(),
        "next_action_due": local.date().isoformat(),
        "next_action_tz": zone,
    }

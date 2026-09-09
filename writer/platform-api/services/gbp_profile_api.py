"""Google Business Profile **Profile Editor** API — the v1 Business Information
``locations.get`` + ``locations.patch`` surface.

Unlike GBP Posts (v4 REST, raw httpx — no discovery client), the three editable
profile fields live on the **My Business Business Information API v1**
(``mybusinessbusinessinformation.googleapis.com/v1``), which IS in Google's
discovery service. The app already builds a client for it for the auto-match
reads (``gbp_locations_service._build("mybusinessbusinessinformation", creds)`` —
the v1-hardcoded ``_build``, NOT ``gbp_performance_service._build``). This module
adds the WRITE path (get one location's fields + patch one field at a time).

Everything pure (builders, validators, the description linter, field parsing,
the re-read-and-diff, error classification) has **no Google dependency** and is
unit-tested; the live ``get_location``/``patch_location`` calls are synchronous
(discovery client) and meant to run via ``asyncio.to_thread`` from the async job
runners, raising an ``HTTPException`` with a classified ``detail`` on failure.

⚠️ **Field paths need a build-time re-verify.** ``developers.google.com`` is
egress-blocked from the sandbox but reachable from the Railway PLATFORM shell —
re-check ``profile.description``, ``regularHours``/``TimeOfDay`` (v1 uses
structured ``{hours, minutes}`` objects, NOT v4 ``"HHMM"`` strings), the
``serviceItems``/``freeFormServiceItem``/``structuredServiceItem`` shape, and the
``metadata`` pending-edit fields against
``developers.google.com/my-business/reference/businessinformation/rest/v1/accounts.locations``.
The one live-shape constant most likely to need a tweak is
``_FREEFORM_CATEGORY_FIELD`` below. The **service-type picker** additionally
relies on ``categories.batchGet(view=FULL)`` returning per-category
``serviceTypes: [{serviceTypeId, displayName}]`` — re-verify against
``.../businessinformation/rest/v1/categories/batchGet`` (a READ, so safe to test
live).

See: docs/modules/gbp-profile-editor-prd-v1_0.md §2, §7.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# The v1 readMask for every editable field + the context they need (categories to
# attach free-form services to; metadata for editability/pending state). categories
# is REQUIRED so the services editor can offer valid ids. Phase 3a widened this to
# also carry websiteUri / labels / moreHours / openInfo (regularHours / specialHours
# / serviceArea were already here). storefrontAddress feeds the services-matrix
# prefill (parse_storefront_city).
READ_MASK = (
    "name,title,profile.description,regularHours,specialHours,serviceItems,"
    "categories,metadata,serviceArea,storefrontAddress,websiteUri,labels,"
    "moreHours,openInfo"
)

# The editable open/closed states (Phase 3a). CLOSED_PERMANENTLY is drastic and the
# UI gates it behind an extra confirm; the AI never drafts a closure.
OPEN_STATUSES = ("OPEN", "CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY")
# The service-area business types (Phase 3a). Default keeps a storefront visible.
SERVICE_AREA_BUSINESS_TYPES = ("CUSTOMER_AND_BUSINESS_LOCATION", "CUSTOMER_LOCATION_ONLY")
# Google caps labels: 10 per listing, 255 chars each.
LABELS_MAX = 10
LABEL_MAX_CHARS = 255

# Mon..Sun → the v1 DayOfWeek enum. Our internal hours rows key on 0=Monday.
DAY_ENUM = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
_DAY_INDEX = {name: i for i, name in enumerate(DAY_ENUM)}

# v1 FreeFormServiceItem's category field. The v1 Business Information API names
# it ``category`` (a category id / gcid string), where the legacy v4 API used
# ``categoryId``. If a live --edit-test patch is rejected with an unknown-field
# error on services, this is the one-line fix (re-verify per the module note).
_FREEFORM_CATEGORY_FIELD = "category"

# Google caps a Business Profile description at 750 chars.
DESCRIPTION_MAX_CHARS = 750

# Deterministic content-policy trip-wires (hard — a description with these is
# rejected by Google). URLs and phone numbers are not allowed in the description.
_URL_RE = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)
# 7+ digits separated by at most a couple of spacing/bracket chars — catches
# "8135551212", "813-555-1212", "+1 813 555 1212" and the "(813) 555-1212" form
# (the ") " gap). Deliberately a guard, not a parser; Google is the authority.
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]{0,2}){7,}\d(?!\d)")

# Advisory (linter-only) signals — never a gate; Google's `rejected` verdict is
# the source of truth. Promotional superlatives Google's guidelines discourage.
_PROMO_RE = re.compile(
    r"\b(best|#1|number one|guaranteed?|cheapest|lowest price|world[- ]?class|"
    r"unbeatable|top[- ]?rated|award[- ]?winning)\b",
    re.IGNORECASE,
)
_EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]"
)


# ───────────────────────────────────────────────────────────────────────────
# Description — validation + advisory linter (pure, unit-tested)
# ───────────────────────────────────────────────────────────────────────────
def validate_description(text: str, max_chars: int = DESCRIPTION_MAX_CHARS) -> str:
    """Return the trimmed description or raise ValueError with a deterministic
    code (``description_too_long`` / ``description_contains_url`` /
    ``description_contains_phone``). These are the three content-policy rules
    Google enforces deterministically; everything fuzzy is advisory (``lint``)."""
    value = (text or "").strip()
    if len(value) > max_chars:
        raise ValueError(f"description_too_long:{len(value)}/{max_chars}")
    if _URL_RE.search(value):
        raise ValueError("description_contains_url")
    if _PHONE_RE.search(value):
        raise ValueError("description_contains_phone")
    return value


def _caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def lint_description(text: str, max_chars: int = DESCRIPTION_MAX_CHARS) -> list[dict]:
    """Advisory content-policy warnings for a description — **never a gate**
    (decision Q9/Q12). Each is ``{code, message}``. Google's `rejected` verdict +
    the reconciler remain the source of truth; this only reduces failed submits.
    Pure (unit-tested)."""
    value = (text or "").strip()
    out: list[dict] = []
    if len(value) > max_chars:
        out.append({"code": "too_long", "message": f"Over {max_chars} characters ({len(value)})."})
    if _URL_RE.search(value):
        out.append({"code": "url", "message": "Contains a URL — Google removes/rejects links in the description."})
    if _PHONE_RE.search(value):
        out.append({"code": "phone", "message": "Contains a phone number — not allowed in the description."})
    if len(value) >= 40 and _caps_ratio(value) > 0.30:
        out.append({"code": "all_caps", "message": "Heavy use of ALL-CAPS reads as promotional."})
    if _PROMO_RE.search(value):
        out.append({"code": "promotional", "message": "Promotional superlatives (best / #1 / guaranteed) can trip review."})
    if value.count("!") >= 3:
        out.append({"code": "punctuation", "message": "Excessive exclamation marks read as spammy."})
    if len(_EMOJI_RE.findall(value)) >= 3:
        out.append({"code": "emoji", "message": "Lots of emoji can look unprofessional / trip review."})
    return out


def build_description_patch(text: str, max_chars: int = DESCRIPTION_MAX_CHARS) -> tuple[dict, str]:
    """(body, updateMask) for a description edit. Validates first. Pure."""
    value = validate_description(text, max_chars)
    return {"profile": {"description": value}}, "profile.description"


# ───────────────────────────────────────────────────────────────────────────
# Hours — weekly rows ⇄ v1 regularHours.periods (TimeOfDay). Pure, unit-tested.
# ───────────────────────────────────────────────────────────────────────────
def parse_time_of_day(hhmm: str) -> dict:
    """'HH:MM' → a v1 TimeOfDay ``{hours, minutes}``. Accepts '24:00' (the v1
    end-of-day convention, hours may be 0–24). Raises ValueError on a bad value."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", (hhmm or "").strip())
    if not m:
        raise ValueError(f"invalid_time:{hhmm}")
    h, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 24 and 0 <= mm <= 59) or (h == 24 and mm != 0):
        raise ValueError(f"invalid_time:{hhmm}")
    tod: dict = {}
    if h:
        tod["hours"] = h
    if mm:
        tod["minutes"] = mm
    # An all-zero TimeOfDay ({}) is midnight — the v1 default; sent as an empty
    # object so a period can express 00:00 without relying on proto zero-drop.
    return tod


def format_time_of_day(tod: Optional[dict]) -> str:
    """A v1 TimeOfDay → 'HH:MM' for display. None/{} → '00:00'. Pure."""
    tod = tod or {}
    return f"{int(tod.get('hours', 0)):02d}:{int(tod.get('minutes', 0)):02d}"


def _minutes(tod: dict) -> int:
    return int(tod.get("hours", 0)) * 60 + int(tod.get("minutes", 0))


def build_hours_patch(
    regular_rows: list[dict], special_rows: Optional[list[dict]] = None
) -> tuple[dict, str]:
    """Build (body, updateMask) for an hours edit from our internal weekly rows.

    ``regular_rows``: one entry per open day — ``{day: 0..6 (Mon..Sun),
    open_24: bool, periods: [{open: 'HH:MM', close: 'HH:MM'}]}``. A day with no
    entry (or ``periods: []`` and not ``open_24``) is CLOSED (no period emitted).
    A close time ≤ its open time is treated as crossing midnight (closeDay =
    next day). ``open_24`` emits a single 00:00→24:00 period.

    ``special_rows`` (optional): holiday/special hours — ``{start: {year,month,
    day}, end: {...}, closed: bool, open: 'HH:MM', close: 'HH:MM'}``. ``None``
    leaves specialHours untouched (mask excludes it); ``[]`` clears them. Pure.
    """
    periods = _weekly_periods(regular_rows)
    body: dict = {"regularHours": {"periods": periods}}
    mask = "regularHours"
    if special_rows is not None:
        body["specialHours"] = {"specialHourPeriods": _build_special_periods(special_rows)}
        mask = "regularHours,specialHours"
    return body, mask


def _weekly_periods(rows: list[dict]) -> list[dict]:
    """Weekly open-day rows → a flat list of v1 TimePeriods (openDay/openTime →
    closeDay/closeTime). Shared by regularHours and moreHours. ``open_24`` emits a
    single 00:00→24:00 period; a close ≤ open crosses midnight (closeDay = next
    day). Pure."""
    periods: list[dict] = []
    for row in rows or []:
        day = int(row.get("day"))
        if not (0 <= day <= 6):
            raise ValueError(f"invalid_day:{day}")
        open_day = DAY_ENUM[day]
        if row.get("open_24"):
            periods.append({
                "openDay": open_day, "openTime": {},
                "closeDay": open_day, "closeTime": {"hours": 24},
            })
            continue
        for p in row.get("periods") or []:
            open_t = parse_time_of_day(p.get("open"))
            close_t = parse_time_of_day(p.get("close"))
            close_day = open_day
            if _minutes(close_t) <= _minutes(open_t):
                close_day = DAY_ENUM[(day + 1) % 7]
            periods.append({
                "openDay": open_day, "openTime": open_t,
                "closeDay": close_day, "closeTime": close_t,
            })
    return periods


def _build_special_periods(special_rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in special_rows or []:
        start = row.get("start") or {}
        period: dict = {"startDate": _as_date(start)}
        end = row.get("end") or start
        period["endDate"] = _as_date(end)
        if row.get("closed"):
            period["closed"] = True
        else:
            period["openTime"] = parse_time_of_day(row.get("open"))
            period["closeTime"] = parse_time_of_day(row.get("close"))
        out.append(period)
    return out


def _as_date(d: dict) -> dict:
    try:
        return {"year": int(d["year"]), "month": int(d["month"]), "day": int(d["day"])}
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid_special_hours_date")


# ───────────────────────────────────────────────────────────────────────────
# Services — free-form list ⇄ v1 serviceItems. Pure, unit-tested.
# ───────────────────────────────────────────────────────────────────────────
def build_services_patch(
    services: list[dict], allowed_categories: Optional[set[str]] = None
) -> tuple[dict, str]:
    """Build (body, updateMask) for a services edit from our internal list.

    Each service is one of:

    - a **structured** service ``{kind: 'structured', service_type_id,
      description?}`` — a Google-defined service type (picked from the listing's
      categories) → emits a ``structuredServiceItem`` with the row's own
      (editable) description;
    - a **structured passthrough** ``{kind: 'structured', raw: <serviceItem dict>}``
      — a legacy structured row with no explicit ``service_type_id`` preserved
      verbatim (back-compat for old drafts / strategist stages);
    - a **free-form (custom)** entry ``{kind: 'free_form', label, description?,
      category_id}`` — an operator-authored custom service.

    Free-form services require ``label`` + ``category_id`` (validated against
    ``allowed_categories`` when given, else ValueError). Structured services are
    deduped by ``serviceTypeId``, free-form by label (case-insensitive). Both
    carry an optional description. Pure (unit-tested)."""
    items: list[dict] = []
    seen_free: set[str] = set()
    seen_struct: set[str] = set()
    for svc in services or []:
        kind = (svc.get("kind") or "free_form").strip()
        if kind == "structured":
            stid = (svc.get("service_type_id") or "").strip()
            if not stid:
                # Legacy passthrough (no explicit id on the row) → keep verbatim.
                raw = svc.get("raw")
                if isinstance(raw, dict):
                    rid = ((raw.get("structuredServiceItem") or {}).get("serviceTypeId") or "").strip()
                    if rid and rid in seen_struct:
                        continue
                    if rid:
                        seen_struct.add(rid)
                    items.append(raw)
                    continue
                raise ValueError("service_type_id_required")
            if stid in seen_struct:
                continue
            seen_struct.add(stid)
            # Build from the id + the row's own description, so editing a
            # structured service's description actually takes effect (the stored
            # raw would otherwise carry the pre-edit description).
            item: dict = {"structuredServiceItem": {"serviceTypeId": stid}}
            desc = (svc.get("description") or "").strip()
            if desc:
                item["structuredServiceItem"]["description"] = desc
            items.append(item)
            continue
        label = (svc.get("label") or "").strip()
        if not label:
            raise ValueError("service_label_required")
        key = label.lower()
        if key in seen_free:
            continue
        seen_free.add(key)
        category = (svc.get("category_id") or "").strip()
        if not category:
            raise ValueError(f"service_category_required:{label}")
        if allowed_categories is not None and category not in allowed_categories:
            raise ValueError(f"invalid_service_category:{label}")
        free: dict = {_FREEFORM_CATEGORY_FIELD: category, "label": {
            "displayName": label, "languageCode": "en",
        }}
        desc = (svc.get("description") or "").strip()
        if desc:
            free["label"]["description"] = desc
        items.append({"freeFormServiceItem": free})
    return {"serviceItems": items}, "serviceItems"


# ───────────────────────────────────────────────────────────────────────────
# Phase 3a — Tier A fields (same locations.patch endpoint, one field per mask):
# website, labels, special hours, more hours, service area, open info. Every
# builder is pure + unit-tested and returns (body, updateMask); each raises a
# ValueError with a deterministic code the service maps to a 400.
# ───────────────────────────────────────────────────────────────────────────
_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
_HOST_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.IGNORECASE)


def build_website_patch(url: str) -> tuple[dict, str]:
    """(body, updateMask) for the website URL. Empty clears it. A bare host gets
    an ``https://`` scheme; anything that doesn't look like a URL raises
    ``invalid_website_url``. Pure."""
    value = (url or "").strip()
    if value:
        if "://" in value:
            # A scheme is present — it MUST be http(s); a foreign scheme is junk.
            if not _SCHEME_RE.match(value):
                raise ValueError("invalid_website_url")
        else:
            value = "https://" + value
        if not _HOST_RE.match(value) or "." not in value.split("//", 1)[-1]:
            raise ValueError("invalid_website_url")
    return {"websiteUri": value}, "websiteUri"


def build_labels_patch(
    labels: list[str], max_labels: int = LABELS_MAX, max_len: int = LABEL_MAX_CHARS
) -> tuple[dict, str]:
    """(body, updateMask) for the listing's labels (internal organisation tags,
    not customer-facing). Strips + dedupes (case-insensitive) + drops empties;
    ``too_many_labels`` / ``label_too_long`` on a breach. ``[]`` clears them. Pure."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in labels or []:
        value = (raw or "").strip() if isinstance(raw, str) else ""
        if not value:
            continue
        if len(value) > max_len:
            raise ValueError(f"label_too_long:{value[:40]}")
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    if len(cleaned) > max_labels:
        raise ValueError(f"too_many_labels:{len(cleaned)}/{max_labels}")
    return {"labels": cleaned}, "labels"


def build_special_hours_patch(special_rows: list[dict]) -> tuple[dict, str]:
    """(body, updateMask) for holiday / one-off hours. ``[]`` clears them. Each row
    is ``{start:{year,month,day}, end?, closed?, open?, close?}`` — same shape the
    hours field's optional special rows use. Pure."""
    return {"specialHours": {"specialHourPeriods": _build_special_periods(special_rows or [])}}, "specialHours"


def build_more_hours_patch(
    entries: list[dict], allowed_type_ids: Optional[set[str]] = None
) -> tuple[dict, str]:
    """(body, updateMask) for additional hours (kitchen / delivery / senior hours…).

    Each entry is ``{hours_type_id, regular: [weekly rows]}`` — the weekly rows are
    the same shape as regularHours (``{day, open_24, periods:[{open, close}]}``).
    ``hours_type_id`` must be one of the primary category's valid MoreHoursType ids
    (validated against ``allowed_type_ids`` when given → ``invalid_more_hours_type``).
    An entry that resolves to no periods is dropped (a type with no hours = removed).
    ``[]`` clears all more-hours. Pure."""
    out: list[dict] = []
    seen: set[str] = set()
    for entry in entries or []:
        tid = (entry.get("hours_type_id") or "").strip()
        if not tid:
            raise ValueError("more_hours_type_required")
        if allowed_type_ids is not None and tid not in allowed_type_ids:
            raise ValueError(f"invalid_more_hours_type:{tid}")
        if tid in seen:
            continue
        periods = _weekly_periods(entry.get("regular") or [])
        if not periods:
            continue  # a more-hours type with no periods means "not set" → omit
        seen.add(tid)
        out.append({"hoursTypeId": tid, "periods": periods})
    return {"moreHours": out}, "moreHours"


def build_service_area_patch(value: dict) -> tuple[dict, str]:
    """(body, updateMask) for a service-area business's coverage.

    ``value`` = ``{business_type, places: [{name, place_id}], region_code?}``.
    ``business_type`` defaults to CUSTOMER_AND_BUSINESS_LOCATION (keeps a storefront
    visible). Every place must carry a Google ``place_id`` (resolved up front via
    maps_geocode) → else ``invalid_service_area``; the display ``name`` rides along.
    An empty places list clears the coverage. Pure.

    ⚠️ The v1 serviceArea write shape (placeInfos require placeId; regionCode for a
    CAB business) is one to re-verify live at build time per the module note — a
    wrong shape surfaces as a ``rejected`` edit, never a silent bad write."""
    value = value or {}
    business_type = (value.get("business_type") or "").strip() or SERVICE_AREA_BUSINESS_TYPES[0]
    if business_type not in SERVICE_AREA_BUSINESS_TYPES:
        raise ValueError(f"invalid_service_area:business_type:{business_type}")
    infos: list[dict] = []
    seen: set[str] = set()
    for place in value.get("places") or []:
        pid = (place.get("place_id") or "").strip()
        name = (place.get("name") or "").strip()
        if not pid:
            raise ValueError(f"invalid_service_area:unresolved:{name or '?'}")
        if pid in seen:
            continue
        seen.add(pid)
        info: dict = {"placeId": pid}
        if name:
            info["placeName"] = name
        infos.append(info)
    area: dict = {"businessType": business_type, "places": {"placeInfos": infos}}
    region = (value.get("region_code") or "").strip()
    if region:
        area["regionCode"] = region
    return {"serviceArea": area}, "serviceArea"


def build_open_info_patch(value: dict) -> tuple[dict, str]:
    """(body, updateMask) for the open/closed status. ``value`` =
    ``{status, opening_date?}``. ``status`` ∈ OPEN_STATUSES (``invalid_open_status``
    otherwise). ``opening_date`` (a future open date) is optional and only carried
    when present. Pure. The AI never drafts a closure; the UI gates any CLOSED_*
    behind an extra confirm."""
    value = value or {}
    status = (value.get("status") or "").strip().upper()
    if status not in OPEN_STATUSES:
        raise ValueError(f"invalid_open_status:{status or '?'}")
    open_info: dict = {"status": status}
    od = value.get("opening_date")
    if isinstance(od, dict) and od.get("year"):
        open_info["openingDate"] = _as_date(od)
    return {"openInfo": open_info}, "openInfo"


# ───────────────────────────────────────────────────────────────────────────
# Read a location's fields into our internal shape. Pure, unit-tested.
# ───────────────────────────────────────────────────────────────────────────
def parse_categories(loc: dict) -> list[dict]:
    """The listing's categories as ``[{id, name}]`` (id = the gcid the services
    editor attaches to). Primary first, then additional. Pure."""
    cats = (loc or {}).get("categories") or {}
    out: list[dict] = []
    primary = cats.get("primaryCategory")
    for cat in ([primary] if primary else []) + (cats.get("additionalCategories") or []):
        if not isinstance(cat, dict):
            continue
        cid = cat.get("name")
        if cid:
            out.append({"id": cid, "name": cat.get("displayName") or cid})
    return out


def parse_categories_value(loc: dict) -> dict:
    """The listing's categories as the editable ``{primary: {id, name} | None,
    additional: [{id, name}]}`` shape (Phase 3b — distinct from the flat
    ``parse_categories`` picker list the services editor uses). Pure."""
    cats = (loc or {}).get("categories") or {}

    def _ref(cat) -> Optional[dict]:
        if not isinstance(cat, dict):
            return None
        cid = cat.get("name")
        return {"id": cid, "name": cat.get("displayName") or cid} if cid else None

    primary = _ref(cats.get("primaryCategory"))
    additional: list[dict] = []
    seen = {primary["id"]} if primary else set()
    for cat in cats.get("additionalCategories") or []:
        ref = _ref(cat)
        if ref and ref["id"] not in seen:
            seen.add(ref["id"])
            additional.append(ref)
    return {"primary": primary, "additional": additional}


# ───────────────────────────────────────────────────────────────────────────
# Phase 3b — categories (rides locations.patch like a Tier-A field, but needs a
# live category catalog SEARCH to pick valid gcids; changing the PRIMARY category
# shifts ranking behaviour so the UI gates it behind an extra confirm). Consumes
# the existing gbp_audit.category_gaps finding via the strategist loop's generic
# stage_strategist_draft — no new wiring, categories is just a valid field now.
# ───────────────────────────────────────────────────────────────────────────
def build_categories_patch(value: dict, allowed_ids: Optional[set[str]] = None) -> tuple[dict, str]:
    """(body, updateMask) for the listing's categories. ``value`` =
    ``{primary: {id, name}, additional: [{id, name}]}``. The primary category is
    REQUIRED (``primary_category_required``); each id must be a category resource
    name (``categories/gcid:…``). ``additional`` is deduped and never contains the
    primary. When ``allowed_ids`` is given every id is validated against it
    (``invalid_category``) — the picker resolves ids from the live catalog, so this
    guards a hand-crafted payload. Pure."""
    value = value or {}
    primary = (value.get("primary") or {}) if isinstance(value.get("primary"), dict) else {}
    pid = (primary.get("id") or "").strip()
    if not pid:
        raise ValueError("primary_category_required")
    if allowed_ids is not None and pid not in allowed_ids:
        raise ValueError(f"invalid_category:{pid}")
    body: dict = {"categories": {"primaryCategory": {"name": pid}}}
    additional: list[dict] = []
    seen = {pid}
    for cat in value.get("additional") or []:
        cid = (cat.get("id") or "").strip() if isinstance(cat, dict) else ""
        if not cid or cid in seen:
            continue
        if allowed_ids is not None and cid not in allowed_ids:
            raise ValueError(f"invalid_category:{cid}")
        seen.add(cid)
        additional.append({"name": cid})
    if additional:
        body["categories"]["additionalCategories"] = additional
    return body, "categories"


def parse_category_search(response: dict) -> list[dict]:
    """A v1 ``categories.list`` response → ``[{id, name}]`` for the category picker.
    Pure (unit-tested)."""
    out: list[dict] = []
    seen: set[str] = set()
    for cat in (response or {}).get("categories") or []:
        if not isinstance(cat, dict):
            continue
        cid = cat.get("name")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append({"id": cid, "name": cat.get("displayName") or cid})
    return out


def search_categories(
    query: str, region_code: str = "US", language_code: str = "en", limit: int = 20,
) -> dict:
    """v1 ``categories.list`` — search Google's business-category catalog by display
    name (``filter='displayName=<term>'``), region/language-scoped. Returns the raw
    response (``parse_category_search`` shapes it). Raises a classified HTTPException
    on failure. An empty query returns no categories (the picker searches on type)."""
    term = (query or "").strip()
    if not term:
        return {"categories": []}
    try:
        return (
            _info_client().categories()
            .list(
                regionCode=region_code, languageCode=language_code, view="BASIC",
                filter=f'displayName="{term}"', pageSize=max(1, min(limit, 100)),
            )
            .execute()
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — google HttpError / transport
        _raise(exc, field="categories")


# ───────────────────────────────────────────────────────────────────────────
# Phase 3b — attributes. UNLIKE every other editable field, attributes do NOT
# ride locations.patch: they live on a SEPARATE endpoint pair —
# ``locations.getAttributes`` / ``locations.updateAttributes`` (an ``Attributes``
# resource keyed at ``locations/{id}/attributes``) — with a per-attribute
# ``updateMask``, category-scoped availability (``attributes.list``), and
# value-typed values (BOOL / ENUM / URL / REPEATED_ENUM). So the service layer
# branches the read/write for attributes; everything shaping/validating/diffing
# stays here, pure + unit-tested.
#
# ⚠️ The v1 attributes write shape is one to re-verify live at build time per the
# module note: the ``updateMask`` entries are the full attribute resource names
# (``attributes/{id}``), comma-joined; a wrong shape surfaces as a ``rejected``
# edit at activation test time, never a silent bad write.
# ───────────────────────────────────────────────────────────────────────────
ATTRIBUTE_VALUE_TYPES = ("BOOL", "ENUM", "URL", "REPEATED_ENUM")


def _coerce_attr_url(value: str) -> str:
    """A URL-attribute value → a normalized http(s) URL, else ValueError. A bare
    host gets ``https://``; a foreign scheme is junk. Pure."""
    v = (value or "").strip()
    if "://" in v:
        if not _SCHEME_RE.match(v):
            raise ValueError("invalid_attribute_url")
    else:
        v = "https://" + v
    if not _HOST_RE.match(v) or "." not in v.split("//", 1)[-1]:
        raise ValueError("invalid_attribute_url")
    return v


def build_attributes_patch(entries: list[dict], allowed_ids: Optional[set[str]] = None) -> tuple[dict, str]:
    """(body, updateMask) for an attributes edit. ``entries`` is the SUBSET of
    attributes to set/clear — each ``{attribute_id, value_type, ...value...}`` —
    and the mask names exactly those ids (attributes NOT listed are untouched;
    updateAttributes is masked, not a full replace). An entry with no value clears
    that attribute (kept in the mask so the clear takes). Pure (unit-tested).

    Per value type:
      - BOOL: ``values: [true|false]`` (``[]`` clears)
      - ENUM: ``values: ['<enum value>']`` (single-select; ``[]`` clears)
      - URL: ``urls: ['https://…']`` → ``uriValues`` (each validated)
      - REPEATED_ENUM: ``set_values`` / ``unset_values`` → ``repeatedEnumValue``

    ``attribute_id`` must be an ``attributes/{id}`` resource name
    (``invalid_attribute`` otherwise); ``value_type`` ∈ ATTRIBUTE_VALUE_TYPES
    (``invalid_attribute_value_type`` otherwise). When ``allowed_ids`` is given
    every id is validated against it (the picker resolves ids from the live
    availability list, so this guards a hand-crafted payload)."""
    attributes: list[dict] = []
    masks: list[str] = []
    seen: set[str] = set()
    for entry in entries or []:
        aid = (entry.get("attribute_id") or "").strip()
        if not aid:
            raise ValueError("attribute_id_required")
        if not aid.startswith("attributes/"):
            raise ValueError(f"invalid_attribute:{aid}")
        if allowed_ids is not None and aid not in allowed_ids:
            raise ValueError(f"invalid_attribute:{aid}")
        if aid in seen:
            continue
        seen.add(aid)
        vt = (entry.get("value_type") or "").strip().upper()
        if vt not in ATTRIBUTE_VALUE_TYPES:
            raise ValueError(f"invalid_attribute_value_type:{aid}")
        attr: dict = {"name": aid, "valueType": vt}
        if vt == "URL":
            attr["uriValues"] = [
                {"uri": _coerce_attr_url(u)}
                for u in (entry.get("urls") or []) if isinstance(u, str) and u.strip()
            ]
        elif vt == "REPEATED_ENUM":
            attr["repeatedEnumValue"] = {
                "setValues": [str(v).strip() for v in (entry.get("set_values") or []) if str(v).strip()],
                "unsetValues": [str(v).strip() for v in (entry.get("unset_values") or []) if str(v).strip()],
            }
        elif vt == "BOOL":
            vals = entry.get("values") or []
            attr["values"] = [bool(vals[0])] if vals else []
        else:  # ENUM (single-select)
            vals = [str(v).strip() for v in (entry.get("values") or []) if str(v).strip()]
            attr["values"] = vals[:1]
        attributes.append(attr)
        masks.append(aid)
    if not attributes:
        raise ValueError("no_attributes")
    return {"attributes": attributes}, ",".join(masks)


def parse_attributes(response: dict) -> list[dict]:
    """A v1 ``Attributes`` resource → our internal editor list
    ``[{attribute_id, value_type, ...value...}]`` — only the attributes that carry
    a value (getAttributes returns the merchant-set ones). Pure (unit-tested)."""
    out: list[dict] = []
    for attr in (response or {}).get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        aid = (attr.get("name") or "").strip()
        vt = (attr.get("valueType") or "").strip().upper()
        if not aid or vt not in ATTRIBUTE_VALUE_TYPES:
            continue
        entry: dict = {"attribute_id": aid, "value_type": vt}
        if vt == "URL":
            entry["urls"] = [
                (u.get("uri") or "").strip()
                for u in attr.get("uriValues") or [] if isinstance(u, dict) and u.get("uri")
            ]
        elif vt == "REPEATED_ENUM":
            rev = attr.get("repeatedEnumValue") or {}
            entry["set_values"] = [str(v) for v in (rev.get("setValues") or [])]
            entry["unset_values"] = [str(v) for v in (rev.get("unsetValues") or [])]
        else:  # BOOL / ENUM
            entry["values"] = list(attr.get("values") or [])
        out.append(entry)
    return out


def parse_attribute_metadata(response: dict) -> list[dict]:
    """A v1 ``attributes.list`` response → the attribute picker shape
    ``[{attribute_id, value_type, display_name, group_name, deprecated,
    repeatable, value_options}]`` (value_options only for ENUM/REPEATED_ENUM),
    grouped-sorted by display group then name. Pure (unit-tested)."""
    out: list[dict] = []
    seen: set[str] = set()
    for meta in (response or {}).get("attributeMetadata") or []:
        if not isinstance(meta, dict):
            continue
        aid = (meta.get("parent") or "").strip()
        if not aid or aid in seen:
            continue
        seen.add(aid)
        item: dict = {
            "attribute_id": aid,
            "value_type": (meta.get("valueType") or "").strip().upper(),
            "display_name": meta.get("displayName") or aid,
            "group_name": meta.get("groupDisplayName") or "",
            "deprecated": bool(meta.get("deprecated")),
            "repeatable": bool(meta.get("repeatable")),
        }
        options = [
            {"value": vm.get("value"), "display_name": vm.get("displayName") or str(vm.get("value"))}
            for vm in meta.get("valueMetadata") or []
            if isinstance(vm, dict) and vm.get("value") is not None
        ]
        if options:
            item["value_options"] = options
        out.append(item)
    out.sort(key=lambda x: (x.get("group_name") or "", x.get("display_name") or ""))
    return out


def _attr_value_key(entry: dict) -> object:
    """The comparable value of a single attribute entry (order-insensitive for
    repeated / URL). An entry with no set value returns None (absent == cleared).
    Pure."""
    vt = (entry.get("value_type") or "").strip().upper()
    if vt == "URL":
        urls = frozenset((u or "").strip() for u in (entry.get("urls") or []) if isinstance(u, str) and (u or "").strip())
        return ("URL", urls) if urls else None
    if vt == "REPEATED_ENUM":
        sv = frozenset(str(v).strip() for v in (entry.get("set_values") or []) if str(v).strip())
        return ("REPEATED_ENUM", sv) if sv else None
    vals = [v for v in (entry.get("values") or [])]
    return (vt, tuple(vals)) if vals else None


def _attributes_map(entries: list[dict]) -> dict:
    """Attribute entries → ``{attribute_id: value_key}`` dropping cleared ones, so
    an absent attribute compares equal to a cleared one. Pure."""
    out: dict = {}
    for entry in entries or []:
        aid = (entry.get("attribute_id") or "").strip()
        if not aid:
            continue
        key = _attr_value_key(entry)
        if key is not None:
            out[aid] = key
    return out


def attributes_diff(snapshot: list[dict], live: list[dict]) -> bool:
    """True if the whole attribute set drifted between the draft snapshot and a
    fresh live read (the re-read-and-diff guard, Q3 — conservative: any attribute
    changing out-of-band trips it). Order-insensitive. Pure (unit-tested)."""
    return _attributes_map(snapshot) != _attributes_map(live)


def attributes_subset_applied(proposed: list[dict], live: list[dict]) -> bool:
    """True when every attribute in the proposed SUBSET is reflected in the live
    read (the applied/rejected outcome check — a cleared attribute must be absent
    live, a set one must match). Attributes outside the subset are ignored. Pure
    (unit-tested)."""
    live_map = _attributes_map(live)
    for entry in proposed or []:
        aid = (entry.get("attribute_id") or "").strip()
        if not aid:
            continue
        want = _attr_value_key(entry)
        if want is None:  # this edit clears it → must be absent live
            if aid in live_map:
                return False
        elif live_map.get(aid) != want:
            return False
    return True


def parse_service_area(loc: dict) -> list[str]:
    """The service-area place NAMES a listing publishes (v1
    ``serviceArea.places.placeInfos[].placeName``) — the towns/areas the business
    serves. A candidate list for the services matrix; pure (unit-tested)."""
    infos = (((loc or {}).get("serviceArea") or {}).get("places") or {}).get("placeInfos") or []
    out: list[str] = []
    seen: set[str] = set()
    for pi in infos:
        if not isinstance(pi, dict):
            continue
        nm = (pi.get("placeName") or "").strip()
        key = nm.lower()
        if nm and key not in seen:
            seen.add(key)
            out.append(nm)
    return out


def parse_storefront_city(loc: dict) -> str:
    """The listing's home city as ``"City, ST"`` (v1 ``storefrontAddress``:
    ``locality`` + ``administrativeArea``), or the best single part available, or
    ``""`` for a pure service-area business with no storefront. Pure."""
    addr = (loc or {}).get("storefrontAddress") or {}
    city = (addr.get("locality") or "").strip()
    state = (addr.get("administrativeArea") or "").strip()
    if city and state:
        return f"{city}, {state}"
    return city or state or ""


def _group_periods(periods: list[dict]) -> list[dict]:
    """A flat v1 TimePeriod list → our internal weekly rows (``{day, open_24,
    periods:[{open, close}]}``), grouped by open day, open_24 detected. Shared by
    regularHours and moreHours. Pure."""
    by_day: dict[int, dict] = {}
    for p in periods or []:
        day = _DAY_INDEX.get(p.get("openDay"))
        if day is None:
            continue
        row = by_day.setdefault(day, {"day": day, "open_24": False, "periods": []})
        open_t = p.get("openTime") or {}
        close_t = p.get("closeTime") or {}
        if not open_t and int(close_t.get("hours", 0)) == 24:
            row["open_24"] = True
            continue
        row["periods"].append({
            "open": format_time_of_day(open_t),
            "close": format_time_of_day(close_t),
        })
    return [by_day[d] for d in sorted(by_day)]


def parse_hours(loc: dict) -> dict:
    """v1 regularHours/specialHours → our internal ``{regular: [rows], special:
    [rows]}``. Groups periods by open day into per-day rows (open_24 detected).
    Pure."""
    regular = _group_periods(((loc or {}).get("regularHours") or {}).get("periods") or [])
    special = []
    for sp in ((loc or {}).get("specialHours") or {}).get("specialHourPeriods") or []:
        entry = {"start": sp.get("startDate"), "end": sp.get("endDate"), "closed": bool(sp.get("closed"))}
        if not entry["closed"]:
            entry["open"] = format_time_of_day(sp.get("openTime"))
            entry["close"] = format_time_of_day(sp.get("closeTime"))
        special.append(entry)
    return {"regular": regular, "special": special}


def parse_services(loc: dict) -> list[dict]:
    """v1 serviceItems → our internal editor list. Free-form items become
    editable ``{kind:'free_form', label, description, category_id}``; structured
    items are preserved read-only as ``{kind:'structured', label, raw}``. Pure."""
    out: list[dict] = []
    for item in (loc or {}).get("serviceItems") or []:
        if not isinstance(item, dict):
            continue
        free = item.get("freeFormServiceItem")
        if isinstance(free, dict):
            label = (free.get("label") or {})
            out.append({
                "kind": "free_form",
                "label": label.get("displayName") or "",
                "description": label.get("description") or "",
                "category_id": free.get(_FREEFORM_CATEGORY_FIELD) or free.get("categoryId") or "",
            })
            continue
        structured = item.get("structuredServiceItem")
        if isinstance(structured, dict):
            stid = structured.get("serviceTypeId") or ""
            out.append({
                "kind": "structured",
                "label": stid,
                "service_type_id": stid,
                "description": structured.get("description") or "",
                "raw": item,
            })
    return out


# ───────────────────────────────────────────────────────────────────────────
# Phase 3a — parse the new editable fields into our internal shapes. Pure.
# ───────────────────────────────────────────────────────────────────────────
def parse_website(loc: dict) -> str:
    return ((loc or {}).get("websiteUri") or "").strip()


def parse_labels(loc: dict) -> list[str]:
    return [l.strip() for l in ((loc or {}).get("labels") or []) if isinstance(l, str) and l.strip()]


def parse_special_hours(loc: dict) -> list[dict]:
    """Just the special-hours rows (holiday hours) — the special_hours field's
    value. Pure."""
    return parse_hours(loc)["special"]


def parse_more_hours(loc: dict) -> list[dict]:
    """v1 moreHours → our internal ``[{hours_type_id, regular: [weekly rows]}]``
    (one entry per additional-hours type, its periods grouped by day). Pure."""
    out: list[dict] = []
    for mh in (loc or {}).get("moreHours") or []:
        if not isinstance(mh, dict):
            continue
        tid = (mh.get("hoursTypeId") or "").strip()
        if not tid:
            continue
        out.append({"hours_type_id": tid, "regular": _group_periods(mh.get("periods") or [])})
    return out


def parse_service_area_full(loc: dict) -> dict:
    """v1 serviceArea → our internal editor shape ``{business_type, places:
    [{name, place_id}], region_code}``. Places keep their placeId so an unedited
    coverage re-applies unchanged (only newly-added places need resolving). Pure."""
    area = (loc or {}).get("serviceArea") or {}
    infos = ((area.get("places") or {}).get("placeInfos")) or []
    places: list[dict] = []
    seen: set[str] = set()
    for pi in infos:
        if not isinstance(pi, dict):
            continue
        pid = (pi.get("placeId") or "").strip()
        name = (pi.get("placeName") or "").strip()
        key = pid or name.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        places.append({"name": name, "place_id": pid})
    return {
        "business_type": (area.get("businessType") or "").strip(),
        "places": places,
        "region_code": (area.get("regionCode") or "").strip(),
    }


def parse_open_info(loc: dict) -> dict:
    """v1 openInfo → our internal ``{status, opening_date}`` (opening_date =
    ``{year, month, day}`` or None). ``can_reopen`` is output-only context. Pure."""
    info = (loc or {}).get("openInfo") or {}
    od = info.get("openingDate")
    return {
        "status": (info.get("status") or "").strip(),
        "opening_date": od if isinstance(od, dict) and od.get("year") else None,
    }


def parse_more_hours_types(response: dict, categories: Optional[list[dict]] = None) -> list[dict]:
    """A v1 ``categories.batchGet`` (view=FULL) response → the more-hours-type
    picker shape: ``[{id, name, more_hours_types: [{hours_type_id, display_name}]}]``,
    ordered to match the listing's own category order. Mirrors
    ``parse_service_types`` (moreHoursTypes ride the SAME batchGet). Pure."""
    name_by_id = {c["id"]: c["name"] for c in (categories or []) if c.get("id")}
    order = [c["id"] for c in (categories or []) if c.get("id")]
    out: list[dict] = []
    for cat in (response or {}).get("categories") or []:
        cid = cat.get("name")
        if not cid:
            continue
        types: list[dict] = []
        seen: set[str] = set()
        for mt in cat.get("moreHoursTypes") or []:
            if not isinstance(mt, dict):
                continue
            tid = mt.get("hoursTypeId")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            types.append({
                "hours_type_id": tid,
                "display_name": mt.get("displayName") or mt.get("localizedDisplayName") or tid,
            })
        if types:
            out.append({
                "id": cid,
                "name": cat.get("displayName") or name_by_id.get(cid) or cid,
                "more_hours_types": types,
            })
    out.sort(key=lambda c: order.index(c["id"]) if c["id"] in order else len(order))
    return out


# ───────────────────────────────────────────────────────────────────────────
# Service types — the Google-defined services pickable for a listing's
# categories (v1 ``categories.batchGet`` with ``view=FULL``). Pure parse +
# the live call. One of two services ADD paths: Google-approved picks (here) +
# operator-authored custom (free-form) services (``build_services_patch``).
# ───────────────────────────────────────────────────────────────────────────
def humanize_service_type_id(stid: str) -> str:
    """A serviceTypeId ('job_type_id:flex_office_rentals') → a readable fallback
    ('Flex Office Rentals') for the rare case Google returns no displayName.
    Pure (mirrors the frontend serviceLabel)."""
    bare = re.sub(r"^[^:]*:", "", stid or "").replace("_", " ").strip()
    return bare.title() if bare else (stid or "")


def parse_service_types(response: dict, categories: Optional[list[dict]] = None) -> list[dict]:
    """A v1 ``categories.batchGet`` (view=FULL) response → the operator's picker
    shape: ``[{id, name, service_types: [{service_type_id, display_name}]}]``,
    ordered to match the listing's own category order when ``categories``
    ([{id, name}]) is given. Pure (unit-tested)."""
    name_by_id = {c["id"]: c["name"] for c in (categories or []) if c.get("id")}
    order = [c["id"] for c in (categories or []) if c.get("id")]
    out: list[dict] = []
    for cat in (response or {}).get("categories") or []:
        cid = cat.get("name")
        if not cid:
            continue
        types: list[dict] = []
        seen: set[str] = set()
        for st in cat.get("serviceTypes") or []:
            if not isinstance(st, dict):
                continue
            stid = st.get("serviceTypeId")
            if not stid or stid in seen:
                continue
            seen.add(stid)
            types.append({
                "service_type_id": stid,
                "display_name": st.get("displayName") or humanize_service_type_id(stid),
            })
        out.append({
            "id": cid,
            "name": cat.get("displayName") or name_by_id.get(cid) or cid,
            "service_types": types,
        })
    out.sort(key=lambda c: order.index(c["id"]) if c["id"] in order else len(order))
    return out


def list_service_types(
    category_names: list[str], region_code: str = "US", language_code: str = "en",
    view: str = "FULL",
) -> dict:
    """v1 ``categories.batchGet`` — the Google-defined service types for the given
    category resource names (``categories/gcid:...``). ``view='FULL'`` is required
    to get ``serviceTypes``. Returns the raw response (``parse_service_types``
    shapes it). Raises a classified HTTPException on failure."""
    names = [n for n in (category_names or []) if n]
    if not names:
        return {"categories": []}
    try:
        return (
            _info_client().categories()
            .batchGet(names=names, regionCode=region_code, languageCode=language_code, view=view)
            .execute()
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — google HttpError / transport
        _raise(exc, field="services")


def parse_metadata(loc: dict) -> dict:
    """The editability/pending flags the UI needs from Location.metadata (output
    only). ``can_modify_service_list`` gates the services editor; ``has_pending_edits``
    tells the user a prior edit is still settling. Pure."""
    meta = (loc or {}).get("metadata") or {}
    return {
        "has_pending_edits": bool(meta.get("hasPendingEdits")),
        "can_modify_service_list": meta.get("canModifyServiceList"),
        "can_operate_local_post": meta.get("canOperateLocalPost"),
        # Voice of Merchant: whether the account still has verified control of the
        # listing. Explicit False is the API's strongest 'suspended / lost control'
        # signal; None means Google didn't return it (unknown — never alarm).
        "has_voice_of_merchant": meta.get("hasVoiceOfMerchant"),
        "place_id": meta.get("placeId"),
        "maps_uri": meta.get("mapsUri"),
    }


def parse_location_fields(loc: dict) -> dict:
    """Read a v1 Location into everything the editor + drafters need. Pure."""
    loc = loc or {}
    hours = parse_hours(loc)
    return {
        "name": loc.get("name"),
        "title": loc.get("title"),
        "description": (loc.get("profile") or {}).get("description") or "",
        "hours": hours,
        "services": parse_services(loc),
        "categories": parse_categories(loc),
        "metadata": parse_metadata(loc),
        # Phase 3a — Tier A fields.
        "website": parse_website(loc),
        "labels": parse_labels(loc),
        "special_hours": hours["special"],
        "more_hours": parse_more_hours(loc),
        "service_area": parse_service_area_full(loc),
        "open_info": parse_open_info(loc),
        # Phase 3b — categories (editable {primary, additional}); distinct from the
        # flat `categories` picker list above (which the services editor uses).
        "categories_value": parse_categories_value(loc),
    }


# ───────────────────────────────────────────────────────────────────────────
# Profile monitor — snapshot the fields Google or an outside source might change
# + suspension/access detection. Pure snapshot/diff; the live read + alerting
# live in services/gbp_monitor.py. See docs/modules/gbp-profile-editor-prd-v1_0.md.
# ───────────────────────────────────────────────────────────────────────────
# A wider read than the editor's — the monitor also watches identity fields
# (name / phone / website / address / categories) an outside source (a scraper,
# a hijack, or Google itself) can change, plus openInfo + voice-of-merchant.
MONITOR_READ_MASK = (
    "name,title,profile.description,regularHours,specialHours,serviceItems,"
    "categories,phoneNumbers,websiteUri,storefrontAddress,openInfo,metadata"
)

# The monitored fields, in the order alerts list them. Each maps to a snapshot
# key; hours/services diff via the field-aware ``diff_field``, the rest compare
# with normalized equality.
MONITOR_FIELDS = (
    "title", "description", "categories", "phone", "website", "address",
    "hours", "services", "open_status",
)
_MONITOR_LABELS = {
    "title": "business name", "description": "description", "categories": "categories",
    "phone": "phone number", "website": "website", "address": "address",
    "hours": "hours", "services": "services", "open_status": "open/closed status",
}


def _phone_value(loc: dict) -> dict:
    phones = (loc or {}).get("phoneNumbers") or {}
    return {
        "primary": (phones.get("primaryPhone") or "").strip(),
        "additional": [p.strip() for p in (phones.get("additionalPhones") or []) if isinstance(p, str)],
    }


def _address_value(loc: dict) -> dict:
    addr = (loc or {}).get("storefrontAddress") or {}
    return {
        "lines": [l.strip() for l in (addr.get("addressLines") or []) if isinstance(l, str)],
        "locality": (addr.get("locality") or "").strip(),
        "region": (addr.get("administrativeArea") or "").strip(),
        "postal_code": (addr.get("postalCode") or "").strip(),
        "country": (addr.get("regionCode") or "").strip(),
    }


def monitor_snapshot(loc: dict) -> dict:
    """The monitored fields of a v1 Location, in the internal comparable shape.
    Pure (unit-tested)."""
    loc = loc or {}
    meta = parse_metadata(loc)
    return {
        "title": (loc.get("title") or "").strip(),
        "description": ((loc.get("profile") or {}).get("description") or "").strip(),
        "categories": [c["id"] for c in parse_categories(loc)],
        "phone": _phone_value(loc),
        "website": (loc.get("websiteUri") or "").strip(),
        "address": _address_value(loc),
        "hours": parse_hours(loc),
        "services": parse_services(loc),
        "open_status": ((loc.get("openInfo") or {}).get("status") or "").strip(),
        "has_voice_of_merchant": meta.get("has_voice_of_merchant"),
    }


def snapshot_access_status(snapshot: dict) -> str:
    """'suspended' when Voice of Merchant is explicitly False (lost verified
    control — the API's strongest suspension signal), else 'ok'. A None VoM is
    unknown and never alarms. Pure."""
    return "suspended" if (snapshot or {}).get("has_voice_of_merchant") is False else "ok"


# A classified get-failure code (from ``classify_profile_error``) that means the
# account can no longer READ the listing — a hard suspension or lost management,
# distinct from a transient/quota/api-disabled blip (which must not flip state).
_ACCESS_LOST_CODES = frozenset({
    "gbp_location_not_found", "gbp_listing_read_only", "gbp_listing_unverified",
})


def access_status_for_code(code: str) -> Optional[str]:
    """Map a classified get-failure code to 'no_access', or None when the failure
    is transient/quota/api-disabled (skip the cycle — don't flip state). Pure."""
    return "no_access" if code in _ACCESS_LOST_CODES else None


def diff_snapshot(baseline: dict, live: dict) -> list[dict]:
    """Out-of-band changes between a stored baseline snapshot and a fresh live
    snapshot. Returns ``[{field, label}]`` for each monitored field that changed
    (hours/services via ``diff_field``; the rest via normalized equality). Pure
    (unit-tested). ``has_voice_of_merchant`` is NOT a content change — it drives
    access status, not the change list."""
    baseline = baseline or {}
    live = live or {}
    changes: list[dict] = []
    for field in MONITOR_FIELDS:
        b = baseline.get(field)
        l = live.get(field)
        if field in ("hours", "services"):
            changed = diff_field(field, b, l)
        else:
            changed = _norm(b) != _norm(l)
        if changed:
            changes.append({"field": field, "label": _MONITOR_LABELS.get(field, field)})
    return changes


# ───────────────────────────────────────────────────────────────────────────
# Re-read-and-diff (Q3) — has the live field drifted since the draft snapshot?
# ───────────────────────────────────────────────────────────────────────────
def _norm(value) -> object:
    """Normalize a field value for order/whitespace-insensitive comparison."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in sorted(value.items()) if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def diff_field(field: str, snapshot, live) -> bool:
    """True if the live field value differs from the draft-time snapshot — the
    re-read-and-diff guard (Q3). Compares the field's stored internal shape
    (description string / hours dict / services list), order- and
    whitespace-normalized. Pure (unit-tested)."""
    if field == "services":
        # Compare only the editable identity of each service (label + category +
        # description), order-insensitive — a structured passthrough never drifts.
        return _services_key(snapshot) != _services_key(live)
    if field == "service_area":
        # Coverage is a SET of places (Google may re-order them on read-back), so
        # compare business type + region + the place-id set, order-insensitive.
        return _service_area_key(snapshot) != _service_area_key(live)
    return _norm(snapshot) != _norm(live)


def _service_area_key(value) -> tuple:
    value = value or {}
    pids = frozenset(
        (p.get("place_id") or p.get("name") or "").strip().lower()
        for p in (value.get("places") or [])
    )
    return (
        (value.get("business_type") or "").strip(),
        (value.get("region_code") or "").strip(),
        pids,
    )


def _services_key(services) -> set:
    key = set()
    for svc in services or []:
        if (svc.get("kind") or "free_form") == "structured":
            # Key on the serviceTypeId + description. A fresh pick carries the id
            # in ``service_type_id`` (``label`` is the human display name); a
            # live-parsed structured item carries it in both — so keying on the
            # id makes a picked service and its live read-back compare equal.
            # Description is included so a description-only edit is detected.
            sid = (svc.get("service_type_id") or svc.get("label") or "").strip().lower()
            key.add(("structured", sid, (svc.get("description") or "").strip()))
        else:
            key.add((
                "free_form",
                (svc.get("label") or "").strip().lower(),
                (svc.get("category_id") or "").strip(),
                (svc.get("description") or "").strip(),
            ))
    return key


# ───────────────────────────────────────────────────────────────────────────
# Error classification (reuses the GBP/GSC status extraction).
# ───────────────────────────────────────────────────────────────────────────
def extract_error(exc: Exception) -> tuple[Optional[int], str]:
    """(status_code, message) from a Google ``HttpError`` (or a test double with
    ``status_code``/``message``). Best-effort message from the error JSON body."""
    from services import gsc_service  # lazy

    code = gsc_service._extract_status_code(exc)
    message = ""
    content = getattr(exc, "content", None)
    if content:
        try:
            import json

            body = json.loads(content.decode() if isinstance(content, bytes) else content)
            message = ((body or {}).get("error") or {}).get("message", "") or ""
        except Exception:  # noqa: BLE001 — body may not be JSON
            message = str(content)[:300]
    if not message:
        message = getattr(exc, "message", "") or str(exc)
    return code, message


def classify_profile_error(status_code: Optional[int], message: str = "", field: str = "") -> str:
    """Map an HTTP status + message from a v1 get/patch to an actionable code the
    ErrorDetails registry renders. Pure (unit-tested)."""
    msg = (message or "").lower()
    if status_code == 403 and ("has not been used" in msg or "is disabled" in msg):
        return "gbp_api_not_enabled"
    if status_code == 429 or "resource_exhausted" in msg or "quota" in msg:
        return "gbp_quota_not_granted"
    if status_code in (401, 403):
        if field == "services" or "service" in msg or "canmodifyservicelist" in msg:
            return "cannot_modify_services"
        if "verif" in msg or "unverified" in msg:
            return "gbp_listing_unverified"
        return "gbp_listing_read_only"
    if status_code == 404:
        return "gbp_location_not_found"
    if status_code == 400:
        if field == "description" or "description" in msg:
            if "url" in msg or "link" in msg:
                return "description_contains_url"
            if "phone" in msg:
                return "description_contains_phone"
            if "750" in msg or "too long" in msg or "length" in msg:
                return "description_too_long"
        if field == "website" or "websiteuri" in msg or "website" in msg:
            return "invalid_website_url"
        if field == "labels" or "label" in msg:
            return "invalid_labels"
        if field == "more_hours" or "morehours" in msg or "hourstype" in msg:
            return "invalid_more_hours_type"
        if field == "service_area" or "servicearea" in msg or "place" in msg:
            return "invalid_service_area"
        if field == "open_info" or "openinfo" in msg or "openstatus" in msg:
            return "invalid_open_status"
        if field == "categories":
            return "invalid_category"
        if field == "attributes" or "attribute" in msg:
            return "invalid_attribute"
        if "category" in msg or "service" in msg:
            return "invalid_service_category"
        return "invalid_edit_content"
    return f"http_{status_code}" if status_code else "unknown_error"


# ───────────────────────────────────────────────────────────────────────────
# Live calls (synchronous; run via asyncio.to_thread from async runners).
# ───────────────────────────────────────────────────────────────────────────
def _info_client():
    """The v1 Business Information discovery client, via the same credential
    selection the auto-match reads use (OAuth preferred, SA fallback)."""
    from services import gbp_auth  # lazy — no google import at module load
    from services import gbp_locations_service as loc_svc

    return loc_svc._build("mybusinessbusinessinformation", gbp_auth.credentials())


def _raise(exc: Exception, field: str = "") -> None:
    code, message = extract_error(exc)
    detail = classify_profile_error(code, message, field)
    logger.info("gbp_profile_api.error", extra={"status": code, "code": detail, "field": field})
    raise HTTPException(status_code=502, detail=detail)


def get_location(name: str, read_mask: str = READ_MASK) -> dict:
    """v1 ``locations.get`` — the raw Location dict (the caller parses it).
    ``name`` is ``locations/{id}``. Raises a classified HTTPException on failure."""
    try:
        return _info_client().locations().get(name=name, readMask=read_mask).execute()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — google HttpError / transport
        _raise(exc)


def patch_location(name: str, body: dict, update_mask: str, field: str = "") -> dict:
    """v1 ``locations.patch`` — writes exactly the fields named in ``update_mask``
    (anything else is untouched). Returns the updated Location dict. Raises a
    classified HTTPException on failure (``field`` sharpens the code)."""
    try:
        return (
            _info_client().locations()
            .patch(name=name, updateMask=update_mask, body=body)
            .execute()
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        _raise(exc, field=field)


# ── attributes (separate getAttributes / updateAttributes endpoint pair) ─────
def attributes_name(location_name: str) -> str:
    """The v1 ``Attributes`` resource name for a location ('locations/{id}' →
    'locations/{id}/attributes')."""
    base = (location_name or "").strip().rstrip("/")
    return base + "/attributes" if not base.endswith("/attributes") else base


def get_attributes(name: str) -> dict:
    """v1 ``locations.getAttributes`` — the raw ``Attributes`` resource for a
    location. ``name`` is ``locations/{id}/attributes``. Raises a classified
    HTTPException on failure."""
    try:
        return _info_client().locations().getAttributes(name=name).execute()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        _raise(exc, field="attributes")


def update_attributes(name: str, body: dict, update_mask: str, field: str = "attributes") -> dict:
    """v1 ``locations.updateAttributes`` — writes exactly the attributes named in
    ``update_mask`` (comma-joined ``attributes/{id}`` resource names). ``name`` is
    ``locations/{id}/attributes``. Returns the updated ``Attributes`` resource.
    Raises a classified HTTPException on failure."""
    try:
        return (
            _info_client().locations()
            .updateAttributes(name=name, updateMask=update_mask, body=body)
            .execute()
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        _raise(exc, field=field)


def list_available_attributes(
    location_name: str, region_code: str = "US", language_code: str = "en",
    show_all: bool = False, limit: int = 200,
) -> dict:
    """v1 ``attributes.list`` — the attributes AVAILABLE for a listing (scoped to
    its primary category + region), the picker's source. Returns the raw response
    (``parse_attribute_metadata`` shapes it). Raises a classified HTTPException on
    failure."""
    try:
        return (
            _info_client().attributes()
            .list(
                parent=location_name, regionCode=region_code, languageCode=language_code,
                showAll=show_all, pageSize=max(1, min(limit, 500)),
            )
            .execute()
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        _raise(exc, field="attributes")

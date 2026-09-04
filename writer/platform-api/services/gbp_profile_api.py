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
``serviceItems``/``freeFormServiceItem`` shape, and the ``metadata`` pending-edit
fields against
``developers.google.com/my-business/reference/businessinformation/rest/v1/accounts.locations``.
The one live-shape constant most likely to need a tweak is
``_FREEFORM_CATEGORY_FIELD`` below.

See: docs/modules/gbp-profile-editor-prd-v1_0.md §2, §7.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# The v1 readMask for the three editable fields + the context they need
# (categories to attach free-form services to; metadata for editability/pending
# state). categories is REQUIRED so the services editor can offer valid ids.
READ_MASK = (
    "name,title,profile.description,regularHours,specialHours,serviceItems,"
    "categories,metadata"
)

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
    periods: list[dict] = []
    for row in regular_rows or []:
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
            # close ≤ open → the period runs past midnight into the next day.
            close_day = open_day
            if _minutes(close_t) <= _minutes(open_t):
                close_day = DAY_ENUM[(day + 1) % 7]
            periods.append({
                "openDay": open_day, "openTime": open_t,
                "closeDay": close_day, "closeTime": close_t,
            })

    body: dict = {"regularHours": {"periods": periods}}
    mask = "regularHours"
    if special_rows is not None:
        body["specialHours"] = {"specialHourPeriods": _build_special_periods(special_rows)}
        mask = "regularHours,specialHours"
    return body, mask


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

    Each service is either a free-form entry
    ``{kind: 'free_form', label, description?, category_id}`` — the editable kind,
    v1 free-form (decision Q8) — or a passthrough ``{kind: 'structured', raw:
    <original serviceItem dict>}`` preserving a structured item the listing
    already has (so a free-form-only patch never clobbers structured services).

    ``label`` and ``category_id`` are required on every free-form service; when
    ``allowed_categories`` is given, ``category_id`` must be one of the listing's
    categories (else ValueError ``invalid_service_category:<label>``). Duplicate
    free-form labels (case-insensitive) are dropped. Pure (unit-tested)."""
    items: list[dict] = []
    seen: set[str] = set()
    for svc in services or []:
        kind = (svc.get("kind") or "free_form").strip()
        if kind == "structured":
            raw = svc.get("raw")
            if isinstance(raw, dict):
                items.append(raw)
            continue
        label = (svc.get("label") or "").strip()
        if not label:
            raise ValueError("service_label_required")
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
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


def parse_hours(loc: dict) -> dict:
    """v1 regularHours/specialHours → our internal ``{regular: [rows], special:
    [rows]}``. Groups periods by open day into per-day rows (open_24 detected).
    Pure."""
    periods = ((loc or {}).get("regularHours") or {}).get("periods") or []
    by_day: dict[int, dict] = {}
    for p in periods:
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
    regular = [by_day[d] for d in sorted(by_day)]
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
            out.append({
                "kind": "structured",
                "label": structured.get("serviceTypeId") or "",
                "description": structured.get("description") or "",
                "raw": item,
            })
    return out


def parse_metadata(loc: dict) -> dict:
    """The editability/pending flags the UI needs from Location.metadata (output
    only). ``can_modify_service_list`` gates the services editor; ``has_pending_edits``
    tells the user a prior edit is still settling. Pure."""
    meta = (loc or {}).get("metadata") or {}
    return {
        "has_pending_edits": bool(meta.get("hasPendingEdits")),
        "can_modify_service_list": meta.get("canModifyServiceList"),
        "can_operate_local_post": meta.get("canOperateLocalPost"),
        "place_id": meta.get("placeId"),
        "maps_uri": meta.get("mapsUri"),
    }


def parse_location_fields(loc: dict) -> dict:
    """Read a v1 Location into everything the editor + drafters need. Pure."""
    loc = loc or {}
    return {
        "name": loc.get("name"),
        "title": loc.get("title"),
        "description": (loc.get("profile") or {}).get("description") or "",
        "hours": parse_hours(loc),
        "services": parse_services(loc),
        "categories": parse_categories(loc),
        "metadata": parse_metadata(loc),
    }


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
    return _norm(snapshot) != _norm(live)


def _services_key(services) -> set:
    key = set()
    for svc in services or []:
        if (svc.get("kind") or "free_form") == "structured":
            key.add(("structured", (svc.get("label") or "").strip().lower()))
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

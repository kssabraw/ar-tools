"""GBP Profile Audit — the user-facing Audit tab of the GBP module.

Two halves (owner: "both, in one Audit tab"):

1. **Profile health / optimization audit** — score the client's LIVE Google
   Business Profile (read via the v1 Business Information API, the same wider
   ``MONITOR_READ_MASK`` the monitor uses) and list what's missing or weak, each
   with a fix. It REUSES the deterministic ``gbp_audit.audit`` engine (which also
   feeds the Action Plan + strategist) for the competitor-relative parts
   (category gaps, review deficit vs the competitor median, description quality),
   but overrides its inputs with the AUTHORITATIVE live reads (description,
   categories, website, phone, hours) rather than the captured ``clients.gbp``
   snapshot, and adds live-only checks (services listed, marked open, verified /
   Voice of Merchant).

2. **Change audit trail** — a chronological history of the team's own applied
   edits (``gbp_profile_edits``) merged with the outside / Google changes the
   monitor detected (``gbp_profile_change_log``).

The scoring + adaptation + recommendation builders are pure (unit-tested); the
live read + DB gather live in ``run_audit`` / ``get_history``. Read-only — the
audit never writes to the listing.

See docs/modules/gbp-profile-editor-prd-v1_0.md.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import HTTPException

from db.supabase_client import get_supabase
from services import gbp_audit
from services import gbp_profile_api as api
from services import gbp_profile_service as svc

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────────────
# Pure: live Location → the client_gbp shape gbp_audit.audit expects
# ───────────────────────────────────────────────────────────────────────────
def _address_str(address: dict) -> str:
    """A comma-joined address string for the audit's location-term extraction."""
    a = address or {}
    parts = [*(a.get("lines") or []), a.get("locality"), a.get("region"),
             a.get("postal_code"), a.get("country")]
    return ", ".join(p for p in parts if p)


def build_live_fields(parsed: dict, snapshot: dict) -> dict:
    """Normalize the parsed live Location (``parse_location_fields``) + monitor
    snapshot into the fields the audit needs. Pure."""
    return {
        "description": parsed.get("description") or "",
        "categories": parsed.get("categories") or [],  # [{id, name}]
        "services": parsed.get("services") or [],
        "hours": parsed.get("hours") or {},
        "phone": (snapshot or {}).get("phone") or {},
        "website": (snapshot or {}).get("website") or "",
        "address_str": _address_str((snapshot or {}).get("address") or {}),
        "open_status": (snapshot or {}).get("open_status") or "",
        "has_voice_of_merchant": (snapshot or {}).get("has_voice_of_merchant"),
    }


def _adapt_for_engine(live: dict, captured: dict) -> dict:
    """Map the live fields onto the ``client_gbp`` shape ``gbp_audit.audit`` reads,
    overriding the captured snapshot with the authoritative live values and
    keeping captured-only fields (photo / review count / service areas — not in
    the v1 read). Pure."""
    cat_names = [c.get("name") for c in (live.get("categories") or []) if c.get("name")]
    has_hours = bool((live.get("hours") or {}).get("regular"))
    captured = captured or {}
    return {
        # Live-authoritative:
        "description": live.get("description") or "",
        "gbp_category": cat_names[0] if cat_names else None,
        "gbp_categories": cat_names,
        "website": live.get("website") or "",
        "phone": (live.get("phone") or {}).get("primary") or "",
        "hours": "set" if has_hours else "",
        "address": live.get("address_str") or captured.get("address") or "",
        # Captured-only (media + reviews aren't in the Business Information read):
        "photo": captured.get("photo"),
        "gbp_review_count": captured.get("gbp_review_count") or captured.get("review_count"),
        "service_area_places": captured.get("service_area_places"),
    }


# Severity ranks for ordering the recommendations (highest first).
_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
# Which failed checks are editable in OUR Profile editor vs only in Google's
# dashboard (media, categories, verification).
_PROFILE_EDITABLE = {"description", "services", "hours", "website", "phone"}


def _band(score: Optional[int]) -> Optional[str]:
    if score is None:
        return None
    if score >= 85:
        return "strong"
    if score >= 60:
        return "fair"
    return "needs_work"


def audit_live(live: dict, captured: dict, competitors: list[dict]) -> dict:
    """The full profile-health audit from the LIVE listing + captured competitor
    context. Returns ``{score, band, checks, recommendations, category_gaps,
    review_gap, description_quality, competitor_count}``. Pure (unit-tested)."""
    base = gbp_audit.audit(_adapt_for_engine(live, captured), competitors)
    checks = list(base["checks"])

    # Live-only checks the captured-snapshot audit can't see.
    services = live.get("services") or []
    checks.append({"key": "services", "label": "Services listed", "ok": len(services) > 0,
                   "detail": f"{len(services)} listed" if services else "none"})
    open_status = (live.get("open_status") or "").upper()
    checks.append({"key": "open", "label": "Marked open on Google",
                   "ok": open_status in ("", "OPEN"),
                   "detail": open_status.replace("_", " ").title() if open_status else "unknown"})
    vom = live.get("has_voice_of_merchant")
    checks.append({"key": "voice_of_merchant", "label": "Verified (Voice of Merchant)",
                   "ok": vom is not False,
                   "detail": "verified" if vom else ("NOT verified" if vom is False else "unknown")})

    passed = sum(1 for c in checks if c["ok"])
    score = round(passed / len(checks) * 100) if checks else None
    recs = _recommendations(checks, base)
    return {
        "score": score,
        "band": _band(score),
        "checks": checks,
        "recommendations": recs,
        "category_gaps": base.get("category_gaps") or [],
        "review_gap": base.get("review_gap"),
        "description_quality": base.get("description_quality"),
        "competitor_count": base.get("competitor_count", 0),
    }


_CHECK_RECS = {
    # key: (severity, title, detail, target)
    "voice_of_merchant": ("critical", "Listing isn't verified",
                          "Google shows this profile isn't verified (Voice of Merchant lost) — it may be suspended. Check the Google Business Profile dashboard.", "dashboard"),
    "open": ("high", "Listing marked closed",
             "Google shows the business as closed. If that's wrong, reopen it in the GBP dashboard.", "dashboard"),
    "primary_category": ("high", "Set a primary category",
                         "No primary category is set — it's the biggest local-ranking signal. Set it in the GBP dashboard.", "dashboard"),
    "description": ("high", "Add a business description",
                    "The profile has no (or a very thin) description. Add one in the Profile editor.", "profile"),
    "services": ("high", "Add services",
                 "No services are listed. Add the services this business offers in the Profile editor.", "profile"),
    "hours": ("high", "Set opening hours",
              "No opening hours are set. Add them in the Profile editor.", "profile"),
    "website": ("medium", "Link a website",
                "No website is linked on the profile. Add it in the Profile editor.", "profile"),
    "phone": ("medium", "Add a phone number",
              "No phone number is on the profile. Add it in the Profile editor.", "profile"),
    "photo": ("medium", "Add photos",
              "The profile has no photos. Add some in the GBP dashboard (photos aren't editable here).", "dashboard"),
    "secondary_categories": ("low", "Add more categories",
                             "Only one category is set. Additional relevant categories can widen reach.", "dashboard"),
}


def _recommendations(checks: list[dict], base: dict) -> list[dict]:
    """Build the ordered, deduped recommendation list from failed checks + the
    competitor-relative gaps. Pure."""
    recs: list[dict] = []
    failed = {c["key"] for c in checks if not c["ok"]}
    for key in failed:
        meta = _CHECK_RECS.get(key)
        if not meta:
            continue
        sev, title, detail, target = meta
        recs.append({"key": key, "severity": sev, "title": title, "detail": detail, "target": target})

    # Description present but weak (only when the completeness check passed).
    dq = base.get("description_quality") or {}
    if "description" not in failed and dq.get("issues"):
        labels = {"too_short": "it's short", "missing_service_keyword": "it doesn't name the core service",
                  "missing_location": "it doesn't mention the location"}
        why = ", ".join(labels.get(i, i) for i in dq["issues"])
        recs.append({"key": "description_quality", "severity": "medium",
                     "title": "Improve the description",
                     "detail": f"The description is present but weak — {why}. Strengthen it in the Profile editor.",
                     "target": "profile"})

    # Review deficit vs the competitor median.
    rg = base.get("review_gap")
    if rg:
        recs.append({"key": "reviews", "severity": "medium", "title": "Get more reviews",
                     "detail": (f"{rg['client']} reviews vs a competitor median of {rg['competitor_median']} "
                                f"— about {rg['deficit']} behind. More reviews lift local-pack presence."),
                     "target": "reviews"})

    # Category gaps competitors carry.
    cg = base.get("category_gaps") or []
    if cg:
        recs.append({"key": "category_gaps", "severity": "low", "title": "Consider more categories",
                     "detail": "Categories most local-pack competitors carry that this profile doesn't: "
                               + ", ".join(cg) + ".",
                     "target": "dashboard"})

    recs.sort(key=lambda r: _SEV_RANK.get(r["severity"], 9))
    return recs


# ───────────────────────────────────────────────────────────────────────────
# Impure: run the audit (live read + DB gather)
# ───────────────────────────────────────────────────────────────────────────
def _captured_gbp(client_id: str) -> dict:
    try:
        rows = get_supabase().table("clients").select("gbp").eq("id", client_id).limit(1).execute().data
        return (rows[0].get("gbp") if rows else None) or {}
    except Exception as exc:  # noqa: BLE001 — best-effort captured context
        logger.info("gbp_profile_audit.captured_failed", extra={"error": str(exc)[:200]})
        return {}


def _competitors(client_id: str) -> list[dict]:
    try:
        from services import competitor_gbp  # lazy

        return competitor_gbp.latest_profiles(client_id) or []
    except Exception as exc:  # noqa: BLE001 — audit still runs without competitors
        logger.info("gbp_profile_audit.competitors_failed", extra={"error": str(exc)[:200]})
        return []


async def run_audit(client_id: str, location_row_id: str) -> dict:
    """Read the live listing + captured competitor context and return the profile
    health audit. On an access-lost read (suspended / removed) the audit leads
    with that; a transient read error raises so the UI can retry."""
    svc._assert_enabled()
    location = svc._location(location_row_id, client_id)
    name = svc._location_name(location)
    try:
        loc = await asyncio.to_thread(api.get_location, name, api.MONITOR_READ_MASK)
    except HTTPException as exc:
        access = api.access_status_for_code(str(exc.detail or ""))
        if access is None:
            raise  # transient — let the UI surface + retry
        return {
            "access_status": access, "score": None, "band": None, "checks": [],
            "recommendations": [{
                "key": "voice_of_merchant", "severity": "critical",
                "title": "Listing can't be read",
                "detail": ("Google won't return this listing to our connected account "
                           "(suspended, removed, or access revoked). Check the GBP dashboard / connection."),
                "target": "dashboard",
            }],
            "category_gaps": [], "review_gap": None, "description_quality": None, "competitor_count": 0,
        }
    parsed = api.parse_location_fields(loc)
    snapshot = api.monitor_snapshot(loc)
    live = build_live_fields(parsed, snapshot)
    result = audit_live(live, _captured_gbp(client_id), _competitors(client_id))
    result["access_status"] = api.snapshot_access_status(snapshot)
    return result


# ───────────────────────────────────────────────────────────────────────────
# Change audit trail (own edits + monitor-detected outside changes)
# ───────────────────────────────────────────────────────────────────────────
def log_change(client_id: str, location_row_id: str, kind: str, detail: Optional[dict] = None) -> None:
    """Append a monitor-detected event to the change log. Best-effort — never
    raises (called from the monitor). ``kind`` ∈ outside_change / suspended /
    access_lost / restored."""
    try:
        get_supabase().table("gbp_profile_change_log").insert({
            "client_id": client_id, "location_row_id": location_row_id,
            "kind": kind, "detail": detail,
        }).execute()
    except Exception as exc:  # noqa: BLE001
        logger.info("gbp_profile_audit.log_change_failed", extra={"error": str(exc)[:200]})


_FIELD_LABELS = {
    "title": "business name", "description": "description", "categories": "categories",
    "phone": "phone number", "website": "website", "address": "address",
    "hours": "hours", "services": "services", "open_status": "open/closed status",
}


def merge_history(edits: list[dict], changes: list[dict], names: dict, limit: int) -> list[dict]:
    """Merge the team's own applied edits with monitor-detected outside changes
    into one reverse-chronological trail. Pure (unit-tested)."""
    events: list[dict] = []
    for e in edits or []:
        at = e.get("applied_at") or e.get("updated_at") or e.get("created_at")
        events.append({
            "at": at, "source": "team", "kind": "edit",
            "field": e.get("field"),
            "detail": f"{e.get('source') or 'manual'} edit — {e.get('status')}",
            "who": names.get(e.get("created_by")) if e.get("created_by") else None,
            "edit_source": e.get("source"), "status": e.get("status"),
        })
    for c in changes or []:
        kind = c.get("kind")
        if kind == "outside_change":
            fields = ((c.get("detail") or {}).get("fields")) or []
            label = ", ".join(_FIELD_LABELS.get(f, f) for f in fields) or "profile"
            detail = f"Changed outside the tool: {label}"
        elif kind == "suspended":
            detail = "Listing appears suspended (Voice of Merchant lost)"
        elif kind == "access_lost":
            detail = "Listing became unreadable by our account"
        else:  # restored
            detail = "Access restored"
        events.append({
            "at": c.get("detected_at"), "source": "external", "kind": kind,
            "field": None, "detail": detail, "who": None,
        })
    events.sort(key=lambda x: x.get("at") or "", reverse=True)
    return events[:limit]


def get_history(client_id: str, location_row_id: str, limit: int = 50) -> list[dict]:
    """The change trail for one location: team edits + outside changes, newest
    first."""
    svc._assert_enabled()
    svc._location(location_row_id, client_id)  # ownership check
    supabase = get_supabase()
    edits = (
        supabase.table("gbp_profile_edits")
        .select("field, source, status, created_by, applied_at, updated_at, created_at")
        .eq("client_id", client_id).eq("location_row_id", location_row_id)
        .in_("status", ["applied", "pending_review", "rejected", "live_changed"])
        .order("updated_at", desc=True).limit(limit).execute().data or []
    )
    changes = (
        supabase.table("gbp_profile_change_log")
        .select("kind, detail, detected_at")
        .eq("location_row_id", location_row_id)
        .order("detected_at", desc=True).limit(limit).execute().data or []
    )
    names = _resolve_names([e.get("created_by") for e in edits if e.get("created_by")])
    return merge_history(edits, changes, names, limit)


def _resolve_names(ids: list[str]) -> dict:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    try:
        rows = get_supabase().table("profiles").select("id, full_name").in_("id", ids).execute().data or []
        return {r["id"]: r.get("full_name") for r in rows}
    except Exception:  # noqa: BLE001 — names are a nicety
        return {}

"""Auto-run a prospect's reports when it is saved (create + edit).

A prospect exists to run quick reports *with a client during a meeting*, so
saving one should kick off the analyses that need no manual setup rather than
making someone open each tool and configure it:

  - **Organic** (Domain Intelligence overview) — from the website alone.
  - **AI Visibility** ("aio") — a brand-presence scan on the GBP primary
    category (geo-qualified with the client's city so a *local* prospect can
    actually surface), falling back to the business name when there's no GBP.
  - **Maps** (local-pack geo-grid) — only when a GBP is linked: the GBP supplies
    the grid centre + place id, and its primary category is the scan keyword.

Design decisions (see the prospects feature notes):

  - The keyword for Maps + AI is the **GBP primary category** — the only source
    that needs zero setup, which is why Maps is gated on a GBP being entered.
  - Everything is **best-effort**: a failure in one analysis never blocks the
    save or the other analyses.
  - On an **edit** we only re-fire the analysis whose input actually changed
    (organic ← website change; Maps + AI ← GBP change), so routine edits don't
    re-spend on the paid Maps/AI scans. On create everything applicable fires.
  - This is **prospect-only** — it is never called for a real client, so it
    can't auto-spend on paid scans for the whole book.
"""
from __future__ import annotations

import logging
from typing import Optional

from db.supabase_client import get_supabase

logger = logging.getLogger("prospect_analyses")

# Bound the paid Maps geo-grid + AI scan to a single keyword per prospect.
_DEFAULT_RADIUS_MILES = 5


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def primary_category(gbp: Optional[dict]) -> Optional[str]:
    """The GBP's primary category, or the first listed one. None when absent."""
    if not isinstance(gbp, dict):
        return None
    cat = (gbp.get("gbp_category") or "").strip()
    if cat:
        return cat
    for c in gbp.get("gbp_categories") or []:
        if isinstance(c, str) and c.strip():
            return c.strip()
    return None


def city_of(client: dict) -> Optional[str]:
    """A human city string for geo-qualifying the AI keyword. Uses the client's
    business_location (typically "City, ST" — the locality before the comma)."""
    loc = (client.get("business_location") or "").strip()
    if not loc:
        return None
    return loc.split(",")[0].strip() or None


def gbp_center(gbp: Optional[dict]) -> tuple[Optional[float], Optional[float]]:
    """Best-effort (lat, lng) from the stored GBP payload."""
    if not isinstance(gbp, dict):
        return None, None
    lat = gbp.get("latitude")
    lng = gbp.get("longitude")
    try:
        return (
            float(lat) if lat is not None else None,
            float(lng) if lng is not None else None,
        )
    except (TypeError, ValueError):
        return None, None


def maps_keyword(gbp: Optional[dict]) -> Optional[str]:
    """The bare primary category — the geo-grid itself supplies the location."""
    return primary_category(gbp)


def ai_keyword(gbp: Optional[dict], name: str, city: Optional[str]) -> Optional[str]:
    """The AI-visibility scan term: "<category> <city>" when both are known (so a
    local prospect can plausibly surface), else the bare category, else the
    business name (a bare brand-presence check)."""
    cat = primary_category(gbp)
    if cat:
        return f"{cat} {city}".strip() if city else cat
    return (name or "").strip() or None


# ---------------------------------------------------------------------------
# Per-analysis runners (impure, best-effort — never raise)
# ---------------------------------------------------------------------------
def _run_organic(client: dict, user_id: Optional[str]) -> Optional[str]:
    """Enqueue the Domain Intelligence overview from the website. Returns a
    short status token for the summary."""
    from services import domain_intel

    domain = domain_intel.normalize_domain(client.get("website_url"))
    if not domain:
        return "skipped_no_website"
    try:
        domain_intel.enqueue_domain_overview(
            client["id"], domain, role="prospect", user_id=user_id, force=True
        )
        return "enqueued"
    except Exception as exc:  # noqa: BLE001 — best-effort, must never block the save
        logger.warning(
            "prospect_analyses.organic_failed",
            extra={"client_id": client["id"], "error": str(exc)},
        )
        return "error"


def _run_ai(client: dict, user_id: Optional[str]) -> Optional[str]:
    """Seed a brand keyword (from the GBP category / city / name) and enqueue an
    AI-visibility scan across all six engines."""
    from fastapi import HTTPException

    from services import brand_scan, brand_service

    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else None
    kw = ai_keyword(gbp, client.get("name") or "", city_of(client))
    if not kw:
        return "skipped_no_keyword"
    try:
        try:
            row = brand_service.add_keyword(client["id"], kw, category=primary_category(gbp))
            kw_id = row["id"]
        except HTTPException as exc:
            # Already tracked (409) — reuse the existing keyword row.
            if exc.status_code != 409:
                raise
            existing = (
                get_supabase().table("brand_tracked_keywords")
                .select("id").eq("client_id", client["id"]).ilike("keyword", kw)
                .limit(1).execute()
            ).data
            if not existing:
                return "error"
            kw_id = existing[0]["id"]
        brand_scan.enqueue_brand_scan(
            client["id"], [kw_id], list(brand_scan.ENGINE_ORDER),
            include_competitors=False, user_id=user_id,
        )
        return "enqueued"
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning(
            "prospect_analyses.ai_failed",
            extra={"client_id": client["id"], "error": str(exc)},
        )
        return "error"


def _run_maps(client: dict) -> Optional[str]:
    """Bootstrap a geo-grid config from the GBP (place id + centre), seed the
    category keyword, and enqueue a one-off (trigger='manual') scan. Requires a
    GBP place id + coordinates; skips cleanly otherwise."""
    from services import local_dominator

    gbp = client.get("gbp") if isinstance(client.get("gbp"), dict) else None
    place_id = client.get("gbp_place_id")
    lat, lng = gbp_center(gbp)
    kw = maps_keyword(gbp)
    if not place_id or lat is None or lng is None:
        return "skipped_no_gbp_location"
    if not kw:
        return "skipped_no_keyword"
    supabase = get_supabase()
    try:
        # Bootstrap the grid config from the GBP if one isn't configured yet
        # (mirrors the Maps Setup prefill). upsert keeps an existing config.
        existing_cfg = (
            supabase.table("maps_scan_configs").select("client_id")
            .eq("client_id", client["id"]).limit(1).execute()
        ).data
        if not existing_cfg:
            supabase.table("maps_scan_configs").upsert(
                {
                    "client_id": client["id"],
                    "google_place_id": place_id,
                    "business_name": client.get("name"),
                    "center_lat": lat,
                    "center_lng": lng,
                    "radius_miles": _DEFAULT_RADIUS_MILES,
                },
                on_conflict="client_id",
            ).execute()
        # Seed the category keyword (unique on client_id+keyword; dupes ignored).
        supabase.table("maps_keywords").upsert(
            {"client_id": client["id"], "keyword": kw},
            on_conflict="client_id,keyword", ignore_duplicates=True,
        ).execute()
        # One-off scan: trigger='manual' keeps it out of the reporting series and
        # raises no alerts (right for a prospect). Deduped against in-flight scans.
        local_dominator.enqueue_maps_scan(client["id"], trigger="manual")
        return "enqueued"
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning(
            "prospect_analyses.maps_failed",
            extra={"client_id": client["id"], "error": str(exc)},
        )
        return "error"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def run_prospect_analyses(
    client: dict,
    user_id: Optional[str],
    *,
    is_create: bool,
    website_changed: bool = False,
    gbp_changed: bool = False,
) -> dict:
    """Fire the applicable prospect analyses on save. Best-effort throughout.

    - Organic runs on create, or when the website changed.
    - AI + Maps run on create, or when the GBP changed (their keyword + Maps
      centre come from the GBP). Maps additionally needs GBP coordinates.

    Returns a summary of what each analysis did (for logging), e.g.
    ``{"organic": "enqueued", "ai": "enqueued", "maps": "skipped_no_gbp_location"}``.
    """
    summary: dict = {}
    if is_create or website_changed:
        summary["organic"] = _run_organic(client, user_id)
    if is_create or gbp_changed:
        summary["ai"] = _run_ai(client, user_id)
        summary["maps"] = _run_maps(client)
    logger.info(
        "prospect_analyses_run",
        extra={"client_id": client.get("id"), "summary": summary},
    )
    return summary

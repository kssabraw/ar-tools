"""LeadOff live-GBP competitor pins — persist + read (owner request 2026-08-21).

The app-owned store of the real competitor GBP locations that scout/tryout
capture from the live Maps SERP (see leadoff_brand.map_pins_from_items). Keyed
by the scanner market (city_id, category_id); a recapture replaces the market's
prior field. Read by leadoff_proximity for the market map — DELIBERATELY
separate from public.competitor_locations, whose Census pins feed the board
grade (leadoff_proximity.market_proximity_score); these live pins are a
display/advice layer only, so scouting never shifts a grade.

Recapture is **insert-then-delete-stale**, keyed on a per-batch timestamp: the
fresh rows are inserted first (stamped with the batch ts), then the market's
older rows are deleted. A failed insert therefore leaves the previous field
intact (no delete-then-insert data loss), and a whole tryout's categories are
written in one insert + one delete instead of 2×N round-trips.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_PIN_COLS = ("rank_position", "place_id", "business_name", "domain",
             "rating", "review_count", "lat", "lng")


def _rows_for(source: str, city_id: int, category_id: str,
              pins: list[dict[str, Any]], batch_ts: str) -> list[dict[str, Any]]:
    return [{"source": source, "city_id": city_id, "category_id": category_id,
             "captured_at": batch_ts,
             **{c: p.get(c) for c in _PIN_COLS}}
            for p in (pins or [])
            if p.get("lat") is not None and p.get("lng") is not None]


def persist_gbp_pins_batch(source: str, city_id: int,
                           by_category: dict[str, list[dict[str, Any]]]) -> int:
    """Replace the live-GBP field for one or more categories of a single market.
    Best-effort — a persistence failure must never fail the paid enrichment job
    that produced the pins. Returns the number of rows written.

    Insert-then-delete-stale: the new rows carry an explicit `captured_at` batch
    timestamp; the delete removes only this market's rows for the touched
    categories that are OLDER than the batch. So a failed insert keeps the prior
    field, and the delete never touches a row this batch just wrote (the stamp
    is client-side, immune to client/server clock skew). Categories not in
    `by_category` are left untouched.
    """
    from db.supabase_client import get_supabase

    if not city_id:
        return 0
    cats = [cid for cid in by_category if cid]
    if not cats:
        return 0
    batch_ts = datetime.now(timezone.utc).isoformat()
    all_rows: list[dict[str, Any]] = []
    for cid in cats:
        all_rows.extend(_rows_for(source, city_id, cid, by_category[cid], batch_ts))

    supabase = get_supabase()
    try:
        if all_rows:
            supabase.table("leadoff_gbp_pins").insert(all_rows).execute()
        # Drop the market's prior rows for these categories. Runs only after a
        # successful insert; guarded to strictly-older rows so a just-inserted
        # row (captured_at == batch_ts) is never removed.
        (supabase.table("leadoff_gbp_pins").delete()
         .eq("city_id", city_id).in_("category_id", cats)
         .lt("captured_at", batch_ts).execute())
        return len(all_rows)
    except Exception:
        logger.warning("leadoff_gbp_pins.persist_failed",
                       extra={"city_id": city_id, "categories": len(cats)},
                       exc_info=True)
        return 0


def persist_gbp_pins(source: str, city_id: int, category_id: str,
                     pins: list[dict[str, Any]]) -> int:
    """Single-market convenience over persist_gbp_pins_batch."""
    if not category_id:
        return 0
    return persist_gbp_pins_batch(source, city_id, {category_id: pins})


def read_gbp_pins(city_id: int, category_id: str) -> list[dict[str, Any]]:
    """This market's stored live-GBP pins (empty when never scouted/tried)."""
    from db.supabase_client import get_supabase

    return (get_supabase().table("leadoff_gbp_pins")
            .select("rank_position, place_id, business_name, domain, "
                    "rating, review_count, lat, lng")
            .eq("city_id", city_id).eq("category_id", category_id)
            .order("rank_position").execute().data or [])

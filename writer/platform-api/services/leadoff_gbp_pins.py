"""LeadOff live-GBP competitor pins — persist + read (owner request 2026-08-21).

The app-owned store of the real competitor GBP locations that scout/tryout
capture from the live Maps SERP (see leadoff_brand.map_pins_from_items). Keyed
by the scanner market (city_id, category_id); a recapture replaces the market's
prior field (delete-then-insert). Read by leadoff_proximity for the market map —
DELIBERATELY separate from public.competitor_locations, whose Census pins feed
the board grade (leadoff_proximity.market_proximity_score); these live pins are
a display/advice layer only, so scouting never shifts a grade.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PIN_COLS = ("rank_position", "place_id", "business_name", "domain",
             "rating", "review_count", "lat", "lng")


def persist_gbp_pins(source: str, city_id: int, category_id: str,
                     pins: list[dict[str, Any]]) -> int:
    """Replace this market's live-GBP field with `pins`. Best-effort — a
    persistence failure must never fail the paid enrichment job that produced
    the pins. Returns the number of rows written."""
    from db.supabase_client import get_supabase

    if not city_id or not category_id:
        return 0
    supabase = get_supabase()
    try:
        supabase.table("leadoff_gbp_pins").delete() \
            .eq("city_id", city_id).eq("category_id", category_id).execute()
        rows = [{"source": source, "city_id": city_id, "category_id": category_id,
                 **{c: p.get(c) for c in _PIN_COLS}}
                for p in (pins or [])
                if p.get("lat") is not None and p.get("lng") is not None]
        if rows:
            supabase.table("leadoff_gbp_pins").insert(rows).execute()
        return len(rows)
    except Exception:
        logger.warning("leadoff_gbp_pins.persist_failed",
                       extra={"city_id": city_id, "category_id": category_id},
                       exc_info=True)
        return 0


def read_gbp_pins(city_id: int, category_id: str) -> list[dict[str, Any]]:
    """This market's stored live-GBP pins (empty when never scouted/tried)."""
    from db.supabase_client import get_supabase

    return (get_supabase().table("leadoff_gbp_pins")
            .select("rank_position, place_id, business_name, domain, "
                    "rating, review_count, lat, lng")
            .eq("city_id", city_id).eq("category_id", category_id)
            .order("rank_position").execute().data or [])

"""LeadOff proximity — the Distance pillar's octant read (plan §2).

Computes, per market (city × category), where the competitive field is
physically anchored and where it is NOT: octant coverage (competitor count,
review-weighted prominence, distance-decayed defense), underserved octants,
suggested GBP placement pins along the weak bearings, and a 0-1
`proximity_opportunity`. Input is the geocoded competitor pin set recovered
by `leadoff_geocode` into public.competitor_locations ($0 Census path).

Spec: docs/modules/leadoff-proximity-plan-v1_0.md — method §1.2/§2, shared
vocabulary with the post-client geo-grid (`maps_octants.dest_point`,
octants, weak zones). Context signal only — NEVER a grade input (the
no-frankenscore rule); pre-client proximity is a forecast the geo-grid
later verifies.

Honesty guards baked in (plan §1.3 + §5 tradeoffs):
  * `thin_data` below `min_pins` — no verdict off a handful of pins (same
    discipline as the field-momentum floor).
  * The coverage note names the resolution limit: pins are Census
    street-centroids of the scanner's ranked field — an "empty" octant means
    no *ranked* competitor is anchored there, not that nobody serves it.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

from services.maps_octants import OCTANTS, dest_point

logger = logging.getLogger(__name__)

# Octant centre bearings (same compass vocabulary as maps_octants).
OCTANT_BEARINGS = {"N": 0, "NE": 45, "E": 90, "SE": 135,
                   "S": 180, "SW": 225, "W": 270, "NW": 315}

_MILES_PER_METER = 1 / 1609.344
_DECAY_MILES = 2.0          # 1/(1+d/2mi) — the §1.2 prototype's decay
_MAX_PLACEMENT_PINS = 2     # suggest at most the two weakest bearings


# ── Pure core (unit-tested) ───────────────────────────────────────────────────

def bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, 0-360."""
    f1, f2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    y = math.sin(dl) * math.cos(f2)
    x = math.cos(f1) * math.sin(f2) - math.sin(f1) * math.cos(f2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    s = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(s)) * _MILES_PER_METER


def octant_of(bearing: float) -> str:
    """Compass octant for a bearing (N spans 337.5-22.5, then 45° buckets)."""
    return OCTANTS[int(((bearing + 22.5) % 360) // 45)]


def build_octant_coverage(center_lat: float, center_lng: float,
                          pins: list[dict[str, Any]],
                          radius_miles: float) -> dict[str, Any]:
    """Per-octant coverage from competitor pins (§1.2 formula).

    defense = Σ max(reviews, 1) × 1/(1 + distance_mi/2) over the octant's
    pins — review-weighted prominence, distance-decayed toward the centre.
    Pins beyond `radius_miles` are excluded (geocode noise / other-metro
    strays); pins at the exact centre (distance 0) still land in an octant
    via their bearing, which is fine at street-centroid resolution.
    """
    per = {o: {"octant": o, "count": 0, "reviews": 0, "defense": 0.0,
               "anchors": []} for o in OCTANTS}
    used = skipped = 0
    for p in pins:
        lat, lng = p.get("lat"), p.get("lng")
        if lat is None or lng is None:
            continue
        d = haversine_miles(center_lat, center_lng, lat, lng)
        if d > radius_miles:
            skipped += 1
            continue
        used += 1
        o = octant_of(bearing_deg(center_lat, center_lng, lat, lng))
        reviews = int(p.get("review_count") or 0)
        cell = per[o]
        cell["count"] += 1
        cell["reviews"] += reviews
        cell["defense"] += max(reviews, 1) * (1 / (1 + d / _DECAY_MILES))
        cell["anchors"].append({"name": p.get("business_name"),
                                "reviews": reviews, "miles": round(d, 1)})
    # keep only the strongest few anchors per octant for display
    for cell in per.values():
        cell["anchors"] = sorted(cell["anchors"], key=lambda a: -a["reviews"])[:3]
        cell["defense"] = round(cell["defense"], 1)
    return {"octants": [per[o] for o in OCTANTS], "used": used, "skipped": skipped}


def underserved_octants(octants: list[dict[str, Any]],
                        weak_frac: float) -> list[str]:
    """Octants whose defense sits below `weak_frac` × the median *defended*
    octant (plan §2.2). The yardstick is the typical octant that HAS a field
    — a raw all-8 median goes to zero the moment the field concentrates in a
    minority of octants, which is exactly when the read matters most.
    All-zero markets return nothing — no field, no read."""
    nonzero = sorted(c["defense"] for c in octants if c["defense"] > 0)
    if not nonzero:
        return []
    n = len(nonzero)
    median = (nonzero[n // 2] if n % 2 else
              (nonzero[n // 2 - 1] + nonzero[n // 2]) / 2)
    cut = weak_frac * median
    weak = [c for c in octants if c["defense"] < cut]
    return [c["octant"] for c in sorted(weak, key=lambda c: c["defense"])]


def proximity_opportunity(octants: list[dict[str, Any]]) -> float:
    """0-1 share of the market's demand-space that is weakly defended:
    mean over octants of (1 − defense/max_defense). 0 when there is no
    field to be weak against (plan §2.4)."""
    top = max((c["defense"] for c in octants), default=0.0)
    if top <= 0:
        return 0.0
    return round(sum(1 - c["defense"] / top for c in octants) / len(octants), 3)


def placement_pins(center_lat: float, center_lng: float,
                   weak: list[str], radius_miles: float) -> list[dict[str, Any]]:
    """Suggested GBP pins along the weakest bearings — `maps_octants.dest_point`
    at ⅔ of the analysis radius (inside the demand area, away from the packed
    centre), same vocabulary as the geo-grid's hyper-local pin layer."""
    dist_m = (radius_miles * 2 / 3) / _MILES_PER_METER
    out = []
    for o in weak[:_MAX_PLACEMENT_PINS]:
        dp = dest_point(center_lat, center_lng, OCTANT_BEARINGS[o], dist_m)
        out.append({"octant": o, "lat": dp["lat"], "lng": dp["lng"],
                    "radius_mi": round(radius_miles * 2 / 3, 1),
                    "maps_url": f"https://www.google.com/maps?q={dp['lat']},{dp['lng']}"})
    return out


def build_proximity(center_lat: float, center_lng: float,
                    pins: list[dict[str, Any]], *,
                    radius_miles: float, min_pins: int,
                    weak_frac: float) -> dict[str, Any]:
    """The §2 payload from a pin list. Pure."""
    cov = build_octant_coverage(center_lat, center_lng, pins, radius_miles)
    octants = cov["octants"]
    top = max((c["defense"] for c in octants), default=0.0)
    for c in octants:
        c["bar_pct"] = round(100 * c["defense"] / top) if top > 0 else 0
    thin = cov["used"] < min_pins
    weak = [] if thin else underserved_octants(octants, weak_frac)
    return {
        "available": cov["used"] > 0,
        "thin_data": thin,
        "pins_used": cov["used"],
        "pins_out_of_radius": cov["skipped"],
        "radius_miles": radius_miles,
        "octants": octants,
        "underserved": weak,
        "placement": placement_pins(center_lat, center_lng, weak, radius_miles),
        "opportunity": 0.0 if thin else proximity_opportunity(octants),
        "note": ("Pins are Census street-centroids of the scanner's ranked "
                 "field — an empty octant means no ranked competitor is "
                 "anchored there, not that nobody serves it (plan §1.3). "
                 "Context only, never a grade input."),
    }


# ── Impure assembly (DB reads + optional zone naming) ─────────────────────────

def _city_center(city_id: int) -> Optional[tuple[float, float]]:
    from services.leadoff_db import get_leadoff_client
    rows = (get_leadoff_client().table("cities")
            .select("latitude, longitude").eq("city_id", city_id)
            .limit(1).execute().data or [])
    if not rows or rows[0].get("latitude") is None:
        return None
    return float(rows[0]["latitude"]), float(rows[0]["longitude"])


def _market_pins(city_id: int, category_id: str) -> list[dict[str, Any]]:
    from db.supabase_client import get_supabase
    return (get_supabase().table("competitor_locations")
            .select("business_name, review_count, lat, lng")
            .eq("city_id", city_id).eq("category_id", category_id)
            .not_.is_("lat", "null").execute().data or [])


async def market_proximity(city_id: int, category_id: str) -> dict[str, Any]:
    """The proximity read for one market. Degrades explicitly, never raises
    to the caller: no city coords / no geocoded pins → {available: False}."""
    from config import settings

    center = _city_center(city_id)
    if center is None:
        return {"available": False, "reason": "city_has_no_coordinates"}
    pins = _market_pins(city_id, category_id)
    if not pins:
        return {"available": False, "reason": "no_geocoded_competitors",
                "hint": ("This market's competitors were not in the imported "
                         "scan (e.g. a tryout market) or none geocoded.")}
    result = build_proximity(
        center[0], center[1], pins,
        radius_miles=settings.leadoff_proximity_radius_miles,
        min_pins=settings.leadoff_proximity_min_pins,
        weak_frac=settings.leadoff_proximity_weak_frac,
    )
    # Best-effort zone naming (plan §2.2/§2.3): label each suggested pin with
    # its nearest locality via the geo-grid's cached reverse geocoder. Passes
    # through unnamed when GOOGLE_MAPS_API_KEY is absent or the call fails.
    if result.get("placement"):
        try:
            from db.supabase_client import get_supabase
            from services.maps_geocode import reverse_geocode_points
            named = await reverse_geocode_points(result["placement"],
                                                 supabase=get_supabase())
            for pin, loc in zip(result["placement"], named):
                pin["locality"] = loc.get("city") or loc.get("admin_area")
        except Exception:
            logger.warning("leadoff_proximity.naming_failed", exc_info=True)
    return result

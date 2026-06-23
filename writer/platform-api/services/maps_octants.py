"""Hyper-local GBP pin selection by compass octant (faithful port).

A Python port of an n8n "Code node" that selects up to four (or two) hyper-local
GBP pin coordinates in the *weakest* compass octants of a geo-grid heatmap. The
logic — octant weakness ranking, WEAK/MED classification, edge-spread bearings,
the per-rule behaviours ("4-octants" / "2-far-apart" / "none"), external weak
overrides, and all fallbacks — mirrors the original JavaScript exactly, down to
the rounding and the human-readable summaries.

Pure (no I/O), stdlib ``math`` only. Behaviour is intentionally NOT "improved"
relative to the source — match it.
"""

from __future__ import annotations

import functools
import math

# --- Tunables (kept identical to the JS source) ----------------------------
EDGE_SPREAD_DEG = 10
MIN_DISTANCE_M = 1609
PREFER_OUTER_RINGS = True
USE_SECTOR_WEAKNESS = True
ALLOW_MED_IF_INSUFFICIENT = True
PREFERRED_OCTANTS_COUNT = 3
REQUIRE_DIFFERENT_OCTANTS = True
AVOID_SAME_SECTOR_WHEN_POSSIBLE = True

_SECTOR_BEARING = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
OCTANTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
VALID_OCTANTS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

_RULE_BEHAVIORS = {
    "R1": "4-octants", "R2": "4-octants", "R3": "2-far-apart", "R4": "4-octants",
    "R5": "2-far-apart", "R6": "4-octants", "R7": "4-octants", "R8": "none",
}

_NAME_TO_ABBR = {
    "north": "N", "northeast": "NE", "east": "E", "southeast": "SE",
    "south": "S", "southwest": "SW", "west": "W", "northwest": "NW",
    "n": "N", "ne": "NE", "e": "E", "se": "SE", "s": "S", "sw": "SW", "w": "W", "nw": "NW",
}


# --- Geometry helpers (faithful) -------------------------------------------
def _meters_to_miles(m: float) -> float:
    return m / 1609.344


def _to_rad(d: float) -> float:
    return d * math.pi / 180


def _to_deg(r: float) -> float:
    return r * 180 / math.pi


def _round6(x: float) -> float:
    # JS `+x.toFixed(6)` — fixed 6-decimal rounding then back to number.
    return float(f"{x:.6f}")


def _round2(x: float) -> float:
    return float(f"{x:.2f}")


def _round1(x: float) -> float:
    return float(f"{x:.1f}")


def dest_point(lat: float, lng: float, bearing_deg: float, distance_meters: float) -> dict:
    """Destination point from (lat,lng) along a bearing for a given distance.

    Spherical great-circle formula; lat/lng rounded to 6 decimals like the JS.
    """
    R = 6371000
    brng = _to_rad(bearing_deg)
    f1 = _to_rad(lat)
    l1 = _to_rad(lng)
    d = distance_meters / R
    sinf1 = math.sin(f1)
    cosf1 = math.cos(f1)
    sind = math.sin(d)
    cosd = math.cos(d)
    sinf2 = sinf1 * cosd + cosf1 * sind * math.cos(brng)
    f2 = math.asin(sinf2)
    y = math.sin(brng) * sind * cosf1
    x = cosd - sinf1 * sinf2
    l2 = l1 + math.atan2(y, x)
    return {
        "lat": _round6(_to_deg(f2)),
        "lng": _round6(((_to_deg(l2) + 540) % 360) - 180),
    }


def haversine_meters(a: dict, b: dict) -> float:
    R = 6371000
    f1 = _to_rad(a["lat"])
    f2 = _to_rad(b["lat"])
    df = _to_rad(b["lat"] - a["lat"])
    dl = _to_rad(b["lng"] - a["lng"])
    s = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(s))


def _norm_key(s) -> str:
    out = []
    for ch in str(s if s is not None else "").lower():
        if "a" <= ch <= "z":
            out.append(ch)
    return "".join(out)


def _flatten(seq) -> list:
    """Flatten arbitrarily-nested lists (JS `.flat(Infinity)`)."""
    out: list = []
    for v in seq:
        if isinstance(v, list):
            out.extend(_flatten(v))
        else:
            out.append(v)
    return out


def _bearings_for_sector(sec: str, az_off: float) -> list[float]:
    base = ((_SECTOR_BEARING.get(sec, 0)) + az_off + 360) % 360
    return [(base - EDGE_SPREAD_DEG + 360) % 360, (base + EDGE_SPREAD_DEG) % 360]


def _classify_strength(s: dict):
    cells = float(s.get("cells") or 0)
    ranked = float(s.get("ranked") or 0)
    top10 = float(s.get("top10") or 0)
    gt10 = float(s.get("gt10") or 0)
    avg = None if s.get("avg_rank") is None else float(s.get("avg_rank"))
    if cells > 0 and ranked == 0:
        return "WEAK"
    if gt10 > 0:
        return "WEAK"
    if avg is not None and avg >= 11:
        return "WEAK"
    if ranked < cells and top10 <= ranked:
        return "WEAK"
    if (avg is not None and 4 <= avg <= 10) or (top10 >= 1 and top10 < cells):
        return "MED"
    return None


def _fmt(x) -> str:
    """Number → trimmed string, like the JS `fmt` (String() of a number)."""
    if x is None:
        return ""
    if isinstance(x, float):
        if x.is_integer():
            return str(int(x))
        return repr(x)
    return str(x)


def _fmt6(x) -> str:
    if x is None:
        return ""
    return f"{float(x):.6f}"


def select_octant_pins(
    heatmap: dict,
    rule_code: str,
    *,
    weak_octants: list[str] | None = None,
    weak_octants_full: list[str] | None = None,
    use_external_weak: bool = True,
    external_weak_mode: str = "restrict",
) -> dict:
    """Select hyper-local GBP pins in the weakest octants of a heatmap.

    Returns the inner object the JS node emits as ``{ json: {...} }`` — keys:
    ``ok``, ``used_rule``, ``reason``, ``points``, and (on success/none) ``debug``.
    """
    hm = heatmap
    RULE = "" if rule_code is None else str(rule_code).upper()

    # --- Early guards (match JS shapes) ------------------------------------
    if (
        not hm
        or not isinstance(hm.get("center"), dict)
        or not isinstance(hm["center"].get("lat"), (int, float))
        or isinstance(hm["center"].get("lat"), bool)
        or not isinstance(hm["center"].get("lng"), (int, float))
        or isinstance(hm["center"].get("lng"), bool)
    ):
        return {"ok": False, "used_rule": RULE or None, "reason": "Missing/invalid heatmap center", "points": []}
    if not RULE:
        return {"ok": False, "used_rule": None, "reason": "rule_code is required (e.g., R5)", "points": []}

    behavior = _RULE_BEHAVIORS.get(RULE, "4-octants")
    az_off = float(hm.get("azimuth_offset_deg") or 0)

    # --- Octant weakness ordering from sectors_overall ---------------------
    sector_weak = []
    for s in (hm.get("sectors_overall") or []):
        cells = max(1, float(s.get("cells") or 0))
        not_ranked_ratio = float(s.get("not_ranked") or 0) / cells
        sector_weak.append({
            "sector": s.get("sector"),
            "top3": float(s.get("coverage_pct_top3") or 0),
            "top10": float(s.get("coverage_pct_top10") or 0),
            "notRankedRatio": not_ranked_ratio,
        })

    def _cmp(a, b):
        if a["top3"] != b["top3"]:
            return -1 if a["top3"] < b["top3"] else 1
        if a["top10"] != b["top10"]:
            return -1 if a["top10"] < b["top10"] else 1
        if a["notRankedRatio"] != b["notRankedRatio"]:
            return -1 if b["notRankedRatio"] < a["notRankedRatio"] else 1
        return 0

    sector_weak.sort(key=functools.cmp_to_key(_cmp))
    base_octant_weak_order = [s["sector"] for s in sector_weak]

    # --- External weak override --------------------------------------------
    raw_external = weak_octants_full if weak_octants_full is not None else weak_octants
    if raw_external is None:
        raw_external = []
    if isinstance(raw_external, list) and len(raw_external) and isinstance(raw_external[0], list):
        raw_external = _flatten(raw_external)

    external_weak_octants: list[str] = []
    if isinstance(raw_external, list) and len(raw_external):
        for v in raw_external:
            string = str(v if v is not None else "")
            key = _norm_key(string)
            mapped = _NAME_TO_ABBR.get(key)
            if mapped and mapped in VALID_OCTANTS:
                external_weak_octants.append(mapped)
                continue
            up = string.upper()
            external_weak_octants.append(up if up in VALID_OCTANTS else None)
        external_weak_octants = [o for o in external_weak_octants if o]

    octant_weak_order = list(base_octant_weak_order)
    external_applied = False
    external_mode_used = None
    if use_external_weak and len(external_weak_octants):
        external_applied = True
        seen: set = set()
        ext_unique = []
        for o in external_weak_octants:
            if o in seen:
                continue
            seen.add(o)
            ext_unique.append(o)
        rest = [o for o in octant_weak_order if o not in ext_unique]
        octant_weak_order = [*ext_unique, *rest]
        external_mode_used = "restrict" if external_weak_mode == "restrict" else "prioritize"

    octant_rank_index = {o: i for i, o in enumerate(octant_weak_order)}

    # --- Rings -------------------------------------------------------------
    ring_summaries = [
        r for r in (hm.get("ring_summaries") or [])
        if (r.get("ring") or 0) > 0 and (r.get("radius_m") or 0) > 0
    ]
    if not len(ring_summaries):
        return {"ok": False, "used_rule": RULE, "reason": "No ring_summaries available", "points": []}

    center = hm["center"]
    all_candidates: list[dict] = []
    restrict_set = set(external_weak_octants) if (external_applied and external_weak_mode == "restrict") else None
    for r in ring_summaries:
        for s in (r.get("sectors") or []):
            if restrict_set is not None and s.get("sector") not in restrict_set:
                continue
            # Per-ring sectors may not carry `not_ranked`; compute cells - ranked.
            s_for_class = dict(s)
            if s_for_class.get("not_ranked") is None:
                s_for_class["not_ranked"] = (s.get("cells") or 0) - (s.get("ranked") or 0)
            strength = _classify_strength(s_for_class)
            if not strength:
                continue
            bearings = _bearings_for_sector(s.get("sector"), az_off)
            for b in bearings:
                dp = dest_point(center["lat"], center["lng"], b, r["radius_m"])
                all_candidates.append({
                    "sector": s.get("sector"),
                    "octant": s.get("sector"),
                    "ring": r.get("ring"),
                    "radius_m": r.get("radius_m"),
                    "radius_mi": _round2(_meters_to_miles(r["radius_m"])),
                    "bearing_deg": _round1(b),
                    "lat": dp["lat"],
                    "lng": dp["lng"],
                    "strength": strength,
                })

    if not len(all_candidates):
        return {"ok": False, "used_rule": RULE, "reason": "No WEAK or MED candidates found.", "points": []}

    weak_c = [c for c in all_candidates if c["strength"] == "WEAK"]
    med_c = [c for c in all_candidates if c["strength"] == "MED"]

    def _sort_pool(pool: list[dict]) -> None:
        def _key(p):
            primary = octant_rank_index.get(p["octant"], 999) if USE_SECTOR_WEAKNESS else 0
            ring_key = -p["ring"] if PREFER_OUTER_RINGS else 0
            return (primary, ring_key, str(p["sector"]))

        # Match JS sequential comparator semantics with a stable sort.
        pool.sort(key=_key)

    _sort_pool(weak_c)
    _sort_pool(med_c)

    def _bucket_by_octant(pool: list[dict]) -> dict:
        b = {o: [] for o in OCTANTS}
        for p in pool:
            if p["octant"] in b:
                b[p["octant"]].append(p)
        return b

    by_oct_weak = _bucket_by_octant(weak_c)
    by_oct_med = _bucket_by_octant(med_c)

    selected: list[dict] = []
    reason = ""
    fallback_used = False
    pair_distance = None

    def _pick_one(lst):
        return lst[0] if len(lst) else None

    def _find_pair(points, min_meters, require_different_octants=False, avoid_same_sector=False):
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                if require_different_octants and points[i]["octant"] == points[j]["octant"]:
                    continue
                if avoid_same_sector and points[i]["sector"] == points[j]["sector"]:
                    continue
                if haversine_meters(points[i], points[j]) >= min_meters:
                    return [points[i], points[j]]
        return None

    def _make_debug():
        return {
            "totalCandidates": len(all_candidates),
            "weakCount": len(weak_c),
            "medCount": len(med_c),
            "ruleBehavior": behavior,
            "octantWeaknessRank": octant_weak_order,
            "byOctWeakCounts": {o: len(by_oct_weak[o]) for o in OCTANTS},
            "byOctMedCounts": {o: len(by_oct_med[o]) for o in OCTANTS},
            "fallback_used": fallback_used,
            "pair_distance_m": pair_distance,
            "external_weak_applied": external_applied,
            "external_mode": external_mode_used,
            "external_weak_octants": external_weak_octants,
        }

    # --- Behaviour: none / R8 ----------------------------------------------
    if behavior == "none" or RULE == "R8":
        debug = _make_debug()
        bearing_summary, human_summary, human_summary_md = _build_summaries(
            RULE, behavior, [], octant_weak_order, fallback_used, pair_distance,
            external_applied, external_mode_used, external_weak_octants,
            len(all_candidates), len(weak_c), len(med_c), by_oct_weak, by_oct_med,
        )
        debug["bearing_summary"] = bearing_summary
        debug["human_summary"] = human_summary
        debug["human_summary_md"] = human_summary_md
        return {
            "ok": True,
            "used_rule": RULE,
            "reason": "R8 → return 0 coordinates.",
            "points": [],
            "debug": debug,
        }

    # --- Behaviour: 4-octants ----------------------------------------------
    if behavior == "4-octants":
        preferred_octants = octant_weak_order[:8]
        chosen_octants: set = set()
        for o in preferred_octants:
            if len(chosen_octants) >= 4:
                break
            pick = _pick_one(by_oct_weak[o]) if o in by_oct_weak else None
            if pick:
                selected.append(pick)
                chosen_octants.add(o)
        if len(selected) < 4 and ALLOW_MED_IF_INSUFFICIENT:
            for o in preferred_octants:
                if len(chosen_octants) >= 4:
                    break
                if o in chosen_octants:
                    continue
                med_pick = _pick_one(by_oct_med[o]) if o in by_oct_med else None
                if med_pick:
                    selected.append(med_pick)
                    chosen_octants.add(o)
                    fallback_used = True
        if len(selected) < 4 and ALLOW_MED_IF_INSUFFICIENT:
            seen = {f"{p['lat']},{p['lng']}" for p in selected}
            for p in med_c:
                key = f"{p['lat']},{p['lng']}"
                if key not in seen:
                    selected.append(p)
                    seen.add(key)
                    fallback_used = True
                if len(selected) >= 4:
                    break
        selected = selected[:4]
        reason = (
            f"Rule {RULE}: 4 coordinates across 4 distinct octants (weak-first). "
            f"{'MED used to fill gaps.' if fallback_used else 'WEAK-only.'}"
        )
        if not len(selected):
            return {
                "ok": False,
                "used_rule": RULE,
                "reason": "No WEAK octants available and MED fallback disabled or unavailable.",
                "points": [],
            }

    # --- Behaviour: 2-far-apart --------------------------------------------
    if behavior == "2-far-apart":
        weak_counts_by_oct = {o: len(by_oct_weak[o]) for o in OCTANTS}
        preferred_octants: list[str] = []
        for o in octant_weak_order:
            if weak_counts_by_oct.get(o, 0) > 0:
                preferred_octants.append(o)
            if len(preferred_octants) >= PREFERRED_OCTANTS_COUNT:
                break
        if len(preferred_octants) < PREFERRED_OCTANTS_COUNT and ALLOW_MED_IF_INSUFFICIENT:
            for o in octant_weak_order:
                if o not in preferred_octants and (len(by_oct_med[o]) if o in by_oct_med else 0) > 0:
                    preferred_octants.append(o)
                    if len(preferred_octants) >= PREFERRED_OCTANTS_COUNT:
                        break

        weak_top_o = [p for p in weak_c if p["octant"] in preferred_octants]
        med_top_o = [p for p in med_c if p["octant"] in preferred_octants]
        pair = None
        if REQUIRE_DIFFERENT_OCTANTS:
            pair = _find_pair(weak_top_o, MIN_DISTANCE_M, require_different_octants=True,
                              avoid_same_sector=AVOID_SAME_SECTOR_WHEN_POSSIBLE)
        if not pair and ALLOW_MED_IF_INSUFFICIENT:
            pool = weak_top_o + med_top_o
            pair = _find_pair(pool, MIN_DISTANCE_M, require_different_octants=True,
                              avoid_same_sector=AVOID_SAME_SECTOR_WHEN_POSSIBLE)
            if pair:
                fallback_used = any(p["strength"] == "MED" for p in pair)
        if not pair:
            pair = _find_pair(weak_top_o, MIN_DISTANCE_M, require_different_octants=False,
                              avoid_same_sector=AVOID_SAME_SECTOR_WHEN_POSSIBLE)
        if not pair and (len(weak_top_o) + len(med_top_o)) >= 2 and ALLOW_MED_IF_INSUFFICIENT:
            pool = weak_top_o + med_top_o
            best = {"d": -1, "a": None, "b": None}
            for i in range(len(pool)):
                for j in range(i + 1, len(pool)):
                    d = haversine_meters(pool[i], pool[j])
                    if d > best["d"]:
                        best = {"d": d, "a": pool[i], "b": pool[j]}
            if best["a"] and best["b"]:
                pair = [best["a"], best["b"]]
                pair_distance = round(best["d"])
                fallback_used = True

        if not pair:
            return {
                "ok": False,
                "used_rule": RULE,
                "reason": (
                    f"No WEAK/MED pair ≥ {MIN_DISTANCE_M} m found inside preferred "
                    f"octants ({', '.join(preferred_octants)})."
                ),
                "points": [],
                "debug": {
                    "preferredOctants": preferred_octants,
                    "weakTopO": len(weak_top_o),
                    "medTopO": len(med_top_o),
                    "octantWeaknessRank": octant_weak_order,
                    "external_weak_applied": external_applied,
                    "external_mode": external_mode_used,
                    "external_weak_octants": external_weak_octants,
                },
            }

        pair_distance = pair_distance if pair_distance is not None else round(haversine_meters(pair[0], pair[1]))
        reason = (
            f"Rule {RULE}: {'Fallback used' if fallback_used else 'WEAK-only'} pair "
            f"≥ {MIN_DISTANCE_M} m inside octants ({', '.join(preferred_octants)}). "
            f"Distance {pair_distance} m."
        )
        selected = pair

    points = [
        {
            "sector": p["sector"], "octant": p["octant"], "ring": p["ring"],
            "radius_m": p["radius_m"], "radius_mi": p["radius_mi"],
            "bearing_deg": p["bearing_deg"], "lat": p["lat"], "lng": p["lng"],
            "strength": p["strength"],
        }
        for p in selected
    ]

    debug = _make_debug()
    debug["pair_distance_m"] = pair_distance
    debug["fallback_used"] = fallback_used
    bearing_summary, human_summary, human_summary_md = _build_summaries(
        RULE, behavior, points, octant_weak_order, fallback_used, pair_distance,
        external_applied, external_mode_used, external_weak_octants,
        len(all_candidates), len(weak_c), len(med_c), by_oct_weak, by_oct_med,
    )
    debug["bearing_summary"] = bearing_summary
    debug["human_summary"] = human_summary
    debug["human_summary_md"] = human_summary_md

    return {
        "ok": len(points) > 0,
        "used_rule": RULE,
        "reason": reason,
        "points": points,
        "debug": debug,
    }


def _build_summaries(
    rule, behavior, points, octant_weak_order, fallback_used, pair_distance,
    external_applied, external_mode_used, external_weak_octants,
    total_candidates, weak_count, med_count, by_oct_weak, by_oct_med,
):
    """Build bearing_summary (list), plain-text and Markdown human summaries."""
    bearing_summary = [
        {
            "octant": p["octant"], "ring": p["ring"], "bearing_deg": p["bearing_deg"],
            "radius_mi": p["radius_mi"], "strength": p["strength"],
            "lat": p["lat"], "lng": p["lng"],
        }
        for p in points
    ]

    header_cols = ["#", "Octant", "Ring", "Bearing", "Radius(mi)", "Strength", "Lat", "Lng"]

    # --- Markdown table -----------------------------------------------------
    md_lines = []
    md_lines.append(f"**Rule {rule} — {behavior}**")
    md_lines.append("")
    if not points:
        md_lines.append("_No coordinates returned._")
    else:
        md_lines.append("| " + " | ".join(header_cols) + " |")
        md_lines.append("|" + "|".join(["---"] * len(header_cols)) + "|")
        for i, p in enumerate(points, start=1):
            md_lines.append(
                "| " + " | ".join([
                    str(i), str(p["octant"]), str(p["ring"]),
                    _fmt(p["bearing_deg"]), _fmt(p["radius_mi"]), str(p["strength"]),
                    _fmt6(p["lat"]), _fmt6(p["lng"]),
                ]) + " |"
            )
    md_lines.append("")
    md_lines.append(
        f"_Octant weakness order: {', '.join(octant_weak_order)}. "
        f"Fallback used: {'yes' if fallback_used else 'no'}._"
    )
    if pair_distance is not None:
        md_lines.append(f"_Pair distance: {pair_distance} m._")
    if external_applied:
        md_lines.append(
            f"_External weak ({external_mode_used}): {', '.join(external_weak_octants)}._"
        )
    human_summary_md = "\n".join(md_lines)

    # --- Plain-text padded table -------------------------------------------
    rows = []
    for i, p in enumerate(points, start=1):
        rows.append([
            str(i), str(p["octant"]), str(p["ring"]),
            _fmt(p["bearing_deg"]), _fmt(p["radius_mi"]), str(p["strength"]),
            _fmt6(p["lat"]), _fmt6(p["lng"]),
        ])

    widths = [len(c) for c in header_cols]
    for r in rows:
        for k, cell in enumerate(r):
            if len(cell) > widths[k]:
                widths[k] = len(cell)

    def _pad_row(cells):
        return "  ".join(cells[k].ljust(widths[k]) for k in range(len(cells)))

    txt_lines = []
    txt_lines.append(f"Rule {rule} — {behavior}")
    if not points:
        txt_lines.append("No coordinates returned.")
    else:
        txt_lines.append(_pad_row(header_cols))
        txt_lines.append("  ".join("-" * widths[k] for k in range(len(header_cols))))
        for r in rows:
            txt_lines.append(_pad_row(r))
    txt_lines.append(
        f"Octant weakness order: {', '.join(octant_weak_order)}. "
        f"Fallback used: {'yes' if fallback_used else 'no'}."
    )
    if pair_distance is not None:
        txt_lines.append(f"Pair distance: {pair_distance} m.")
    if external_applied:
        txt_lines.append(
            f"External weak ({external_mode_used}): {', '.join(external_weak_octants)}."
        )
    human_summary = "\n".join(txt_lines)

    return bearing_summary, human_summary, human_summary_md

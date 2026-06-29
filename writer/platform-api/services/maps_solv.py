"""Share of Local Voice (SoLV) — derived, on-read, from the geo-grid scans we
already store. No new table or fetch: it reuses each `maps_scan_results` row's
client Top-3 coverage (`top3_pins` / `total_pins`) and the stored per-keyword
`competitors` leaderboard (each competitor carries its own `top3_pins`).

"Share" here is *local-pack presence* — the % of in-circle grid pins where a
business sits in the top 3. It is NOT a partition (several businesses can be
top-3 at the same pin), so client + competitor shares do not sum to 100%.

Pure helpers (unit-tested); the router wraps the dicts in response models and
the reoptimization planner reuses `overall_coverage` + `detect_solv_drop` for an
Action Plan signal.
"""

from __future__ import annotations


def _pct(part, whole) -> "float | None":
    if not whole:
        return None
    return round((part or 0) / whole * 100, 1)


def overall_coverage(results: list[dict]) -> dict:
    """Aggregate one scan's per-keyword results into the client's overall Top-3 /
    Top-10 local-pack coverage and a ranked competitor-share list. Pure."""
    total = 0
    client_top3 = 0
    client_top10 = 0
    comp: dict[str, dict] = {}
    for r in results:
        rt = r.get("total_pins") or 0
        total += rt
        client_top3 += r.get("top3_pins") or 0
        client_top10 += r.get("top10_pins") or 0
        for c in r.get("competitors") or []:
            pid = c.get("place_id")
            if not pid:
                continue
            slot = comp.setdefault(pid, {"place_id": pid, "name": c.get("name"), "top3_pins": 0})
            slot["top3_pins"] += c.get("top3_pins") or 0
            if c.get("name"):
                slot["name"] = c.get("name")
    shares = [
        {**c, "share_pct": _pct(c["top3_pins"], total)}
        for c in comp.values()
        if c["top3_pins"] > 0
    ]
    shares.sort(key=lambda c: (-(c["top3_pins"]), (c["name"] or "")))
    return {
        "total_pins": total,
        "client_top3_pins": client_top3,
        "client_coverage_pct": _pct(client_top3, total),
        "client_coverage_top10_pct": _pct(client_top10, total),
        "competitor_shares": shares,
    }


def build_solv(scans: list[dict], results: list[dict], top_competitors: int = 8) -> dict:
    """Build the SoLV payload from completed scans + their results. Returns:
      {series:    [{scan_id, completed_at, trigger, client_coverage_pct,
                    client_coverage_top10_pct, total_pins, client_top3_pins}],
       competitors:[{place_id, name, top3_pins, share_pct}]  # latest scan, top N
       keywords:  [{keyword, client_coverage_pct, total_pins, client_top3_pins,
                    competitor_shares: [...]}]}              # latest scan
    Only scans that carry competitor data inform the competitor breakdown; the
    coverage series spans every completed scan. Pure (DB-free)."""
    meta = {s["id"]: s for s in scans}
    by_scan: dict[str, list[dict]] = {}
    for r in results:
        if r.get("scan_id") in meta:
            by_scan.setdefault(r["scan_id"], []).append(r)

    series = []
    for sid, rows in by_scan.items():
        s = meta[sid]
        ov = overall_coverage(rows)
        series.append(
            {
                "scan_id": sid,
                "completed_at": s.get("completed_at"),
                "trigger": s.get("trigger", "scheduled"),
                "total_pins": ov["total_pins"],
                "client_top3_pins": ov["client_top3_pins"],
                "client_coverage_pct": ov["client_coverage_pct"],
                "client_coverage_top10_pct": ov["client_coverage_top10_pct"],
            }
        )
    series.sort(key=lambda p: p["completed_at"] or "")

    competitors: list[dict] = []
    keywords: list[dict] = []
    if series:
        latest_id = series[-1]["scan_id"]
        latest_rows = by_scan.get(latest_id, [])
        competitors = overall_coverage(latest_rows)["competitor_shares"][:top_competitors]
        for r in sorted(latest_rows, key=lambda r: r.get("keyword") or ""):
            total = r.get("total_pins") or 0
            shares = [
                {
                    "place_id": c.get("place_id"),
                    "name": c.get("name"),
                    "top3_pins": c.get("top3_pins") or 0,
                    "share_pct": _pct(c.get("top3_pins"), total),
                }
                for c in (r.get("competitors") or [])
                if (c.get("top3_pins") or 0) > 0
            ][:top_competitors]
            keywords.append(
                {
                    "keyword": r.get("keyword"),
                    "total_pins": total,
                    "client_top3_pins": r.get("top3_pins") or 0,
                    "client_coverage_pct": _pct(r.get("top3_pins"), total),
                    "competitor_shares": shares,
                }
            )

    return {"series": series, "competitors": competitors, "keywords": keywords}


def detect_solv_drop(latest: list[dict], previous: list[dict], min_drop_pct: float) -> "dict | None":
    """Compare the client's overall Top-3 coverage between the two most recent
    scans; return a drop signal when it fell by >= min_drop_pct points (and a
    competitor gained), else None. Pure — feeds the Action Plan, not an alert."""
    if not latest or not previous:
        return None
    now = overall_coverage(latest)
    prev = overall_coverage(previous)
    now_pct = now["client_coverage_pct"]
    prev_pct = prev["client_coverage_pct"]
    if now_pct is None or prev_pct is None:
        return None
    delta = prev_pct - now_pct  # positive = lost share
    if delta < min_drop_pct:
        return None
    # The competitor that gained the most Top-3 presence over the same window.
    prev_by = {c["place_id"]: c for c in prev["competitor_shares"]}
    gained = None
    for c in now["competitor_shares"]:
        p = prev_by.get(c["place_id"])
        g = (c.get("share_pct") or 0) - ((p or {}).get("share_pct") or 0)
        if g > 0 and (gained is None or g > gained[1]):
            gained = (c.get("name") or "A competitor", g)
    return {
        "from_pct": prev_pct,
        "to_pct": now_pct,
        "delta_pct": round(delta, 1),
        "top_gainer": gained[0] if gained else None,
    }

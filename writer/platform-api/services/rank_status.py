"""Rank trend status + summary metrics computation.

Organic Rank Tracker (Module #4), M3. Pure functions over a keyword's
materialized date axis (one (date, gsc_position) point per day, position None
on days GSC returned nothing). No I/O — exhaustively unit-tested.

The status taxonomy and the "gap only matters with an established baseline"
rule are from docs/modules/organic-rank-tracker-prd-v1_0.md §7. Thresholds are
deliberately conservative tunables (PRD §12).
"""

from __future__ import annotations

from datetime import date
from statistics import mean
from typing import Optional, Sequence, Union

# --- Tunable thresholds (start conservative; expose as config later) --------
DEINDEX_CONSECUTIVE_DAYS = 7   # trailing NULL days that trip deindex_risk
BASELINE_MIN_DAYS = 5          # non-null days required to count as "established"
TREND_THRESHOLD = 3.0          # avg-position delta (positions) for climb/drop
VOLATILE_RANGE_THRESHOLD = 10.0  # recent peak-to-trough swing → volatile
VOLATILITY_WINDOW = 14         # non-null points scanned for swing range

DatePoint = tuple[Union[str, date], Optional[float]]


def _to_date(value: Union[str, date]) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _sorted_points(series: Sequence[DatePoint]) -> list[tuple[date, Optional[float]]]:
    return sorted(((_to_date(d), p) for d, p in series), key=lambda x: x[0])


def _trailing_null_count(points: Sequence[tuple[date, Optional[float]]]) -> int:
    count = 0
    for _, p in reversed(points):
        if p is None:
            count += 1
        else:
            break
    return count


def compute_status(series: Sequence[DatePoint]) -> str:
    """Classify a keyword's trend into the §7 taxonomy.

    Lower position is better (1 = top). Improving = position decreasing.
    """
    points = _sorted_points(series)
    non_null = [p for _, p in points if p is not None]

    # Never established presence → awaiting first data (aspirational keyword).
    if not non_null:
        return "no_data"

    # Sustained disappearance after an established baseline = deindex signature.
    if (
        len(non_null) >= BASELINE_MIN_DAYS
        and _trailing_null_count(points) >= DEINDEX_CONSECUTIVE_DAYS
    ):
        return "deindex_risk"

    # Too little history to judge a trend — present but inconclusive.
    if len(non_null) < 4:
        return "stable"

    # Trend = second half vs first half (non-overlapping, so a transient spike
    # in the middle doesn't dominate either side). Positive delta = worse.
    mid = len(non_null) // 2
    first_half = non_null[:mid]
    second_half = non_null[mid:]
    delta = mean(second_half) - mean(first_half)

    swing = non_null[-VOLATILITY_WINDOW:]
    swing_range = max(swing) - min(swing)

    # Swung hard but landed back near baseline → drop-and-recover.
    if swing_range >= VOLATILE_RANGE_THRESHOLD and abs(delta) < TREND_THRESHOLD:
        return "volatile"
    if delta <= -TREND_THRESHOLD:
        return "climbing"
    if delta >= TREND_THRESHOLD:
        return "dropping"
    return "stable"


def rolling_average(
    series: Sequence[DatePoint], days: int, today: date
) -> Optional[float]:
    """Mean non-null position over the last `days` days, or None."""
    cutoff = today.toordinal() - days + 1
    vals = [
        p
        for d, p in _sorted_points(series)
        if p is not None and _to_date(d).toordinal() >= cutoff
    ]
    return round(mean(vals), 1) if vals else None


def _window_sum(series_full: Sequence[dict], days: int, today: date, field: str) -> int:
    cutoff = today.toordinal() - days + 1
    return sum(
        int(row.get(field) or 0)
        for row in series_full
        if _to_date(row["date"]).toordinal() >= cutoff
    )


def determine_primary_source(rows: Sequence[dict], today: date, coverage_days: int) -> str:
    """Which source represents this keyword: GSC if the site ranks for it
    recently, else DataForSEO if we have a live rank, else none (awaiting data)."""
    cutoff = today.toordinal() - coverage_days + 1
    has_recent_gsc = any(
        r.get("gsc_position") is not None and _to_date(r["date"]).toordinal() >= cutoff
        for r in rows
    )
    if has_recent_gsc:
        return "gsc"
    if any(r.get("tracked_rank") is not None for r in rows):
        return "dataforseo"
    return "none"


def _latest_tracked_rank(rows: Sequence[dict]) -> Optional[int]:
    for row in sorted(rows, key=lambda r: r["date"], reverse=True):
        if row.get("tracked_rank") is not None:
            return row["tracked_rank"]
    return None


def compute_keyword_summary(rows: Sequence[dict], today: date, coverage_days: int = 14) -> dict:
    """Build the read-side summary for one keyword, source-aware.

    GSC-covered keywords show GSC rolling averages + clicks/impressions/sparkline.
    DataForSEO-fallback keywords (no recent GSC) drop those and show the live
    rank ("Today") + a rank sparkline — never reconciling the two sources.
    """
    source = determine_primary_source(rows, today, coverage_days)
    today_rank = _latest_tracked_rank(rows)
    base = {
        "primary_source": source,
        "avg_7": None, "avg_30": None, "avg_60": None, "avg_90": None,
        "clicks_30d": 0, "impressions_30d": 0, "ctr_30d": 0.0,
        "sparkline": [], "direction": None, "today_rank": today_rank,
    }

    if source == "gsc":
        series = [(row["date"], row.get("gsc_position")) for row in rows]
        base["avg_7"] = rolling_average(series, 7, today)
        base["avg_30"] = rolling_average(series, 30, today)
        base["avg_60"] = rolling_average(series, 60, today)
        base["avg_90"] = rolling_average(series, 90, today)
        base["clicks_30d"] = _window_sum(rows, 30, today, "clicks")
        base["impressions_30d"] = _window_sum(rows, 30, today, "impressions")
        base["ctr_30d"] = round(base["clicks_30d"] / base["impressions_30d"], 4) if base["impressions_30d"] else 0.0
        cutoff = today.toordinal() - 30 + 1
        base["sparkline"] = [p for d, p in _sorted_points(series) if _to_date(d).toordinal() >= cutoff]
        if base["avg_7"] is not None and base["avg_90"] is not None:
            diff = base["avg_7"] - base["avg_90"]
            base["direction"] = "up" if diff < -0.1 else "down" if diff > 0.1 else "flat"

    elif source == "dataforseo":
        # Sparse weekly rank series; sparkline = the live-rank points over 90 days.
        series = [(row["date"], row.get("tracked_rank")) for row in rows]
        cutoff = today.toordinal() - 90 + 1
        vals = [(d, v) for d, v in _sorted_points(series) if _to_date(d).toordinal() >= cutoff]
        base["sparkline"] = [v for _, v in vals]
        non_null = [v for _, v in vals if v is not None]
        if len(non_null) >= 2:
            diff = non_null[-1] - non_null[0]  # later − earlier; negative = improved
            base["direction"] = "up" if diff < -0.5 else "down" if diff > 0.5 else "flat"

    return base


def aggregate_pages(page_rows: Sequence[dict]) -> list[dict]:
    """Pivot gsc_query_page_daily by page for the Pages view.

    Per page: total clicks/impressions, distinct keyword count, and an
    impression-weighted average position. Sorted by clicks desc.
    """
    by_page: dict[str, dict] = {}
    for row in page_rows:
        page = row["page"]
        b = by_page.setdefault(page, {"clicks": 0, "impressions": 0, "queries": set(), "pos_num": 0.0, "pos_den": 0})
        clicks = int(row.get("clicks", 0) or 0)
        impressions = int(row.get("impressions", 0) or 0)
        b["clicks"] += clicks
        b["impressions"] += impressions
        b["queries"].add(str(row.get("query", "")).lower())
        pos = row.get("position")
        if pos is not None and impressions:
            b["pos_num"] += pos * impressions
            b["pos_den"] += impressions

    out = []
    for page, b in by_page.items():
        avg_pos = round(b["pos_num"] / b["pos_den"], 1) if b["pos_den"] else None
        out.append({
            "page": page,
            "clicks": b["clicks"],
            "impressions": b["impressions"],
            "keywords": len(b["queries"]),
            "avg_position": avg_pos,
        })
    out.sort(key=lambda p: (p["clicks"], p["impressions"]), reverse=True)
    return out


def aggregate_hero(rows: Sequence[dict], today: date, days: int) -> list[dict]:
    """Account-level daily series for the Overview hero chart.

    Across ALL keywords' rows, per day: impression-weighted-agnostic mean of
    non-null gsc_position, plus summed clicks/impressions. One point per day in
    the last `days`, ordered ascending. Days with no data still appear (so the
    line/gap is faithful), with avg_position None.
    """
    cutoff = today.toordinal() - days + 1
    by_date: dict[str, dict] = {}
    for row in rows:
        d = _to_date(row["date"])
        if d.toordinal() < cutoff:
            continue
        iso = d.isoformat()
        bucket = by_date.setdefault(iso, {"positions": [], "clicks": 0, "impressions": 0})
        pos = row.get("gsc_position")
        if pos is not None:
            bucket["positions"].append(pos)
        bucket["clicks"] += int(row.get("clicks", 0) or 0)
        bucket["impressions"] += int(row.get("impressions", 0) or 0)

    out = []
    for iso in sorted(by_date):
        b = by_date[iso]
        out.append(
            {
                "date": iso,
                "avg_position": round(mean(b["positions"]), 1) if b["positions"] else None,
                "clicks": b["clicks"],
                "impressions": b["impressions"],
            }
        )
    return out

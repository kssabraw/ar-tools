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


def compute_keyword_summary(rows: Sequence[dict], today: date) -> dict:
    """Build the read-side summary for one keyword from its materialized rows.

    `rows` are rank_keyword_metrics records (date, clicks, impressions, ctr,
    gsc_position, tracked_rank). Returns the values the Keywords table + Overview
    triage render: rolling average positions, recent GSC totals, a sparkline
    (positions with None gaps preserved), and the 7d-vs-90d direction.
    """
    series = [(row["date"], row.get("gsc_position")) for row in rows]

    avg_7 = rolling_average(series, 7, today)
    avg_30 = rolling_average(series, 30, today)
    avg_60 = rolling_average(series, 60, today)
    avg_90 = rolling_average(series, 90, today)

    clicks_30 = _window_sum(rows, 30, today, "clicks")
    impressions_30 = _window_sum(rows, 30, today, "impressions")
    ctr_30 = round(clicks_30 / impressions_30, 4) if impressions_30 else 0.0

    # Sparkline: positions over the last 30 days, gaps preserved as None.
    cutoff = today.toordinal() - 30 + 1
    sparkline = [
        p for d, p in _sorted_points(series) if _to_date(d).toordinal() >= cutoff
    ]

    # Net direction: 7d vs 90d (negative delta = improved). None if either absent.
    direction = None
    if avg_7 is not None and avg_90 is not None:
        diff = avg_7 - avg_90
        direction = "up" if diff < -0.1 else "down" if diff > 0.1 else "flat"

    # Latest DataForSEO live rank, if any (M4 fills this).
    today_rank = None
    for row in sorted(rows, key=lambda r: r["date"], reverse=True):
        if row.get("tracked_rank") is not None:
            today_rank = row["tracked_rank"]
            break

    return {
        "avg_7": avg_7,
        "avg_30": avg_30,
        "avg_60": avg_60,
        "avg_90": avg_90,
        "clicks_30d": clicks_30,
        "impressions_30d": impressions_30,
        "ctr_30d": ctr_30,
        "sparkline": sparkline,
        "direction": direction,
        "today_rank": today_rank,
    }


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

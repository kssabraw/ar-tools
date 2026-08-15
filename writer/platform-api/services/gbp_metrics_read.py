"""Read-side aggregation for the GBP performance dashboard.

Pure helpers that turn raw ``gbp_metric_daily`` rows into the dashboard payload:
period-over-period growth cards + a daily folded time series for charting. No
I/O — the router does the DB reads and calls these.

Growth math is delegated to ``gbp_metrics_ingest.compute_metric_growth`` so the
interactive dashboard and the client PDF report
(``client_report._gather_gbp_metric_growth``) agree to the number. The impression
sub-types collapse into one owner-friendly "Profile views" headline here, exactly
as the report does (``client_report._GBP_IMPRESSION_METRICS`` /
``_GBP_METRIC_LABELS``) — keep the two label sets in step if either changes.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from services.gbp_metrics_ingest import compute_metric_growth

# The four impression sub-types collapse into one "profile_views" headline.
IMPRESSION_METRICS = frozenset(
    {
        "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
        "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
        "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
        "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
    }
)

# Canonical dashboard metrics in display order, with human labels. Keys are the
# folded metric keys ("profile_views") or raw Performance metric names.
METRIC_LABELS: list[tuple[str, str]] = [
    ("profile_views", "Profile views"),
    ("CALL_CLICKS", "Calls"),
    ("WEBSITE_CLICKS", "Website clicks"),
    ("BUSINESS_DIRECTION_REQUESTS", "Direction requests"),
    ("BUSINESS_CONVERSATIONS", "Messages"),
]
_LABELS = dict(METRIC_LABELS)
_ORDER = [k for k, _ in METRIC_LABELS]


def fold_metric(metric: Optional[str]) -> Optional[str]:
    """Collapse an impression sub-type to 'profile_views'; pass others through."""
    return "profile_views" if metric in IMPRESSION_METRICS else metric


def fold_rows(daily_rows: list[dict]) -> list[dict]:
    """Rewrite each row's ``metric`` to its folded key (impressions → profile_views)."""
    return [{**r, "metric": fold_metric(r.get("metric"))} for r in daily_rows]


def _as_iso(d) -> Optional[str]:
    if isinstance(d, date):
        return d.isoformat()
    return d or None


def build_growth_cards(daily_rows: list[dict], end: date, window_days: int) -> list[dict]:
    """Ordered period-over-period growth cards for the dashboard's headline metrics.

    Returns ``[{metric, label, current, previous, delta, pct}]`` in display order,
    omitting any metric with no data in either window.
    """
    folded = fold_rows(daily_rows)
    growth = compute_metric_growth(folded, end, window_days)
    return [
        {"metric": key, "label": label, **growth[key]}
        for key, label in METRIC_LABELS
        if key in growth
    ]


def last_data_date(daily_rows: list[dict]) -> Optional[date]:
    """The most recent date present in the rows, or None. GBP performance data
    lands ~3–5 days late, so this is where a chart should stop rather than the
    requested ``end`` (which would tack phantom zeros onto the not-yet-arrived
    tail and read as a crash)."""
    dates = []
    for r in daily_rows:
        iso = _as_iso(r.get("date"))
        if iso:
            try:
                dates.append(date.fromisoformat(iso))
            except ValueError:
                continue
    return max(dates) if dates else None


def build_series(daily_rows: list[dict], start: date, end: date) -> list[dict]:
    """Dense per-day folded series over ``[start, min(end, last_data_date)]``.

    One point per day (zero-filled between events) so the chart's x-axis is evenly
    spaced. The series stops at the last date with any data so the reporting lag
    doesn't render as a drop to zero. Returns ``[{date, values:{metric: int}}]``;
    ``values`` always carries every dashboard metric key.
    """
    effective_end = end
    ld = last_data_date(daily_rows)
    if ld is None:
        return []
    if ld < effective_end:
        effective_end = ld
    if effective_end < start:
        return []

    by_date: dict[str, dict[str, int]] = {}
    for r in fold_rows(daily_rows):
        m = r.get("metric")
        if m not in _LABELS:
            continue
        iso = _as_iso(r.get("date"))
        if not iso:
            continue
        bucket = by_date.setdefault(iso, {})
        bucket[m] = bucket.get(m, 0) + int(r.get("value", 0) or 0)

    out: list[dict] = []
    cur = start
    while cur <= effective_end:
        iso = cur.isoformat()
        vals = by_date.get(iso, {})
        out.append({"date": iso, "values": {k: int(vals.get(k, 0)) for k in _ORDER}})
        cur += timedelta(days=1)
    return out

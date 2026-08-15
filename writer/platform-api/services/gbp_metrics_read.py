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

# Which group each metric belongs to on the dashboard: how many people saw the
# listing (visibility) vs what they did next (actions).
_GROUP = {
    "profile_views": "visibility",
    "CALL_CLICKS": "actions",
    "WEBSITE_CLICKS": "actions",
    "BUSINESS_DIRECTION_REQUESTS": "actions",
    "BUSINESS_CONVERSATIONS": "actions",
}
# The four raw impression sub-types decomposed by surface + device — for the
# "where did your views come from" breakout the folded profile_views hides.
_IMPRESSION_SURFACE = {
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": "search",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": "search",
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": "maps",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS": "maps",
}
_IMPRESSION_DEVICE = {
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": "desktop",
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": "desktop",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": "mobile",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS": "mobile",
}
_ACTION_METRICS = ["CALL_CLICKS", "WEBSITE_CLICKS", "BUSINESS_DIRECTION_REQUESTS", "BUSINESS_CONVERSATIONS"]


def _pct(cur: int, prev: int) -> Optional[float]:
    """Percent change, or None when the prior window was zero (no baseline)."""
    return round((cur - prev) / prev * 100, 1) if prev else None


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
        {"metric": key, "label": label, "group": _GROUP.get(key, ""), **growth[key]}
        for key, label in METRIC_LABELS
        if key in growth
    ]


def build_breakdown(daily_rows: list[dict], end: date, window_days: int) -> dict:
    """Decompose profile views by **surface** (Search vs Maps) and **device**
    (Desktop vs Mobile) over the trailing window vs the prior one — the cut the
    folded "Profile views" headline hides. Returns
    ``{surface:[{label,current,previous,pct,share}], device:[…]}`` (share = % of
    the current total). Raw (unfolded) rows, so it reads the four sub-types."""
    raw = compute_metric_growth(daily_rows, end, window_days)  # per raw metric

    def _agg(mapping: dict, bucket: str) -> tuple[int, int]:
        cur = sum(raw.get(m, {}).get("current", 0) for m, b in mapping.items() if b == bucket)
        prev = sum(raw.get(m, {}).get("previous", 0) for m, b in mapping.items() if b == bucket)
        return cur, prev

    def _rows(mapping: dict, buckets: list[tuple[str, str]]) -> list[dict]:
        pairs = [(label, *_agg(mapping, key)) for key, label in buckets]
        total = sum(cur for _, cur, _ in pairs) or 0
        return [
            {
                "label": label, "current": cur, "previous": prev, "pct": _pct(cur, prev),
                "share": round(cur / total * 100, 1) if total else 0.0,
            }
            for label, cur, prev in pairs
        ]

    return {
        "surface": _rows(_IMPRESSION_SURFACE, [("search", "Search"), ("maps", "Maps")]),
        "device": _rows(_IMPRESSION_DEVICE, [("desktop", "Desktop"), ("mobile", "Mobile")]),
    }


def build_actions_summary(daily_rows: list[dict], end: date, window_days: int) -> dict:
    """Total customer actions (calls + website clicks + directions + messages) and
    the engagement rate (actions ÷ profile views), current vs prior window."""
    raw = compute_metric_growth(daily_rows, end, window_days)
    cur = sum(raw.get(m, {}).get("current", 0) for m in _ACTION_METRICS)
    prev = sum(raw.get(m, {}).get("previous", 0) for m in _ACTION_METRICS)
    views_cur = sum(raw.get(m, {}).get("current", 0) for m in IMPRESSION_METRICS)
    views_prev = sum(raw.get(m, {}).get("previous", 0) for m in IMPRESSION_METRICS)
    return {
        "current": cur, "previous": prev, "delta": cur - prev, "pct": _pct(cur, prev),
        "engagement_current": round(cur / views_cur * 100, 1) if views_cur else None,
        "engagement_previous": round(prev / views_prev * 100, 1) if views_prev else None,
    }


def _trend_word(pct: Optional[float]) -> str:
    if pct is None:
        return "started this period"
    if pct >= 5:
        return f"up {abs(pct):g}%"
    if pct <= -5:
        return f"down {abs(pct):g}%"
    return "about the same"


def build_insights(cards: list[dict], breakdown: dict, actions: dict) -> list[str]:
    """A few plain-English sentences an owner can read at a glance. Deterministic
    — no LLM. Empty when there's nothing to say (no data)."""
    out: list[str] = []
    by_metric = {c["metric"]: c for c in cards}
    views = by_metric.get("profile_views")
    if views and (views["current"] or views["previous"]):
        out.append(
            f"Your profile was seen {views['current']:,} times — "
            f"{_trend_word(views.get('pct'))} vs the previous period."
        )
    # Where the views came from (surface + device leaders).
    surf = max(breakdown.get("surface") or [], key=lambda r: r["current"], default=None)
    dev = max(breakdown.get("device") or [], key=lambda r: r["current"], default=None)
    if surf and surf["current"] and dev and dev["current"]:
        out.append(
            f"Most views came from {surf['label']} ({surf['share']:g}%), "
            f"mostly on {dev['label'].lower()} ({dev['share']:g}%)."
        )
    if actions.get("current") or actions.get("previous"):
        eng = actions.get("engagement_current")
        eng_txt = f" — {eng:g}% of viewers took an action" if eng is not None else ""
        out.append(
            f"Customers took {actions['current']:,} actions "
            f"(calls, directions, clicks, messages), {_trend_word(actions.get('pct'))}{eng_txt}."
        )
    # Biggest action mover (only when there's a real, non-new swing).
    movers = [c for c in cards if c["group"] == "actions" and c.get("pct") is not None and abs(c["pct"]) >= 15]
    if movers:
        top = max(movers, key=lambda c: abs(c["pct"]))
        direction = "up" if top["pct"] > 0 else "down"
        out.append(f"{top['label']} are {direction} {abs(top['pct']):g}% — the biggest change this period.")
    return out


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

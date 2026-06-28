"""Rank-drop alert detection — the Organic Rank Tracker's in-app alerting.

Module #4, M4's remaining piece. Pure detection over a keyword's materialized
date axis + a reconcile step that maintains an episode-based alert log
(`rank_alerts`). Runs inside the daily materialize job (no new scheduler/job).

Alerts are evaluated on the keyword's PRIMARY source (PRD §2): GSC average
position where the site is GSC-covered, else the DataForSEO weekly rank — never
mixing the two in one comparison. GSC positions are decimal impression-weighted
averages, so the GSC paths compare 7-day rolling averages to damp anonymization
noise; DataForSEO ranks are weekly point-in-time integers, compared as points.

Rules (thresholds are conservative tunables, like rank_status.py):
  - weekly_drop      : baseline (a week ago) in 1–15 and dropped ≥6 spots
  - page_one_exit    : was on page 1 (≤10) a week ago, now off it (>10)
  - thirty_day_drop  : baseline (30 days ago) in ~top 20 and dropped ≥6 spots
  - deindexed        : status == 'deindex_risk' (GSC-only sustained NULL signal)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from statistics import mean
from typing import Optional, Sequence

from services.rank_status import DatePoint, _sorted_points, _to_date

logger = logging.getLogger(__name__)

# --- Tunable thresholds -----------------------------------------------------
WEEKLY_DROP_SPOTS = 6
WEEKLY_DROP_BASELINE_MAX = 15      # "previously ranking in spots 1–15"
PAGE_ONE = 10                       # first page = top 10
THIRTY_DAY_DROP_SPOTS = 6
THIRTY_DAY_BASELINE_MAX = 20       # floor: only alert if it was ~top 20
WEEK_DAYS = 7
MONTH_DAYS = 30
GSC_SMOOTH_DAYS = 7                # rolling-average window for the GSC paths
DF_RECENT_TOLERANCE = 4           # DataForSEO "now" vs a point on/before today−4
DF_MONTH_TOLERANCE = 25           # DataForSEO "a month ago" vs on/before today−25

ALERT_TYPES = ("weekly_drop", "page_one_exit", "thirty_day_drop", "deindexed")


@dataclass
class AlertSignal:
    alert_type: str
    source: str
    message: str
    from_position: Optional[float] = None
    to_position: Optional[float] = None
    delta: Optional[float] = None
    details: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def _window_average(
    series: Sequence[DatePoint], end_days_ago: int, length: int, today: date
) -> Optional[float]:
    """Mean non-null position over a window ending `end_days_ago` days before
    today and spanning `length` days, or None if empty.

    end_days_ago=0, length=7 → the last 7 days; end_days_ago=7, length=7 → the
    prior week (days today−13..today−7).
    """
    hi = today.toordinal() - end_days_ago
    lo = hi - length + 1
    vals = [
        p
        for d, p in _sorted_points(series)
        if p is not None and lo <= _to_date(d).toordinal() <= hi
    ]
    return round(mean(vals), 1) if vals else None


def _value_on_or_before(series: Sequence[DatePoint], cutoff: date) -> Optional[float]:
    """Most recent non-null value dated on or before `cutoff` (for the sparse
    weekly DataForSEO series)."""
    best: Optional[tuple[date, float]] = None
    for d, p in _sorted_points(series):
        if p is None:
            continue
        dd = _to_date(d)
        if dd.toordinal() <= cutoff.toordinal():
            best = (dd, p)
    return best[1] if best else None


def _latest_value(series: Sequence[DatePoint]) -> Optional[float]:
    for d, p in reversed(_sorted_points(series)):
        if p is not None:
            return p
    return None


def _reference_ranks(
    merged: Sequence[dict], primary: str, today: date
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """(current, week_ago, month_ago) effective rank for the keyword, by source."""
    if primary == "gsc":
        series = [(r["date"], r.get("gsc_position")) for r in merged]
        current = _window_average(series, 0, GSC_SMOOTH_DAYS, today)
        week_ago = _window_average(series, WEEK_DAYS, GSC_SMOOTH_DAYS, today)
        month_ago = _window_average(series, MONTH_DAYS, GSC_SMOOTH_DAYS, today)
        return current, week_ago, month_ago
    if primary == "dataforseo":
        series = [(r["date"], r.get("tracked_rank")) for r in merged]
        current = _latest_value(series)
        from datetime import timedelta

        week_ago = _value_on_or_before(series, today - timedelta(days=DF_RECENT_TOLERANCE))
        month_ago = _value_on_or_before(series, today - timedelta(days=DF_MONTH_TOLERANCE))
        return current, week_ago, month_ago
    return None, None, None


def _fmt(pos: Optional[float]) -> str:
    return f"{round(pos)}" if pos is not None else "—"


def detect_alerts(
    keyword: str, merged: Sequence[dict], primary: str, status: str, today: date
) -> list[AlertSignal]:
    """Active alert conditions for one keyword right now (no history/dedup)."""
    signals: list[AlertSignal] = []

    # deindexed — reuse the established deindex_risk signal (GSC-only by nature).
    if status == "deindex_risk":
        signals.append(
            AlertSignal(
                alert_type="deindexed",
                source="gsc",
                message=f'"{keyword}" may be deindexed — sustained days with no GSC impressions.',
            )
        )

    if primary not in ("gsc", "dataforseo"):
        return signals

    current, week_ago, month_ago = _reference_ranks(merged, primary, today)

    if current is not None and week_ago is not None:
        delta_w = round(current - week_ago, 1)
        if week_ago <= WEEKLY_DROP_BASELINE_MAX and delta_w >= WEEKLY_DROP_SPOTS:
            signals.append(
                AlertSignal(
                    alert_type="weekly_drop",
                    source=primary,
                    from_position=week_ago,
                    to_position=current,
                    delta=delta_w,
                    message=f'"{keyword}" dropped {round(delta_w)} spots in a week '
                    f"(from {_fmt(week_ago)} to {_fmt(current)}).",
                )
            )
        if week_ago <= PAGE_ONE and current > PAGE_ONE:
            signals.append(
                AlertSignal(
                    alert_type="page_one_exit",
                    source=primary,
                    from_position=week_ago,
                    to_position=current,
                    delta=round(current - week_ago, 1),
                    message=f'"{keyword}" fell off page 1 '
                    f"(from {_fmt(week_ago)} to {_fmt(current)}).",
                )
            )

    if current is not None and month_ago is not None:
        delta_m = round(current - month_ago, 1)
        if month_ago <= THIRTY_DAY_BASELINE_MAX and delta_m >= THIRTY_DAY_DROP_SPOTS:
            signals.append(
                AlertSignal(
                    alert_type="thirty_day_drop",
                    source=primary,
                    from_position=month_ago,
                    to_position=current,
                    delta=delta_m,
                    message=f'"{keyword}" dropped {round(delta_m)} spots over 30 days '
                    f"(from {_fmt(month_ago)} to {_fmt(current)}).",
                )
            )

    return signals


def summarize_drop_alerts(opened_alerts: list[dict]) -> dict:
    """A {title, summary, severity} digest for a batch of newly-opened drop
    alerts, for the notification copy. Pure (unit-tested)."""
    n = len(opened_alerts)
    severity = "critical" if any(a.get("alert_type") == "deindexed" for a in opened_alerts) else "warning"
    title = f"{n} ranking {'drop' if n == 1 else 'drops'} detected"
    msgs = [a.get("message", "") for a in opened_alerts[:5]]
    summary = " ".join(m for m in msgs if m)
    if n > 5:
        summary += f" …and {n - 5} more."
    return {"title": title, "summary": summary, "severity": severity}


# ----------------------------------------------------------------------------
# Reconcile (I/O) — open/resolve the episode log.
# ----------------------------------------------------------------------------
def reconcile_alerts(
    supabase, client_id: str, per_keyword: list[tuple[str, str, list[AlertSignal]]], today: date
) -> dict:
    """Open new alerts and resolve cleared ones for a client's keywords.

    `per_keyword` is (keyword_id, keyword, signals) for EVERY active keyword
    (those with no signals are needed so recovered alerts get resolved). Episode
    rule: one open alert per (keyword_id, alert_type); insert when the condition
    first holds, set resolved_at when it clears.
    """
    keyword_ids = [kid for kid, _, _ in per_keyword]
    if not keyword_ids:
        return {"opened": 0, "resolved": 0}

    open_rows = (
        supabase.table("rank_alerts")
        .select("id, keyword_id, alert_type")
        .in_("keyword_id", keyword_ids)
        .is_("resolved_at", "null")
        .execute()
    ).data or []
    open_by_key = {(r["keyword_id"], r["alert_type"]): r["id"] for r in open_rows}

    active_by_kw: dict[str, set] = {kid: {s.alert_type for s in sigs} for kid, _, sigs in per_keyword}

    inserts: list[dict] = []
    for keyword_id, keyword, signals in per_keyword:
        for s in signals:
            if (keyword_id, s.alert_type) in open_by_key:
                continue  # already an open episode — don't re-fire
            inserts.append(
                {
                    "client_id": client_id,
                    "keyword_id": keyword_id,
                    "keyword": keyword,
                    "alert_type": s.alert_type,
                    "source": s.source,
                    "from_position": s.from_position,
                    "to_position": s.to_position,
                    "delta": s.delta,
                    "message": s.message,
                    "details": s.details or None,
                    "triggered_on": today.isoformat(),
                }
            )

    resolve_ids = [
        alert_id
        for (kid, atype), alert_id in open_by_key.items()
        if atype not in active_by_kw.get(kid, set())
    ]

    if inserts:
        supabase.table("rank_alerts").insert(inserts).execute()
    if resolve_ids:
        supabase.table("rank_alerts").update({"resolved_at": "now()"}).in_("id", resolve_ids).execute()

    if inserts or resolve_ids:
        logger.info(
            "rank_alerts_reconciled",
            extra={"client_id": client_id, "opened": len(inserts), "resolved": len(resolve_ids)},
        )
    # Keywords with a newly-opened alert this run — the caller uses these to
    # trigger a (rate-limited) rankability snapshot + a notification.
    opened_keyword_ids = sorted({i["keyword_id"] for i in inserts})
    opened_alerts = [
        {"keyword": i["keyword"], "alert_type": i["alert_type"], "message": i["message"]}
        for i in inserts
    ]
    return {
        "opened": len(inserts),
        "resolved": len(resolve_ids),
        "opened_keyword_ids": opened_keyword_ids,
        "opened_alerts": opened_alerts,
    }

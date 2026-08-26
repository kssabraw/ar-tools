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
  - gradual_drop     : a slow, steady slide the window-over-window rules miss —
                       a keyword bleeding ~1 spot/week never accumulates ≥6 in a
                       single 7- or 30-day window, so it would otherwise notify
                       no one. Measures CUMULATIVE displacement over ~8 weeks and
                       fires only when the decline is genuinely gradual (not a
                       cliff the sudden rules already own, not mid-window noise).
  - deindexed        : status == 'deindex_risk' (GSC-only sustained NULL signal)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
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

# --- gradual_drop tunables --------------------------------------------------
# A slow slide the fast rules miss. Endpoints (tight 7-day windows / sparse-DFS
# points) set the MAGNITUDE; three segment means set the SHAPE, so a sudden
# cliff (one segment carries almost the whole move) is rejected and left to the
# weekly/thirty-day rules that fired when it happened. Kept as module constants
# alongside the sibling thresholds above (start conservative; the on/off switch
# is settings.rank_gradual_drop_enabled).
GRADUAL_WINDOW_DAYS = 56           # ~8 weeks — long enough that ~1 spot/week clears the bar
GRADUAL_DROP_SPOTS = 5             # cumulative positions lost, start-to-end, to fire
GRADUAL_BASELINE_MAX = 20          # only alert if it was ~top 20 eight weeks ago
GRADUAL_SEGMENTS = 3               # split the window into thirds for the shape test
GRADUAL_MAX_STEP_SHARE = 0.75      # no single segment step may exceed this share of the move
GRADUAL_STEP_NOISE = 1.5           # a segment may improve by up to this and still count as a steady slide
GRADUAL_DF_TOLERANCE = 10          # DFS baseline: nearest point on/before today-(window-tol)

ALERT_TYPES = ("weekly_drop", "page_one_exit", "thirty_day_drop", "gradual_drop", "deindexed")


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


def _segment_means(
    series: Sequence[DatePoint], today: date, window_days: int, segments: int
) -> list[Optional[float]]:
    """Split the trailing `window_days` into `segments` equal date-buckets
    (oldest first) and return the mean non-null position in each (None if empty).

    Source-agnostic — works for dense GSC series and sparse weekly DataForSEO
    points alike. Used only for the SHAPE test (is the slide steady, or a cliff),
    never the magnitude, which the tighter endpoints in `detect_gradual_drop`
    carry.
    """
    hi = today.toordinal()
    lo = hi - window_days + 1
    seg_len = window_days / segments
    buckets: list[list[float]] = [[] for _ in range(segments)]
    for d, p in _sorted_points(series):
        if p is None:
            continue
        o = _to_date(d).toordinal()
        if not (lo <= o <= hi):
            continue
        idx = int((o - lo) / seg_len)
        if idx >= segments:  # the final day lands exactly on the boundary
            idx = segments - 1
        buckets[idx].append(p)
    return [round(mean(b), 1) if b else None for b in buckets]


def detect_gradual_drop(
    merged: Sequence[dict], primary: str, today: date
) -> Optional[tuple[float, float, float]]:
    """A slow, sustained multi-week slide the sudden-drop rules miss.

    Returns (baseline, current, delta) when a gradual decline is present, else
    None. 'Gradual' means ALL of:
      * magnitude — position worsened by ≥ GRADUAL_DROP_SPOTS across the window,
        measured from tight endpoints (7-day averages / sparse-DFS points), so a
        ~1 spot/week bleed that never trips a 7- or 30-day window still clears it;
      * baseline was ranking — ≤ GRADUAL_BASELINE_MAX eight weeks ago (deep
        keywords aren't worth a gradual alert);
      * steady — no segment materially better than the one before it (a real
        mid-window recovery means it isn't a monotonic slide);
      * not a cliff — no single segment step is most of the move. An old sudden
        drop (baseline pre-cliff, current post-cliff) would otherwise look
        gradual now, but the weekly/thirty-day rules already fired when it fell;
        this keeps gradual_drop distinct instead of re-alerting a stale cliff.
    """
    if primary == "gsc":
        series: list[DatePoint] = [(r["date"], r.get("gsc_position")) for r in merged]
        current = _window_average(series, 0, GSC_SMOOTH_DAYS, today)
        baseline = _window_average(
            series, GRADUAL_WINDOW_DAYS - GSC_SMOOTH_DAYS, GSC_SMOOTH_DAYS, today
        )
    elif primary == "dataforseo":
        series = [(r["date"], r.get("tracked_rank")) for r in merged]
        current = _latest_value(series)
        baseline = _value_on_or_before(
            series, today - timedelta(days=GRADUAL_WINDOW_DAYS - GRADUAL_DF_TOLERANCE)
        )
    else:
        return None

    if current is None or baseline is None or baseline > GRADUAL_BASELINE_MAX:
        return None
    delta = round(current - baseline, 1)
    if delta < GRADUAL_DROP_SPOTS:
        return None

    means = _segment_means(series, today, GRADUAL_WINDOW_DAYS, GRADUAL_SEGMENTS)
    if any(m is None for m in means):
        return None  # need coverage across the whole window to judge the shape

    steps: list[float] = []
    prev: Optional[float] = None
    for m in means:
        if prev is not None:
            step = m - prev
            if step < -GRADUAL_STEP_NOISE:
                return None  # recovered mid-window → not a steady slide
            steps.append(step)
        prev = m
    span = means[-1] - means[0]
    if span > 0 and steps and max(steps) > GRADUAL_MAX_STEP_SHARE * span:
        return None  # one segment carries the move → a cliff, not a slide

    return baseline, current, delta


def detect_alerts(
    keyword: str,
    merged: Sequence[dict],
    primary: str,
    status: str,
    today: date,
    include_gradual: bool = True,
) -> list[AlertSignal]:
    """Active alert conditions for one keyword right now (no history/dedup).

    `include_gradual` gates the slow-slide detector (settings.rank_gradual_drop_
    enabled at the call site). A gradual_drop is suppressed whenever a sudden
    drop (weekly_drop / thirty_day_drop) or deindexed already fired this run, so
    the same fall never opens two overlapping episodes.
    """
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

    # Gradual slide — only when no sudden drop already fired for this keyword
    # (else the same fall opens two overlapping episodes). page_one_exit is a
    # milestone, not a magnitude, so it doesn't suppress the gradual signal.
    if include_gradual and not (
        {"weekly_drop", "thirty_day_drop", "deindexed"} & {s.alert_type for s in signals}
    ):
        gradual = detect_gradual_drop(merged, primary, today)
        if gradual is not None:
            baseline, current_pos, delta_g = gradual
            weeks = round(GRADUAL_WINDOW_DAYS / 7)
            signals.append(
                AlertSignal(
                    alert_type="gradual_drop",
                    source=primary,
                    from_position=baseline,
                    to_position=current_pos,
                    delta=delta_g,
                    message=f'"{keyword}" has slid {round(delta_g)} spots over the past '
                    f"{weeks} weeks (from {_fmt(baseline)} to {_fmt(current_pos)}) — a slow, "
                    "steady decline that no single-week drop alert would catch.",
                    details={"window_days": GRADUAL_WINDOW_DAYS},
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

    created: list[dict] = []
    if inserts:
        created = supabase.table("rank_alerts").insert(inserts).execute().data or []
    if resolve_ids:
        supabase.table("rank_alerts").update({"resolved_at": "now()"}).in_("id", resolve_ids).execute()

    # Native task manager producer (PRD §11): open a task per new drop, close
    # tasks whose alert auto-resolved. Self-gated + best-effort inside.
    if created or resolve_ids:
        from services import task_producers

        task_producers.on_rank_alerts(client_id, created, resolve_ids)

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

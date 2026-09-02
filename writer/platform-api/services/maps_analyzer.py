"""Geo-grid analyzer + alerting for the Maps tracker (Module #5).

When a Maps scan completes, this compares each keyword's newest scan to its
PREVIOUS completed scan and detects declines in local-pack visibility, then opens
episode-deduped alerts that ride the shared notifications service (in-app + Slack).

Mirrors the Organic Rank Tracker's `rank_alerts` pattern: pure detectors return
`MapsAlertSignal`s, `reconcile_alerts` maintains an episode log (`maps_alerts`,
one open alert per (client, keyword, alert_type, sector)), and the caller emits a
notification for the batch of newly-opened alerts. All octant/ring metrics are
recomputed from the stored `rank_grid` via `maps_analytics.build_geogrid_analytics`
— the analyzer never depends on the separate `maps_report` job's persisted
`report_analytics` (the two jobs run independently on completion).

Alert types:
  - grid_rank_drop   : average grid rank worsened by >= threshold vs last scan
  - coverage_drop    : Top-3 or Top-10 pin coverage % fell by >= threshold
  - lost_pack        : went ranked->unranked in the core ring, or found-pin
                       coverage collapsed (critical)
  - area_decline     : a specific compass octant's coverage/avg-rank worsened
                       (one episode per octant)
  - competitor_surge : a competitor newly outranks the client on many more pins
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Sequence

from statistics import mean

from config import settings
from db.supabase_client import get_supabase
from services import maps_compare, maps_reporting
from services.maps_analytics import OCTANT_FULL, build_geogrid_analytics

logger = logging.getLogger(__name__)

ALERT_TYPES = (
    "grid_rank_drop",
    "coverage_drop",
    "lost_pack",
    "area_decline",
    "competitor_surge",
    "gradual_decline",
)

# An octant needs at least this many in-circle cells (in BOTH scans) before a
# per-area decline is trusted — keeps thin edge octants from firing on noise.
AREA_MIN_CELLS = 3

# --- gradual_decline shape gates --------------------------------------------
# A slow multi-scan slide the scan-over-scan detectors miss. Endpoints (oldest
# vs newest scan in the window) set MAGNITUDE; three segment means set SHAPE, so
# a sudden step (one segment carries almost the whole move — a cliff the
# grid_rank_drop/coverage_drop rules already own) is rejected. Per-metric noise
# tolerances are scaled to each metric (rank spots vs coverage points).
GRADUAL_SEGMENTS = 3
GRADUAL_MAX_STEP_SHARE = 0.75
GRADUAL_RANK_NOISE = 1.0    # avg-rank spots a segment may improve and still count as a steady slide
GRADUAL_TOP3_NOISE = 7.0    # Top-3 coverage points likewise
# Sudden magnitude alerts on the same keyword this scan suppress the gradual one
# (one decline never opens two overlapping episodes). area_decline (per-octant)
# and competitor_surge (a different axis) deliberately do NOT suppress.
GRADUAL_SUPPRESSORS = frozenset({"grid_rank_drop", "coverage_drop", "lost_pack"})


@dataclass
class MapsAlertSignal:
    alert_type: str
    sector: Optional[str] = None
    from_value: Optional[float] = None
    to_value: Optional[float] = None
    delta: Optional[float] = None
    message: str = ""
    details: dict = field(default_factory=dict)

    @property
    def key(self) -> tuple:
        return (self.alert_type, self.sector or "")


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def _pct(num: Optional[int], denom: Optional[int]) -> Optional[float]:
    if not denom:
        return None
    return round(100 * (num or 0) / denom, 1)


def _competitor_beats(competitors_above: Optional[dict]) -> tuple[dict[str, int], dict[str, str]]:
    """From a result's `competitors_above` ({directory, grid}), tally per place_id
    the number of in-circle pins where that competitor outranks the client, plus a
    place_id -> name map. Mirrors the cell-walk in `build_competitor_trends`."""
    beats: dict[str, int] = {}
    names: dict[str, str] = {}
    ca = competitors_above or {}
    directory = ca.get("directory") or {}
    for pid, info in directory.items():
        if isinstance(info, dict) and info.get("name"):
            names[pid] = info["name"]
    for row in ca.get("grid") or []:
        for cell in row or []:
            if not cell:  # None (out-of-circle) or [] (client ranks 1st)
                continue
            for entry in cell:
                if not isinstance(entry, (list, tuple)) or len(entry) < 1:
                    continue
                pid = entry[0]
                beats[pid] = beats.get(pid, 0) + 1
    return beats, names


# --- individual detectors ---------------------------------------------------
def detect_grid_rank_drop(
    keyword: str, curr: dict, prev: dict, min_drop: Optional[float] = None
) -> list[MapsAlertSignal]:
    if min_drop is None:
        min_drop = settings.maps_alert_grid_rank_drop_min
    cur_avg = curr.get("average_rank")
    prv_avg = prev.get("average_rank")
    if cur_avg is None or prv_avg is None:
        return []
    delta = round(float(cur_avg) - float(prv_avg), 2)  # positive = worse
    if delta < min_drop:
        return []
    return [
        MapsAlertSignal(
            alert_type="grid_rank_drop",
            from_value=round(float(prv_avg), 2),
            to_value=round(float(cur_avg), 2),
            delta=delta,
            message=(
                f'"{keyword}" average grid rank slipped {delta:g} spots '
                f"(from {prv_avg:.1f} to {cur_avg:.1f})."
            ),
        )
    ]


def detect_coverage_drop(
    keyword: str, curr: dict, prev: dict, min_drop_pct: Optional[float] = None
) -> list[MapsAlertSignal]:
    if min_drop_pct is None:
        min_drop_pct = settings.maps_alert_coverage_drop_pct
    cur_t3 = _pct(curr.get("top3_pins"), curr.get("total_pins"))
    prv_t3 = _pct(prev.get("top3_pins"), prev.get("total_pins"))
    cur_t10 = _pct(curr.get("top10_pins"), curr.get("total_pins"))
    prv_t10 = _pct(prev.get("top10_pins"), prev.get("total_pins"))

    candidates: list[tuple[str, float, float, float]] = []  # (label, prev, cur, drop)
    if cur_t3 is not None and prv_t3 is not None:
        candidates.append(("Top-3", prv_t3, cur_t3, round(prv_t3 - cur_t3, 1)))
    if cur_t10 is not None and prv_t10 is not None:
        candidates.append(("Top-10", prv_t10, cur_t10, round(prv_t10 - cur_t10, 1)))
    qualifying = [c for c in candidates if c[3] >= min_drop_pct]
    if not qualifying:
        return []
    label, prv, cur, drop = max(qualifying, key=lambda c: c[3])
    return [
        MapsAlertSignal(
            alert_type="coverage_drop",
            from_value=prv,
            to_value=cur,
            delta=drop,
            message=(
                f'"{keyword}" {label} grid coverage fell {drop:g} points '
                f"(from {prv:g}% to {cur:g}%)."
            ),
            details={"metric": label, "all": {c[0]: {"from": c[1], "to": c[2]} for c in candidates}},
        )
    ]


def detect_lost_pack(
    keyword: str,
    curr: dict,
    prev: dict,
    curr_an: dict,
    prev_an: dict,
    found_drop_pct: Optional[float] = None,
) -> list[MapsAlertSignal]:
    if found_drop_pct is None:
        found_drop_pct = settings.maps_alert_found_drop_pct

    # (a) core ring (innermost) — was ranked somewhere, now ranked nowhere.
    prev_rings = prev_an.get("ring_summaries") or []
    curr_rings = curr_an.get("ring_summaries") or []
    if prev_rings and curr_rings:
        pr, cr = prev_rings[0], curr_rings[0]
        if (pr.get("ranked") or 0) > 0 and (cr.get("ranked") or 0) == 0 and (cr.get("cells") or 0) > 0:
            return [
                MapsAlertSignal(
                    alert_type="lost_pack",
                    from_value=float(pr.get("ranked") or 0),
                    to_value=0.0,
                    delta=-float(pr.get("ranked") or 0),
                    message=(
                        f'"{keyword}" dropped out of the local pack in the core area — '
                        f"ranked on {pr.get('ranked')} of {cr.get('cells')} central pins last "
                        f"scan, none now."
                    ),
                    details={"reason": "core_ring"},
                )
            ]

    # (b) found-pin coverage collapse.
    cur_found = _pct(curr.get("found_pins"), curr.get("total_pins"))
    prv_found = _pct(prev.get("found_pins"), prev.get("total_pins"))
    if cur_found is not None and prv_found is not None and prv_found > 0:
        drop = round(prv_found - cur_found, 1)
        if drop >= found_drop_pct:
            return [
                MapsAlertSignal(
                    alert_type="lost_pack",
                    from_value=prv_found,
                    to_value=cur_found,
                    delta=drop,
                    message=(
                        f'"{keyword}" visibility collapsed — appears on {cur_found:g}% of pins, '
                        f"down {drop:g} points from {prv_found:g}%."
                    ),
                    details={"reason": "found_collapse"},
                )
            ]
    return []


def detect_area_decline(
    keyword: str,
    curr_an: dict,
    prev_an: dict,
    coverage_drop_pct: Optional[float] = None,
    rank_drop: Optional[float] = None,
) -> list[MapsAlertSignal]:
    if coverage_drop_pct is None:
        coverage_drop_pct = settings.maps_alert_area_coverage_drop_pct
    if rank_drop is None:
        rank_drop = settings.maps_alert_area_rank_drop

    prev_by_sector = {s["sector"]: s for s in (prev_an.get("sectors_overall") or [])}
    signals: list[MapsAlertSignal] = []
    for cur in curr_an.get("sectors_overall") or []:
        sector = cur["sector"]
        prv = prev_by_sector.get(sector)
        if not prv:
            continue
        if (cur.get("cells") or 0) < AREA_MIN_CELLS or (prv.get("cells") or 0) < AREA_MIN_CELLS:
            continue
        cov_drop = round((prv.get("coverage_pct_top3") or 0) - (cur.get("coverage_pct_top3") or 0), 1)
        cur_rank, prv_rank = cur.get("avg_rank"), prv.get("avg_rank")
        rank_delta = (
            round(float(cur_rank) - float(prv_rank), 2)
            if cur_rank is not None and prv_rank is not None
            else None
        )
        full = OCTANT_FULL.get(sector, sector)
        if cov_drop >= coverage_drop_pct:
            signals.append(
                MapsAlertSignal(
                    alert_type="area_decline",
                    sector=sector,
                    from_value=prv.get("coverage_pct_top3"),
                    to_value=cur.get("coverage_pct_top3"),
                    delta=cov_drop,
                    message=(
                        f'"{keyword}" weakened to the {full} — Top-3 coverage fell {cov_drop:g} '
                        f"points there (from {prv.get('coverage_pct_top3'):g}% to "
                        f"{cur.get('coverage_pct_top3'):g}%)."
                    ),
                    details={"metric": "coverage_pct_top3"},
                )
            )
        elif rank_delta is not None and rank_delta >= rank_drop:
            signals.append(
                MapsAlertSignal(
                    alert_type="area_decline",
                    sector=sector,
                    from_value=round(float(prv_rank), 2),
                    to_value=round(float(cur_rank), 2),
                    delta=rank_delta,
                    message=(
                        f'"{keyword}" weakened to the {full} — average rank there slipped '
                        f"{rank_delta:g} spots (from {prv_rank:.1f} to {cur_rank:.1f})."
                    ),
                    details={"metric": "avg_rank"},
                )
            )
    return signals


def detect_competitor_surge(
    keyword: str,
    curr: dict,
    prev: dict,
    min_pins: Optional[int] = None,
) -> list[MapsAlertSignal]:
    if min_pins is None:
        min_pins = settings.maps_alert_competitor_surge_pins
    cur_ca = curr.get("competitors_above")
    prv_ca = prev.get("competitors_above")
    if not cur_ca or not prv_ca:  # need both to compute a gain (skip pre-capture scans)
        return []
    cur_beats, cur_names = _competitor_beats(cur_ca)
    prv_beats, prv_names = _competitor_beats(prv_ca)
    names = {**prv_names, **cur_names}

    best: Optional[tuple[str, int, int, int]] = None  # (pid, prev, cur, gain)
    for pid, cur_pins in cur_beats.items():
        gain = cur_pins - prv_beats.get(pid, 0)
        if cur_pins >= min_pins and gain >= min_pins:
            if best is None or gain > best[3]:
                best = (pid, prv_beats.get(pid, 0), cur_pins, gain)
    if best is None:
        return []
    pid, prev_pins, cur_pins, gain = best
    name = names.get(pid) or "A competitor"
    return [
        MapsAlertSignal(
            alert_type="competitor_surge",
            from_value=float(prev_pins),
            to_value=float(cur_pins),
            delta=float(gain),
            message=(
                f'{name} surged on "{keyword}" — now outranks you on {cur_pins} pins, '
                f"up {gain} from {prev_pins} last scan."
            ),
            details={"place_id": pid, "name": names.get(pid)},
        )
    ]


def analyze_keyword(keyword: str, curr: dict, prev: Optional[dict]) -> list[MapsAlertSignal]:
    """All scan-over-scan decline signals for one keyword vs its previous scan.
    Empty when there is no previous scan (first-ever scan → nothing to compare).

    NOTE: gradual_decline is NOT computed here — it needs the multi-scan series,
    not a single prior scan, so it's produced in analyze_scan via
    detect_gradual_decline over the trailing window.
    """
    if prev is None:
        return []
    signals: list[MapsAlertSignal] = []
    signals += detect_grid_rank_drop(keyword, curr, prev)
    signals += detect_coverage_drop(keyword, curr, prev)
    curr_an = build_geogrid_analytics(curr.get("rank_grid") or [])
    prev_an = build_geogrid_analytics(prev.get("rank_grid") or [])
    signals += detect_lost_pack(keyword, curr, prev, curr_an, prev_an)
    signals += detect_area_decline(keyword, curr_an, prev_an)
    signals += detect_competitor_surge(keyword, curr, prev)
    return signals


# --- gradual_decline (slow multi-scan slide the scan-over-scan rules miss) ---
def _segment_means_over(
    points: Sequence[tuple[int, Optional[float]]], lo: int, hi: int, segments: int
) -> list[Optional[float]]:
    """Split the ordinal span [lo, hi] into `segments` equal buckets (oldest
    first) and return the mean non-null value in each (None if empty). Pure."""
    span = hi - lo + 1
    seg_len = span / segments
    buckets: list[list[float]] = [[] for _ in range(segments)]
    for o, v in points:
        if v is None or not (lo <= o <= hi):
            continue
        idx = int((o - lo) / seg_len)
        if idx >= segments:  # the newest point lands exactly on the boundary
            idx = segments - 1
        buckets[idx].append(float(v))
    return [round(mean(b), 2) if b else None for b in buckets]


def _gradual_metric(
    points: Sequence[tuple[int, Optional[float]]],
    today_ord: int,
    window_days: int,
    min_delta: float,
    noise: float,
    lower_is_better: bool,
) -> Optional[tuple[float, float, float]]:
    """One metric's cumulative worsening across the window, if it's a genuine
    gradual slide. Returns (baseline, current, worsening>0) or None. Pure.

    Magnitude comes from the window endpoints (oldest vs newest scan point);
    the three segment means gate the SHAPE — no mid-window recovery (steady),
    and no single segment carrying almost the whole move (that's a cliff the
    scan-over-scan rules already own). Oriented so 'worse' is always larger, so
    avg-rank (lower better) and Top-3 coverage (higher better) share one path.
    """
    lo = today_ord - window_days + 1
    win = [(o, v) for o, v in points if v is not None and lo <= o <= today_ord]
    if len(win) < 2:
        return None
    win.sort(key=lambda p: p[0])
    baseline, current = float(win[0][1]), float(win[-1][1])
    worsening = round((current - baseline) if lower_is_better else (baseline - current), 2)
    if worsening < min_delta:
        return None

    # Steady (no mid-window recovery): tested on the SMOOTHED 3-segment means, so
    # a single noisy up-tick between weekly scans doesn't disqualify a real slide.
    means = _segment_means_over(win, lo, today_ord, GRADUAL_SEGMENTS)
    if any(m is None for m in means):
        return None  # need coverage across the whole window to judge the shape
    oriented_means = means if lower_is_better else [-m for m in means]  # higher = worse
    for i in range(1, len(oriented_means)):
        if oriented_means[i] - oriented_means[i - 1] < -noise:
            return None  # recovered mid-window → not a steady slide

    # Not a cliff: no single scan-over-scan step carries most of the move. Measured
    # on the RAW consecutive points (not the smoothed segments), so a one-scan
    # cliff is caught wherever it falls — including straddling a segment boundary,
    # which smears across a segment mean and slipped the old segment-based test.
    # `worsening` is the sum of these steps and is > 0 here (>= min_delta), so this
    # gate always applies (no degenerate span<=0 skip).
    oriented_raw = [v if lower_is_better else -v for _, v in win]
    max_step = max(
        (oriented_raw[i] - oriented_raw[i - 1] for i in range(1, len(oriented_raw))),
        default=0.0,
    )
    if max_step > GRADUAL_MAX_STEP_SHARE * worsening:
        return None  # a cliff, not a gradual slide
    return round(baseline, 2), round(current, 2), worsening


def detect_gradual_decline(
    keyword: str,
    points: Sequence[dict],
    today: date,
    *,
    window_days: int,
    min_points: int,
    rank_drop: float,
    top3_drop: float,
) -> list[MapsAlertSignal]:
    """One combined `gradual_decline` signal for a keyword whose average grid
    rank OR Top-3 pin coverage has slid steadily across the window. Pure.

    `points`: one dict per scan, {'ord': date-ordinal, 'average_rank', 'top3_pct'}
    (any order). Each metric needs >= min_points in-window readings to be judged,
    and fires only when the slide is genuinely gradual (see _gradual_metric).
    """
    today_ord = today.toordinal()
    lo = today_ord - window_days + 1
    rank_pts = [(p["ord"], p.get("average_rank")) for p in points]
    top3_pts = [(p["ord"], p.get("top3_pct")) for p in points]
    n_rank = sum(1 for o, v in rank_pts if v is not None and lo <= o <= today_ord)
    n_top3 = sum(1 for o, v in top3_pts if v is not None and lo <= o <= today_ord)

    rank_res = (
        _gradual_metric(rank_pts, today_ord, window_days, rank_drop, GRADUAL_RANK_NOISE, True)
        if n_rank >= min_points else None
    )
    top3_res = (
        _gradual_metric(top3_pts, today_ord, window_days, top3_drop, GRADUAL_TOP3_NOISE, False)
        if n_top3 >= min_points else None
    )
    if not rank_res and not top3_res:
        return []

    weeks = round(window_days / 7)
    parts: list[str] = []
    details: dict = {"window_days": window_days}
    from_value = to_value = delta = None
    if rank_res:
        b, c, d = rank_res
        parts.append(f"average grid rank slipped {d:g} spots (from {b:.1f} to {c:.1f})")
        details["average_rank"] = {"from": b, "to": c, "delta": d}
        from_value, to_value, delta = b, c, d  # avg-rank is the primary metric when present
    if top3_res:
        b, c, d = top3_res
        parts.append(f"Top-3 coverage fell {d:g} points (from {b:g}% to {c:g}%)")
        details["top3_pct"] = {"from": b, "to": c, "delta": d}
        if not rank_res:
            from_value, to_value, delta = b, c, d
    message = (
        f'"{keyword}" has slowly declined over the past ~{weeks} weeks — '
        + " and ".join(parts)
        + " — a steady slide no single-scan drop alert would catch."
    )
    return [
        MapsAlertSignal(
            alert_type="gradual_decline",
            from_value=from_value,
            to_value=to_value,
            delta=delta,
            message=message,
            details=details,
        )
    ]


def _severity_for(alert_type: str) -> str:
    return "critical" if alert_type == "lost_pack" else "warning"


def summarize_maps_alerts(opened_alerts: list[dict]) -> dict:
    """A {title, summary, severity} digest for a batch of newly-opened maps
    alerts, for the notification copy. Pure (unit-tested)."""
    n = len(opened_alerts)
    severity = "critical" if any(a.get("alert_type") == "lost_pack" for a in opened_alerts) else "warning"
    title = f"{n} local-pack {'alert' if n == 1 else 'alerts'} detected"
    msgs = [a.get("message", "") for a in opened_alerts[:5]]
    summary = " ".join(m for m in msgs if m)
    if n > 5:
        summary += f" …and {n - 5} more."
    return {"title": title, "summary": summary, "severity": severity}


# ----------------------------------------------------------------------------
# "What changed" read view (pure, DB-free) — powers GET /maps/changes.
# ----------------------------------------------------------------------------
def build_maps_changes(
    curr_scan: Optional[dict],
    prev_scan: Optional[dict],
    curr_results: Sequence[dict],
    prev_results: Sequence[dict],
) -> dict:
    """Per-keyword scan-over-scan deltas + declining octants + fired alert types.
    Works on the first scan too (prev_scan None → has_previous False, current
    values only). Returns a plain dict matching MapsChangesResponse.

    Deltas are measured on the ground the two scans share: if the grid was
    resized between them, both sides are re-measured on the smaller grid first,
    so a widened radius doesn't render as a drop (see services.maps_compare).
    """
    curr_results, prev_results, normalized_to = maps_compare.normalize_pair(
        curr_results, prev_results
    )
    prev_by_kw = {r["keyword"]: r for r in prev_results}
    has_previous = bool(prev_scan)

    keywords: list[dict] = []
    for cur in sorted(curr_results, key=lambda r: r.get("keyword") or ""):
        kw = cur.get("keyword")
        prev = prev_by_kw.get(kw)
        cur_avg = cur.get("average_rank")
        prv_avg = prev.get("average_rank") if prev else None
        rank_delta = (
            round(float(cur_avg) - float(prv_avg), 2)
            if cur_avg is not None and prv_avg is not None
            else None
        )
        octants: list[dict] = []
        if prev:
            cur_an = build_geogrid_analytics(cur.get("rank_grid") or [])
            prev_an = build_geogrid_analytics(prev.get("rank_grid") or [])
            prev_by_sector = {s["sector"]: s for s in (prev_an.get("sectors_overall") or [])}
            for s in cur_an.get("sectors_overall") or []:
                p = prev_by_sector.get(s["sector"])
                if not p:
                    continue
                t3_now = s.get("coverage_pct_top3")
                t3_prev = p.get("coverage_pct_top3")
                rank_now, rank_prev = s.get("avg_rank"), p.get("avg_rank")
                worse = (t3_prev or 0) - (t3_now or 0) > 0 or (
                    rank_now is not None and rank_prev is not None and rank_now > rank_prev
                )
                if worse:
                    octants.append(
                        {
                            "sector": s["sector"],
                            "avg_rank_now": rank_now,
                            "avg_rank_prev": rank_prev,
                            "top3_pct_now": t3_now,
                            "top3_pct_prev": t3_prev,
                        }
                    )
            octants.sort(key=lambda o: (o["top3_pct_prev"] or 0) - (o["top3_pct_now"] or 0), reverse=True)
        alert_types = sorted({s.alert_type for s in analyze_keyword(kw, cur, prev)})
        keywords.append(
            {
                "keyword": kw,
                "average_rank_now": cur_avg,
                "average_rank_prev": prv_avg,
                "average_rank_delta": rank_delta,
                "found_pct_now": _pct(cur.get("found_pins"), cur.get("total_pins")),
                "found_pct_prev": _pct(prev.get("found_pins"), prev.get("total_pins")) if prev else None,
                "top3_pct_now": _pct(cur.get("top3_pins"), cur.get("total_pins")),
                "top3_pct_prev": _pct(prev.get("top3_pins"), prev.get("total_pins")) if prev else None,
                "top10_pct_now": _pct(cur.get("top10_pins"), cur.get("total_pins")),
                "top10_pct_prev": _pct(prev.get("top10_pins"), prev.get("total_pins")) if prev else None,
                "octants": octants,
                "alert_types": alert_types,
            }
        )
    return {
        "has_previous": has_previous,
        "current_scan_id": (curr_scan or {}).get("id"),
        "previous_scan_id": (prev_scan or {}).get("id"),
        # Set only when the grid was resized between the two scans, so the UI can
        # say which shared area the deltas were measured on.
        "compared_on_radius_miles": maps_compare.radius_miles_for_side(normalized_to),
        "keywords": keywords,
    }


# ----------------------------------------------------------------------------
# Multi-window period summary (pure, DB-free) — powers GET /maps/periods.
# Last 7 / 30 / 90 days + since-start deltas, overall + per-keyword, for the
# core visibility metrics. Computed from the existing scan time series (the same
# data build_maps_trends reads) — no new storage.
# ----------------------------------------------------------------------------
_PERIOD_METRICS = [
    ("average_rank", "Avg rank"),
    ("top3_pct", "Top-3 %"),
    ("top10_pct", "Top-10 %"),
    ("found_pct", "Found %"),
]
_PERIOD_WINDOWS = [("7d", 7), ("30d", 30), ("90d", 90)]  # plus "start"


def _date_ord(value) -> Optional[int]:
    try:
        return date.fromisoformat(str(value)[:10]).toordinal()
    except Exception:
        return None


def _overall_metrics(rows: Sequence[dict]) -> dict:
    """Pin-weighted client rollup across one scan's per-keyword rows."""
    ranks = [r["average_rank"] for r in rows if r.get("average_rank") is not None]
    total = sum(r.get("total_pins") or 0 for r in rows)
    return {
        "average_rank": round(mean(ranks), 2) if ranks else None,
        "top3_pct": _pct(sum(r.get("top3_pins") or 0 for r in rows), total),
        "top10_pct": _pct(sum(r.get("top10_pins") or 0 for r in rows), total),
        "found_pct": _pct(sum(r.get("found_pins") or 0 for r in rows), total),
    }


def _window_delta(points: Sequence[dict], key: str, now, baseline: Optional[dict]) -> dict:
    """A {from_value, now, delta, baseline_at} cell for one metric/window."""
    if baseline is None:
        return {"from_value": None, "now": now, "delta": None, "baseline_at": None}
    frm = baseline.get(key)
    delta = round(now - frm, 2) if (now is not None and frm is not None) else None
    return {"from_value": frm, "now": now, "delta": delta, "baseline_at": baseline.get("date")}


def _windows_for(points: Sequence[dict], key: str, today: date) -> dict[str, dict]:
    """7/30/90-day + since-start deltas of one metric over an oldest→newest series.
    Baseline = the latest point strictly before the current one and on/before the
    window cutoff; `start` = the earliest point (only when there's prior history)."""
    now = points[-1].get(key) if points else None
    windows: dict[str, dict] = {}
    for wk, days in _PERIOD_WINDOWS:
        cutoff = today.toordinal() - days
        baseline = None
        for p in points[:-1]:
            if p["ord"] is not None and p["ord"] <= cutoff:
                baseline = p
        windows[wk] = _window_delta(points, key, now, baseline)
    windows["start"] = _window_delta(points, key, now, points[0] if len(points) >= 2 else None)
    return windows


def _scope_for(keyword: Optional[str], points: Sequence[dict], today: date) -> dict:
    """Build a metric-by-window scope from one entity's oldest→newest series."""
    last = points[-1] if points else None
    metrics = [
        {"metric": key, "label": label, "now": last.get(key) if last else None,
         "windows": _windows_for(points, key, today)}
        for key, label in _PERIOD_METRICS
    ]
    return {"keyword": keyword, "metrics": metrics}


def build_maps_periods(scans: Sequence[dict], results: Sequence[dict], today: date) -> dict:
    """7/30/90-day + since-start deltas for the visibility metrics, overall +
    per-keyword. `scans` = completed scans ({id, completed_at}); `results` = their
    per-keyword rows. Pure — matches MapsPeriodsResponse.

    These windows can span a grid resize, and every number here is a delta, so
    the whole series is first re-measured on the grid all of its scans share
    (see services.maps_compare). Without that, widening the radius would show
    as a 90-day decline across every metric at once."""
    results, _normalized_to = maps_compare.normalize_series(results)
    meta = {s["id"]: s for s in scans}
    by_scan: dict[str, list[dict]] = {}
    by_kw: dict[str, list[dict]] = {}
    for r in results:
        sid = r.get("scan_id")
        if sid not in meta:
            continue
        by_scan.setdefault(sid, []).append(r)
        by_kw.setdefault(r["keyword"], []).append(r)

    def _point(metrics: dict, completed_at) -> dict:
        return {**metrics, "date": str(completed_at)[:10] if completed_at else None, "ord": _date_ord(completed_at)}

    overall_points = sorted(
        (p for sid, rows in by_scan.items()
         if (p := _point(_overall_metrics(rows), meta[sid].get("completed_at")))["ord"] is not None),
        key=lambda p: p["ord"],
    )
    overall = _scope_for(None, overall_points, today) if overall_points else None

    kw_scopes = []
    for kw in sorted(by_kw):
        pts = sorted(
            (p for r in by_kw[kw]
             if (p := _point(
                 {
                     "average_rank": r.get("average_rank"),
                     "top3_pct": _pct(r.get("top3_pins"), r.get("total_pins")),
                     "top10_pct": _pct(r.get("top10_pins"), r.get("total_pins")),
                     "found_pct": _pct(r.get("found_pins"), r.get("total_pins")),
                 },
                 meta[r["scan_id"]].get("completed_at"),
             ))["ord"] is not None),
            key=lambda p: p["ord"],
        )
        if pts:
            kw_scopes.append(_scope_for(kw, pts, today))

    return {
        "as_of": overall_points[-1]["date"] if overall_points else None,
        "scan_count": len(by_scan),
        "overall": overall,
        "keywords": kw_scopes,
    }


# ----------------------------------------------------------------------------
# Area-level multi-window trends + narrative (pure) — GET /maps/area-trends.
# Per compass octant: Top-3 coverage over 7/30/90/since-start, with a
# deterministic plain-English narrative naming the most-weakened directions.
# ----------------------------------------------------------------------------
_AREA_NARRATIVE_MIN_DROP = 10.0  # pts of Top-3 coverage to call an octant out
_WINDOW_PHRASE = {
    "7d": "Over the last 7 days, the {area} weakened most",
    "30d": "Over the last 30 days, the {area} weakened most",
    "90d": "Over the last 90 days, the {area} weakened most",
    "start": "Since tracking began, the {area} has weakened most",
}


def _area_narrative(areas: list[dict]) -> list[str]:
    """One line per window naming the octant with the biggest Top-3 coverage drop
    (≥ threshold). Falls back to a single positive line when nothing weakened."""
    lines: list[str] = []
    saw_window_data = False
    for wk in ("7d", "30d", "90d", "start"):
        worst = None
        for a in areas:
            d = a["windows"].get(wk)
            if not d or d.get("delta") is None:
                continue
            saw_window_data = True
            if d["delta"] < 0 and (worst is None or d["delta"] < worst["windows"][wk]["delta"]):
                worst = a
        if worst is None:
            continue
        d = worst["windows"][wk]
        if abs(d["delta"]) < _AREA_NARRATIVE_MIN_DROP:
            continue
        area = worst["sector_full"] + (f", around {worst['city']}" if worst.get("city") else "")
        lines.append(
            _WINDOW_PHRASE[wk].format(area=area)
            + f" — Top-3 coverage there fell {abs(d['delta']):.0f} pts "
            f"(from {d['from_value']:.0f}% to {d['now']:.0f}%)."
        )
    if not lines and saw_window_data:
        lines.append("Coverage has held or improved across all directions over the tracked windows.")
    return lines


def build_area_periods(
    scans: Sequence[dict], results: Sequence[dict], today: date,
    octant_city: Optional[dict] = None,
) -> dict:
    """Per-octant Top-3 coverage trend (7/30/90/since-start) + narrative, computed
    from each scan's rank grids (pin-weighted across keywords). Pure — matches
    MapsAreaTrendsResponse. `octant_city` = {sector: nearest city} (best-effort)."""
    octant_city = octant_city or {}
    meta = {s["id"]: s for s in scans}

    # Per scan, aggregate octants across keywords (pin-weighted).
    scan_oct: dict[str, dict[str, dict]] = {}
    for r in results:
        sid = r.get("scan_id")
        if sid not in meta:
            continue
        for sec in build_geogrid_analytics(r.get("rank_grid") or []).get("sectors_overall") or []:
            agg = scan_oct.setdefault(sid, {}).setdefault(
                sec["sector"], {"top3": 0, "cells": 0, "ranked": 0, "rank_sum": 0.0}
            )
            ranked = sec.get("ranked") or 0
            agg["top3"] += sec.get("top3") or 0
            agg["cells"] += sec.get("cells") or 0
            agg["ranked"] += ranked
            if sec.get("avg_rank") is not None:
                agg["rank_sum"] += sec["avg_rank"] * ranked

    # Per-octant oldest→newest series.
    series: dict[str, list[dict]] = {}
    for sid, octs in scan_oct.items():
        o = _date_ord(meta[sid].get("completed_at"))
        if o is None:
            continue
        d = str(meta[sid].get("completed_at"))[:10]
        for sector, agg in octs.items():
            series.setdefault(sector, []).append({
                "date": d, "ord": o,
                "top3_pct": _pct(agg["top3"], agg["cells"]),
                "avg_rank": round(agg["rank_sum"] / agg["ranked"], 2) if agg["ranked"] else None,
            })
    for pts in series.values():
        pts.sort(key=lambda p: p["ord"])

    areas = []
    for sector, pts in series.items():
        last = pts[-1]
        areas.append({
            "sector": sector,
            "sector_full": OCTANT_FULL.get(sector, sector),
            "city": octant_city.get(sector),
            "now_top3_pct": last["top3_pct"],
            "now_avg_rank": last["avg_rank"],
            "windows": _windows_for(pts, "top3_pct", today),
        })
    # Weakest current coverage first (None last).
    areas.sort(key=lambda a: (a["now_top3_pct"] is None, a["now_top3_pct"] or 0))

    all_pts = [p for pts in series.values() for p in pts]
    as_of = max(all_pts, key=lambda p: p["ord"])["date"] if all_pts else None
    return {
        "as_of": as_of,
        "scan_count": len(scan_oct),
        "areas": areas,
        "narrative": _area_narrative(areas),
    }


# ----------------------------------------------------------------------------
# Reconcile (I/O) — open/resolve the episode log.
# ----------------------------------------------------------------------------
def reconcile_alerts(
    supabase,
    client_id: str,
    scan_id: Optional[str],
    prev_scan_id: Optional[str],
    per_keyword: list[tuple[str, list[MapsAlertSignal]]],
    today: date,
) -> dict:
    """Open new alerts and resolve cleared ones for a client's keywords.

    `per_keyword` is (keyword, signals) for EVERY keyword in the current scan (so
    recovered alerts get resolved). Episode rule: one open alert per
    (client, keyword, alert_type, sector); insert when the condition first holds,
    set resolved_at when it clears."""
    open_rows = (
        supabase.table("maps_alerts")
        .select("id, keyword, alert_type, sector")
        .eq("client_id", client_id)
        .is_("resolved_at", "null")
        .execute()
    ).data or []
    open_by_key = {
        (r["keyword"], r["alert_type"], r.get("sector") or ""): r["id"] for r in open_rows
    }

    active_keys: set[tuple] = set()
    inserts: list[dict] = []
    for keyword, signals in per_keyword:
        for s in signals:
            full_key = (keyword, s.alert_type, s.sector or "")
            active_keys.add(full_key)
            if full_key in open_by_key:
                continue  # already an open episode — don't re-fire
            inserts.append(
                {
                    "client_id": client_id,
                    "scan_id": scan_id,
                    "prev_scan_id": prev_scan_id,
                    "keyword": keyword,
                    "alert_type": s.alert_type,
                    "sector": s.sector,
                    "from_value": s.from_value,
                    "to_value": s.to_value,
                    "delta": s.delta,
                    "message": s.message,
                    "details": s.details or None,
                    "triggered_on": today.isoformat(),
                }
            )

    resolve_ids = [
        alert_id for key, alert_id in open_by_key.items() if key not in active_keys
    ]

    created: list[dict] = []
    if inserts:
        created = supabase.table("maps_alerts").insert(inserts).execute().data or []
    if resolve_ids:
        supabase.table("maps_alerts").update({"resolved_at": "now()"}).in_("id", resolve_ids).execute()

    # Native task manager producer (PRD §11). Self-gated + best-effort inside.
    if created or resolve_ids:
        from services import task_producers

        task_producers.on_maps_alerts(client_id, created, resolve_ids)

    if inserts or resolve_ids:
        logger.info(
            "maps_alerts_reconciled",
            extra={"client_id": client_id, "opened": len(inserts), "resolved": len(resolve_ids)},
        )
    opened_alerts = [
        {
            "keyword": i["keyword"],
            "alert_type": i["alert_type"],
            "sector": i.get("sector"),
            "message": i["message"],
        }
        for i in inserts
    ]
    return {
        "opened": len(inserts),
        "resolved": len(resolve_ids),
        "opened_alerts": opened_alerts,
    }


# ----------------------------------------------------------------------------
# Orchestration (I/O) + async job.
# ----------------------------------------------------------------------------
def _previous_completed_scan(supabase, client_id: str, completed_at: Optional[str], scan_id: str) -> Optional[dict]:
    """The most recent completed SCHEDULED scan strictly older than this one (by
    completed_at). Excludes failed/cancelled so a retry isn't a bogus baseline,
    and excludes one-off runs so an ad-hoc scan can't become the baseline the
    next scheduled scan is diffed against (services.maps_reporting)."""
    query = maps_reporting.only_reporting(
        supabase.table("maps_scans")
        .select("id, completed_at")
        .eq("client_id", client_id)
        .eq("status", "complete")
        .neq("id", scan_id)
    )
    if completed_at:
        query = query.lt("completed_at", completed_at)
    rows = query.order("completed_at", desc=True).limit(1).execute().data or []
    return rows[0] if rows else None


_RESULT_FIELDS = (
    "keyword, average_rank, found_pins, total_pins, top3_pins, top10_pins, "
    "rank_grid, competitors_above"
)

# Safety ceiling on window result rows (scans × keywords); well above any real
# maps client so PostgREST's default 1000-row cap can't silently truncate the
# gradual series and strand keywords with a partial history.
_GRADUAL_MAX_RESULT_ROWS = 10_000

# Leaner than _RESULT_FIELDS: the gradual pass needs only avg_rank + Top-3
# coverage (top3_pins/total_pins) and rank_grid (which normalize_series reads to
# detect/crop a mid-window geometry change). It never uses competitors_above /
# found_pins / top10_pins, so they're dropped to avoid loading the large
# per-pin competitors_above grid across the whole window.
_GRADUAL_RESULT_FIELDS = "scan_id, keyword, average_rank, total_pins, top3_pins, rank_grid"


def _gradual_signals(supabase, client_id: str, today: date) -> dict[str, list[MapsAlertSignal]]:
    """Per-keyword gradual_decline signals over the trailing window of completed
    SCHEDULED scans. Empty when too few scans exist to judge a trend.

    Loads only reporting scans (a one-off never joins the baseline series),
    caps the scan count, normalizes the whole series onto the common grid all of
    its scans share (so a mid-window radius change can't fake a slide — the same
    guard the scan-over-scan path and the periods view use), then runs
    detect_gradual_decline per keyword.
    """
    window_days = settings.maps_gradual_window_days
    min_points = settings.maps_gradual_min_points
    start = (today - timedelta(days=window_days)).isoformat()

    # Derive the scan cap from the window so widening maps_gradual_window_days
    # can't silently truncate the series (a fixed cap would): weekly cadence
    # yields ~ceil(window/7) scans, and 2x + min_points leaves generous headroom.
    # Bounded by the absolute ceiling to cap load. DESC order means any truncation
    # keeps the most recent scans, so the effect is a conservative shorter window
    # (an under-alert), never a false positive.
    expected_weekly = -(-window_days // 7)  # ceil(window_days / 7)
    scan_cap = min(settings.maps_gradual_max_scans, 2 * expected_weekly + min_points)
    scans = (
        maps_reporting.only_reporting(
            supabase.table("maps_scans")
            .select("id, completed_at")
            .eq("client_id", client_id)
            .eq("status", "complete")
        )
        .gte("completed_at", start)
        .order("completed_at", desc=True)
        .limit(scan_cap)
        .execute()
    ).data or []
    if len(scans) < min_points:
        return {}
    if len(scans) >= scan_cap:
        # Hit the cap — more scheduled scans in the window than expected (a faster
        # cadence than weekly). We kept the most recent; the gradual window is
        # effectively shorter this run. Observable rather than silent.
        logger.info(
            "maps_gradual_window_truncated",
            extra={"client_id": client_id, "scan_cap": scan_cap, "window_days": window_days},
        )
    meta = {s["id"]: s for s in scans}

    results = (
        supabase.table("maps_scan_results")
        .select(_GRADUAL_RESULT_FIELDS)
        .in_("scan_id", list(meta.keys()))
        .limit(_GRADUAL_MAX_RESULT_ROWS)
        .execute()
    ).data or []
    if not results:
        return {}
    results, _normalized_to = maps_compare.normalize_series(results)

    by_kw: dict[str, list[dict]] = {}
    for r in results:
        m = meta.get(r.get("scan_id"))
        if not m:
            continue
        o = _date_ord(m.get("completed_at"))
        if o is None:
            continue
        by_kw.setdefault(r["keyword"], []).append(
            {
                "ord": o,
                "average_rank": r.get("average_rank"),
                "top3_pct": _pct(r.get("top3_pins"), r.get("total_pins")),
            }
        )

    out: dict[str, list[MapsAlertSignal]] = {}
    for kw, pts in by_kw.items():
        sigs = detect_gradual_decline(
            kw, pts, today,
            window_days=window_days,
            min_points=min_points,
            rank_drop=settings.maps_gradual_rank_drop,
            top3_drop=settings.maps_gradual_top3_drop,
        )
        if sigs:
            out[kw] = sigs
    return out


def analyze_scan(scan_id: str) -> dict:
    """Compare a completed scan to the client's previous completed scan; open/
    resolve alerts and emit a notification for the batch of newly-opened ones."""
    supabase = get_supabase()
    scan = (
        supabase.table("maps_scans").select("id, client_id, status, completed_at, trigger")
        .eq("id", scan_id).limit(1).execute()
    ).data
    if not scan:
        return {"skipped": "scan_not_found"}
    scan = scan[0]
    if scan.get("status") != "complete":
        return {"skipped": "scan_not_complete"}
    # Alerts drive notifications and Action Plan items, so they are reporting:
    # a one-off run never opens or resolves one. The completion hook already
    # skips these, but analyze_scan is also callable directly.
    if not maps_reporting.is_reporting_scan(scan):
        return {"skipped": "scan_not_in_reporting", "opened": 0}
    client_id = scan["client_id"]

    curr_results = (
        supabase.table("maps_scan_results").select(_RESULT_FIELDS).eq("scan_id", scan_id).execute()
    ).data or []
    if not curr_results:
        return {"skipped": "no_results"}

    prev_scan = _previous_completed_scan(supabase, client_id, scan.get("completed_at"), scan_id)
    if not prev_scan:
        return {"skipped": "no_previous_scan", "opened": 0}

    prev_results = (
        supabase.table("maps_scan_results").select(_RESULT_FIELDS)
        .eq("scan_id", prev_scan["id"]).execute()
    ).data or []

    # If the grid was resized between these two scans, re-measure both on the
    # ground they share before diffing. Otherwise the extra outer pins of a
    # widened grid — where the business ranks worse — would open alerts that
    # describe a measurement change as a ranking drop. No-op when the geometry
    # matched, which is the normal case.
    curr_cmp, prev_cmp, normalized_to = maps_compare.normalize_pair(curr_results, prev_results)
    if normalized_to:
        logger.info(
            "maps_analyze_normalized_geometry",
            extra={"scan_id": scan_id, "prev_scan_id": prev_scan["id"], "grid_side": normalized_to},
        )
    prev_by_kw = {r["keyword"]: r for r in prev_cmp}

    per_keyword = [
        (r["keyword"], analyze_keyword(r["keyword"], r, prev_by_kw.get(r["keyword"])))
        for r in curr_cmp
    ]
    today = datetime.now(timezone.utc).date()

    # Gradual multi-scan slide — added per keyword, but suppressed when a sudden
    # magnitude alert already fired for that keyword this scan (one decline never
    # opens two overlapping episodes). Best-effort: a failure here never blocks
    # the scan-over-scan alert path.
    if settings.maps_gradual_decline_enabled:
        try:
            gradual_by_kw = _gradual_signals(supabase, client_id, today)
        except Exception as exc:
            logger.warning("maps_gradual_signals_failed", extra={"scan_id": scan_id, "error": str(exc)})
            gradual_by_kw = {}
        if gradual_by_kw:
            per_keyword = [
                (
                    kw,
                    sigs + (
                        gradual_by_kw.get(kw, [])
                        if not (GRADUAL_SUPPRESSORS & {s.alert_type for s in sigs})
                        else []
                    ),
                )
                for kw, sigs in per_keyword
            ]

    result = reconcile_alerts(supabase, client_id, scan_id, prev_scan["id"], per_keyword, today)

    opened = result.get("opened_alerts") or []
    if opened:
        try:
            from services import notifications

            digest = summarize_maps_alerts(opened)
            summary = digest["summary"]
            # On a critical collapse, replace the terse "N alerts detected" digest
            # with a reasoned "why + top move" brief so the alert delivers the
            # reasoning (competitor named, sectors lost, recommended move) inline
            # to BOTH Slack and the in-app feed — not a pointer that says go look.
            # Best-effort: any failure keeps the deterministic digest summary.
            if digest["severity"] == "critical":
                try:
                    from services import maps_brief

                    client_row = (
                        supabase.table("clients").select("name")
                        .eq("id", client_id).limit(1).execute()
                    ).data
                    client_name = (client_row[0].get("name") if client_row else "") or ""
                    brief = maps_brief.generate_brief(client_name, opened)
                    if brief:
                        summary = brief
                except Exception as brief_exc:  # best-effort — never block the alert
                    logger.warning(
                        "maps_brief_generate_failed",
                        extra={"scan_id": scan_id, "error": str(brief_exc)},
                    )
            notifications.emit(
                client_id=client_id,
                kind="maps_drop",
                title=digest["title"],
                summary=summary,
                severity=digest["severity"],
                # `facts` preserves the deterministic alert digest even when
                # `summary` carries the reasoned brief, so the raw signal is never lost.
                payload={
                    "link": f"clients/{client_id}/maps",
                    "alerts": opened,
                    "facts": digest["summary"],
                },
            )
        except Exception as exc:  # notifications are best-effort
            logger.warning("maps_alert_notify_failed", extra={"scan_id": scan_id, "error": str(exc)})

        # Silently rebuild the Action Plan so the new local-pack declines surface
        # as recommendations. Rides the maps_drop notification above — the rebuild
        # itself emits nothing (trigger != "scheduled").
        try:
            from services.reopt_planner import enqueue_reopt_plan

            enqueue_reopt_plan(client_id, trigger="maps_drop")
        except Exception as exc:  # best-effort
            logger.warning("maps_drop_reopt_enqueue_failed", extra={"scan_id": scan_id, "error": str(exc)})

    return result


def enqueue_maps_analyze(scan_id: str) -> bool:
    """Enqueue scan-over-scan analysis for a completed scan (deduped)."""
    supabase = get_supabase()
    existing = (
        supabase.table("async_jobs").select("id")
        .eq("job_type", "maps_analyze").eq("entity_id", scan_id)
        .in_("status", ["pending", "running"]).limit(1).execute()
    )
    if existing.data:
        return False
    supabase.table("async_jobs").insert(
        {"job_type": "maps_analyze", "entity_id": scan_id, "payload": {"scan_id": scan_id}}
    ).execute()
    return True


async def run_maps_analyze_job(job: dict) -> None:
    """async_jobs handler for 'maps_analyze' — analyze one completed scan."""
    payload = job.get("payload") or {}
    scan_id = payload.get("scan_id")
    job_id = job["id"]
    supabase = get_supabase()
    try:
        # analyze_scan is synchronous (blocking Supabase reads + a best-effort
        # brief LLM call on a critical collapse) — run it off the event loop so
        # it never stalls the worker's other jobs.
        result = await asyncio.to_thread(analyze_scan, scan_id)
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job_id).execute()
        logger.info("maps_analyze_complete", extra={"scan_id": scan_id, **{k: result.get(k) for k in ("opened", "resolved") if k in result}})
    except Exception as exc:
        logger.error("maps_analyze_job_failed", extra={"scan_id": scan_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job_id).execute()

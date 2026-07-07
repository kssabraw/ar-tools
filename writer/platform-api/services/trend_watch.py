"""Trend watching (strategist roadmap phase 4 — the final phase).

Two watches, both deterministic:

  * ALGO-UPDATE DETECTION (cross-client): the drop classifier reads one
    client at a time, so a Google update looks like N unrelated emergencies.
    The daily sweep counts DISTINCT clients opening rank-drop alerts inside a
    sliding window; when enough of the portfolio moves together
    (>= algo_min_clients AND >= algo_min_share of clients with tracked
    keywords) an `algo_events` row is recorded (deduped by window overlap) +
    an agency-level warning notification. Every surface that renders a drop
    (Action Plan, digest) annotates drops that opened inside an event window
    — "verify against industry trackers; don't reoptimize into a rolling
    update" (Organic SOP §A).

  * SEASONAL DEMAND: DataForSEO's search-volume response carries 12 months
    of history (`monthly_searches`) which the keyword_market cache now
    stores. `demand_outlook` turns a client's tracked-keyword profiles into
    a volume-weighted seasonality read: is search demand about to rise or
    fall over the next quarter, which months peak, and which keywords swing
    hardest. Cache-only — no new paid calls; history fills on the existing
    monthly market refresh.

Pure helpers are unit-tested; the sweep is DB-reads-only, daily on the
shared scheduler (inline, like the offpage sweep — no job type).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 14          # how far back the sweep scans for co-occurring drops
_EVENT_NOTE_WINDOW_DAYS = 60  # how long a detected event keeps annotating drops
_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------------------
# Pure: algo-update window detection
# ---------------------------------------------------------------------------
def detect_algo_windows(
    alerts: list[dict],
    total_clients: int,
    min_clients: int,
    min_share: float,
    window_days: int,
) -> list[dict]:
    """Sliding-window co-occurrence over drop alerts. Pure.

    alerts: [{client_id, created_at(date/iso)}] — open OR resolved (a rolling
    update's early drops may auto-resolve before detection). Returns
    non-overlapping windows (earliest first), each {window_start, window_end,
    client_ids, drop_count}, where distinct clients >= max(min_clients,
    ceil(min_share * total_clients)).
    """
    if not alerts or total_clients <= 1:
        return []
    bar = max(min_clients, -(-int(min_share * total_clients * 100) // 100))  # ceil via int math
    by_day: dict[date, list[str]] = {}
    for a in alerts:
        d = _to_date(a.get("created_at"))
        cid = a.get("client_id")
        if d and cid:
            by_day.setdefault(d, []).append(cid)
    if not by_day:
        return []
    days = sorted(by_day)
    windows: list[dict] = []
    i = days[0]
    last = days[-1]
    claimed_until: Optional[date] = None
    while i <= last:
        end = i + timedelta(days=window_days - 1)
        clients: set[str] = set()
        drops = 0
        for d, cids in by_day.items():
            if i <= d <= end:
                clients.update(cids)
                drops += len(cids)
        if len(clients) >= bar and (claimed_until is None or i > claimed_until):
            windows.append({
                "window_start": i,
                "window_end": end,
                "client_ids": sorted(clients),
                "drop_count": drops,
            })
            claimed_until = end  # don't re-report overlapping slides of the same event
        i += timedelta(days=1)
    return windows


def windows_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """Inclusive date-range overlap. Pure."""
    return a_start <= b_end and b_start <= a_end


def _to_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Pure: seasonal demand
# ---------------------------------------------------------------------------
def seasonality_profile(monthly_searches: Optional[list[dict]]) -> Optional[dict]:
    """Relative demand index per calendar month from DataForSEO's 12-month
    history. Pure. Returns {index: {1..12: float}, peak_months, low_months}
    where 1.0 = the year's mean; None when history is too thin (<6 months)
    or flat-zero."""
    rows = [
        r for r in (monthly_searches or [])
        if r.get("month") and r.get("search_volume") is not None
    ]
    if len(rows) < 6:
        return None
    # Latest reading per calendar month (histories can span >12 rows).
    by_month: dict[int, int] = {}
    for r in sorted(rows, key=lambda r: (r.get("year") or 0, r.get("month") or 0)):
        by_month[int(r["month"])] = int(r["search_volume"])
    mean = sum(by_month.values()) / len(by_month)
    if mean <= 0:
        return None
    index = {m: round(v / mean, 2) for m, v in by_month.items()}
    ranked = sorted(index.items(), key=lambda kv: -kv[1])
    return {
        "index": index,
        "peak_months": [m for m, v in ranked[:2] if v >= 1.15],
        "low_months": [m for m, v in sorted(index.items(), key=lambda kv: kv[1])[:2] if v <= 0.85],
    }


def demand_outlook(
    profiles: list[tuple[str, Optional[int], Optional[dict]]], today: date
) -> Optional[dict]:
    """Volume-weighted portfolio demand read for the next quarter. Pure.

    profiles: [(keyword, avg_volume, seasonality_profile-or-None)].
    Compares the next 3 calendar months' mean index vs the current month's,
    volume-weighted; names the strongest per-keyword swings."""
    usable = [(kw, vol or 0, p) for kw, vol, p in profiles if p and (vol or 0) > 0]
    if not usable:
        return None
    cur_m = today.month
    next_months = [(cur_m + i - 1) % 12 + 1 for i in (1, 2, 3)]

    total_w = sum(vol for _, vol, _ in usable)
    cur_idx = sum(vol * p["index"].get(cur_m, 1.0) for _, vol, p in usable) / total_w
    next_idx = sum(
        vol * (sum(p["index"].get(m, 1.0) for m in next_months) / 3)
        for _, vol, p in usable
    ) / total_w
    change_pct = round((next_idx - cur_idx) / cur_idx * 100, 1) if cur_idx else 0.0
    direction = "rising" if change_pct >= 10 else "falling" if change_pct <= -10 else "stable"

    swings: list[dict] = []
    for kw, vol, p in usable:
        k_cur = p["index"].get(cur_m, 1.0)
        k_next = sum(p["index"].get(m, 1.0) for m in next_months) / 3
        pct = round((k_next - k_cur) / k_cur * 100, 1) if k_cur else 0.0
        if abs(pct) >= 20:
            swings.append({
                "keyword": kw, "change_pct": pct, "volume": vol,
                "peak_months": [_MONTH_NAMES[m - 1] for m in p.get("peak_months") or []],
            })
    swings.sort(key=lambda s: -abs(s["change_pct"]))
    return {
        "direction": direction,
        "change_pct_next_quarter": change_pct,
        "months_ahead": [_MONTH_NAMES[m - 1] for m in next_months],
        "keywords_with_history": len(usable),
        "notable_swings": swings[:8],
    }


# ---------------------------------------------------------------------------
# Sweep (daily, DB-reads only)
# ---------------------------------------------------------------------------
def run_trend_sweep() -> dict:
    """Detect new cross-client algo-update windows and record + notify once."""
    if not settings.trend_watch_enabled:
        return {"status": "disabled"}
    supabase = get_supabase()
    today = date.today()
    cutoff = (today - timedelta(days=_LOOKBACK_DAYS)).isoformat()
    try:
        alerts = (
            supabase.table("rank_alerts").select("client_id, created_at")
            .gte("created_at", cutoff).execute()
        ).data or []
        client_ids = {
            r["client_id"] for r in (
                supabase.table("tracked_keywords").select("client_id")
                .eq("active", True).execute()
            ).data or []
        }
    except Exception as exc:
        logger.error("trend_watch.sweep_read_failed", extra={"error": str(exc)})
        return {"status": "failed"}

    windows = detect_algo_windows(
        alerts, len(client_ids),
        settings.algo_min_clients, settings.algo_min_share, settings.algo_window_days,
    )
    if not windows:
        return {"status": "ok", "events": 0}

    try:
        existing = (
            supabase.table("algo_events").select("window_start, window_end")
            .gte("window_end", (today - timedelta(days=_LOOKBACK_DAYS * 2)).isoformat())
            .execute()
        ).data or []
    except Exception:
        existing = []

    created = 0
    for w in windows:
        if any(
            windows_overlap(
                w["window_start"], w["window_end"],
                _to_date(e["window_start"]), _to_date(e["window_end"]),
            )
            for e in existing
            if _to_date(e.get("window_start")) and _to_date(e.get("window_end"))
        ):
            continue
        try:
            names = {
                c["id"]: c.get("name") for c in (
                    supabase.table("clients").select("id, name")
                    .in_("id", w["client_ids"]).execute()
                ).data or []
            }
            supabase.table("algo_events").insert({
                "window_start": w["window_start"].isoformat(),
                "window_end": w["window_end"].isoformat(),
                "clients_affected": len(w["client_ids"]),
                "clients_total": len(client_ids),
                "drop_count": w["drop_count"],
                "affected_clients": [
                    {"client_id": cid, "name": names.get(cid)} for cid in w["client_ids"]
                ],
            }).execute()
            created += 1
            from services import notifications

            affected = ", ".join(sorted(n for n in names.values() if n))[:300]
            notifications.emit(
                None,  # agency-level — this is a portfolio event, not one client's
                "algo_update_suspected",
                f"Possible Google algorithm update — {len(w['client_ids'])} of "
                f"{len(client_ids)} clients opened rank drops "
                f"{w['window_start'].isoformat()}–{w['window_end'].isoformat()}",
                summary=(
                    f"{w['drop_count']} drop alerts across: {affected}. Verify against "
                    "industry trackers before reoptimizing — updates often keep rolling "
                    "for 1–2 weeks (Organic SOP §A)."
                ),
                severity="warning",
                payload={"window_start": w["window_start"].isoformat(),
                         "window_end": w["window_end"].isoformat()},
            )
        except Exception as exc:
            logger.warning("trend_watch.event_insert_failed", extra={"error": str(exc)})
    return {"status": "ok", "events": created}


# ---------------------------------------------------------------------------
# Reads for the surfaces
# ---------------------------------------------------------------------------
def recent_algo_events(days: int = _EVENT_NOTE_WINDOW_DAYS) -> list[dict]:
    """Events whose window ended within the last `days` (newest first)."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    try:
        return (
            get_supabase().table("algo_events").select("*")
            .gte("window_end", cutoff).order("window_end", desc=True).limit(10).execute()
        ).data or []
    except Exception:
        return []


def algo_note_for(created_at, events: list[dict]) -> Optional[str]:
    """The annotation for a drop that opened inside a detected event window
    (a small grace after the window — updates roll). Pure given events."""
    d = _to_date(created_at)
    if not d:
        return None
    for e in events:
        start, end = _to_date(e.get("window_start")), _to_date(e.get("window_end"))
        if start and end and start <= d <= end + timedelta(days=3):
            return (
                f"⚠ Opened during a suspected Google algorithm update "
                f"({e.get('clients_affected')} of {e.get('clients_total')} clients hit "
                f"{start.isoformat()}–{end.isoformat()}) — verify against industry "
                "trackers before reoptimizing; updates often keep rolling for 1–2 weeks."
            )
    return None


def build_demand_outlook(client_id: str, today: Optional[date] = None) -> Optional[dict]:
    """Seasonal demand read for a client's tracked keywords (cache-only)."""
    from services.dataforseo_rank import location_code_for

    supabase = get_supabase()
    today = today or date.today()
    client = (
        supabase.table("clients").select("*").eq("id", client_id).limit(1).execute()
    ).data or [{}]
    kws = [
        k["keyword"] for k in (
            supabase.table("tracked_keywords").select("keyword")
            .eq("client_id", client_id).eq("active", True).execute()
        ).data or []
    ]
    if not kws:
        return None
    rows = (
        supabase.table("keyword_market")
        .select("keyword, search_volume, monthly_searches")
        .in_("keyword", kws).eq("location_code", location_code_for(client[0]))
        .execute()
    ).data or []
    profiles = [
        (r["keyword"], r.get("search_volume"), seasonality_profile(r.get("monthly_searches")))
        for r in rows
    ]
    outlook = demand_outlook(profiles, today)
    if outlook:
        outlook["keywords_without_history"] = len(kws) - outlook["keywords_with_history"]
    return outlook

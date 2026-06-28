"""SERP Landscape Trends — over-time + cross-keyword views over SERP snapshots.

Organic Rank Tracker (Module #4). Reads the dated `serp_snapshots` archive (with
its derived intent signals, AIO/local flags, and the client's per-page UR /
per-domain DR) and turns it into three views:

  1. Per-keyword timeline — each dated snapshot for a keyword with the signal set,
     the client's rank/UR/DR, and the delta vs the previous snapshot (signals
     added/removed, rank/DR movement). "How did Google change for this query?"
  2. Client-level rollup — per-signal prevalence over time (% of the client's
     keywords whose SERP shows each signal), as an as-of weekly series so the
     weekly auto-capture cadence + ad-hoc captures both read cleanly. "How is
     Google shifting across the board?"
  3. "What changed" digest — signals that appeared/disappeared on each keyword
     since its previous capture.

The pure helpers (no I/O) are unit-tested; the two get_* functions do the
Supabase reads and assemble the response dicts (the router wraps them in models).
This is also the data foundation for a future automated reoptimization planner.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from db.supabase_client import get_supabase
from services.serp_snapshot import _SIGNAL_ORDER

# Signals tracked across time: AIO + local pack first (the headline shifts), then
# the SERP-feature + title-format signals in their canonical order.
TRACKED_SIGNALS = ["aio", "local"] + _SIGNAL_ORDER


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
def signal_set(snap: dict) -> set[str]:
    """The full set of intent signals present on a snapshot: the derived
    intent_signals plus the AIO and local-pack flags (their own columns)."""
    s = set(snap.get("intent_signals") or [])
    if snap.get("aio_present"):
        s.add("aio")
    if snap.get("local_intent"):
        s.add("local")
    return s


def _snap_date(snap: dict) -> date:
    return date.fromisoformat((snap.get("captured_at") or "")[:10])


def _delta(cur: Optional[int], prev: Optional[int]) -> Optional[int]:
    if cur is None or prev is None:
        return None
    return cur - prev


def compute_timeline_deltas(snaps: list[dict]) -> list[dict]:
    """Annotate each snapshot (ascending by date) with its change vs the previous:
    signals_added / signals_removed (ordered by TRACKED_SIGNALS) and the client
    rank/DR deltas. The first entry has empty/None deltas."""
    out: list[dict] = []
    prev: Optional[dict] = None
    for snap in snaps:
        cur = signal_set(snap)
        entry = dict(snap)
        if prev is not None:
            prev_sigs = signal_set(prev)
            entry["signals_added"] = [s for s in TRACKED_SIGNALS if s in cur and s not in prev_sigs]
            entry["signals_removed"] = [s for s in TRACKED_SIGNALS if s in prev_sigs and s not in cur]
            entry["client_rank_delta"] = _delta(snap.get("client_rank"), prev.get("client_rank"))
            entry["client_rd_delta"] = _delta(snap.get("client_rd"), prev.get("client_rd"))
            entry["client_dr_delta"] = _delta(snap.get("client_dr"), prev.get("client_dr"))
        else:
            entry["signals_added"] = []
            entry["signals_removed"] = []
            entry["client_rank_delta"] = None
            entry["client_rd_delta"] = None
            entry["client_dr_delta"] = None
        out.append(entry)
        prev = snap
    return out


def build_week_ends(today: date, weeks: int) -> list[date]:
    """The last `weeks` week-ending dates (oldest first), 7 days apart, ending today."""
    return [today - timedelta(days=7 * i) for i in range(weeks - 1, -1, -1)]


def weekly_prevalence(snaps_by_kw: dict[str, list[dict]], week_ends: list[date]) -> list[dict]:
    """As-of weekly prevalence. For each week-end and each keyword, take that
    keyword's most recent snapshot on-or-before the week-end and count which
    signals it shows. Returns one dict per week:
    ``{date, keyword_count, counts: {signal: n}}`` where keyword_count is how many
    keywords had any snapshot as-of that week (the denominator for %).

    Each keyword's snapshot list must be ascending by capture date.
    """
    weeks: list[dict] = []
    for we in week_ends:
        kw_count = 0
        counts = {sig: 0 for sig in TRACKED_SIGNALS}
        for snaps in snaps_by_kw.values():
            latest: Optional[dict] = None
            for snap in snaps:
                if _snap_date(snap) <= we:
                    latest = snap
                else:
                    break  # ascending — no later snapshot can qualify
            if latest is None:
                continue
            kw_count += 1
            for sig in signal_set(latest):
                if sig in counts:
                    counts[sig] += 1
        weeks.append({"date": we.isoformat(), "keyword_count": kw_count, "counts": counts})
    return weeks


def prevalence_series(weeks_list: list[dict]) -> list[dict]:
    """Pivot the per-week aggregates into one series per signal that ever appears:
    ``{signal, counts: [...], pct: [...]}`` (pct is None for a week with no data)."""
    series: list[dict] = []
    for sig in TRACKED_SIGNALS:
        counts = [w["counts"].get(sig, 0) for w in weeks_list]
        if not any(counts):
            continue  # never seen — omit the row entirely
        pct = [
            (w["counts"].get(sig, 0) / w["keyword_count"]) if w["keyword_count"] else None
            for w in weeks_list
        ]
        series.append({"signal": sig, "counts": counts, "pct": pct})
    return series


def compute_change_digest(snaps_by_kw: dict[str, list[dict]], names: dict[str, str]) -> list[dict]:
    """Per-keyword "what changed since last capture": keywords whose newest
    snapshot gained or lost a signal vs the one before it. Ascending input.
    Sorted by the number of changes (most-changed first)."""
    changes: list[dict] = []
    for kid, snaps in snaps_by_kw.items():
        if len(snaps) < 2:
            continue
        latest, prev = snaps[-1], snaps[-2]
        cur, prev_sigs = signal_set(latest), signal_set(prev)
        added = [s for s in TRACKED_SIGNALS if s in cur and s not in prev_sigs]
        removed = [s for s in TRACKED_SIGNALS if s in prev_sigs and s not in cur]
        if not (added or removed):
            continue
        changes.append(
            {
                "keyword_id": kid,
                "keyword": names.get(kid, ""),
                "captured_at": latest.get("captured_at"),
                "added": added,
                "removed": removed,
                "client_rank_delta": _delta(latest.get("client_rank"), prev.get("client_rank")),
            }
        )
    changes.sort(key=lambda c: len(c["added"]) + len(c["removed"]), reverse=True)
    return changes


# ----------------------------------------------------------------------------
# DB reads + assembly.
# ----------------------------------------------------------------------------
def get_keyword_timeline(keyword_id: str) -> Optional[dict]:
    """Per-keyword timeline: dated snapshots + client UR/DR + deltas, or None if
    the keyword doesn't exist."""
    supabase = get_supabase()
    kw = (
        supabase.table("tracked_keywords").select("id, keyword").eq("id", keyword_id).limit(1).execute()
    )
    if not kw.data:
        return None
    keyword = kw.data[0]["keyword"]

    snaps = (
        supabase.table("serp_snapshots")
        .select("id, captured_at, status, query_intent, local_intent, intent_signals, aio_present, targeted_count, client_rank")
        .eq("keyword_id", keyword_id)
        .in_("status", ["complete", "partial"])
        .order("captured_at")
        .execute()
    ).data or []
    if not snaps:
        return {"keyword_id": keyword_id, "keyword": keyword, "points": []}

    ids = [s["id"] for s in snaps]
    ur_rows = (
        supabase.table("serp_snapshot_results")
        .select("snapshot_id, url_rating, referring_domains")
        .eq("is_client", True)
        .in_("snapshot_id", ids)
        .execute()
    ).data or []
    dr_rows = (
        supabase.table("serp_snapshot_domains")
        .select("snapshot_id, domain_rating")
        .eq("is_client", True)
        .in_("snapshot_id", ids)
        .execute()
    ).data or []
    # The client can rank multiple pages → keep the strongest page per snapshot
    # (highest UR), and read both UR and page-level RD (referring domains) from
    # that same page so the two stay consistent.
    best_by: dict[str, dict] = {}
    for r in ur_rows:
        sid = r["snapshot_id"]
        cur = best_by.get(sid)
        if cur is None or (r.get("url_rating") or -1) > (cur.get("url_rating") or -1):
            best_by[sid] = r
    ur_by = {sid: r.get("url_rating") for sid, r in best_by.items()}
    rd_by = {sid: r.get("referring_domains") for sid, r in best_by.items()}
    dr_by = {r["snapshot_id"]: r.get("domain_rating") for r in dr_rows}

    enriched = [
        {
            "snapshot_id": s["id"],
            "captured_at": s["captured_at"],
            "status": s["status"],
            "query_intent": s.get("query_intent"),
            "local_intent": bool(s.get("local_intent")),
            "intent_signals": s.get("intent_signals") or [],
            "aio_present": bool(s.get("aio_present")),
            "targeted_count": s.get("targeted_count"),
            "client_rank": s.get("client_rank"),
            "client_rd": rd_by.get(s["id"]),
            "client_ur": ur_by.get(s["id"]),
            "client_dr": dr_by.get(s["id"]),
        }
        for s in snaps
    ]
    return {"keyword_id": keyword_id, "keyword": keyword, "points": compute_timeline_deltas(enriched)}


def get_client_trends(client_id: str, weeks: int = 12, today: Optional[date] = None) -> dict:
    """Client-level rollup + change digest over the SERP-snapshot archive."""
    supabase = get_supabase()
    today = today or date.today()

    kws = (
        supabase.table("tracked_keywords")
        .select("id, keyword")
        .eq("client_id", client_id)
        .eq("active", True)
        .execute()
    ).data or []
    if not kws:
        return {"week_ends": [], "keyword_counts": [], "series": [], "changes": []}
    names = {k["id"]: k["keyword"] for k in kws}

    snaps = (
        supabase.table("serp_snapshots")
        .select("keyword_id, captured_at, intent_signals, aio_present, local_intent, client_rank")
        .in_("keyword_id", list(names))
        .in_("status", ["complete", "partial"])
        .order("captured_at")
        .execute()
    ).data or []
    by_kw: dict[str, list[dict]] = {}
    for s in snaps:
        by_kw.setdefault(s["keyword_id"], []).append(s)

    week_ends = build_week_ends(today, weeks)
    weeks_list = weekly_prevalence(by_kw, week_ends)
    return {
        "week_ends": [w["date"] for w in weeks_list],
        "keyword_counts": [w["keyword_count"] for w in weeks_list],
        "series": prevalence_series(weeks_list),
        "changes": compute_change_digest(by_kw, names),
    }

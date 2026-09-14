"""Client Health board report (SerMaStr) — Chief Client Officer to the board.

The genuinely new report: one scannable portfolio scorecard, EVERY non-archived
client (green included), every week — the overview SerMaStr's deep per-client
reviews (active-signal-gated, N messages) never give. All deterministic, no paid
calls; each per-client sub-read is isolated so one module failing just drops that
column.

Pure assembly (`client_rag`/`client_line`/`build_report`) is unit-tested; the
per-client gather (`_client_row`) and `run` do the I/O.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import maps_reporting
from services.board_reports import common

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure per-client verdict + line (unit-tested)
# ---------------------------------------------------------------------------
def client_rag(row: dict) -> str:
    """RAG for one client row. Pure.
    red — frozen, any goal overdue, or a keyword at deindex risk.
    yellow — any goal behind, any open alert, or organic net-declining.
    green — otherwise."""
    if row.get("frozen") or row.get("goals_overdue", 0) or row.get("at_risk", 0):
        return "red"
    if (
        row.get("goals_behind", 0)
        or row.get("alerts", 0)
        or (row.get("dropping", 0) > row.get("climbing", 0) and row.get("dropping", 0) > 0)
    ):
        return "yellow"
    return "green"


def client_line(row: dict) -> str:
    """The one-line detail for a client row. Pure — only includes parts with data."""
    bits: list[str] = []
    if row.get("goals_total"):
        bits.append(f"goals {row.get('goals_ok', 0)}/{row['goals_total']} on track")
    if row.get("page_one") is not None:
        organic = f"{row['page_one']} on p1"
        if row.get("avg_position") is not None:
            organic += f", avg #{round(row['avg_position'])}"
        bits.append("organic: " + organic)
    if row.get("maps_pct") is not None:
        bits.append(f"maps {row['maps_pct']:g}% pack")
    if row.get("ai_pct") is not None:
        bits.append(f"AI {row['ai_pct']:g}%")
    if row.get("calls_delta"):
        bits.append(f"calls {row['calls_delta']}")
    if row.get("alerts"):
        bits.append(f"{row['alerts']} alert{'s' if row['alerts'] != 1 else ''}")
    if row.get("frozen"):
        bits.append("❄️ FROZEN")
    return " · ".join(bits) if bits else "no data yet"


def build_report(today: date, rows: list[dict]) -> dict:
    """Assemble the portfolio Client Health board report from per-client rows. Pure."""
    for r in rows:
        r["rag"] = client_rag(r)
        r["line"] = client_line(r)
    greens = [r for r in rows if r["rag"] == "green"]
    yellows = [r for r in rows if r["rag"] == "yellow"]
    reds = [r for r in rows if r["rag"] == "red"]
    total = len(rows)

    rag = common.worst_rag(r["rag"] for r in rows)
    verdict = (
        f"{len(greens)} of {total} clients on track"
        + (f", {len(yellows)} to watch" if yellows else "")
        + (f", {len(reds)} need action" if reds else "")
        + "."
    ) if total else "No clients to report."

    goals_ok = sum(r.get("goals_ok", 0) for r in rows)
    goals_total = sum(r.get("goals_total", 0) for r in rows)
    frozen = sum(1 for r in rows if r.get("frozen"))
    page_one = sum(r.get("page_one", 0) or 0 for r in rows)
    alerts = sum(r.get("alerts", 0) or 0 for r in rows)
    striking = sum(r.get("striking", 0) or 0 for r in rows)

    scorecard = [
        {"label": "Clients",
         "value": f"{len(greens)} 🟢 / {len(yellows)} 🟡 / {len(reds)} 🔴"},
        {"label": "Goals on track", "value": f"{goals_ok}/{goals_total}"},
        {"label": "Frozen", "value": str(frozen)},
        {"label": "Page-1 keywords (portfolio)", "value": str(page_one)},
        {"label": "Open alerts", "value": str(alerts)},
        {"label": "Quick wins (striking distance)", "value": str(striking)},
    ]

    # rows sorted worst-first, then by name
    order = {"red": 0, "yellow": 1, "green": 2}
    detail = sorted(rows, key=lambda r: (order.get(r["rag"], 3), (r.get("name") or "").lower()))
    row_items = [{"rag": r["rag"], "name": r.get("name") or "Client", "line": r["line"]} for r in detail]

    # wins — biggest climbers across the portfolio
    movers = []
    for r in rows:
        g = r.get("top_gainer")
        if g and g.get("delta"):
            movers.append((r.get("name"), g))
    movers.sort(key=lambda m: -(m[1].get("delta") or 0))
    wins: list[str] = []
    for name, g in movers[:3]:
        wins.append(f"{name}: “{g.get('keyword')}” up ~{g.get('delta'):g} to about #{round(g.get('position'))}"
                    if g.get("position") is not None
                    else f"{name}: “{g.get('keyword')}” up ~{g.get('delta'):g}")
    if not reds and not yellows and total:
        wins.append("Every client green this week.")

    # risks — red accounts with the reason + action
    risks: list[dict] = []
    for r in reds:
        reasons = []
        if r.get("frozen"):
            reasons.append("frozen (manual action / deindex)")
        if r.get("goals_overdue"):
            reasons.append(f"{r['goals_overdue']} goal(s) overdue")
        if r.get("at_risk"):
            reasons.append(f"{r['at_risk']} keyword(s) at deindex risk")
        risks.append({
            "issue": f"{r.get('name')} — " + (", ".join(reasons) or "off track"),
            "severity": "critical" if r.get("frozen") else None,
            "action": "recovery plan / escalate" if r.get("frozen") else "reoptimize & re-scope",
        })

    asks: list[str] = []
    if reds:
        asks.append(
            "Budget/decision for at-risk accounts: " + ", ".join(r.get("name") for r in reds[:6]) + "."
        )

    outlook = None
    outlook_bits = []
    if striking:
        outlook_bits.append(f"{striking} keyword(s) in striking distance — the quickest wins")
    overdue_goals = sum(r.get("goals_overdue", 0) for r in rows)
    if overdue_goals:
        outlook_bits.append(f"{overdue_goals} goal(s) already overdue")
    if outlook_bits:
        outlook = "; ".join(outlook_bits) + "."

    return {
        "agent": "SerMaStr",
        "title": f"Client Health board report · week of {common.monday_of(today).isoformat()}",
        "verdict": verdict, "rag": rag, "as_of": today.isoformat(),
        "scorecard": scorecard,
        "rows": {"title": "Clients", "items": row_items},
        "wins": wins, "risks": risks, "asks": asks, "outlook": outlook,
    }


# ---------------------------------------------------------------------------
# Impure per-client gather (each sub-read isolated)
# ---------------------------------------------------------------------------
def _safe(label: str, fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — a dead module drops one column, never the row
        logger.warning("board_reports.client_subread_failed", extra={"part": label, "error": str(exc)})
        return None


def _goals(supabase, cid: str, today: date, row: dict) -> None:
    from services import campaign_goals

    goals = campaign_goals.assess_goals(cid, today) or []
    measurable = [g for g in goals if g.get("status") not in ("manual",)]
    row["goals_total"] = len(measurable)
    row["goals_ok"] = sum(1 for g in measurable if g.get("status") in ("achieved", "on_track"))
    row["goals_behind"] = sum(1 for g in measurable if g.get("status") == "behind")
    row["goals_overdue"] = sum(1 for g in measurable if g.get("status") == "overdue")


def _organic(supabase, cid: str, today: date, row: dict) -> None:
    from services import rank_status, rank_summary

    kws = (
        supabase.table("tracked_keywords")
        .select("id, keyword, status").eq("client_id", cid).eq("active", True)
        .execute()
    ).data or []
    if not kws:
        return
    kw_ids = [k["id"] for k in kws]
    cutoff = (today - timedelta(days=90)).isoformat()
    metrics: dict[str, list[dict]] = {}
    for i in range(0, len(kw_ids), 200):
        chunk = kw_ids[i:i + 200]
        for m in (
            supabase.table("rank_keyword_metrics")
            .select("keyword_id, date, gsc_position, tracked_rank, clicks, impressions")
            .in_("keyword_id", chunk).gte("date", cutoff).execute()
        ).data or []:
            metrics.setdefault(m["keyword_id"], []).append(m)
    summaries = []
    for k in kws:
        s = rank_status.compute_keyword_summary(
            metrics.get(k["id"], []), today, settings.rank_gsc_coverage_days
        )
        summaries.append({**s, "status": k.get("status"), "keyword": k.get("keyword")})
    summ = rank_summary.build_rank_summary(
        summaries, striking_min=settings.striking_distance_min,
        striking_max=settings.striking_distance_max,
    )
    stats = summ.get("stats") or {}
    row["page_one"] = stats.get("page_one", 0)
    row["avg_position"] = stats.get("avg_position")
    row["at_risk"] = stats.get("at_risk", 0)
    row["striking"] = stats.get("striking", 0)
    row["climbing"] = stats.get("climbing", 0)
    row["dropping"] = stats.get("dropping", 0)
    row["top_gainer"] = summ.get("top_gainer")


def _maps(supabase, cid: str, today: date, row: dict) -> None:
    scans = (
        maps_reporting.only_reporting(supabase.table("maps_scans").select("id"))
        .eq("client_id", cid).eq("status", "complete")
        .order("completed_at", desc=True).limit(1).execute()
    ).data or []
    if not scans:
        return
    results = (
        supabase.table("maps_scan_results").select("total_pins, top3_pins")
        .eq("scan_id", scans[0]["id"]).execute()
    ).data or []
    total = sum(r.get("total_pins") or 0 for r in results)
    top3 = sum(r.get("top3_pins") or 0 for r in results)
    if total:
        row["maps_pct"] = round(100.0 * top3 / total, 1)


def _ai(supabase, cid: str, today: date, row: dict) -> None:
    from services import brand_service

    trends = brand_service.get_trends(cid)
    if trends:
        row["ai_pct"] = trends[-1].get("visibility_pct")


def _gbp_leads(supabase, cid: str, today: date, row: dict) -> None:
    from services import gbp_metrics_read

    locs = (
        supabase.table("gbp_locations").select("id")
        .eq("client_id", cid).eq("access_status", "ok").execute()
    ).data or []
    loc_ids = [l["id"] for l in locs]
    if not loc_ids:
        return
    rows = (
        supabase.table("gbp_metric_daily").select("date, metric, value")
        .in_("location_row_id", loc_ids)
        .gte("date", (today - timedelta(days=14)).isoformat()).execute()
    ).data or []
    if not rows:
        return
    cards = {c["metric"]: c for c in gbp_metrics_read.build_growth_cards(rows, today, 7)}
    calls = cards.get("CALL_CLICKS")
    if calls:
        delta = common.pct_delta(calls.get("current"), calls.get("previous"))
        row["calls_delta"] = f"{calls.get('current')}" + (f" ({delta})" if delta else "")


def _alerts(supabase, cid: str, today: date, row: dict) -> None:
    count = 0
    for table in ("rank_alerts", "maps_alerts"):
        resp = (
            supabase.table(table).select("id", count="exact")
            .eq("client_id", cid).is_("resolved_at", "null").limit(1).execute()
        )
        count += resp.count if resp.count is not None else len(resp.data or [])
    row["alerts"] = count


def _frozen(supabase, cid: str, today: date, row: dict) -> None:
    from services import freeze

    row["frozen"] = bool(freeze.is_frozen(cid))


def _client_row(supabase, client: dict, today: date) -> dict:
    """Gather one client's scorecard row — every sub-read isolated."""
    cid = client["id"]
    row: dict = {"client_id": cid, "name": client.get("name") or cid}
    for label, fn in (
        ("goals", _goals), ("organic", _organic), ("maps", _maps), ("ai", _ai),
        ("gbp_leads", _gbp_leads), ("alerts", _alerts), ("frozen", _frozen),
    ):
        _safe(label, lambda fn=fn: fn(supabase, cid, today, row))
    return row


def run(today: Optional[date] = None) -> dict:
    """Build + emit the Client Health board report. Best-effort."""
    today = today or date.today()
    supabase = get_supabase()
    clients = (
        supabase.table("clients").select("id, name")
        .eq("archived", False).order("name").execute()
    ).data or []
    rows = [_client_row(supabase, c, today) for c in clients]
    report = build_report(today, rows)
    common.attach_narrative(report, "SerMaStr, the Chief Client Officer")
    return common.emit_report(report, kind="client_board_report", today=today, link="/")

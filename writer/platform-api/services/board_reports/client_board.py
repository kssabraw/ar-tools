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
import re
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


# The redundant short lead the drop-classifier prefixes, e.g. `[A] "Sitewide" — `
# (the informative `[§A — Sitewide decline]` that follows is kept, unwrapped).
_LEAD_JUNK_RE = re.compile(r'^\s*\[[A-Za-z0-9]{1,3}\]\s*[“"][^”"]*[”"]\s*[—-]\s*')
# A leading `[CODE — Label]` classification tag → capture just "Label".
_CODE_TAG_RE = re.compile(r'^\s*\[[^\]]*?[—-]\s*([^\]]+?)\]\s*')
# Recommendation headlines too vague to be a board plan line on their own.
_VAGUE_PLAN = {
    "an indexing/visibility problem",
    "standard diagnostic, in order",
}


def _clean(text) -> str:
    """Collapse whitespace. Pure — no tag removal (that's per-field)."""
    return " ".join(str(text or "").split()).strip()


def _headline(text, cap: int = 170) -> str:
    """The board-level directive from an SOP-style line: the first sentence, with
    the '(SOP …)' runbook tail and numbered steps dropped, capped at a word
    boundary (never mid-word). Pure. Does NOT strip classification tags."""
    t = _clean(text)
    if not t:
        return ""
    i = t.find("(SOP")
    if i > 0:
        t = t[:i].rstrip(" —-:;,")
    end = t.find(". ")
    if 0 < end < cap:
        t = t[:end]
    if len(t) > cap:
        t = t[:cap].rsplit(" ", 1)[0].rstrip(" —-:;,") + "…"
    return t.strip()


def _diagnosis_headline(text, cap: int = 170) -> str:
    """A classified drop diagnosis as a board line: drop the redundant `[A]
    "Sitewide" —` lead, unwrap the `[§A — Sitewide decline]` code tag to
    'Sitewide decline — …', then take the first sentence. Pure."""
    t = _clean(text)
    if not t:
        return ""
    t = _LEAD_JUNK_RE.sub("", t)
    m = _CODE_TAG_RE.match(t)
    if m:
        t = f"{m.group(1).strip()} — {t[m.end():]}"
    return _headline(t, cap)


def _plan_line(plan_items: list[dict]) -> str:
    """ONE board plan line: the lead 1–2 distinct directive headlines, SOP runbook
    stripped, a vague indexing headline promoted to a concrete action. Pure."""
    seen: set[str] = set()
    out: list[str] = []
    for it in plan_items[:3]:
        h = _headline(it.get("recommendation"))
        if h.lower().rstrip(".") in _VAGUE_PLAN:
            h = "Confirm indexing (URL-inspect → request re-indexing) on the flagged pages"
        key = h.lower()
        if h and key not in seen:
            seen.add(key)
            out.append(h)
        if len(out) >= 2:
            break
    return "; ".join(out)


def _client_case(r: dict) -> dict:
    """Board-altitude case for one non-green client: root cause · goals · plan ·
    competitors — the specifics a board needs, not the IC runbook. Pure — reads
    the enriched row fields (goals_detail, at_risk_keywords, top_decliner,
    plan_items, episodes, competitors, market). No repeated SOP recipe, no status
    line (it's in the All-clients table), sentence-bounded (never truncated)."""
    plan_items = r.get("plan_items") or []
    detail: list[dict] = []

    # Root cause — from structured fields + the lead classified diagnosis sentence.
    rc: list[str] = []
    if r.get("frozen"):
        rc.append(f"frozen — {r.get('frozen_reason') or 'manual action / deindex'}")
    for it in plan_items:
        lead = _diagnosis_headline(it.get("diagnosis"))
        if lead:
            rc.append(lead)
            break
    ark = r.get("at_risk_keywords") or []
    if ark:
        show = ", ".join(f"“{k}”" for k in ark[:3])
        more = f" +{len(ark) - 3} more" if len(ark) > 3 else ""
        rc.append(f"{len(ark)} page(s) at deindex risk: {show}{more}")
    dec = r.get("top_decliner")
    if dec and dec.get("delta"):
        pos = f" to ~#{round(dec['position'])}" if dec.get("position") is not None else ""
        rc.append(f"biggest drop “{dec.get('keyword')}” −{abs(dec['delta']):g}{pos}")
    if rc:
        text = "; ".join(rc)
        detail.append({"label": "Root cause", "text": text[0].upper() + text[1:] + "."})

    # Goals — behind/overdue with the numbers (current → target by due).
    goal_bits: list[str] = []
    for g in (r.get("goals_detail") or [])[:3]:
        cur, tgt = g.get("current"), g.get("target")
        b = f"“{g.get('label')}” {g.get('status')}"
        if cur is not None and tgt is not None:
            b += f" ({cur:g}→{tgt:g})"
        if g.get("due"):
            b += f" by {str(g['due'])[:10]}"
        goal_bits.append(b)
    if goal_bits:
        detail.append({"label": "Goals", "text": "; ".join(goal_bits) + "."})

    # Plan — ONE board line (lead directive), plus how many responses are in flight.
    plan = _plan_line(plan_items)
    eps = r.get("episodes") or []
    if eps:
        plan = (plan + "; " if plan else "") + f"{len(eps)} response{'s' if len(eps) != 1 else ''} open"
    if plan:
        detail.append({"label": "Plan", "text": plan + "."})

    # Who & where — named competitors (+ market).
    ww: list[str] = []
    if r.get("competitors"):
        ww.append("vs " + ", ".join(r["competitors"][:5]))
    if r.get("market"):
        ww.append(str(r["market"]))
    if ww:
        detail.append({"label": "Competitors", "text": " · ".join(ww)})

    return {"name": r.get("name") or "Client", "rag": r.get("rag"), "detail": detail}


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

    # Detailed per-client cases for every non-green client (why / what's being
    # done / who & where) — the depth beyond the one-line table.
    nongreen = [r for r in detail if r["rag"] != "green"]
    case_items = [_client_case(r) for r in nongreen[:12]]
    cases = {
        "title": "Accounts that need attention",
        # Drop bare-header cases with no detail — the account is already in the
        # All-clients table; a case earns its space only when it has specifics.
        "items": [c for c in case_items if c["detail"]],
    }

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

    # The per-red detail now lives in `cases`; keep `risks` empty so the section
    # isn't a redundant terse echo above the full write-ups.
    risks: list[dict] = []

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
        "rows": {"title": "All clients", "items": row_items},
        "cases": cases,
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
    # The specific behind/overdue goals with their numbers — the WHY for a case.
    row["goals_detail"] = [
        {"label": g.get("label") or g.get("goal_type"), "status": g.get("status"),
         "current": g.get("current_value"), "target": g.get("effective_target"),
         "due": g.get("due_date")}
        for g in measurable if g.get("status") in ("behind", "overdue")
    ][:4]


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
    row["top_decliner"] = summ.get("top_decliner")
    row["at_risk_keywords"] = [
        s.get("keyword") for s in summaries
        if s.get("status") == "deindex_risk" and s.get("keyword")
    ][:6]


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

    fr = freeze.active_freeze(cid)
    row["frozen"] = bool(fr)
    if fr:
        row["frozen_reason"] = (
            fr.get("reason") or fr.get("freeze_type") or fr.get("kind")
            or "manual action / deindex"
        )


def _plan(supabase, cid: str, today: date, row: dict) -> None:
    """The client's latest Action Plan top items — the per-problem diagnosis +
    recommendation (the WHY + HOW)."""
    rows = (
        supabase.table("reopt_plans").select("items, created_at")
        .eq("client_id", cid).order("created_at", desc=True).limit(1).execute()
    ).data or []
    if not rows:
        return
    items = rows[0].get("items") or []
    # Keep enough text for a full sentence; the pure case builder trims to a
    # board-level headline (sentence-bounded), so this cap only bounds memory —
    # it must not clip mid-sentence, which is what produced truncated cases before.
    row["plan_items"] = [
        {"kind": a.get("kind"), "keyword": a.get("keyword"),
         "classification": a.get("classification"),
         "diagnosis": (a.get("diagnosis") or "")[:600],
         "recommendation": (a.get("recommendation") or "")[:600],
         "severity": a.get("severity")}
        for a in items[:3]
    ]


def _episodes(supabase, cid: str, today: date, row: dict) -> None:
    """Open response episodes (the verify-loop clock) — what's in flight."""
    rows = (
        supabase.table("response_episodes")
        .select("keyword, channel, status, opened_at")
        .eq("client_id", cid).in_("status", ["open", "escalated"])
        .order("opened_at", desc=True).limit(3).execute()
    ).data or []
    notes = []
    for ep in rows:
        opened = (ep.get("opened_at") or "")[:10]
        notes.append(
            f"{ep.get('keyword')} ({ep.get('channel')}) — {ep.get('status')}"
            + (f", open since {opened}" if opened else "")
        )
    if notes:
        row["episodes"] = notes


def _competitors(supabase, cid: str, today: date, row: dict) -> None:
    """Named competitors (the WHO) from the client's competitor registry."""
    rows = (
        supabase.table("client_competitors").select("name, domain, active")
        .eq("client_id", cid).eq("active", True).limit(6).execute()
    ).data or []
    names = [(c.get("name") or c.get("domain")) for c in rows if (c.get("name") or c.get("domain"))]
    if names:
        row["competitors"] = names[:5]


def _client_row(supabase, client: dict, today: date) -> dict:
    """Gather one client's scorecard row — every sub-read isolated."""
    cid = client["id"]
    row: dict = {
        "client_id": cid, "name": client.get("name") or cid,
        "market": client.get("business_location"),
    }
    for label, fn in (
        ("goals", _goals), ("organic", _organic), ("maps", _maps), ("ai", _ai),
        ("gbp_leads", _gbp_leads), ("alerts", _alerts), ("frozen", _frozen),
        ("plan", _plan), ("episodes", _episodes), ("competitors", _competitors),
    ):
        _safe(label, lambda fn=fn: fn(supabase, cid, today, row))
    return row


def run(today: Optional[date] = None) -> dict:
    """Build + emit the Client Health board report. Best-effort."""
    today = today or date.today()
    supabase = get_supabase()
    clients = (
        supabase.table("clients").select("id, name, business_location")
        .eq("archived", False).neq("kind", "prospect").order("name").execute()
    ).data or []
    rows = [_client_row(supabase, c, today) for c in clients]
    report = build_report(today, rows)
    common.attach_narrative(report, "SerMaStr, the Chief Client Officer")
    return common.emit_report(report, kind="client_board_report", today=today, link="/")

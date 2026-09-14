"""DORA board report — Chief of Staff / COO of the operating machine.

Owns: is the four-agent operation reliable, and where does automation need
governance. Reuses `director.read_model.build_read_model(None, today)` wholesale
(no fresh queries) and maps it to the board shape.

Pure assembly (`reliability`/`build_report`) is unit-tested; `run` does the emit.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from db.supabase_client import get_supabase
from services.board_reports import common

logger = logging.getLogger(__name__)

# seam key → (short label, board action). Mirrors director/digest._SEAM_ORDER.
_SEAM_ACTION: dict[str, tuple[str, str]] = {
    "content_shipped_degraded": ("content shipped off-brand", "re-run through voice-aware reoptimize"),
    "unwatched_seam": ("work from an unwatched producer source", "register/own the source"),
    "qa_idle": ("nothing reaching QA", "confirm the QA path is flowing"),
    "strategist_proposal_pending": ("strategist proposals awaiting a decision", "approve or dismiss"),
    "strategist_approved_unplaced": ("approved proposals not yet assigned", "place them on the board"),
    "autonomy_proposed_unactioned": ("autonomy proposals unactioned", "review the ledger"),
    "duplicate_target": ("two agents acting on one target", "de-conflict the target"),
}
# Why each seam matters — the board-level consequence (the WHY behind the flag).
_SEAM_WHY: dict[str, str] = {
    "content_shipped_degraded": "Off-brand or low-quality content reached a client — reputational + rework risk.",
    "unwatched_seam": "Work is being created by a source nothing owns — it can pile up unseen.",
    "qa_idle": "Nothing is reaching QA — deliverables may be shipping unchecked.",
    "strategist_proposal_pending": "Strategy proposals are stalling for a human decision — recommended work isn't starting.",
    "strategist_approved_unplaced": "Approved work isn't on anyone's board — it won't get done.",
    "autonomy_proposed_unactioned": "The autonomy agent flagged work nobody has actioned.",
    "duplicate_target": "Two agents are acting on the same target — wasted or conflicting effort.",
}
# Seams severe enough to make the whole operation red regardless of count.
_RED_SEAMS = {"content_shipped_degraded", "unwatched_seam"}
_RED_SEAM_COUNT = 5


def _flag_desc(flag: dict, names: dict) -> str:
    """A specific 'Client — <what> (since date)' descriptor for one seam flag. Pure."""
    cid = flag.get("client_id")
    who = names.get(cid, cid) if cid else "portfolio"
    ev = flag.get("evidence") or {}
    specific = (
        ev.get("title") or ev.get("page") or ev.get("url") or ev.get("keyword")
        or ev.get("source") or ev.get("name")
    )
    txt = str(who)
    if specific:
        txt += f" — {specific}"
    if flag.get("since"):
        txt += f" (since {str(flag['since'])[:10]})"
    return txt


def _client_names(client_ids) -> dict:
    ids = [c for c in {c for c in client_ids if c}]
    if not ids:
        return {}
    try:
        rows = get_supabase().table("clients").select("id, name").in_("id", ids).execute().data or []
        return {r["id"]: r.get("name") or r["id"] for r in rows}
    except Exception as exc:  # noqa: BLE001
        logger.warning("board_reports.dora_names_failed", extra={"error": str(exc)})
        return {}


def _rate(numer: int, denom: int) -> Optional[int]:
    return round(100 * numer / denom) if denom else None


def reliability(pace_audit: Optional[dict], sermastr_audit: Optional[dict], qa: Optional[dict]) -> dict:
    """Pull the agent-reliability rates from the audit + QA blocks. Pure.
    Returns {pace_approved_pct, pace_reverted, sermastr_approved_pct,
    sermastr_worked_pct, qa_pass_pct, qa_reviews}."""
    out: dict = {
        "pace_approved_pct": None, "pace_reverted": 0,
        "sermastr_approved_pct": None, "sermastr_worked_pct": None,
        "qa_pass_pct": None, "qa_reviews": 0,
    }
    pd = (pace_audit or {}).get("decisions") or {}
    human = sum(pd.get(k, 0) for k in
                ("approved", "approved_with_modifications", "denied", "deferred", "cancelled"))
    out["pace_approved_pct"] = _rate(pd.get("approved", 0) + pd.get("approved_with_modifications", 0), human)
    out["pace_reverted"] = pd.get("reverted", 0)

    sd = (sermastr_audit or {}).get("decisions") or {}
    decided = sd.get("approved", 0) + sd.get("dismissed", 0)
    graded = sd.get("worked", 0) + sd.get("partial", 0) + sd.get("no_effect", 0)
    out["sermastr_approved_pct"] = _rate(sd.get("approved", 0), decided)
    out["sermastr_worked_pct"] = _rate(sd.get("worked", 0), graded)

    mix = (qa or {}).get("verdict_mix") or {}
    reviews = (qa or {}).get("reviews_considered", 0)
    out["qa_reviews"] = reviews
    out["qa_pass_pct"] = _rate(mix.get("pass", 0) + mix.get("advisory", 0), reviews)
    return out


def build_report(today: date, *, model: dict, names: dict) -> dict:
    """Assemble the DORA board report from the read model. Pure."""
    flow = model.get("flow") or {}
    flags = flow.get("flags") or []
    seam_count = len(flags)
    by_seam: dict[str, list[dict]] = {}
    for f in flags:
        by_seam.setdefault(f.get("seam"), []).append(f)

    autonomy = model.get("autonomy") or {}
    rel = reliability(model.get("pace_audit"), model.get("sermastr_audit"), model.get("qa"))
    interventions = model.get("interventions") or {}
    iv = interventions.get("by_verdict") or {}
    holds = (model.get("assignment") or {}).get("open_holds") or []

    # ── RAG + verdict ──
    has_red_seam = any(s in by_seam for s in _RED_SEAMS)
    if has_red_seam or seam_count >= _RED_SEAM_COUNT:
        rag = "red"
        verdict = f"Operating model needs attention — {seam_count} cross-agent seam(s) open."
    elif seam_count:
        rag = "yellow"
        verdict = f"Machine mostly clean — {seam_count} seam(s) to clear."
    else:
        rag = "green"
        verdict = "Operating model clean — no cross-agent seams open."

    def _pct_str(v):
        return f"{v}%" if v is not None else "n/a"

    scorecard = [
        {"label": "Open cross-agent seams", "value": str(seam_count)},
        {"label": "PACE actions approved", "value": _pct_str(rel["pace_approved_pct"]),
         "delta": f"{rel['pace_reverted']} later reverted" if rel["pace_reverted"] else None},
        {"label": "SerMaStr proposals approved", "value": _pct_str(rel["sermastr_approved_pct"])},
        {"label": "SerMaStr proposals that worked", "value": _pct_str(rel["sermastr_worked_pct"])},
        {"label": "QA pass rate", "value": _pct_str(rel["qa_pass_pct"]),
         "delta": f"{rel['qa_reviews']} reviewed" if rel["qa_reviews"] else None},
        {"label": "Autonomy exec/proposed/escalated",
         "value": f"{autonomy.get('executed', 0)}/{autonomy.get('proposed', 0)}/{autonomy.get('escalated', 0)}"},
        {"label": "Interventions worked/partial/no-effect",
         "value": f"{iv.get('worked', 0)}/{iv.get('partial', 0)}/{iv.get('no_effect', 0)}"},
    ]

    wins: list[str] = []
    if rel["pace_approved_pct"] is not None and rel["pace_approved_pct"] >= 80:
        wins.append(f"PACE's actions are landing — {rel['pace_approved_pct']}% approved by the team.")
    if rel["sermastr_worked_pct"] is not None and rel["sermastr_worked_pct"] >= 50:
        wins.append(f"SerMaStr's approved plays moved the metric {rel['sermastr_worked_pct']}% of the time.")
    if autonomy.get("executed") and not autonomy.get("escalated"):
        wins.append(f"Autonomy handled {autonomy['executed']} action(s) with no escalation.")
    if not seam_count:
        wins.append("Zero cross-agent handoffs stalled this week.")

    # Detailed per-seam cases: the specific items (client + what + since), why it
    # matters, and the action. Replaces the terse risks list.
    cases_items: list[dict] = []
    for seam, items in by_seam.items():
        label, action = _SEAM_ACTION.get(seam, (seam, "review"))
        descs = [_flag_desc(f, names) for f in items[:6]]
        if len(items) > 6:
            descs.append(f"…+{len(items) - 6} more")
        detail = [{"label": "Items", "text": "; ".join(descs)}]
        if _SEAM_WHY.get(seam):
            detail.append({"label": "Why it matters", "text": _SEAM_WHY[seam]})
        detail.append({"label": "Action", "text": action[:1].upper() + action[1:] + "."})
        cases_items.append({
            "name": label, "rag": "red" if seam in _RED_SEAMS else "yellow", "detail": detail,
        })
    if holds:
        hd = "; ".join(
            f"{names.get(h.get('client_id'), h.get('client_id') or 'portfolio')} — "
            f"{h.get('name')}" + (f" ({h.get('reason')})" if h.get("reason") else "")
            for h in holds[:6]
        )
        cases_items.append({
            "name": "Capacity holds — work waiting on an assignee", "rag": "yellow",
            "detail": [
                {"label": "Items", "text": hd},
                {"label": "Action", "text": "Assign owners or add capacity."},
            ],
        })
    risks: list[dict] = []

    asks: list[str] = []
    if autonomy.get("proposed", 0) > max(autonomy.get("executed", 0), 2):
        asks.append(
            f"Governance: autonomy proposed {autonomy['proposed']} vs executed "
            f"{autonomy.get('executed', 0)} — decide whether to widen its tiers."
        )
    if holds:
        asks.append(f"Staff to clear {len(holds)} open capacity hold(s).")
    if "unwatched_seam" in by_seam:
        asks.append("An unwatched producer source is creating work — assign ownership.")

    outlook = None
    if rel["pace_approved_pct"] is not None or rel["sermastr_worked_pct"] is not None:
        lean = (
            "room to lean on automation further"
            if (rel["pace_approved_pct"] or 0) >= 80 and not cases_items
            else "hold current autonomy posture while seams clear"
        )
        outlook = f"Reliability supports {lean}."

    return {
        "agent": "DORA",
        "title": f"DORA operations board report · week of {common.monday_of(today).isoformat()}",
        "verdict": verdict, "rag": rag, "as_of": today.isoformat(),
        "scorecard": scorecard, "wins": wins, "risks": risks, "asks": asks,
        "cases": {"title": "Cross-agent seams — what, who, why & the fix", "items": cases_items},
        "outlook": outlook,
    }


def run(today: Optional[date] = None) -> dict:
    """Build + emit the DORA board report. Best-effort."""
    from services.director import read_model

    today = today or date.today()
    model = read_model.build_read_model(None, today)
    flags = (model.get("flow") or {}).get("flags") or []
    names = _client_names([f.get("client_id") for f in flags])
    report = build_report(today, model=model, names=names)
    common.attach_narrative(report, "DORA, the Chief of Staff for the agent operation")
    return common.emit_report(report, kind="ops_board_report", today=today, link="/director")

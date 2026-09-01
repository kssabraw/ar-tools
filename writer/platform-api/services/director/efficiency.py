"""DORA — agency-wide process-efficiency analysis (WS4 — agent-coordination-and-
efficiency-plan-v1_0).

DORA sees the whole picture across every agent + the coordination bus and is the
single voice that reports PROCESS efficiency to humans. This module synthesises
that picture — PACE's efficiency findings (WS2), the agent-to-agent coordination
health (WS3), the friction seams DORA already tracks (approved-but-unplaced,
autonomy-unactioned, duplicate-target), and execution effort spent on tactics the
intervention loop graded ``no_effect`` — into ranked, proposal-worded
recommendations, and delivers them three ways: a weekly ``ops_efficiency`` digest,
as-detected alerts, and on-demand in ``/director`` chat (the read model carries
``pace_efficiency`` + ``coordination`` so DORA answers it grounded).

Read-only / advisory — DORA proposes process improvements to humans and names the
owning agent; it never executes. Gated on ``director_efficiency_enabled`` (default
False). ``build_efficiency_view`` / ``build_report_body`` / ``significant`` are
pure + unit-tested; the LLM narrative + emits are best-effort.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

# The friction seams that are genuinely about work snagging BETWEEN agents (a
# coordination/process signal), as opposed to a single agent's backlog.
_FRICTION_SEAMS = {
    "strategist_approved_unplaced": "approved strategy proposals nobody placed on the board",
    "autonomy_proposed_unactioned": "autonomy candidates proposed but not acted on",
    "duplicate_target": "two agents acting on the same target",
}
_SEV_RANK = {"critical": 0, "warning": 1, "info": 2}


# ---------------------------------------------------------------------------
# Pure synthesis
# ---------------------------------------------------------------------------
def build_efficiency_view(model: dict) -> dict:
    """The deterministic process-efficiency picture from a portfolio read model.
    Pure. Returns {observations, counts} — observations are the ranked process
    leaks, each {key, area, severity, headline, recommendation}."""
    model = model or {}
    obs: list[dict] = []

    eff = model.get("pace_efficiency") or {}
    for f in eff.get("findings") or []:
        obs.append({
            "key": f"finding:{f.get('finding_key')}",
            "area": f.get("category") or "process",
            "severity": f.get("severity") or "info",
            "headline": f.get("title") or "Process finding",
            "recommendation": f.get("recommendation"),
        })

    coord = model.get("coordination") or {}
    for b in coord.get("open_blockers") or []:
        obs.append({
            "key": f"coordination:blocker:{b.get('ref')}",
            "area": "coordination", "severity": "warning",
            "headline": b.get("subject") or "Capacity/dependency blocker between agents",
            "recommendation": "Free capacity or reassign so the blocked work can move.",
        })
    stalled = coord.get("stalled") or []
    if stalled:
        obs.append({
            "key": "coordination:stalled",
            "area": "coordination", "severity": "warning",
            "headline": f"{len(stalled)} handoff(s) stalled between agents",
            "recommendation": ("Chase the oldest handoffs — work is sitting in the gap "
                               "between agents, not being worked."),
        })
    if coord.get("loops"):
        obs.append({
            "key": "coordination:loops",
            "area": "coordination", "severity": "info",
            "headline": f"{len(coord['loops'])} back-and-forth loop(s) between agents",
            "recommendation": "A handoff is bouncing — clarify ownership to break the loop.",
        })

    flags = (model.get("flow") or {}).get("flags") or []
    seam_counts: dict[str, int] = {}
    for fl in flags:
        seam_counts[fl.get("seam")] = seam_counts.get(fl.get("seam"), 0) + 1
    for seam, desc in _FRICTION_SEAMS.items():
        n = seam_counts.get(seam, 0)
        if n:
            obs.append({
                "key": f"seam:{seam}",
                "area": "coordination", "severity": "warning" if seam != "duplicate_target" else "info",
                "headline": f"{n} case(s) of {desc}",
                "recommendation": ("Route to the owning agent (PACE places/chases; SerMaStr "
                                   "decides strategy) — the work is decided but not flowing."),
            })

    interv = model.get("interventions") or {}
    no_effect = (interv.get("by_verdict") or {}).get("no_effect", 0)
    if no_effect >= 3:
        obs.append({
            "key": "effort:no_effect",
            "area": "effort", "severity": "info",
            "headline": f"{no_effect} tactic(s) graded no_effect — execution effort not moving metrics",
            "recommendation": ("Feed this back to SerMaStr's tactic self-analysis so it stops "
                               "proposing what doesn't work; retire the dead tactics."),
        })

    obs.sort(key=lambda o: _SEV_RANK.get(o.get("severity"), 3))
    counts = {"observations": len(obs),
              "by_area": _tally(obs, "area"),
              "by_severity": _tally(obs, "severity")}
    return {"observations": obs, "counts": counts}


def _tally(obs: list[dict], field: str) -> dict:
    out: dict[str, int] = {}
    for o in obs:
        out[o.get(field)] = out.get(o.get(field), 0) + 1
    return out


def significant(view: dict) -> list[dict]:
    """The observations worth an as-detected alert — warning/critical only (a
    blocker, a rework/slip finding, a stalled handoff), each with its stable key.
    Pure."""
    return [o for o in (view.get("observations") or [])
            if o.get("severity") in ("warning", "critical")]


def alertable(view: dict, cap: Optional[int] = None) -> list[dict]:
    """The significant observations to actually alert on this run, capped so a
    day when many findings open at once can't burst dozens of notifications (the
    rest still surface in the weekly briefing). Observations are already
    severity-ranked, so the cap keeps the worst. Pure."""
    items = significant(view)
    cap = cap if cap is not None else settings.director_efficiency_max_alerts
    return items[:cap] if cap and cap > 0 else items


def build_report_body(view: dict) -> str:
    """The deterministic weekly report body (Slack mrkdwn). Pure. "" when there's
    nothing worth reporting (all-clear)."""
    obs = view.get("observations") or []
    if not obs:
        return ""
    lines = ["*Process efficiency — where the agency can run leaner*"]
    for o in obs[:12]:
        mark = {"critical": "🔴", "warning": "🟠"}.get(o.get("severity"), "•")
        line = f"{mark} {o.get('headline')}"
        if o.get("recommendation"):
            line += f" — _{o['recommendation']}_"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM narrative (best-effort)
# ---------------------------------------------------------------------------
def narrate(report_body: str, model: Optional[str] = None) -> str:
    """Rewrite the deterministic report into a ranked, owner-facing process-
    efficiency briefing. Fed the exact observations + told to preserve them, so
    there's no fabrication surface. "" on any failure (caller keeps the body)."""
    if not report_body:
        return ""
    from services import report_llm

    system = (
        "You are DORA, Director of Operations for an SEO agency, briefing the owner "
        "in Slack on where the agency's PROCESSES can run more efficiently — how work "
        "flows BETWEEN the agents (SerMaStr proposes, PACE executes, QA judges), not "
        "any one campaign. Rewrite the findings below into a short, ranked briefing: "
        "lead with the biggest efficiency win, group related items, and for each name "
        "the concrete change and which agent/surface owns it. You are READ-ONLY — "
        "propose, never claim you did it. Slack mrkdwn only: *bold* not **bold**, no "
        "# headers, no tables. Keep EVERY count and fact exactly as given — never "
        "invent or drop one."
    )
    try:
        txt = report_llm.generate_text_sync(
            user=report_body, max_tokens=800, system=system,
            model=model or settings.director_efficiency_model, log_tag="director_efficiency")
        return (txt or "").strip()
    except Exception as exc:
        logger.warning("director_efficiency_narrate_failed", extra={"error": str(exc)})
        return ""


# ---------------------------------------------------------------------------
# Delivery (best-effort — never raises into the scheduler)
# ---------------------------------------------------------------------------
def run_weekly(today: Optional[date] = None) -> dict:
    """The weekly process-efficiency digest to #dora (LLM-narrated). Self-gated on
    director_efficiency_enabled + director_digest_weekday; suppressed on an
    all-clear week. Best-effort."""
    today = today or date.today()
    if not (settings.director_enabled and settings.director_efficiency_enabled):
        return {"emitted": False, "reason": "disabled"}
    weekday = settings.director_digest_weekday
    if weekday is None or today.weekday() != int(weekday):
        return {"emitted": False, "reason": "not_due"}
    try:
        from services import notifications
        from services.director import read_model

        view = build_efficiency_view(read_model.build_read_model(None, today))
        body = build_report_body(view)
        if not body:
            return {"emitted": False, "reason": "all_clear"}
        narrated = narrate(body)
        if narrated:
            body = narrated
        iso_year, iso_week, _ = today.isocalendar()
        nid = notifications.emit(
            client_id=None, kind="ops_efficiency",
            title="Process efficiency — weekly briefing",
            summary=body, severity="info",
            payload={"link": "/director"},
            dedupe_key=f"ops_efficiency:weekly:{iso_year}-W{iso_week:02d}",
        )
        return {"emitted": nid is not None, "observations": view["counts"]["observations"]}
    except Exception as exc:  # noqa: BLE001
        logger.warning("director_efficiency_weekly_failed", extra={"error": str(exc)})
        return {"emitted": False, "reason": "error"}


def run_daily_alerts(today: Optional[date] = None) -> dict:
    """As-detected alerts: one ops_efficiency notification per newly-significant
    process leak (deduped by its stable key, so it fires once when it first
    appears). Self-gated on director_efficiency_enabled; best-effort."""
    today = today or date.today()
    if not (settings.director_enabled and settings.director_efficiency_enabled):
        return {"alerted": 0, "reason": "disabled"}
    try:
        from services import notifications
        from services.director import read_model

        view = build_efficiency_view(read_model.build_read_model(None, today))
        items = alertable(view)
        alerted = 0
        for o in items:
            nid = notifications.emit(
                client_id=None, kind="ops_efficiency",
                title="Process inefficiency detected",
                summary=(f"{o.get('headline')}"
                         + (f"\n_{o['recommendation']}_" if o.get("recommendation") else "")),
                severity="warning",
                payload={"link": "/director", "area": o.get("area")},
                dedupe_key=f"ops_efficiency:alert:{o.get('key')}",
            )
            if nid is not None:
                alerted += 1
        return {"alerted": alerted, "significant": len(items)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("director_efficiency_alerts_failed", extra={"error": str(exc)})
        return {"alerted": 0, "reason": "error"}

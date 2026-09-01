"""Director of Operations — audit-log health monitoring (owner ask 2026-09-01).

DORA reads SerMaStr's and PACE's OWN action logs (``sermastr_action_log`` /
``pace_action_log``) and checks that the propose→decide→outcome pipeline is
running EFFICIENTLY — not just that the agents are producing rows, but that
their output is being acted on and is actually working. Four signals (owner-
chosen):

  * ``stale_pending``     — SerMaStr proposals sitting undecided past the dwell
                            threshold (the human isn't approving/dismissing, so
                            the agent's advice is piling up unused).
  * ``low_effectiveness`` — an approved proposal KIND with a high no-effect rate
                            (SerMaStr is trusted on it, but it doesn't move the
                            metric).
  * ``high_dismiss``      — a proposal KIND (SerMaStr) or action KIND (PACE)
                            dismissed / reverted far more often than accepted
                            (the agent is proposing low-value work).
  * ``coverage_gap``      — an agent produced NOTHING in the window, or clients
                            behind on a goal have no strategy proposal at all
                            (the agent isn't engaging where it should).

These are PROCESS-HEALTH findings, deliberately kept OUT of ``flow.flags`` — a
dismiss-rate problem is an agency-level tuning signal, not one client's board
task. The daily reconcile emits them as ``ops_seam`` notifications (deduped per
ISO week so a persistent problem alerts once/week, not daily); the weekly ops
digest renders them as an "Agent process health" section.

Everything here is PURE (unit-tested); the windowed ledger reads live in
``providers.prov_audit_health`` and feed these assessors their signals.
"""

from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Finding shape
# ---------------------------------------------------------------------------
#   {"agent", "kind", "client_id", "ident", "label", "detail", "severity"}
# ``ident`` is stable per (agent, kind, subject) so the reconciler can build a
# per-ISO-week dedupe key that alerts a persistent finding at most once a week.

_AGENT_LABEL = {"sermastr": "SerMaStr", "pace": "PACE"}


def _pct(rate: float) -> int:
    return int(round((rate or 0.0) * 100))


# ---------------------------------------------------------------------------
# Per-signal assessors (pure)
# ---------------------------------------------------------------------------
def assess_sermastr_dismiss(by_kind: dict, *, min_samples: int, threshold: float,
                            client_id: Optional[str] = None) -> list[dict]:
    """SerMaStr proposal kinds dismissed at/above ``threshold`` over ≥
    ``min_samples`` DECIDED proposals — the agent is proposing work humans keep
    rejecting."""
    findings: list[dict] = []
    for kind, s in sorted((by_kind or {}).items()):
        decided = s.get("decided", 0)
        if decided < min_samples or s.get("dismiss_rate", 0.0) < threshold:
            continue
        findings.append({
            "agent": "sermastr", "kind": "high_dismiss", "client_id": client_id,
            "ident": f"sermastr:high_dismiss:{kind}",
            "label": (f"SerMaStr `{kind}` proposals are dismissed "
                      f"{_pct(s['dismiss_rate'])}% of the time ({s['dismissed']}/{decided} decided)"),
            "detail": {"proposal_kind": kind, "dismissed": s["dismissed"],
                       "decided": decided, "dismiss_rate": s["dismiss_rate"]},
            "severity": "warning",
        })
    return findings


def assess_sermastr_ineffective(by_kind: dict, *, min_samples: int, threshold: float,
                                client_id: Optional[str] = None) -> list[dict]:
    """SerMaStr proposal kinds whose APPROVED, graded tactics show no_effect at/
    above ``threshold`` over ≥ ``min_samples`` graded outcomes — trusted advice
    that isn't moving the metric."""
    findings: list[dict] = []
    for kind, s in sorted((by_kind or {}).items()):
        graded = s.get("graded", 0)
        if graded < min_samples or s.get("ineffective_rate", 0.0) < threshold:
            continue
        findings.append({
            "agent": "sermastr", "kind": "low_effectiveness", "client_id": client_id,
            "ident": f"sermastr:low_effectiveness:{kind}",
            "label": (f"SerMaStr `{kind}` showed no measurable effect on "
                      f"{_pct(s['ineffective_rate'])}% of graded tactics "
                      f"({s['no_effect']}/{graded})"),
            "detail": {"proposal_kind": kind, "no_effect": s["no_effect"],
                       "graded": graded, "ineffective_rate": s["ineffective_rate"]},
            "severity": "warning",
        })
    return findings


def assess_pace_reject(by_action: dict, *, min_samples: int, threshold: float,
                       client_id: Optional[str] = None) -> list[dict]:
    """PACE action kinds denied/reverted at/above ``threshold`` over ≥
    ``min_samples`` logged actions — PACE keeps proposing/doing work humans
    refuse or undo. ``reject_rate`` = (denied + reverted) / total."""
    findings: list[dict] = []
    for action, s in sorted((by_action or {}).items()):
        total = s.get("total", 0)
        if total < min_samples or s.get("reject_rate", 0.0) < threshold:
            continue
        declined = s.get("denied", 0) + s.get("reverted", 0)
        findings.append({
            "agent": "pace", "kind": "high_dismiss", "client_id": client_id,
            "ident": f"pace:high_dismiss:{action}",
            "label": (f"PACE `{action}` is declined or undone "
                      f"{_pct(s['reject_rate'])}% of the time ({declined}/{total})"),
            "detail": {"action": action, "declined": declined, "total": total,
                       "reject_rate": s["reject_rate"]},
            "severity": "warning",
        })
    return findings


def assess_stale_pending(stale_count: int, *, pending_days: int, min_count: int) -> list[dict]:
    """One agency-level finding when ≥ ``min_count`` SerMaStr proposals have sat
    undecided longer than ``pending_days`` — the decision queue is backing up.
    (Per-proposal nudges are already handled by the ``strategist_proposal_pending``
    board seam; this is the aggregate "the queue is stalling" signal.)"""
    if (stale_count or 0) < min_count:
        return []
    return [{
        "agent": "sermastr", "kind": "stale_pending", "client_id": None,
        "ident": "sermastr:stale_pending",
        "label": (f"{stale_count} SerMaStr proposals have waited over {pending_days} days "
                  f"for an approve/dismiss decision"),
        "detail": {"stale_count": stale_count, "pending_days": pending_days},
        "severity": "warning",
    }]


def assess_coverage(*, sermastr_total: int, pace_total: int,
                    sermastr_active: bool, pace_active: bool,
                    behind_uncovered: Optional[list[str]] = None,
                    min_uncovered: int = 1) -> list[dict]:
    """Coverage gaps — an active agent that produced NOTHING in the window, and
    clients behind on a goal with no strategy proposal at all. Only fires for an
    agent that is actually enabled (a disabled agent producing nothing is
    expected, not a gap)."""
    findings: list[dict] = []
    if sermastr_active and (sermastr_total or 0) == 0:
        findings.append({
            "agent": "sermastr", "kind": "coverage_gap", "client_id": None,
            "ident": "sermastr:coverage_gap:no_activity",
            "label": "SerMaStr logged no proposals in the window — it isn't proposing anything",
            "detail": {"proposals": 0}, "severity": "warning",
        })
    if pace_active and (pace_total or 0) == 0:
        findings.append({
            "agent": "pace", "kind": "coverage_gap", "client_id": None,
            "ident": "pace:coverage_gap:no_activity",
            "label": "PACE logged no client-affecting actions in the window — it isn't acting on anything",
            "detail": {"actions": 0}, "severity": "warning",
        })
    behind = [c for c in (behind_uncovered or []) if c]
    if sermastr_active and len(behind) >= max(min_uncovered, 1):
        findings.append({
            "agent": "sermastr", "kind": "coverage_gap", "client_id": None,
            "ident": "sermastr:coverage_gap:behind_goals",
            "label": (f"{len(behind)} client(s) behind on a goal have no SerMaStr proposal "
                      f"addressing it"),
            "detail": {"client_ids": behind, "count": len(behind)},
            "severity": "warning",
        })
    return findings


# ---------------------------------------------------------------------------
# Assembly (pure)
# ---------------------------------------------------------------------------
def build_findings(*, sermastr_signals: Optional[dict], pace_signals: Optional[dict],
                   sermastr_total: int, pace_total: int, stale_count: int,
                   behind_uncovered: Optional[list[str]], thresholds: dict,
                   sermastr_active: bool, pace_active: bool,
                   client_id: Optional[str] = None) -> list[dict]:
    """Compose every audit-health signal into one flat findings list. Pure.

    ``thresholds`` = {min_samples, dismiss_threshold, ineffective_threshold,
    stale_pending_min, pending_days, min_uncovered}. Rate findings are scoped to
    ``client_id`` (a per-client DORA read); coverage + stale are agency-level and
    only computed when ``client_id`` is None (the caller passes empties otherwise).
    """
    ms = thresholds["min_samples"]
    findings: list[dict] = []
    sk = (sermastr_signals or {}).get("by_kind") or {}
    pa = (pace_signals or {}).get("by_action") or {}
    findings += assess_sermastr_dismiss(sk, min_samples=ms,
                                        threshold=thresholds["dismiss_threshold"], client_id=client_id)
    findings += assess_sermastr_ineffective(sk, min_samples=ms,
                                            threshold=thresholds["ineffective_threshold"], client_id=client_id)
    findings += assess_pace_reject(pa, min_samples=ms,
                                   threshold=thresholds["dismiss_threshold"], client_id=client_id)
    findings += assess_stale_pending(stale_count, pending_days=thresholds["pending_days"],
                                     min_count=thresholds["stale_pending_min"])
    findings += assess_coverage(sermastr_total=sermastr_total, pace_total=pace_total,
                                sermastr_active=sermastr_active, pace_active=pace_active,
                                behind_uncovered=behind_uncovered,
                                min_uncovered=thresholds.get("min_uncovered", 1))
    return findings


# ---------------------------------------------------------------------------
# Rendering (pure)
# ---------------------------------------------------------------------------
def finding_dedupe_key(ident: str, iso_year: int, iso_week: int) -> str:
    """A per-ISO-week dedupe key so a daily check alerts a persistent finding at
    most once per week (mirrors the qa_idle weekly dedupe)."""
    return f"ops_seam:audit:{ident}:{iso_year}-W{iso_week:02d}"


_KIND_TITLE = {
    "stale_pending": "Decision queue backing up",
    "low_effectiveness": "Tactic not moving the metric",
    "high_dismiss": "Work getting rejected",
    "coverage_gap": "Agent coverage gap",
}


def notification_title(finding: dict) -> str:
    agent = _AGENT_LABEL.get(finding.get("agent"), finding.get("agent") or "Agent")
    return f"{agent} process health — {_KIND_TITLE.get(finding.get('kind'), 'issue')}"


def format_health_section(findings: list[dict]) -> list[str]:
    """Slack-mrkdwn bullet lines for the weekly ops-digest "Agent process health"
    section. Empty list when there are no findings. Pure."""
    if not findings:
        return []
    lines = ["*Agent process health:*"]
    for f in findings:
        lines.append(f"• {f.get('label')}")
    return lines


def summary_line(findings: list[dict]) -> str:
    """A one-line rollup for compact surfaces (the /director opening brief, the
    daily reconcile return, /director/status). Empty string when all clear. Pure."""
    if not findings:
        return ""
    per_agent: dict[str, int] = {}
    for f in findings:
        per_agent[f.get("agent")] = per_agent.get(f.get("agent"), 0) + 1
    parts = [f"{n} {_AGENT_LABEL.get(a, a)}" for a, n in sorted(per_agent.items())]
    n = len(findings)
    return f"Agent process health: {n} issue{'s' if n != 1 else ''} ({', '.join(parts)})"

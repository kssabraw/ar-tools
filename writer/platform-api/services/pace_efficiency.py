"""PACE process-efficiency detection (WS2 — docs: agent-coordination-and-efficiency-plan-v1_0).

PACE, the project manager, proactively spots where the agency's *processes* are
leaking — recurring slips + bottleneck members, rework churn, cadence mistuning,
and producer noise — and records them as findings **addressed to DORA**. These
are NOT reported to humans by PACE (PACE's normal PM reporting is untouched);
DORA is the single voice that reports process efficiency to humans (WS4). The
"duplicate churn" signal is deliberately NOT re-detected here — DORA already owns
the duplicate-target seam, which WS4 folds into the same efficiency picture (so
we don't invert the DORA-reads-PACE layering by importing director here).

Deterministic (no LLM), from data PACE already computes:
``pm_signals.build_board_digest`` (per-client stale/overdue/unassigned/
unacted-producer/month-pace + the workload report) plus a bounded read of QA
fails / task reopens for the rework signal. Runs daily inline on the shared
scheduler; findings upsert by a stable ``finding_key`` and auto-resolve when no
longer detected. Gated on ``pace_efficiency_enabled`` (default False).

Pure detectors (``detect_*``) are unit-tested; the impure ``run_efficiency_scan``
gathers the inputs, persists (best-effort), and never raises into the scheduler.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

CATEGORIES = ("slip_bottleneck", "rework", "cadence", "producer_noise", "duplicate_churn")


# ---------------------------------------------------------------------------
# Pure detectors — each takes already-gathered inputs, returns finding dicts.
# A finding: {category, finding_key, client_id, member_gid, title, detail,
#             recommendation, evidence, severity}. finding_key is stable so a
# re-run updates in place; a key that stops appearing auto-resolves.
# ---------------------------------------------------------------------------
def _name(names: Optional[dict], client_id) -> str:
    return (names or {}).get(client_id) or "a client"


def detect_slip_bottleneck(board: dict, *, slip_min: int, names: Optional[dict] = None) -> list[dict]:
    """Recurring slips (clients with a run of overdue tasks and/or behind month
    pace) + bottleneck members (the workload report's overloaded subset). Pure."""
    findings: list[dict] = []
    for c in board.get("clients") or []:
        cid = c.get("client_id")
        counts = c.get("counts") or {}
        overdue = counts.get("overdue", 0)
        behind = bool((c.get("month_pace") or {}).get("behind"))
        if overdue >= slip_min or (behind and overdue >= max(1, slip_min - 1)):
            findings.append({
                "category": "slip_bottleneck",
                "finding_key": f"slip:client:{cid}",
                "client_id": cid, "member_gid": None,
                "title": f"Delivery slipping for {_name(names, cid)}",
                "detail": (f"{overdue} overdue task(s)"
                           + (" and behind month pace" if behind else "") + "."),
                "recommendation": ("Rebalance or re-due the overdue work; if the month is "
                                   "behind, pull the plan forward or flag scope."),
                "evidence": {"overdue": overdue, "behind_pace": behind},
                "severity": "warning" if overdue >= slip_min else "info",
            })
    for m in (board.get("workload") or {}).get("overloaded") or []:
        gid = m.get("gid")
        findings.append({
            "category": "slip_bottleneck",
            "finding_key": f"bottleneck:member:{gid}",
            "client_id": None, "member_gid": gid,
            "title": f"{m.get('name') or 'A team member'} is a capacity bottleneck",
            "detail": "; ".join(m.get("flags") or []) or "Open workload over capacity.",
            "recommendation": ("Redistribute this member's open work to under-loaded "
                               "members, or extend due dates."),
            "evidence": {"open_hours": m.get("open_hours"), "open_count": m.get("open_count"),
                         "flags": m.get("flags") or []},
            "severity": "warning",
        })
    return findings


def detect_rework(qa_fail_counts: dict, reopen_counts: dict, *, rework_min: int,
                  names: Optional[dict] = None) -> list[dict]:
    """Rework churn: QA fails clustered on one client+rubric, and task reopens
    clustered on one client. ``qa_fail_counts`` is {(client_id, rubric): n};
    ``reopen_counts`` is {client_id: n}. Pure."""
    findings: list[dict] = []
    for (cid, rubric), n in sorted(qa_fail_counts.items(), key=lambda kv: -kv[1]):
        if n >= rework_min:
            findings.append({
                "category": "rework",
                "finding_key": f"rework:qa:{cid}:{rubric}",
                "client_id": cid, "member_gid": None,
                "title": f"Repeated QA fails on {rubric or 'deliverables'} for {_name(names, cid)}",
                "detail": f"{n} QA failures in the window on '{rubric or 'unknown'}' work.",
                "recommendation": ("Fix the upstream template/process causing repeat fails "
                                   "rather than reworking each item; raise with the owning agent."),
                "evidence": {"qa_fails": n, "rubric": rubric},
                "severity": "warning",
            })
    for cid, n in sorted(reopen_counts.items(), key=lambda kv: -kv[1]):
        if n >= rework_min:
            findings.append({
                "category": "rework",
                "finding_key": f"rework:reopen:{cid}",
                "client_id": cid, "member_gid": None,
                "title": f"Tasks keep reopening for {_name(names, cid)}",
                "detail": f"{n} task reopens in the window — work bouncing back.",
                "recommendation": ("Check the definition-of-done / QA gate for this client's "
                                   "workflow; a reopen loop signals unclear acceptance."),
                "evidence": {"reopens": n},
                "severity": "info",
            })
    return findings


def detect_cadence(board: dict, *, cadence_min_clients: int) -> list[dict]:
    """Cadence mistuning: when many clients are behind month pace at once, the
    monthly generation / chase cadence is likely mistimed (a systemic signal, not
    one client's slip). Pure — one agency-level finding."""
    behind = [c for c in (board.get("clients") or []) if (c.get("month_pace") or {}).get("behind")]
    if len(behind) < cadence_min_clients:
        return []
    return [{
        "category": "cadence",
        "finding_key": "cadence:month_pace",
        "client_id": None, "member_gid": None,
        "title": f"{len(behind)} clients behind month pace",
        "detail": (f"{len(behind)} clients are behind their monthly plan pace at once — "
                   "the generation/chase cadence may be starting too late in the month."),
        "recommendation": ("Move monthly generation earlier (asana_month_generate_day) or "
                           "front-load the chase plan so work isn't compressed into month-end."),
        "evidence": {"behind_clients": len(behind)},
        "severity": "warning",
    }]


def detect_producer_noise(board: dict, *, producer_min: int) -> list[dict]:
    """Producer noise: automated producers creating tasks nobody acts on. Rolls
    the per-client unacted-producer backlog up by source. Pure."""
    by_source: dict[str, int] = {}
    for c in board.get("clients") or []:
        for t in c.get("unacted_producer") or []:
            by_source[t.get("source") or "unknown"] = by_source.get(t.get("source") or "unknown", 0) + 1
    findings: list[dict] = []
    for source, n in sorted(by_source.items(), key=lambda kv: -kv[1]):
        if n >= producer_min:
            findings.append({
                "category": "producer_noise",
                "finding_key": f"producer_noise:{source}",
                "client_id": None, "member_gid": None,
                "title": f"'{source}' producer is creating tasks nobody acts on",
                "detail": f"{n} unacted-on tasks from the '{source}' producer across clients.",
                "recommendation": ("Tune this producer's thresholds or retire it — a backlog of "
                                   "ignored tasks is noise that hides the real work."),
                "evidence": {"unacted": n, "source": source},
                "severity": "info",
            })
    return findings


def collect_findings(board: dict, qa_fail_counts: dict, reopen_counts: dict,
                     names: Optional[dict] = None) -> list[dict]:
    """All detectors over prepared inputs, using the configured thresholds. Pure."""
    return (
        detect_slip_bottleneck(board, slip_min=settings.pace_efficiency_slip_min, names=names)
        + detect_rework(qa_fail_counts, reopen_counts,
                        rework_min=settings.pace_efficiency_rework_min, names=names)
        + detect_cadence(board, cadence_min_clients=settings.pace_efficiency_cadence_min_clients)
        + detect_producer_noise(board, producer_min=settings.pace_efficiency_producer_min)
    )


# ---------------------------------------------------------------------------
# Impure — gather inputs, persist, auto-resolve. Best-effort, never raises.
# ---------------------------------------------------------------------------
def _window_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _gather_rework_counts(days: int) -> tuple[dict, dict]:
    """(qa_fail_counts {(client_id, rubric): n}, reopen_counts {client_id: n}) over
    the window. Best-effort — empty on error."""
    qa: dict = {}
    reopen: dict = {}
    since = _window_iso(days)
    try:
        rows = (get_supabase().table("qa_reviews")
                .select("client_id, rubric, verdict, created_at")
                .eq("verdict", "fail").gte("created_at", since).limit(2000).execute()).data or []
        for r in rows:
            qa[(r.get("client_id"), r.get("rubric"))] = qa.get((r.get("client_id"), r.get("rubric")), 0) + 1
    except Exception as exc:
        logger.warning("pace_efficiency_qa_read_failed", extra={"error": str(exc)})
    try:
        acts = (get_supabase().table("task_activity")
                .select("task_id, kind, created_at")
                .eq("kind", "reopened").gte("created_at", since).limit(2000).execute()).data or []
        task_ids = sorted({a["task_id"] for a in acts if a.get("task_id")})
        client_of: dict = {}
        for i in range(0, len(task_ids), 200):
            chunk = task_ids[i:i + 200]
            trows = (get_supabase().table("tasks").select("id, client_id")
                     .in_("id", chunk).execute()).data or []
            for t in trows:
                client_of[t["id"]] = t.get("client_id")
        for a in acts:
            cid = client_of.get(a.get("task_id"))
            if cid:
                reopen[cid] = reopen.get(cid, 0) + 1
    except Exception as exc:
        logger.warning("pace_efficiency_reopen_read_failed", extra={"error": str(exc)})
    return qa, reopen


def _client_names(client_ids) -> dict:
    ids = sorted({c for c in client_ids if c})
    if not ids:
        return {}
    try:
        rows = (get_supabase().table("clients").select("id, name")
                .in_("id", ids).execute()).data or []
        return {r["id"]: r.get("name") for r in rows}
    except Exception:
        return {}


def _persist(findings: list[dict]) -> dict:
    """Upsert current findings (open) by finding_key + auto-resolve any open row
    whose key no longer appears. Best-effort."""
    sb = get_supabase()
    now = datetime.now(timezone.utc).isoformat()
    current_keys = {f["finding_key"] for f in findings}
    rows = [{
        "category": f["category"], "finding_key": f["finding_key"],
        "client_id": f.get("client_id"), "member_gid": f.get("member_gid"),
        "title": f["title"], "detail": f.get("detail"),
        "recommendation": f.get("recommendation"), "evidence": f.get("evidence") or {},
        "severity": f.get("severity") or "info", "status": "open",
        "resolved_at": None, "last_seen_at": now, "updated_at": now,
    } for f in findings]
    upserted = 0
    if rows:
        try:
            sb.table("pace_efficiency_findings").upsert(rows, on_conflict="finding_key").execute()
            upserted = len(rows)
        except Exception as exc:
            logger.warning("pace_efficiency_upsert_failed", extra={"error": str(exc)})
    resolved = 0
    try:
        open_rows = (sb.table("pace_efficiency_findings").select("id, finding_key")
                     .eq("status", "open").limit(2000).execute()).data or []
        stale = [r["id"] for r in open_rows if r.get("finding_key") not in current_keys]
        for i in range(0, len(stale), 200):
            chunk = stale[i:i + 200]
            (sb.table("pace_efficiency_findings")
             .update({"status": "resolved", "resolved_at": now, "updated_at": now})
             .in_("id", chunk).execute())
        resolved = len(stale)
    except Exception as exc:
        logger.warning("pace_efficiency_resolve_failed", extra={"error": str(exc)})
    return {"found": upserted, "resolved": resolved}


def run_efficiency_scan(today: Optional[date] = None) -> dict:
    """The daily PACE efficiency scan (inline on the shared scheduler). Self-gated
    on ``pace_efficiency_enabled``; best-effort — a failure never breaks the tick.
    Returns {found, resolved} or {reason}."""
    if not settings.pace_efficiency_enabled:
        return {"found": 0, "resolved": 0, "reason": "disabled"}
    today = today or date.today()
    try:
        from services import pm_signals

        board = pm_signals.build_board_digest(None, today)
    except Exception as exc:
        logger.warning("pace_efficiency_board_failed", extra={"error": str(exc)})
        return {"found": 0, "resolved": 0, "reason": "board_error"}
    qa_counts, reopen_counts = _gather_rework_counts(settings.pace_efficiency_window_days)
    client_ids = [c.get("client_id") for c in board.get("clients") or []]
    client_ids += [cid for (cid, _r) in qa_counts] + list(reopen_counts)
    names = _client_names(client_ids)
    findings = collect_findings(board, qa_counts, reopen_counts, names)
    result = _persist(findings)
    logger.info("pace_efficiency_scan", extra=result)
    return result

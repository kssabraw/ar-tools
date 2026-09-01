"""Director of Operations — read-model providers (build spec §4).

Each provider does bounded, read-only Supabase reads and returns a compact
dict or ``None`` on empty. ``read_model.build_read_model`` wraps every call in
its own try/except (mirrors ``slack_assistant/context.py::build_context``), so
one module failing or being empty never breaks the read — it degrades to a
gap. Providers that would otherwise be N+1 across a portfolio (strategy,
autonomy, producers, interventions, duplicates) batch-read once and group in
Python, the same pattern ``build_portfolio_context``'s ``_counts`` helper
uses — not a fresh query per client.

E1 (fail-loud on unknown producer sources): ``prov_producers`` is the seam
that must never silently drop an unrecognized ``tasks.source`` — see
``KNOWN_PRODUCER_SOURCES`` below and ``director.unwatched_source``.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

# The Director's own producer ("director_seam", §6.1) is included so its own
# reconciliation tasks read back as a known source, not an unwatched one.
KNOWN_PRODUCER_SOURCES = frozenset({
    "manual", "monthly", "asana_import", "rank_drop", "maps_alert", "action_plan",
    "content_run", "scan_health", "task_plan", "strategy_proposal", "director_seam",
})

_KNOWN_QA_VERDICTS = frozenset({"pass", "fail", "needs_human", "skipped"})


def _target_key(target: Optional[dict]) -> Optional[str]:
    """A normalized cross-source dedup key for a task/intervention target.
    Pure. Keyword wins over page_url when both are present (a keyword-scoped
    action and a URL-scoped action on the same page are different targets)."""
    target = target or {}
    kw = (target.get("keyword") or "").strip().casefold()
    if kw:
        return f"kw:{kw}"
    url = (target.get("page_url") or "").strip().casefold()
    if url:
        return f"url:{url}"
    return None


# ---------------------------------------------------------------------------
# delivery / assignment — lift from the shared PACE board read (no re-query)
# ---------------------------------------------------------------------------
def prov_delivery(board: dict) -> Optional[dict]:
    """Per-client board state (stale/overdue/unassigned/unacted_producer),
    reused verbatim from ``pm_signals.build_board_digest`` — no fresh query."""
    clients = board.get("clients") or []
    if not clients:
        return None
    return {"clients": clients}


def prov_assignment(supabase, board: dict, client_ids: Optional[list[str]]) -> Optional[dict]:
    """Per-member load (from the shared board's workload report) plus any
    currently-open capacity holds (an unassigned, incomplete task whose most
    recent ``placement_deferred`` activity is its live reason)."""
    workload = board.get("workload") or {}
    holds: list[dict] = []
    try:
        q = (
            supabase.table("tasks")
            .select("id, client_id, name, target")
            .eq("completed", False)
            .is_("deleted_at", "null")
            .is_("assignee_id", "null")
        )
        if client_ids:
            q = q.in_("client_id", client_ids)
        unassigned = q.limit(500).execute().data or []
        by_id = {t["id"]: t for t in unassigned}
        ids = list(by_id.keys())
        if ids:
            activity = (
                supabase.table("task_activity")
                .select("task_id, detail, created_at")
                .eq("kind", "placement_deferred")
                .in_("task_id", ids)
                .order("created_at", desc=True)
                .execute()
            ).data or []
            seen: set[str] = set()
            for row in activity:
                tid = row.get("task_id")
                if not tid or tid in seen:
                    continue
                seen.add(tid)
                detail = row.get("detail") or {}
                task = by_id.get(tid, {})
                holds.append({
                    "task_id": tid,
                    "client_id": task.get("client_id"),
                    "name": task.get("name"),
                    "reason": detail.get("reason"),
                    "category": detail.get("category"),
                    "since": row.get("created_at"),
                })
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.assignment_read_failed", extra={"error": str(exc)})
    if not workload and not holds:
        return None
    return {"workload": workload, "open_holds": holds}


# ---------------------------------------------------------------------------
# strategy — approved-but-unplaced proposals (§5 strategist_approved_unplaced)
# ---------------------------------------------------------------------------
def prov_strategy(supabase, client_ids: Optional[list[str]], today: date) -> Optional[dict]:
    try:
        q = (
            supabase.table("strategy_reviews")
            .select("id, client_id, status, proposals, created_at, completed_at")
            .order("created_at", desc=True)
            .limit(500)
        )
        if client_ids:
            q = q.in_("client_id", client_ids)
        rows = q.execute().data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.strategy_read_failed", extra={"error": str(exc)})
        return None
    if not rows:
        return None

    status_counts: dict[str, int] = {}
    approved_unplaced: list[dict] = []
    proposed_pending: list[dict] = []
    for review in rows:
        since = review.get("completed_at") or review.get("created_at")
        for idx, proposal in enumerate(review.get("proposals") or []):
            st = proposal.get("status") or "proposed"
            status_counts[st] = status_counts.get(st, 0) + 1
            # The exact guard routers/strategist.py:140 uses before pushing —
            # an approved proposal with no asana_task hasn't been placed yet.
            if st == "approved" and not proposal.get("asana_task"):
                approved_unplaced.append({
                    "review_id": review["id"],
                    "client_id": review.get("client_id"),
                    "proposal_index": idx,
                    "title": proposal.get("title"),
                    "since": since,
                })
            # A proposal nobody has approved OR dismissed sits in "proposed"
            # forever (finding #4). Surface it so the seam predicate can flag a
            # stale one — it clears the moment the human approves/dismisses.
            elif st == "proposed":
                proposed_pending.append({
                    "review_id": review["id"],
                    "client_id": review.get("client_id"),
                    "proposal_index": idx,
                    "title": proposal.get("title"),
                    "requires": proposal.get("requires"),
                    "since": since,
                })
    return {
        "status_counts": status_counts,
        "approved_unplaced": approved_unplaced,
        "proposed_pending": proposed_pending,
        "reviews_considered": len(rows),
    }


# ---------------------------------------------------------------------------
# autonomy — proposed-but-unactioned candidates (§5 autonomy_proposed_unactioned)
# ---------------------------------------------------------------------------
def prov_autonomy(supabase, client_ids: Optional[list[str]], today: date) -> Optional[dict]:
    try:
        q = (
            supabase.table("autonomy_runs")
            .select("id, client_id, trigger, decisions, actions_taken, cost_usd, created_at")
            .order("created_at", desc=True)
            .limit(1000)
        )
        if client_ids:
            q = q.in_("client_id", client_ids)
        rows = q.execute().data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.autonomy_read_failed", extra={"error": str(exc)})
        return None
    if not rows:
        return None

    lookback = max(settings.director_autonomy_ledger_lookback_runs, 1)
    per_client: dict[Optional[str], list[dict]] = {}
    for row in rows:
        bucket = per_client.setdefault(row.get("client_id"), [])
        if len(bucket) < lookback:
            bucket.append(row)

    executed = proposed = escalated = 0
    unactioned: list[dict] = []
    for cid, runs in per_client.items():
        for run in runs:
            for decision in run.get("decisions") or []:
                outcome = decision.get("outcome")
                if outcome == "auto" and decision.get("executed"):
                    executed += 1
                elif outcome == "propose":
                    proposed += 1
                    unactioned.append({
                        "client_id": cid,
                        "run_id": run["id"],
                        "action": decision.get("action"),
                        "keyword": decision.get("keyword"),
                        "since": run.get("created_at"),
                    })
                elif outcome == "escalate":
                    escalated += 1
    return {
        "executed": executed,
        "proposed": proposed,
        "escalated": escalated,
        "proposed_unactioned": unactioned,
        "runs_considered": sum(len(v) for v in per_client.values()),
    }


# ---------------------------------------------------------------------------
# producers — open producer tasks by source; E1 unwatched-source fail-loud
# ---------------------------------------------------------------------------
def prov_producers(supabase, client_ids: Optional[list[str]], today: date) -> Optional[dict]:
    try:
        q = (
            supabase.table("tasks")
            .select("id, client_id, source")
            .eq("completed", False)
            .is_("deleted_at", "null")
            .is_("parent_task_id", "null")
        )
        if client_ids:
            q = q.in_("client_id", client_ids)
        rows = q.limit(2000).execute().data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.producers_read_failed", extra={"error": str(exc)})
        return None
    if not rows:
        return None

    by_source: dict[str, int] = {}
    unwatched: dict[str, int] = {}
    for row in rows:
        src = row.get("source") or "manual"
        by_source[src] = by_source.get(src, 0) + 1
        if src not in KNOWN_PRODUCER_SOURCES:
            unwatched[src] = unwatched.get(src, 0) + 1
            # E1 — never silently skip: log every occurrence so a new
            # producer that forgot to register itself is visible immediately,
            # mirroring job_worker's unroutable-job-type discipline.
            logger.warning(
                "director.unwatched_source",
                extra={"source": src, "task_id": row.get("id"), "client_id": row.get("client_id")},
            )
    return {"open_by_source": by_source, "unwatched_seam": unwatched or None}


# ---------------------------------------------------------------------------
# interventions — tactics enrolled + verdict mix
# ---------------------------------------------------------------------------
def prov_interventions(supabase, client_ids: Optional[list[str]], today: date) -> Optional[dict]:
    try:
        q = (
            supabase.table("interventions")
            .select("id, client_id, source, tactic_type, target, verdict, applied_at")
            .order("applied_at", desc=True)
            .limit(1000)
        )
        if client_ids:
            q = q.in_("client_id", client_ids)
        rows = q.execute().data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.interventions_read_failed", extra={"error": str(exc)})
        return None
    if not rows:
        return None

    by_verdict: dict[str, int] = {}
    open_rows: list[dict] = []
    for row in rows:
        verdict = row.get("verdict") or "pending"
        by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
        if row.get("verdict") is None:
            open_rows.append(row)
    return {"by_verdict": by_verdict, "enrolled": len(rows), "open": open_rows}


# ---------------------------------------------------------------------------
# qa — portfolio-only (§2.3): is anything reaching In QA; verdict mix; rework
# ---------------------------------------------------------------------------
def prov_qa(supabase, today: date) -> Optional[dict]:
    window_days = max(settings.director_seam_qa_idle_days, 30)
    cutoff = (today - timedelta(days=window_days)).isoformat()

    entered: list[dict] = []
    try:
        activity = (
            supabase.table("task_activity")
            .select("task_id, detail, created_at")
            .eq("kind", "status_changed")
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(2000)
            .execute()
        ).data or []
        entered = [
            row for row in activity
            if (row.get("detail") or {}).get("to") == settings.qa_trigger_status
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.qa_activity_read_failed", extra={"error": str(exc)})
        activity = []

    reviews: list[dict] = []
    try:
        reviews = (
            supabase.table("qa_reviews")
            .select("verdict, created_at")
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.qa_reviews_read_failed", extra={"error": str(exc)})

    if not activity and not reviews:
        return None

    verdict_mix: dict[str, int] = {}
    for row in reviews:
        verdict = row.get("verdict") or "unknown"
        verdict_mix[verdict] = verdict_mix.get(verdict, 0) + 1
        if verdict not in _KNOWN_QA_VERDICTS:
            logger.warning("director.unwatched_source", extra={"kind": "qa_verdict", "value": verdict})

    return {
        "entered_in_qa_count": len(entered),
        "last_entered_at": entered[0]["created_at"] if entered else None,
        "verdict_mix": verdict_mix,
        "reviews_considered": len(reviews),
    }


# ---------------------------------------------------------------------------
# content — content_shipped_degraded evidence (immediate, no dwell)
# ---------------------------------------------------------------------------
def prov_content(supabase, client_ids: Optional[list[str]], today: date) -> Optional[dict]:
    """A completed run whose writer output shipped at a ``-degraded``/
    ``-no-context`` schema version, or a Local SEO / Ecommerce page whose
    stored voice scorecard failed with an unresolved analysis. Best-effort,
    bounded to the lookback window — an unfamiliar shape here degrades to an
    empty flag list, never a crash (the class of failure the suite's own
    provider-isolation contract exists to absorb)."""
    cutoff = (today - timedelta(days=settings.director_content_degraded_lookback_days)).isoformat()
    flags: list[dict] = []

    try:
        outputs = (
            supabase.table("module_outputs")
            .select("run_id, module_version, completed_at")
            .eq("module", "writer")
            .eq("status", "complete")
            .gte("completed_at", cutoff)
            .order("completed_at", desc=True)
            .limit(500)
            .execute()
        ).data or []
        degraded = [
            row for row in outputs
            if str(row.get("module_version") or "").endswith(("-degraded", "-no-context"))
        ]
        run_ids = [row["run_id"] for row in degraded if row.get("run_id")]
        runs_by_id: dict[str, dict] = {}
        if run_ids:
            q = supabase.table("runs").select("id, client_id, keyword, created_at").in_("id", run_ids)
            if client_ids:
                q = q.in_("client_id", client_ids)
            runs_by_id = {r["id"]: r for r in (q.execute().data or [])}
        for row in degraded:
            run = runs_by_id.get(row.get("run_id"))
            if not run:
                continue  # filtered out by client_ids, or the run vanished
            flags.append({
                "client_id": run.get("client_id"),
                "ident": f"run:{run['id']}",
                "kind": "degraded_run",
                "keyword": run.get("keyword"),
                "schema_version": row.get("module_version"),
                "since": row.get("completed_at"),
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.content_degraded_read_failed", extra={"error": str(exc)})

    for table in ("local_seo_pages", "ecommerce_pages"):
        try:
            q = (
                supabase.table(table)
                .select("id, client_id, page_title, voice_violations, updated_at")
                .not_.is_("voice_violations", "null")
                .gte("updated_at", cutoff)
                .order("updated_at", desc=True)
                .limit(300)
            )
            if client_ids:
                q = q.in_("client_id", client_ids)
            rows = q.execute().data or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("director.content_voice_read_failed", extra={"table": table, "error": str(exc)})
            continue
        for row in rows:
            scorecard = row.get("voice_violations") or {}
            if scorecard.get("passed") is False:
                flags.append({
                    "client_id": row.get("client_id"),
                    "ident": f"{table}:{row['id']}",
                    "kind": "voice_critical",
                    "title": row.get("page_title"),
                    "analysis": scorecard.get("analysis"),
                    "since": row.get("updated_at"),
                })

    if not flags:
        return None
    return {"degraded": flags}


# ---------------------------------------------------------------------------
# agent track records — PACE + SerMaStr action logs (read-only insight, no seam)
# ---------------------------------------------------------------------------
def _top_buckets(buckets: Optional[dict], n: int = 5) -> dict:
    """The n busiest sub-buckets (by ``total``) of a decision-stats rollup, so
    the read-model payload stays bounded on a large agency. Pure."""
    if not buckets:
        return {}
    ranked = sorted(buckets.items(), key=lambda kv: -(kv[1] or {}).get("total", 0))
    return {k: v for k, v in ranked[:n]}


def prov_pace_audit(client_id: Optional[str], today: date) -> Optional[dict]:
    """PACE's OWN action track record over the audit window — approve / deny /
    modify / revert rates, overall and per action kind. Read-only insight (NOT a
    seam), reusing the tested ``pace_audit.stats_window`` rollup rather than
    re-querying. ``client_id`` set → that client; None → the whole agency. Gated
    on ``pace_audit_enabled``; None when nothing was logged in the window."""
    from services import pace_audit

    if not settings.pace_audit_enabled:
        return None
    since = (today - timedelta(days=settings.director_audit_window_days)).isoformat()
    stats = pace_audit.stats_window(client_id=client_id, since=since)
    overall = stats.get("overall") or {}
    if not overall.get("total"):
        return None
    return {
        "window_days": settings.director_audit_window_days,
        "decisions": overall,
        "by_action": _top_buckets(stats.get("by_action")),
        "note": (
            "PACE's own action track record: how humans dispositioned PACE's "
            "client-campaign actions (approved / approved_with_modifications / "
            "denied / deferred / cancelled) and how many executed actions a human "
            "later reverted. Read it as a reliability signal on PACE's execution — "
            "a high denied/reverted rate on an action kind is worth surfacing."
        ),
    }


def prov_sermastr_audit(client_id: Optional[str], today: date) -> Optional[dict]:
    """SerMaStr's OWN proposal track record over the audit window — approve /
    dismiss / still-pending counts plus the reused intervention outcome mix
    (worked / partial / no_effect), overall and per proposal kind. Read-only
    insight (NOT a seam), reusing the tested ``sermastr_audit.stats_window``
    rollup. ``client_id`` set → that client; None → the whole agency. Gated on
    ``sermastr_audit_enabled``; None when nothing was logged in the window."""
    from services import sermastr_audit

    if not settings.sermastr_audit_enabled:
        return None
    since = (today - timedelta(days=settings.director_audit_window_days)).isoformat()
    stats = sermastr_audit.stats_window(client_id=client_id, since=since)
    overall = stats.get("overall") or {}
    if not overall.get("total"):
        return None
    return {
        "window_days": settings.director_audit_window_days,
        "decisions": overall,
        "by_kind": _top_buckets(stats.get("by_kind")),
        "note": (
            "SerMaStr's own proposal track record: how humans decided its "
            "strategy proposals (approved / dismissed / still pending) and, for "
            "approved goal-linked link-building/reoptimization, whether the tactic "
            "worked/partial/no_effect at its 6-week mark. Read it as which kinds of "
            "strategy advice actually get accepted and move the metric."
        ),
    }


# ---------------------------------------------------------------------------
# audit health — is the SerMaStr/PACE propose→decide→outcome pipeline working?
# (owner ask 2026-09-01) — a PROCESS-health read over both agents' own action
# logs, kept OUT of flow.flags (it opens no board task; it drives ops_seam
# alerts + the weekly ops-digest "Agent process health" section instead).
# ---------------------------------------------------------------------------
def _audit_window_rows(supabase, table: str, columns: str, since: str,
                       client_id: Optional[str]) -> list[dict]:
    """One bounded, best-effort read of an action-log window. [] on any error."""
    try:
        q = (supabase.table(table).select(columns)
             .gte("created_at", since).order("created_at", desc=True).limit(5000))
        if client_id:
            q = q.eq("client_id", client_id)
        return q.execute().data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.audit_window_read_failed", extra={"table": table, "error": str(exc)})
        return []


def _stale_pending_count(supabase, since_dwell: str, client_id: Optional[str]) -> int:
    """Count SerMaStr proposals still undecided (decision NULL) that were created
    before ``since_dwell`` — i.e. past the pending dwell threshold. Best-effort."""
    try:
        q = (supabase.table("sermastr_action_log").select("id", count="exact")
             .is_("decision", "null").lt("created_at", since_dwell))
        if client_id:
            q = q.eq("client_id", client_id)
        resp = q.limit(2000).execute()
        return resp.count if resp.count is not None else len(resp.data or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.audit_stale_read_failed", extra={"error": str(exc)})
        return 0


def _behind_uncovered(sermastr_rows: list[dict]) -> list[str]:
    """Clients behind on a goal (reusing the strategist's own behind-goal read)
    with NO SerMaStr proposal logged in the window. Portfolio-only, best-effort —
    [] if the strategist read is unavailable/disabled."""
    try:
        from services.strategist import clients_with_behind_goals

        behind = clients_with_behind_goals() or set()
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.audit_behind_goals_failed", extra={"error": str(exc)})
        return []
    with_proposals = {r.get("client_id") for r in sermastr_rows if r.get("client_id")}
    return sorted(c for c in behind if c and c not in with_proposals)


def prov_audit_health(supabase, client_id: Optional[str], today: date) -> Optional[dict]:
    """DORA's audit-log health read: rate + coverage signals over the SerMaStr +
    PACE action logs, plus the assembled findings the daily reconcile alerts on
    and the weekly digest renders. Gated on ``director_audit_health_enabled``;
    ``client_id`` set scopes the rate signals to that client, None → the whole
    agency (coverage + stale-queue signals are agency-level, so they're computed
    only in the portfolio read). Returns None when the feature is off or nothing
    is logged and no coverage gap exists."""
    if not settings.director_audit_health_enabled:
        return None
    from services import pace_audit, sermastr_audit
    from services.director import audit_health

    portfolio = client_id is None
    window = (today - timedelta(days=settings.director_audit_window_days)).isoformat()
    dwell = (today - timedelta(days=settings.director_seam_proposal_pending_days)).isoformat()

    sermastr_rows = _audit_window_rows(
        supabase, "sermastr_action_log",
        "proposal_kind, client_id, decision, outcome_verdict", window, client_id)
    pace_rows = _audit_window_rows(
        supabase, "pace_action_log",
        "action, client_id, decision, outcome, reverted_at", window, client_id)

    sermastr_signals = sermastr_audit.learning_signals(sermastr_rows)
    pace_signals = pace_audit.learning_signals(pace_rows)

    # Agency-level signals (stale queue + coverage) only in the portfolio read.
    stale_count = _stale_pending_count(supabase, dwell, client_id) if portfolio else 0
    behind_uncovered = _behind_uncovered(sermastr_rows) if portfolio else None

    # "Active" = the agent is actually operational; a dark agent producing
    # nothing is expected, not a coverage gap.
    sermastr_active = portfolio and settings.strategist_enabled and settings.sermastr_audit_enabled
    pace_active = portfolio and settings.pace_enabled and settings.pace_audit_enabled

    thresholds = {
        "min_samples": settings.director_audit_min_samples,
        "dismiss_threshold": settings.director_audit_dismiss_threshold,
        "ineffective_threshold": settings.director_audit_ineffective_threshold,
        "stale_pending_min": settings.director_audit_stale_pending_min,
        "pending_days": settings.director_seam_proposal_pending_days,
        "min_uncovered": 1,
    }
    findings = audit_health.build_findings(
        sermastr_signals=sermastr_signals, pace_signals=pace_signals,
        sermastr_total=len(sermastr_rows), pace_total=len(pace_rows),
        stale_count=stale_count, behind_uncovered=behind_uncovered,
        thresholds=thresholds, sermastr_active=sermastr_active,
        pace_active=pace_active, client_id=client_id)

    if not findings and not sermastr_rows and not pace_rows:
        return None  # nothing logged, nothing flagged — a true gap, not a block

    return {
        "window_days": settings.director_audit_window_days,
        "findings": findings,
        "summary": audit_health.summary_line(findings),
        "sermastr": {"total": len(sermastr_rows),
                     "by_kind": _top_buckets(sermastr_signals.get("by_kind"))},
        "pace": {"total": len(pace_rows),
                 "by_action": _top_buckets(pace_signals.get("by_action"))},
        "stale_pending": stale_count,
        "behind_uncovered": behind_uncovered or [],
        "note": (
            "Process-health signals over SerMaStr's and PACE's OWN action logs — "
            "whether their propose→decide→outcome pipeline is running efficiently "
            "(work getting acted on, accepted, and actually working). These drive "
            "ops_seam alerts + the weekly ops-digest health section; they are NOT "
            "board-task seams."
        ),
    }


# ---------------------------------------------------------------------------
# duplicates — two different-source live items on one target (§9, flag-only)
# ---------------------------------------------------------------------------
def prov_duplicates(supabase, client_ids: Optional[list[str]], today: date) -> Optional[dict]:
    grouped: dict[tuple[Optional[str], str], list[dict]] = {}

    try:
        q = (
            supabase.table("tasks")
            .select("id, client_id, source, target")
            .eq("completed", False)
            .is_("deleted_at", "null")
        )
        if client_ids:
            q = q.in_("client_id", client_ids)
        tasks = q.limit(2000).execute().data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.duplicates_tasks_read_failed", extra={"error": str(exc)})
        tasks = []
    for row in tasks:
        key = _target_key(row.get("target"))
        if not key:
            continue
        grouped.setdefault((row.get("client_id"), key), []).append(
            {"kind": "task", "id": row["id"], "source": row.get("source") or "manual"}
        )

    try:
        q2 = (
            supabase.table("interventions")
            .select("id, client_id, source, target")
            .is_("verdict", "null")
        )
        if client_ids:
            q2 = q2.in_("client_id", client_ids)
        interventions = q2.limit(1000).execute().data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.duplicates_interventions_read_failed", extra={"error": str(exc)})
        interventions = []
    for row in interventions:
        key = _target_key(row.get("target"))
        if not key:
            continue
        grouped.setdefault((row.get("client_id"), key), []).append(
            {"kind": "intervention", "id": row["id"], "source": f"intervention:{row.get('source')}"}
        )

    if not grouped:
        return None

    duplicates = []
    for (client_id, key), items in grouped.items():
        if len({item["source"] for item in items}) >= 2:
            duplicates.append({"client_id": client_id, "target_key": key, "items": items})
    return {"targets_checked": len(grouped), "duplicates": duplicates}


# ---------------------------------------------------------------------------
# pace_efficiency — PACE's process-leak findings addressed to DORA (WS2/WS4)
# ---------------------------------------------------------------------------
def prov_pace_efficiency(supabase, client_ids: Optional[list[str]], today: date) -> Optional[dict]:
    """Open PACE process-efficiency findings (slip/bottleneck, rework, cadence,
    producer-noise). Portfolio read includes the agency-level findings (client_id
    null — a bottleneck member, a cadence problem); a per-client read scopes to
    that client's findings. The data PACE feeds DORA for the WS4 analysis."""
    try:
        q = (
            supabase.table("pace_efficiency_findings")
            .select("category, finding_key, client_id, member_gid, title, detail, "
                    "recommendation, evidence, severity, last_seen_at")
            .eq("status", "open").order("last_seen_at", desc=True).limit(500)
        )
        if client_ids:
            q = q.in_("client_id", client_ids)
        rows = q.execute().data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.pace_efficiency_read_failed", extra={"error": str(exc)})
        return None
    if not rows:
        return None
    by_category: dict[str, int] = {}
    for r in rows:
        by_category[r.get("category") or "other"] = by_category.get(r.get("category") or "other", 0) + 1
    return {"open": len(rows), "by_category": by_category, "findings": rows}


# ---------------------------------------------------------------------------
# coordination — the agent-to-agent bus health (WS3/WS4)
# ---------------------------------------------------------------------------
def prov_coordination(supabase, client_ids: Optional[list[str]], today: date) -> Optional[dict]:
    """How work is flowing BETWEEN the agents, from the coordination bus — open
    blockers (capacity/dependency walls), stalled handoffs, and back-and-forth
    loops. Returns None when the bus is off or empty (agent_bus.recent self-gates
    on agent_bus_enabled)."""
    from services import agent_bus

    msgs = agent_bus.recent(days=settings.director_coordination_recent_days)
    if not msgs:
        return None
    if client_ids:
        msgs = [m for m in msgs if m.get("client_id") in client_ids or m.get("client_id") is None]
    metrics = agent_bus.coordination_metrics(msgs)
    return {
        "open": metrics["open"],
        "by_pair": metrics["by_pair"],
        "open_blockers": metrics["open_blockers"],
        "stalled": metrics["stalled"][:20],
        "loops": metrics["loops"],
    }

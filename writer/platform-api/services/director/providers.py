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
    return {
        "status_counts": status_counts,
        "approved_unplaced": approved_unplaced,
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

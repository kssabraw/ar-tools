"""Native task manager — suite auto-integration producers (PRD §11, Phase 4).

The payoff of building native: suite signals auto-create tasks and auto-close
them when the underlying condition resolves. Every hook here is **best-effort
and never raises** — a task failure must never break the tracker/planner that
hosts it — and every producer is double-gated: the ``native_tasks_enabled``
master flag AND its own config flag, so producers can be enabled incrementally
(PRD §11).

Idempotency rides ``task_service.create_task``'s ``(source, source_ref)``
contract: a completed task keeps its key (a resolved-then-listed-again signal
doesn't re-create), a trashed one releases it.

| source        | opens on                                   | closes when                        |
|---------------|--------------------------------------------|------------------------------------|
| ``rank_drop``   | a rank_alerts row opens                    | that alert auto-resolves           |
| ``maps_alert``  | a maps_alerts row opens                    | that alert auto-resolves           |
| ``action_plan`` | an action enters the latest reopt plan     | the action leaves the latest plan  |
| ``content_run`` | a content run completes (opt-in)           | the run is published               |

Producer tasks land in the client's current-month section (get-or-create,
same idempotent helper the monthly generation uses), unassigned — the team
triages them like any other task.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import task_service

logger = logging.getLogger(__name__)


def _enabled(flag: bool) -> bool:
    return bool(settings.native_tasks_enabled and flag)


def _month_section_id(client_id: str) -> Optional[str]:
    try:
        from services.task_monthly import ensure_month_section

        return ensure_month_section(client_id, date.today())["id"]
    except Exception as exc:
        logger.warning("task_producer_section_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def _create(client_id: str, name: str, *, source: str, source_ref: str, description: str) -> None:
    row = task_service.create_task(
        name,
        client_id=client_id,
        section_id=_month_section_id(client_id),
        description=description,
        source=source,
        source_ref=source_ref,
    )
    # PACE v1.3 (§4.6): optionally auto-place the producer task on the correct
    # party (flag-gated, default off; place_task no-ops if already assigned, so a
    # gap-fill re-run never churns). Best-effort — never fails the producer.
    if settings.pace_autoplace_producers and row and row.get("id"):
        try:
            from services import pm_assign

            pm_assign.place_task(row["id"])
        except Exception as exc:
            logger.warning("task_producer_autoplace_failed", extra={"source_ref": source_ref, "error": str(exc)})


# ---------------------------------------------------------------------------
# Organic rank drops (rank_alerts)
# ---------------------------------------------------------------------------
def on_rank_alerts(client_id: str, opened: list[dict], resolved_ids: list[str]) -> None:
    """Called from rank_alerts.reconcile_alerts with the inserted alert rows
    (must carry ``id``) and the auto-resolved alert ids."""
    if not _enabled(settings.task_producer_rank_drop_enabled):
        return
    try:
        for a in opened:
            if not a.get("id"):
                continue
            keyword = a.get("keyword") or "keyword"
            name = (
                f"Confirm indexing: {keyword}"
                if a.get("alert_type") == "deindexed"
                else f"Diagnose & reoptimize: {keyword}"
            )
            _create(
                client_id,
                name,
                source="rank_drop",
                source_ref=str(a["id"]),
                description=(
                    f"{a.get('message') or 'Ranking drop detected.'}\n\n"
                    f"Action Plan: /clients/{client_id}/action-plan · "
                    f"Rankings: /clients/{client_id}/rankings"
                ),
            )
        for alert_id in resolved_ids:
            task_service.close_task_by_source("rank_drop", str(alert_id))
    except Exception as exc:
        logger.warning("task_producer_rank_drop_failed", extra={"client_id": client_id, "error": str(exc)})


# ---------------------------------------------------------------------------
# Local-pack declines (maps_alerts)
# ---------------------------------------------------------------------------
def on_maps_alerts(client_id: str, opened: list[dict], resolved_ids: list[str]) -> None:
    if not _enabled(settings.task_producer_maps_alert_enabled):
        return
    try:
        for a in opened:
            if not a.get("id"):
                continue
            keyword = a.get("keyword") or "keyword"
            _create(
                client_id,
                f"Local-pack drop: {keyword} — review",
                source="maps_alert",
                source_ref=str(a["id"]),
                description=(
                    f"{a.get('message') or 'Local-pack decline detected.'}\n\n"
                    f"Geo-grid: /clients/{client_id}/maps · "
                    f"Action Plan: /clients/{client_id}/action-plan"
                ),
            )
        for alert_id in resolved_ids:
            task_service.close_task_by_source("maps_alert", str(alert_id))
    except Exception as exc:
        logger.warning("task_producer_maps_alert_failed", extra={"client_id": client_id, "error": str(exc)})


# ---------------------------------------------------------------------------
# Action Plan items (reopt_plans)
# ---------------------------------------------------------------------------
def action_source_ref(client_id: str, action: dict) -> str:
    """Stable per-action key: an action is "the same item" across plan rebuilds
    when its kind + keyword (or CTA label) match — plan rows have no ids.
    Pure — unit-tested."""
    ident = (action.get("keyword") or action.get("cta_label") or action.get("recommendation") or "")[:120]
    return f"{client_id}:{action.get('kind')}:{ident.strip().casefold()}"


def sync_action_plan_tasks(client_id: str, actions: list[dict]) -> None:
    """Mirror the latest plan into tasks: create for new actions (top
    ``task_producer_action_plan_max`` only — the plan is already
    priority-sorted), auto-close tasks whose action left the plan.

    Drop-driven kinds (rank_drop / maps alerts / sitewide banner) are skipped —
    the alert producers above own those with truer open/close semantics."""
    if not _enabled(settings.task_producer_action_plan_enabled):
        return
    try:
        skip_kinds = {"rank_drop", "sitewide_decline", "maps_decline", "maps_competitor"}
        eligible = [a for a in actions if a.get("kind") not in skip_kinds]
        wanted = {
            action_source_ref(client_id, a): a
            for a in eligible[: settings.task_producer_action_plan_max]
        }

        live = (
            get_supabase()
            .table("tasks")
            .select("id, source_ref, completed")
            .eq("client_id", client_id)
            .eq("source", "action_plan")
            .is_("deleted_at", "null")
            .execute()
        ).data or []
        live_refs = {t.get("source_ref") for t in live}

        for ref, a in wanted.items():
            if ref in live_refs:
                continue
            name = a.get("recommendation") or a.get("cta_label") or "Action Plan item"
            _create(
                client_id,
                name[:200],
                source="action_plan",
                source_ref=ref,
                description=(
                    f"{a.get('diagnosis') or ''}\n\n"
                    f"Open the tool: {a.get('cta_path') or f'/clients/{client_id}/action-plan'}"
                ).strip(),
            )
        # An action that left the latest plan resolved (or was superseded).
        current_refs = {action_source_ref(client_id, a) for a in eligible}
        for t in live:
            if not t.get("completed") and t.get("source_ref") and t["source_ref"] not in current_refs:
                task_service.close_task_by_source("action_plan", t["source_ref"])
    except Exception as exc:
        logger.warning("task_producer_action_plan_failed", extra={"client_id": client_id, "error": str(exc)})


# ---------------------------------------------------------------------------
# Content runs (opt-in; PRD marks this producer optional)
# ---------------------------------------------------------------------------
def on_run_completed(run_id: str) -> None:
    if not _enabled(settings.task_producer_content_run_enabled):
        return
    try:
        rows = (
            get_supabase()
            .table("runs")
            .select("id, client_id, keyword, published_at")
            .eq("id", run_id)
            .limit(1)
            .execute()
        ).data
        if not rows or not rows[0].get("client_id") or rows[0].get("published_at"):
            return
        run = rows[0]
        _create(
            run["client_id"],
            f"Review & publish: {run.get('keyword') or 'article'}",
            source="content_run",
            source_ref=str(run_id),
            description=f"The article finished generating — review it and publish.\n\nRun: /runs/{run_id}",
        )
        # QA auto-queue (qa-agent-plan Phase 4, opt-in): move the fresh review
        # task straight to In QA so generated content is QA'd before a human
        # touches it — the status change fires the qa_service trigger.
        if settings.qa_autoqueue_producers and settings.qa_enabled:
            task = task_service.find_by_source("content_run", str(run_id))
            if task and not task.get("completed"):
                task_service.update_task(task["id"], {"status_key": settings.qa_trigger_status})
    except Exception as exc:
        logger.warning("task_producer_content_run_failed", extra={"run_id": run_id, "error": str(exc)})


def on_run_published(run_id: str) -> None:
    """Close the review task when the run publishes (safe to call even when
    the producer is off — closing an existing task is always correct)."""
    if not settings.native_tasks_enabled:
        return
    task_service.close_task_by_source("content_run", str(run_id))

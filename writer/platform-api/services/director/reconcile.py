"""Director of Operations — daily reversible reconciliation (build spec §6.1).

Runs on the shared scheduler, gated on ``director_enabled``. For each newly
tripped seam flag it takes the ONE reversible action the plan permits:

  * a per-client seam (strategist_approved_unplaced / autonomy_proposed_unactioned
    / content_shipped_degraded) -> open one board task through the standard
    producer contract (``source="director_seam"``), which auto-closes via
    ``task_service.close_task_by_source`` once the seam clears — the same
    open/close discipline every ``task_producers.py`` hook already uses.
  * ``duplicate_target`` -> open one task naming BOTH offending items.
    Flag-only (decision 3) — no merge, no suppression.
  * ``qa_idle`` (portfolio) -> an agency notification, not a board task (there
    is no one client to file it against).

Never resolves, merges, reassigns, or reorders anything — a task that can be
trashed and a deduped notification are the entirety of what this writes.
Idempotent by construction (the ``tasks`` table's partial unique index on
``(source, source_ref)``; ``notifications.dedupe_key``).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from config import settings
from db.supabase_client import get_supabase
from services import task_service
from services.director import read_model

logger = logging.getLogger(__name__)

_TITLES = {
    "strategist_proposal_pending": "SerMaStr proposal is waiting on an approve/dismiss decision",
    "strategist_approved_unplaced": "SerMaStr proposal approved but not yet placed on the board",
    "autonomy_proposed_unactioned": "Autonomy proposed an action nobody has picked up",
    "content_shipped_degraded": "Content shipped without full brand context",
    "duplicate_target": "Two agents are acting on the same target",
}


def _month_section_id(client_id: str) -> Optional[str]:
    """Mirrors ``task_producers._month_section_id`` — a director_seam task
    lands in the client's current-month section like any other producer
    task."""
    try:
        from services.task_monthly import ensure_month_section

        return ensure_month_section(client_id, date.today())["id"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.section_resolve_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def _describe(flag: dict) -> str:
    evidence = flag.get("evidence") or {}
    lines = [f"Seam: {flag['seam']}", f"Evidence: {evidence}"]
    if flag.get("since"):
        lines.append(f"Since: {flag['since']}")
    lines.append(
        "\nOpened by the Director of Operations read model — a read-only "
        "observer. This flags the seam for a human; nothing was reassigned "
        "or reprioritized."
    )
    return "\n".join(lines)


def _source_ref(flag: dict) -> str:
    scope = flag.get("client_id") or "portfolio"
    return f"{flag['seam']}:{scope}:{flag.get('ident')}"


def _open_director_seam_refs() -> dict[str, str]:
    """{source_ref: task_id} for every live director_seam task, portfolio-wide."""
    try:
        rows = (
            get_supabase()
            .table("tasks")
            .select("id, source_ref")
            .eq("source", "director_seam")
            .eq("completed", False)
            .is_("deleted_at", "null")
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.open_seam_read_failed", extra={"error": str(exc)})
        return {}
    return {r["source_ref"]: r["id"] for r in rows if r.get("source_ref")}


def _open_seam_task(flag: dict, source_ref: str) -> None:
    client_id = flag.get("client_id")
    if flag["seam"] == "duplicate_target":
        items = (flag.get("evidence") or {}).get("items") or []
        names = ", ".join(f"{item.get('kind')}:{item.get('source')}" for item in items)
        title = f"{_TITLES['duplicate_target']} ({names})" if names else _TITLES["duplicate_target"]
    else:
        title = _TITLES.get(flag["seam"], f"Director seam: {flag['seam']}")

    row = task_service.create_task(
        title,
        client_id=client_id,
        section_id=_month_section_id(client_id) if client_id else None,
        description=_describe(flag),
        source="director_seam",
        source_ref=source_ref,
    )
    if settings.pace_autoplace_producers and client_id and row and row.get("id"):
        try:
            from services import pm_assign

            pm_assign.place_task(row["id"])
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "director.seam_autoplace_failed", extra={"source_ref": source_ref, "error": str(exc)}
            )


def _notify_qa_idle(flag: dict, today: date) -> bool:
    from services import notifications

    iso_year, iso_week, _ = today.isocalendar()
    evidence = flag.get("evidence") or {}
    notification_id = notifications.emit(
        client_id=None,
        kind="ops_seam",
        title=f"QA idle — nothing has entered In QA in {flag.get('threshold_days')}+ days",
        summary=(
            f"Last entry into QA: {evidence.get('last_entered_at') or 'never observed'}. "
            f"{evidence.get('reviews_considered', 0)} QA reviews recorded in the read window."
        ),
        severity="warning",
        payload={"link": "/tasks"},
        dedupe_key=f"ops_seam:qa_idle:{iso_year}-W{iso_week:02d}",
    )
    return notification_id is not None


def _notify_audit_health(model: dict, today: date) -> int:
    """Emit one ``ops_seam`` notification per audit-log health finding, deduped
    per ISO week so a daily check alerts a persistent finding at most once a week
    (mirrors the qa_idle weekly dedupe). Returns the count actually emitted (a
    dedupe conflict returns None from ``emit`` and is not counted)."""
    from services import notifications
    from services.director import audit_health

    findings = ((model.get("audit_health") or {}).get("findings")) or []
    if not findings:
        return 0
    iso_year, iso_week, _ = today.isocalendar()
    emitted = 0
    for finding in findings:
        ident = finding.get("ident")
        if not ident:
            continue
        notification_id = notifications.emit(
            client_id=finding.get("client_id"),
            kind="ops_seam",
            title=audit_health.notification_title(finding),
            summary=finding.get("label"),
            severity=finding.get("severity") or "warning",
            payload={"link": "/strategist/log" if finding.get("agent") == "sermastr" else "/pace/log",
                     "audit_finding": {k: finding.get(k) for k in ("agent", "kind", "ident", "detail")}},
            dedupe_key=audit_health.finding_dedupe_key(ident, iso_year, iso_week),
        )
        if notification_id is not None:
            emitted += 1
    return emitted


def run_daily(today: Optional[date] = None) -> dict:
    """Self-gated on ``director_enabled``; best-effort — never raises into the
    scheduler tick. Returns a summary dict describing what it did."""
    today = today or date.today()
    if not settings.director_enabled:
        return {"reconciled": False, "reason": "disabled"}

    try:
        model = read_model.build_read_model(None, today)
        flags = (model.get("flow") or {}).get("flags") or []
        board_flags = [f for f in flags if f["seam"] != "qa_idle"]
        idle_flag = next((f for f in flags if f["seam"] == "qa_idle"), None)

        open_refs = _open_director_seam_refs()
        live_refs: set[str] = set()
        opened: list[str] = []
        closed: list[str] = []

        for flag in board_flags:
            ref = _source_ref(flag)
            live_refs.add(ref)
            if ref in open_refs:
                continue
            _open_seam_task(flag, ref)
            opened.append(ref)

        for ref, _task_id in open_refs.items():
            if ref not in live_refs and task_service.close_task_by_source("director_seam", ref):
                closed.append(ref)

        notified = bool(idle_flag) and _notify_qa_idle(idle_flag, today)
        # Audit-log process-health alerts (owner ask 2026-09-01) — never board
        # tasks, always ops_seam notifications deduped per ISO week.
        audit_alerts = _notify_audit_health(model, today)

        return {
            "reconciled": True,
            "flags": len(flags),
            "opened": opened,
            "closed": closed,
            "qa_idle_notified": notified,
            "audit_health_alerts": audit_alerts,
        }
    except Exception as exc:  # noqa: BLE001 — one bad tick must not abort the scheduler loop
        logger.warning("director.reconcile_failed", extra={"error": str(exc)})
        return {"reconciled": False, "reason": "error", "error": str(exc)[:200]}

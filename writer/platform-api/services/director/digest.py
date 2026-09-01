"""Director of Operations — weekly operations-flow digest (build spec §6.2,
owner decision 2). Its own weekly hook, not a line on the daily PACE digest —
a deliberate deviation from the plan's original lean, so operations chatter
doesn't crowd the daily delivery digest.

Deterministic assembly (no LLM in v1 — a narrative pass is a deferred polish,
never a source of fabricated numbers). Suppresses entirely on an all-clear
week (zero seam flags AND zero autonomy activity), mirroring
``pace_digest.run_daily_digest``'s ``all_clear`` short-circuit — the guard
against the "weekly narrative is noisy" risk the plan flagged when it leaned
toward the daily line instead.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from config import settings
from services.director import read_model

logger = logging.getLogger(__name__)


def dedupe_key(today: date) -> str:
    """Stable across a redeploy re-run of the same ISO week. Pure."""
    iso_year, iso_week, _ = today.isocalendar()
    return f"ops_digest:{iso_year}-W{iso_week:02d}"


def _client_names(client_ids: list[Optional[str]]) -> dict[str, str]:
    ids = [c for c in set(client_ids) if c]
    if not ids:
        return {}
    try:
        from db.supabase_client import get_supabase

        rows = get_supabase().table("clients").select("id, name").in_("id", ids).execute().data or []
        return {r["id"]: r.get("name") or r["id"] for r in rows}
    except Exception as exc:  # noqa: BLE001
        logger.warning("director.digest_client_names_failed", extra={"error": str(exc)})
        return {}


_SEAM_ORDER = [
    "unwatched_seam", "qa_idle", "strategist_proposal_pending", "strategist_approved_unplaced",
    "autonomy_proposed_unactioned", "content_shipped_degraded", "duplicate_target",
]


def format_digest(model: dict, names: dict[str, str]) -> str:
    """The deterministic narrative body — per-seam counts with the named
    clients (enumerate, don't count — PACE's rule), the week's qa_idle state,
    autonomy executed-vs-proposed totals, the top capacity holds, and any
    ``unwatched_seam`` (E1). Pure."""
    flags = (model.get("flow") or {}).get("flags") or []
    by_seam: dict[str, list[dict]] = {}
    for flag in flags:
        by_seam.setdefault(flag["seam"], []).append(flag)

    def _name(client_id: Optional[str]) -> str:
        return names.get(client_id, client_id) if client_id else "portfolio"

    lines: list[str] = []
    for seam in _SEAM_ORDER:
        items = by_seam.get(seam) or []
        if not items:
            continue
        if seam == "unwatched_seam":
            named = ", ".join(
                f"{f['evidence'].get('source')} ({f['evidence'].get('open_count')} open)" for f in items
            )
            lines.append(f"⚠ Unwatched producer source(s): {named}")
            continue
        clients = ", ".join(sorted({_name(f.get("client_id")) for f in items}))
        lines.append(f"{seam} — {len(items)} ({clients})")

    autonomy = model.get("autonomy") or {}
    if autonomy:
        lines.append(
            f"Autonomy this window — executed {autonomy.get('executed', 0)}, "
            f"proposed {autonomy.get('proposed', 0)}, escalated {autonomy.get('escalated', 0)}"
        )

    holds = (model.get("assignment") or {}).get("open_holds") or []
    if holds:
        named_holds = "; ".join(
            f"{_name(h.get('client_id'))} — {h.get('name')} ({h.get('reason')})" for h in holds[:5]
        )
        lines.append(f"Open capacity holds: {named_holds}")

    # Audit-log process health (owner ask 2026-09-01) — a dedicated section, not
    # a flow.flags seam. Renders the SerMaStr/PACE pipeline-efficiency findings.
    from services.director import audit_health

    lines += audit_health.format_health_section(
        ((model.get("audit_health") or {}).get("findings")) or [])

    return "\n".join(lines) if lines else "No cross-agent seams flagged this week."


def run_weekly(today: Optional[date] = None) -> dict:
    """Self-gated on ``director_enabled``; suppresses on an all-clear week
    (returns without emitting). Best-effort — never raises into the scheduler
    tick."""
    today = today or date.today()
    if not settings.director_enabled:
        return {"emitted": False, "reason": "disabled"}

    try:
        model = read_model.build_read_model(None, today)
        flags = (model.get("flow") or {}).get("flags") or []
        autonomy = model.get("autonomy") or {}
        autonomy_activity = sum(
            autonomy.get(k, 0) or 0 for k in ("executed", "proposed", "escalated")
        )
        audit_findings = ((model.get("audit_health") or {}).get("findings")) or []
        if not flags and not autonomy_activity and not audit_findings:
            return {"emitted": False, "reason": "all_clear"}

        names = _client_names([f.get("client_id") for f in flags])
        body = format_digest(model, names)
        key = dedupe_key(today)
        monday = today - timedelta(days=today.weekday())

        from services import notifications

        notification_id = notifications.emit(
            client_id=None,
            kind="ops_digest",
            title=f"Operations flow · week of {monday.isoformat()}",
            summary=body,
            severity="info",
            payload={"link": "/tasks", "slack_channel": settings.pace_slack_channel or None},
            dedupe_key=key,
        )
        return {
            "emitted": notification_id is not None,
            "flags": len(flags),
            "deduped": notification_id is None,
        }
    except Exception as exc:  # noqa: BLE001 — never break the scheduler tick
        logger.warning("director.digest_failed", extra={"error": str(exc)})
        return {"emitted": False, "reason": "error", "error": str(exc)[:200]}

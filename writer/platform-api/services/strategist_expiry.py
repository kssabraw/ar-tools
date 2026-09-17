"""Strategist proposal auto-expiry — retire stale, un-actioned recommendations.

A strategist proposal is time-decaying advice: a recommendation nobody approved
or dismissed within ``strategist_proposal_expiry_days`` of its review is no
longer actionable, but nothing retired it — so 'proposed' proposals accumulated
forever (342 across 23 clients by 2026-09), and DORA opened a
``strategist_proposal_pending`` seam task per one past
``director_seam_proposal_pending_days``.

This daily sweep moves a still-'proposed' proposal whose review is older than the
window to 'expired' — a SYSTEM state (distinct from a human 'dismissed'; excluded
from the audit learning rates, mirroring 'superseded'). ``prov_strategy`` only
feeds its seam on 'proposed', so expiring a proposal clears its flag and the next
director reconcile closes the seam task — no seam-code change.

Mirrors ``services/goal_recovery.py``'s supersede sweep (pure marker + best-effort
per-review write + audit). Idempotent: only 'proposed' proposals change.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Reviews that just crossed the cutoff sort to the TOP of the "older than cutoff"
# set (created_at desc), and after the one-time backfill they are the only ones
# that can still hold a 'proposed' proposal — so a bounded newest-first scan
# reliably reaches every review needing expiry. Ancient fully-expired reviews at
# the tail are simply re-read as no-ops (one cheap query/day).
_SCAN_LIMIT = 1000


def mark_expired(proposals: list[dict]) -> tuple[list[dict], list[int]]:
    """``proposed`` → ``expired`` (approved / dismissed / superseded untouched).
    Returns the new list and the indices that changed. Pure."""
    out, changed = [], []
    for i, p in enumerate(proposals or []):
        q = dict(p)
        if (q.get("status") or "proposed") == "proposed":
            q["status"] = "expired"
            changed.append(i)
        out.append(q)
    return out, changed


def _client_names(client_ids: list) -> dict:
    """Best-effort id → name for the audit rows (a name only decorates the log)."""
    ids = sorted({c for c in client_ids if c})
    if not ids:
        return {}
    try:
        rows = (get_supabase().table("clients").select("id, name").in_("id", ids).execute()).data or []
        return {r["id"]: r.get("name") for r in rows if r.get("id")}
    except Exception:
        return {}


def expire_stale_proposals(now: Optional[datetime] = None) -> int:
    """Retire every still-'proposed' proposal whose review is older than
    ``strategist_proposal_expiry_days``. Returns how many were expired.
    Best-effort — each review is written + audited independently, and a failure
    on one never aborts the rest."""
    if (not settings.strategist_proposal_expiry_enabled
            or settings.strategist_proposal_expiry_days <= 0):
        return 0
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=settings.strategist_proposal_expiry_days)).isoformat()
    supabase = get_supabase()
    try:
        rows = (
            supabase.table("strategy_reviews")
            .select("id, client_id, trigger, proposals")
            .lt("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(_SCAN_LIMIT)
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("strategist_expiry.read_failed", extra={"error": str(exc)})
        return 0

    names = _client_names([r.get("client_id") for r in rows])
    total = 0
    for r in rows:
        updated, changed = mark_expired(r.get("proposals") or [])
        if not changed:
            continue
        try:
            supabase.table("strategy_reviews").update({"proposals": updated}).eq("id", r["id"]).execute()
        except Exception as exc:
            logger.warning("strategist_expiry.write_failed",
                           extra={"review_id": r.get("id"), "error": str(exc)})
            continue
        total += len(changed)
        try:
            from services import sermastr_audit

            for idx in changed:
                sermastr_audit.record_expired(
                    review_id=r["id"], idx=idx, proposal=updated[idx],
                    client_id=r.get("client_id"), client_name=names.get(r.get("client_id")),
                    trigger=r.get("trigger"),
                )
        except Exception as exc:
            logger.warning("strategist_expiry.audit_failed",
                           extra={"review_id": r.get("id"), "error": str(exc)})
    if total:
        logger.info("strategist_expiry.expired", extra={"count": total, "reviews": len(rows)})
    return total

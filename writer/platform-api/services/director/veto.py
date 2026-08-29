"""Director of Operations — autonomy pre-flight veto (plan §5 decision 4;
build spec §8). Ships dark behind ``director_autonomy_veto_enabled``.

Guards a collision that has not yet been observed in production (autonomy is
a narrow safe-slice today — see ``autonomy_executor.AUTO_EXECUTE``): an
about-to-auto-execute candidate targeting a keyword some OTHER in-flight
agent action already targets for the same client. Fail-**open** — the
autonomy loop is best-effort throughout (``run_autonomy_for_client``: "a
per-step failure degrades to observation, never raises"), and this predicate
must never become the reason an autonomous action silently blocks. Any read
error, or a candidate with no target, means no veto.

``autonomy_policy.classify`` stays pure — the veto lives here, in the impure
executor's act loop, never inside the policy engine.
"""

from __future__ import annotations

import logging

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def preflight_conflict(rec: dict, client_id: str) -> bool:
    """True when ``rec`` (an autonomy candidate about to auto-execute) targets
    a keyword some other in-flight action already targets for ``client_id``.

    Exempt candidates with no target (e.g. ``rebuild_action_plan`` — nothing
    to conflict on). Fail-open: any exception returns ``False``."""
    keyword = (rec.get("keyword") or "").strip().casefold()
    if not keyword:
        return False
    try:
        supabase = get_supabase()

        jobs = (
            supabase.table("async_jobs")
            .select("id, payload")
            .eq("entity_id", client_id)
            .in_("status", ["pending", "running"])
            .execute()
        ).data or []
        for job in jobs:
            payload_kw = ((job.get("payload") or {}).get("keyword") or "").strip().casefold()
            if payload_kw and payload_kw == keyword:
                return True

        tasks = (
            supabase.table("tasks")
            .select("id, target")
            .eq("client_id", client_id)
            .eq("completed", False)
            .is_("deleted_at", "null")
            .execute()
        ).data or []
        for task in tasks:
            target_kw = ((task.get("target") or {}).get("keyword") or "").strip().casefold()
            if target_kw and target_kw == keyword:
                return True

        interventions = (
            supabase.table("interventions")
            .select("id, target")
            .eq("client_id", client_id)
            .is_("verdict", "null")
            .execute()
        ).data or []
        for intervention in interventions:
            target_kw = ((intervention.get("target") or {}).get("keyword") or "").strip().casefold()
            if target_kw and target_kw == keyword:
                return True

        return False
    except Exception as exc:  # noqa: BLE001 — fail-open, never block autonomy
        logger.warning("director.veto_check_failed", extra={"client_id": client_id, "error": str(exc)})
        return False

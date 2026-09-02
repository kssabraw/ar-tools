"""Strategist proposal decisions — the reusable core behind approve/dismiss.

The per-proposal approve/dismiss side-effects (push the approved proposal to the
board + auto-place it, register the intervention, record the action-log decision,
post the SerMaStr→PACE handoff on the coordination bus) used to live inline in the
``POST /strategy-proposals/{review_id}/{idx}`` router. They are extracted here so
the **bulk** plan→PACE handoff (services/plan_handoff.py) can approve every open
proposal through the *same* code path — one source of truth for "approve a
proposal", no drift on a sensitive, side-effect-heavy write.

``apply_decision`` is the whole thing (validate → senior gate → status → approve
side-effects → persist → audit → bus). ``ProposalError`` carries a code the router
maps to an HTTP status. ``handoff_open_proposals`` approves every still-open
proposal of a client's latest review, skipping senior-gated ones a non-admin
can't approve (reported, never failing the batch).
"""

from __future__ import annotations

import logging
from typing import Optional

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# A human can only APPROVE or DISMISS; ``superseded`` is a system state (the
# proposal was replaced by a newer recovery plan — services/goal_recovery.py)
# that closes the proposal without a human verdict.
_TERMINAL = ("approved", "dismissed")
_CLOSED = ("approved", "dismissed", "superseded")


class ProposalError(Exception):
    """A decision that can't be applied. ``code`` mirrors the old router details
    (review_not_found / proposal_not_found / invalid_status /
    senior_approval_required) so the router maps it to the same HTTP status."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _client_name(client_id: Optional[str]) -> Optional[str]:
    if not client_id:
        return None
    try:
        rows = (
            get_supabase().table("clients").select("name").eq("id", client_id).limit(1).execute()
        ).data
        return rows[0].get("name") if rows else None
    except Exception:  # best-effort — a name is only for the audit row
        return None


async def apply_decision(
    review_id: str,
    idx: int,
    decision: str,
    *,
    actor_id: Optional[str],
    actor_role: Optional[str],
    actor_source: str = "web",
) -> dict:
    """Approve or dismiss one proposal, running every side-effect the router does.

    Returns ``{"review_id", "idx", "status", "asana_task"}``. Raises
    ``ProposalError`` for the validation/authorization failures. The approve
    side-effects (task push + place, intervention register, agent_bus handoff) are
    each best-effort — approval never fails over them, mirroring the router.
    """
    if decision not in _TERMINAL:
        raise ProposalError("invalid_status")

    supabase = get_supabase()
    rows = (
        supabase.table("strategy_reviews")
        .select("id, proposals, client_id, trigger")
        .eq("id", review_id).limit(1).execute()
    ).data
    if not rows:
        raise ProposalError("review_not_found")
    proposals = rows[0].get("proposals") or []
    client_id = rows[0].get("client_id")
    review_trigger = rows[0].get("trigger")
    if not (0 <= idx < len(proposals)):
        raise ProposalError("proposal_not_found")
    if proposals[idx].get("status") == "superseded":
        raise ProposalError("proposal_superseded")

    # §3 passthroughs: a requires='senior' proposal is Kyle/Ryan territory —
    # only an admin may approve/dismiss it (admins are the senior owners).
    if proposals[idx].get("requires") == "senior" and actor_role != "admin":
        raise ProposalError("senior_approval_required")

    proposals[idx]["status"] = decision
    proposals[idx]["decided_by"] = actor_id

    if decision == "approved":
        from services import asana_push, interventions

        if client_id:
            # Intervention-outcome loop: stamp the shared source_ref onto the
            # target BEFORE the push so the created task carries it (the native
            # registration hook keys on it → both hooks converge on one row).
            tgt = proposals[idx].get("target")
            if isinstance(tgt, dict):
                tgt.setdefault(
                    "source_ref", interventions.source_ref_for_proposal(review_id, idx)
                )
            # Push the task once (skip when a previous approve→dismiss→approve
            # cycle already created it).
            if not proposals[idx].get("asana_task"):
                task = await asana_push.push_proposal(str(client_id), review_id, proposals[idx])
                if task:
                    proposals[idx]["asana_task"] = task
            # Register the intervention on EVERY approve (idempotent per
            # source_ref, flag-gated inside; only a goal-linked in-scope target
            # enrolls). Unconditional so a transiently-failed first registration
            # retries.
            try:
                iid = interventions.register_from_proposal(
                    str(client_id), review_id, idx, proposals[idx]
                )
                if iid:
                    proposals[idx]["intervention_id"] = iid
            except Exception as exc:
                logger.warning(
                    "intervention_register_failed",
                    extra={"review_id": review_id, "idx": idx, "error": str(exc)},
                )

    supabase.table("strategy_reviews").update({"proposals": proposals}).eq(
        "id", review_id
    ).execute()

    # Action log (audit + learning): record the human decision at SerMaStr's own
    # decision seam. Best-effort — never fails the decision.
    try:
        from services import sermastr_audit

        sermastr_audit.record_decision(
            review_id=review_id, idx=idx, proposal=proposals[idx],
            client_id=client_id, client_name=_client_name(client_id),
            trigger=review_trigger, decision=decision, actor_profile_id=actor_id,
            actor_role=actor_role, actor_source=actor_source,
        )
    except Exception as exc:
        logger.warning("sermastr_audit_decision_failed",
                       extra={"review_id": review_id, "idx": idx, "error": str(exc)})

    # Coordination bus (WS3): an approved proposal is a SerMaStr→PACE handoff.
    # Acked when a board task landed; left OPEN when approval produced no task.
    if decision == "approved" and client_id:
        try:
            from services import agent_bus

            corr = f"strategy_proposal:{review_id}:{idx}"
            task = proposals[idx].get("asana_task")
            agent_bus.post(
                from_agent="sermastr", to_agent="pace", kind="handoff", client_id=client_id,
                subject=proposals[idx].get("title"),
                body="Approved strategist proposal to execute.",
                ref=(task or {}).get("gid") if isinstance(task, dict) else None,
                correlation_id=corr, payload={"review_id": review_id, "idx": idx},
            )
            if task:
                agent_bus.mark_acted(correlation_id=corr, by_agent="pace")
        except Exception as exc:
            logger.warning("agent_bus_handoff_failed",
                           extra={"review_id": review_id, "idx": idx, "error": str(exc)})

    return {
        "review_id": review_id, "idx": idx, "status": decision,
        "asana_task": proposals[idx].get("asana_task"),
    }


def _latest_review_with_proposals(client_id: str) -> Optional[dict]:
    """The client's most recent strategy review that carries any proposals — the
    'plan it created'. None when the client has never had a review with proposals."""
    rows = (
        get_supabase().table("strategy_reviews")
        .select("id, proposals")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    ).data or []
    for r in rows:
        if r.get("proposals"):
            return r
    return None


def open_proposal_indices(proposals: list[dict]) -> list[int]:
    """Indices of proposals still awaiting a human decision (status not
    approved/dismissed). Pure."""
    return [i for i, p in enumerate(proposals or []) if (p.get("status") or "proposed") not in _CLOSED]


async def handoff_open_proposals(
    client_id: str,
    *,
    actor_id: Optional[str],
    actor_role: Optional[str],
    actor_source: str = "system",
) -> dict:
    """Approve every still-open proposal of the client's latest review — each
    approval creates + auto-places its board task through ``apply_decision``.

    A ``requires='senior'`` proposal a non-admin can't approve is skipped (counted
    in ``skipped_senior``), never failing the batch. Returns a summary.
    """
    review = _latest_review_with_proposals(client_id)
    if not review:
        return {"status": "no_review", "review_id": None, "approved": 0,
                "skipped_senior": 0, "failed": 0, "tasks": []}
    review_id = review["id"]
    proposals = review.get("proposals") or []
    indices = open_proposal_indices(proposals)
    approved = 0
    skipped_senior = 0
    failed = 0
    tasks: list[dict] = []
    for idx in indices:
        try:
            res = await apply_decision(
                review_id, idx, "approved",
                actor_id=actor_id, actor_role=actor_role, actor_source=actor_source,
            )
            approved += 1
            if res.get("asana_task"):
                tasks.append(res["asana_task"])
        except ProposalError as exc:
            if exc.code == "senior_approval_required":
                skipped_senior += 1
            else:  # review/proposal vanished mid-loop — count and continue
                failed += 1
        except Exception as exc:  # one bad proposal never aborts the rest
            failed += 1
            logger.warning("proposal_handoff_failed",
                           extra={"review_id": review_id, "idx": idx, "error": str(exc)})
    return {
        "status": "ok",
        "review_id": review_id,
        "open": len(indices),
        "approved": approved,
        "skipped_senior": skipped_senior,
        "failed": failed,
        "tasks": tasks,
    }

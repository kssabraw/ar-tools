"""Autonomous SEO agent — the executor (plan §2.1). SHIPPED DARK.

The loop, per client, on the shared scheduler:

  1. gate       — autonomy_enabled AND the client's effective tier > 0
  2. read goals — campaign_goals.assess_goals; no behind/overdue goal ⇒ nothing
                  to do (a healthy client is left alone; not a make-work engine)
  3. gather     — deterministic candidate actions (gather_candidates, pure)
  4. decide     — autonomy_policy.classify each (effective tier, budget, rate,
                  freeze) → auto | propose | escalate
  5. act        — an AUTO candidate whose action is in the v1 AUTO_EXECUTE
                  allowlist is reserved against the budget (if it costs) and
                  executed; everything else is RECORDED, never run
  6. record     — write the autonomy_runs ledger + emit the owner digest

Two independent clamps keep v1 safe:
  * ``autonomy_enabled`` (default False) — the whole loop is dormant.
  * ``AUTO_EXECUTE`` — even enabled, only a free, idempotent, harmless action
    (rebuild_action_plan) actually runs. Every content / paid candidate is
    recorded as a proposal for the pilot to read in the ledger + digest, and
    is NOT auto-run until AUTO_EXECUTE is deliberately widened after the gate
    run. This is why a striking-distance keyword never silently becomes a new
    (cannibalising) blog post in v1.

Pure decision helpers (``gather_candidates``, ``decide_candidates``) are
unit-tested without a database; the reads/execute/ledger are the thin impure
shell.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Callable, Optional

from config import settings
from db.supabase_client import get_supabase
from services import autonomy_budget, autonomy_policy

logger = logging.getLogger(__name__)

# v1 auto-executable set — deliberately just the free, idempotent, reversible
# plan rebuild. Widen ONLY after a pilot gate run reads the ledger and trusts a
# class. Keys are action names understood by ``_execute``.
AUTO_EXECUTE: frozenset[str] = frozenset({"rebuild_action_plan", "generate_local_seo_page"})

_BEHIND = {"behind", "overdue"}


# --- Pure core --------------------------------------------------------------

def gather_candidates(
    goals: list[dict],
    action_plan: Optional[dict],
    client_location: Optional[str] = None,
) -> list[dict]:
    """Deterministic candidate actions for a client with behind/overdue goals.

    Pure. Emits:
      * one free ``rebuild_action_plan`` whenever any goal is behind/overdue;
      * per Action Plan quick_win / opportunity item, a content candidate whose
        ACTION and AUTO-ELIGIBILITY follow the item's own signal:
          - a "Create page" quick-win (SERP winnable, the client has NO strong
            page yet) with a known client location → ``generate_local_seo_page``,
            ``requires="none"`` (auto-eligible: a net-new page for a keyword the
            client doesn't already rank for can't cannibalise an existing page);
          - everything else — a "Reoptimize" quick-win or an opportunity (both
            want an EXISTING page improved, but the Action Plan item carries no
            URL), or a create-page item with no location — stays
            ``requires="approval"`` (surfaced, never auto-run). The action name
            reflects intent (reoptimize_page vs generate_local_seo_page) so the
            proposal reads correctly and classifies at the right tier.

    Cost estimates are attached so the budget governor gates real spend.
    """
    behind = [g for g in goals if g.get("status") in _BEHIND]
    if not behind:
        return []

    loc = (client_location or "").strip()
    out: list[dict] = [{
        "action": "rebuild_action_plan",
        "cost_usd": 0.0,
        "requires": "none",
        "source": "loop",
        "reason": f"{len(behind)} goal(s) behind/overdue — refresh the Action Plan",
    }]

    for item in (action_plan or {}).get("items") or []:
        kind = item.get("kind")
        if kind not in ("quick_win", "opportunity"):
            continue
        kw = (item.get("keyword") or "").strip()
        if not kw:
            continue
        cta = (item.get("cta_label") or "").strip().lower()
        create_page = kind == "quick_win" and cta == "create page"
        reason = item.get("recommendation") or kind
        source = f"action_plan:{kind}"

        if create_page and loc:
            # Auto-eligible: a genuinely net-new local page.
            out.append({
                "action": "generate_local_seo_page",
                "keyword": kw,
                "location": loc,
                "cost_usd": float(settings.autonomy_local_seo_cost_usd),
                "requires": "none",
                "source": source,
                "reason": reason,
            })
        else:
            # Proposal only: improving an existing page needs a URL the plan
            # doesn't carry, or a create-page item has no location to target.
            out.append({
                "action": "generate_local_seo_page" if create_page else "reoptimize_page",
                "keyword": kw,
                "cost_usd": float(settings.autonomy_content_cost_usd),
                "requires": "approval",
                "source": source,
                "reason": reason,
            })
    return out


def decide_candidates(
    candidates: list[dict],
    *,
    client_tier: int,
    budget_left: float,
    freeze: bool,
    content_this_week: int,
    content_cap: int,
) -> list[dict]:
    """Run each candidate through the policy engine. Pure — returns a list of
    ``{**candidate, outcome, policy_reason}`` records (no execution, no I/O)."""
    decided: list[dict] = []
    for c in candidates:
        d = autonomy_policy.classify(
            c,
            client_tier=client_tier,
            budget_left=budget_left,
            freeze=freeze,
            content_this_week=content_this_week,
            content_cap=content_cap,
        )
        decided.append({**c, "outcome": d.outcome, "policy_reason": d.reason})
    return decided


# --- Impure shell -----------------------------------------------------------

def _execute(candidate: dict, client_id: str) -> None:
    """Execute one auto-approved candidate. Only actions in AUTO_EXECUTE reach
    here. Runs in a worker thread (see run_autonomy_job → asyncio.to_thread), so
    it dispatches via durable async_jobs rows / a synchronous service call — never
    an in-process pipeline task that a thread can't own."""
    action = candidate.get("action")
    if action == "rebuild_action_plan":
        from services import reopt_planner
        # "manual" (an allowed PLAN_TRIGGER): an on-demand rebuild the autonomy
        # loop initiated. NOT "scheduled" — that pushes the reopt weekly digest,
        # and the executor emits its own digest (double-notify). Autonomy
        # provenance is recorded in the autonomy_runs ledger, not this trigger.
        reopt_planner.build_plan(client_id, trigger="manual")
        return
    if action == "generate_local_seo_page":
        # Enqueue a durable local_seo_generate job (the worker picks it up and
        # resolves the area / runs the generator) — no inline pipeline. The
        # generated page lands as a Saved-Pages DRAFT; publishing stays human.
        get_supabase().table("async_jobs").insert({
            "job_type": "local_seo_generate",
            "entity_id": client_id,
            "payload": {
                "client_id": client_id,
                "keyword": candidate.get("keyword"),
                "location": candidate.get("location"),
                "location_code": None,
                "user_id": "",
                "force_refresh": False,
                "entity_provider": None,
            },
        }).execute()
        return
    raise ValueError(f"no executor for action {action!r}")


def _client_row(client_id: str) -> Optional[dict]:
    try:
        rows = (
            get_supabase()
            .table("clients")
            .select("id, name, autonomy_tier, retainer_monthly, is_sab, business_location")
            .eq("id", client_id)
            .limit(1)
            .execute()
        ).data or []
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("autonomy_client_read_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def _latest_action_plan(client_id: str) -> Optional[dict]:
    try:
        rows = (
            get_supabase()
            .table("reopt_plans")
            .select("items")
            .eq("client_id", client_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("autonomy_plan_read_failed", extra={"client_id": client_id, "error": str(exc)})
        return None


def run_autonomy_for_client(
    client_id: str,
    *,
    trigger: str = "scheduled",
    today: Optional[date] = None,
    execute: Callable[[dict, str], None] = _execute,
) -> dict:
    """Walk the loop for one client. Returns a summary; writes a ledger row +
    owner digest when there was anything to decide. Best-effort throughout —
    a per-step failure degrades to observation, never raises into the caller."""
    if not settings.autonomy_enabled:
        return {"status": "disabled"}

    from services import campaign_goals
    from services.freeze import is_frozen

    client = _client_row(client_id)
    if not client:
        return {"status": "no_client"}
    effective = autonomy_policy.effective_tier(client.get("autonomy_tier"), settings.autonomy_max_tier)
    if effective <= 0:
        return {"status": "not_opted_in"}

    try:
        goals = campaign_goals.assess_goals(client_id, today=today)
    except Exception as exc:  # noqa: BLE001
        logger.warning("autonomy_goals_failed", extra={"client_id": client_id, "error": str(exc)})
        goals = []

    candidates = gather_candidates(
        goals, _latest_action_plan(client_id), client.get("business_location")
    )
    if not candidates:
        return {"status": "noop", "reason": "no behind/overdue goals"}

    freeze = False
    try:
        freeze = is_frozen(client_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("autonomy_freeze_check_failed", extra={"client_id": client_id, "error": str(exc)})

    budget = autonomy_budget.budget_for_client(client)
    spent = autonomy_budget.spent_this_month(client_id, today)
    budget_left = autonomy_budget.remaining(budget, spent)

    decided = decide_candidates(
        candidates,
        client_tier=effective,
        budget_left=budget_left,
        freeze=freeze,
        content_this_week=0,  # v1 auto-runs no content, so nothing accrues
        content_cap=settings.autonomy_max_content_per_week,
    )

    actions_taken: list[str] = []
    cost = 0.0
    for rec in decided:
        if rec["outcome"] != "auto" or rec["action"] not in AUTO_EXECUTE:
            continue
        cost_c = float(rec.get("cost_usd") or 0.0)
        if cost_c > 0 and not autonomy_budget.reserve(client_id, cost_c, cap=budget, today=today):
            rec["outcome"] = "propose"
            rec["policy_reason"] = "budget reservation refused"
            continue
        try:
            execute(rec, client_id)
            rec["executed"] = True
            actions_taken.append(rec["action"])
            cost += cost_c
        except Exception as exc:  # noqa: BLE001 — one action's failure isn't the run's
            rec["executed"] = False
            rec["error"] = str(exc)[:300]
            logger.warning("autonomy_execute_failed",
                           extra={"client_id": client_id, "action": rec["action"], "error": str(exc)})

    _write_ledger(client_id, trigger, effective, goals, decided, actions_taken, cost)
    _emit_digest(client, trigger, decided, actions_taken)

    return {
        "status": "ran",
        "tier": effective,
        "candidates": len(decided),
        "executed": actions_taken,
        "proposed": [r["action"] for r in decided if r["outcome"] == "propose"],
        "escalated": [r["action"] for r in decided if r["outcome"] == "escalate"],
        "cost_usd": round(cost, 2),
    }


def _write_ledger(client_id, trigger, tier, goals, decided, actions_taken, cost) -> None:
    try:
        get_supabase().table("autonomy_runs").insert({
            "client_id": client_id,
            "trigger": trigger,
            "tier": tier,
            "goal_snapshot": [
                {"metric": g.get("metric_type") or g.get("goal_type"), "status": g.get("status")}
                for g in goals
            ] or None,
            "decisions": decided or None,
            "actions_taken": actions_taken or None,
            "cost_usd": round(cost, 2),
        }).execute()
    except Exception as exc:  # noqa: BLE001 — the ledger is best-effort
        logger.warning("autonomy_ledger_write_failed", extra={"client_id": client_id, "error": str(exc)})


def _emit_digest(client, trigger, decided, actions_taken) -> None:
    proposed = [r for r in decided if r["outcome"] == "propose"]
    escalated = [r for r in decided if r["outcome"] == "escalate"]
    if not actions_taken and not proposed and not escalated:
        return
    try:
        from services import notifications
        parts = []
        if actions_taken:
            parts.append(f"did: {', '.join(actions_taken)}")
        if proposed:
            parts.append(f"proposed {len(proposed)} (awaiting approval)")
        if escalated:
            parts.append(f"escalated {len(escalated)}")
        notifications.emit(
            client.get("id"),
            "autonomy_run",
            f"Autonomy run — {client.get('name') or 'client'}",
            summary="; ".join(parts),
            severity="info",
            payload={"trigger": trigger, "decisions": decided},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("autonomy_digest_failed", extra={"error": str(exc)})


# --- Job + enqueue ----------------------------------------------------------

def enqueue_autonomy_run(client_id: str, trigger: str = "scheduled", user_id: Optional[str] = None) -> str:
    row = get_supabase().table("async_jobs").insert({
        "job_type": "autonomy_run",
        "entity_id": client_id,
        "payload": {"client_id": client_id, "trigger": trigger, "user_id": user_id},
    }).execute().data[0]
    return row["id"]


_WEEKLY_INTERVAL_DAYS = 6  # a client run this recently is skipped (weekly cadence)


def enqueue_due_autonomy_runs(today_weekday: Optional[int] = None) -> int:
    """Weekly scheduled pass on ``autonomy_weekly_weekday``: one run per opted-in
    (tier > 0) client not already run within the last week. No-ops entirely while
    ``autonomy_enabled`` is False. Self-gated on the autonomy_runs ledger (recency),
    so it needs no scheduler marker and a redeploy can't double-fire it."""
    if not settings.autonomy_enabled:
        return 0
    from datetime import datetime, timedelta, timezone

    if today_weekday is None:
        today_weekday = datetime.now(timezone.utc).weekday()
    if today_weekday != settings.autonomy_weekly_weekday:
        return 0
    supabase = get_supabase()
    try:
        clients = (
            supabase.table("clients").select("id").gt("autonomy_tier", 0).execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("autonomy_due_clients_failed", extra={"error": str(exc)})
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_WEEKLY_INTERVAL_DAYS)).isoformat()
    n = 0
    for c in clients:
        cid = c.get("id")
        try:
            recent = (
                supabase.table("autonomy_runs").select("id")
                .eq("client_id", cid).gte("created_at", cutoff).limit(1).execute()
            ).data
            if recent:
                continue
            enqueue_autonomy_run(cid, "scheduled")
            n += 1
        except Exception as exc:  # noqa: BLE001 — one client can't break the pass
            logger.warning("autonomy_enqueue_failed", extra={"client_id": cid, "error": str(exc)})
    return n


async def run_autonomy_job(job: dict) -> None:
    import asyncio

    payload = job.get("payload") or {}
    client_id = payload.get("client_id") or job.get("entity_id")
    supabase = get_supabase()
    try:
        result = await asyncio.to_thread(
            run_autonomy_for_client, client_id, trigger=payload.get("trigger") or "scheduled"
        )
        supabase.table("async_jobs").update(
            {"status": "complete", "result": result, "completed_at": "now()"}
        ).eq("id", job["id"]).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("autonomy_job_failed", extra={"client_id": client_id, "error": str(exc)})
        supabase.table("async_jobs").update(
            {"status": "failed", "error": str(exc)[:500], "completed_at": "now()"}
        ).eq("id", job["id"]).execute()

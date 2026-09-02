"""Chronic-goal recovery runs — SerMaStr autonomously hands over a SOLUTION.

The chronic-goal escalation (services/goal_escalation.py, #949) made a goal
that stays critically behind LOUD; it did not make the strategist produce the
fix. The owner had to drag a recovery plan out of SerMaStr by chat. This module
closes that gap (PRD: docs/modules/sermastr-autonomous-recovery-plans-prd-v1_0.md):

- when a client's goal is due to (re-)escalate, the daily sweep enqueues ONE
  ``goal_recovery`` strategist run for the client (all its chronic goals),
  capped per tick (``goal_recovery_max_runs_per_tick``, oldest-behind first —
  a capped client is not escalated that day, it rolls forward);
- the run reads the normal digest plus a RECOVERY block (the chronic goals,
  the prior recovery plan's proposals, the budget envelope + tier ceilings)
  and must emit a concrete, costed, SOP-cited recovery plan + a ``root_cause``;
- after the run: budget tiers are assigned DETERMINISTICALLY in code
  (cumulative +25/+50/+100% over deployable, in the strategist's priority
  order), the prior recovery plan's unactioned proposals are ``superseded``,
  the ``goal_escalations`` rows are stamped, and the FINISHED run emits the
  single ``goal_chronic`` message (alarm + root cause + plan). The sweep only
  sends the bare alarm when a run is impossible.

PROPOSE-ONLY (owner ruling 2026-09-02): the run stops at approvable proposals.
Nothing here hands work to PACE; approval goes through the unchanged
``strategist_proposals.apply_decision`` path. The pure helpers are unit-tested;
the impure ones isolate the DB reads and are best-effort.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import settings
from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)

TRIGGER = "goal_recovery"
NOTIFICATION_KIND = "goal_chronic"
DEFAULT_TIERS = (0.25, 0.50, 1.00)
TIER_WITHIN = "within_budget"
TIER_OVER = "over"
TIER_UNBUDGETED = "unbudgeted"

# The notification lists at most this many proposals (the card has them all).
_NOTE_MAX_PROPOSALS = 5


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested — no network)
# ---------------------------------------------------------------------------
def parse_tiers(spec) -> list[float]:
    """``"0.25,0.50,1.00"`` → ``[0.25, 0.5, 1.0]`` (sorted, deduped, positive).
    Anything unparsable falls back to the defaults. Pure."""
    if isinstance(spec, (list, tuple)):
        raw = list(spec)
    else:
        raw = str(spec or "").split(",")
    out: set[float] = set()
    for item in raw:
        try:
            v = float(item)
        except (TypeError, ValueError):
            continue
        if v > 0:
            out.add(round(v, 4))
    return sorted(out) or list(DEFAULT_TIERS)


def tier_key(tier: float) -> str:
    """``0.25`` → ``"plus_25"``. Pure."""
    return f"plus_{int(round(tier * 100))}"


def tier_ceilings(deployable, tiers: list[float]) -> dict:
    """Cumulative dollar ceilings per tier over the deployable envelope, or an
    all-None map when the client has no usable envelope. Pure."""
    try:
        base = float(deployable) if deployable is not None else None
    except (TypeError, ValueError):
        base = None
    if base is None or base <= 0:
        return {TIER_WITHIN: None, **{tier_key(t): None for t in tiers}}
    ceilings = {TIER_WITHIN: round(base, 2)}
    for t in tiers:
        ceilings[tier_key(t)] = round(base * (1.0 + t), 2)
    return ceilings


def tier_rank(tier_label: str, tiers: list[float]) -> int:
    """Ordering of tier labels (within < plus_25 < … < over). Pure."""
    order = [TIER_WITHIN] + [tier_key(t) for t in tiers] + [TIER_OVER]
    return order.index(tier_label) if tier_label in order else len(order)


def assign_tiers(proposals: list[dict], deployable, tiers: list[float]) -> tuple[list[dict], dict]:
    """Walk the proposals in the strategist's priority order keeping a running
    cost total; each gets the first tier whose ceiling covers the running total.
    Returns (proposals with ``tier`` + ``cumulative_cost_usd``, summary). Pure.

    Unpriced proposals (``est_cost_usd`` None) add nothing to the total and take
    the running tier. With no usable envelope every proposal is ``unbudgeted``.
    """
    ceilings = tier_ceilings(deployable, tiers)
    ordered_keys = [TIER_WITHIN] + [tier_key(t) for t in tiers]
    budgeted = ceilings[TIER_WITHIN] is not None
    running = 0.0
    out: list[dict] = []
    by_tier: dict[str, int] = {}
    for p in proposals or []:
        q = dict(p)
        cost = q.get("est_cost_usd")
        try:
            running += float(cost) if cost is not None else 0.0
        except (TypeError, ValueError):
            pass
        if not budgeted:
            label = TIER_UNBUDGETED
        else:
            label = TIER_OVER
            for key in ordered_keys:
                if running <= ceilings[key] + 1e-9:
                    label = key
                    break
        q["tier"] = label
        q["cumulative_cost_usd"] = round(running, 2)
        by_tier[label] = by_tier.get(label, 0) + 1
        out.append(q)
    summary = {
        "fundable_count": by_tier.get(TIER_WITHIN, 0),
        "total_cost_usd": round(running, 2),
        "by_tier": by_tier,
        "ceilings": ceilings,
    }
    return out, summary


def budget_snapshot(envelope: Optional[dict], summary: dict, root_cause: str,
                    goals: list[dict], tiers: list[float]) -> dict:
    """What the plan was costed against — persisted on the review row so an
    edited retainer never silently re-tiers an old plan. Pure."""
    return {
        "envelope": dict(envelope or {}),
        "tiers": summary.get("ceilings") or {},
        "tier_steps": list(tiers),
        "fundable_count": summary.get("fundable_count", 0),
        "total_cost_usd": summary.get("total_cost_usd", 0.0),
        "by_tier": summary.get("by_tier") or {},
        "root_cause": (root_cause or "").strip(),
        "goals": list(goals or []),
    }


def goals_context(items: list[tuple[dict, dict]], today: date) -> list[dict]:
    """(escalation row, goal eval) pairs → the compact goal list the run prompt
    and the notification carry. Pure."""
    from services import goal_escalation as ge

    out = []
    for row, g in items or []:
        weeks = ge.weeks_behind(ge._parse_date(row.get("behind_since")), today)
        out.append({
            "goal_id": g.get("id") or row.get("goal_id"),
            "escalation_id": row.get("id"),
            "label": ge.goal_label(g),
            "goal_type": g.get("goal_type"),
            "status": g.get("status"),
            "weeks_behind": weeks,
            "behind_since": row.get("behind_since"),
            "baseline_value": g.get("baseline_value"),
            "current_value": g.get("current_value"),
            "target_value": g.get("effective_target"),
            "worst_value": row.get("worst_value"),
            "keyword": g.get("keyword"),
        })
    return out


def oldest_behind(goals: list[dict]) -> Optional[str]:
    """The earliest ``behind_since`` across a client's chronic goals. Pure."""
    dates = [g.get("behind_since") for g in goals or [] if g.get("behind_since")]
    return min(dates) if dates else None


def order_for_cap(candidates: list[dict], cap: int) -> tuple[list[dict], list[dict]]:
    """Oldest-behind first; the first ``cap`` get a run this tick, the rest roll
    forward (not escalated at all today). Pure."""
    ordered = sorted(
        candidates or [],
        key=lambda c: (oldest_behind(c.get("goals") or []) or "9999-12-31", c.get("client_id") or ""),
    )
    if cap is None or cap < 0:
        cap = 0
    return ordered[:cap], ordered[cap:]


def _fmt_money(v) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def build_recovery_block(goals: list[dict], prior_proposals: list[dict],
                         envelope: Optional[dict], ceilings: dict,
                         tiers: list[float]) -> str:
    """The RECOVERY block appended to the run prompt. Pure."""
    lines = ["CHRONIC-GOAL RECOVERY CONTEXT"]
    lines.append("Goals critically behind (build the plan around THESE):")
    for g in goals or []:
        lines.append(
            f"- {g.get('label')} [{g.get('goal_type')}] — {g.get('status')} for "
            f"{g.get('weeks_behind')} week(s) since {g.get('behind_since')}; "
            f"baseline {g.get('baseline_value')}, worst {g.get('worst_value')}, "
            f"now {g.get('current_value')}, target {g.get('target_value')}"
            + (f"; keyword '{g.get('keyword')}'" if g.get("keyword") else "")
        )
    if not goals:
        lines.append("- (none listed — read campaign_goals in the digest for the behind/overdue ones)")
    env = envelope or {}
    lines.append("")
    lines.append(
        "Budget envelope this month (from the client card, computed by the Recipe Engine): "
        f"retainer {_fmt_money(env.get('retainer_monthly'))}, deployable "
        f"{_fmt_money(env.get('deployable'))} at margin {env.get('margin_used')}, reporting "
        f"{_fmt_money(env.get('reporting_cost'))}, baseline stack "
        f"{_fmt_money(env.get('baseline_stack_cost'))}, discretionary "
        f"{_fmt_money(env.get('discretionary'))}."
    )
    tier_bits = [f"within budget ≤ {_fmt_money(ceilings.get(TIER_WITHIN))}"] + [
        f"+{int(round(t * 100))}% ≤ {_fmt_money(ceilings.get(tier_key(t)))}" for t in tiers
    ]
    lines.append("Budget tiers (cumulative over deployable, assigned by the SYSTEM from the running "
                 "total of your proposals in the order you list them): " + "; ".join(tier_bits) + ".")
    lines.append("")
    if prior_proposals:
        lines.append("Prior recovery plan — still-open proposals (refresh/re-cost these; anything you "
                     "re-emit replaces them, anything you drop is superseded):")
        for p in prior_proposals:
            lines.append(
                f"- [{p.get('status') or 'proposed'}] {p.get('title')} — "
                f"{_fmt_money(p.get('est_cost_usd')) if p.get('est_cost_usd') is not None else 'unpriced'}"
                + (f", {p.get('age_days')}d old" if p.get("age_days") is not None else "")
            )
    else:
        lines.append("Prior recovery plan: none — this is the first recovery plan for these goals.")
    return "\n".join(lines)


def _proposal_line(i: int, p: dict) -> str:
    cost = p.get("est_cost_usd")
    cost_txt = _fmt_money(cost) if cost is not None else (
        "tool cost" if p.get("cost_basis") == "operational" else "no cost")
    tier = p.get("tier")
    tier_txt = {
        TIER_WITHIN: "within budget", TIER_OVER: "over every tier",
        TIER_UNBUDGETED: "unbudgeted",
    }.get(tier, f"+{tier.split('_', 1)[1]}%" if isinstance(tier, str) and tier.startswith("plus_") else "")
    senior = " · Kyle/Ryan only" if p.get("requires") == "senior" else ""
    return f"{i}. {p.get('title')} — {cost_txt}" + (f" · {tier_txt}" if tier_txt else "") + senior


def build_recovery_notification(client_name: str, goals: list[dict], review: dict,
                                budget: dict, link: str) -> dict:
    """The single ``goal_chronic`` message the FINISHED run sends: alarm + root
    cause + the plan's top proposals + the fundable line + link. Pure."""
    goals = goals or []
    weeks = max([g.get("weeks_behind") or 0 for g in goals] or [0])
    first = goals[0] if goals else {}
    if goals:
        label = first.get("label") or "goal"
        more = f" (+{len(goals) - 1} more)" if len(goals) > 1 else ""
        title = f"STILL CRITICAL (week {weeks}): {client_name or 'client'} — {label}{more}"
        cur, tgt = first.get("current_value"), first.get("target_value")
        gap = (f" — now {cur:g} vs target {tgt:g}"
               if (isinstance(cur, (int, float)) and not isinstance(cur, bool)
                   and isinstance(tgt, (int, float)) and not isinstance(tgt, bool)) else "")
        status = first.get("status") or "behind"
        parts = [f'"{label}" has been {status} for {weeks} week{"s" if weeks != 1 else ""}{gap}.']
    else:
        # The run had no goal context (an on-demand run whose goals could not be
        # re-derived) — never fabricate a "week 0" alarm around a nameless goal.
        title = f"Recovery plan ready: {client_name or 'client'}"
        parts = ["A chronic-goal recovery run completed for this client."]
    root = (budget.get("root_cause") or "").strip()
    if root:
        parts.append(f"Root cause: {root}")
    proposals = [p for p in (review.get("proposals") or []) if (p.get("status") or "proposed") == "proposed"]
    ceilings = budget.get("tiers") or {}
    n = len(proposals)
    fundable = budget.get("fundable_count", 0)
    if n:
        by_tier = budget.get("by_tier") or {}
        tier_steps = budget.get("tier_steps") or list(DEFAULT_TIERS)
        covered_bits = []
        running = 0
        for key in [TIER_WITHIN] + [tier_key(t) for t in tier_steps]:
            running += by_tier.get(key, 0)
            if key != TIER_WITHIN and by_tier.get(key):
                covered_bits.append(f"+{key.split('_', 1)[1]}% covers {running}")
        head = f"Recovery plan ({n} proposal{'s' if n != 1 else ''}, {fundable} within budget"
        if ceilings.get(TIER_WITHIN) is not None:
            head += f" of {_fmt_money(ceilings[TIER_WITHIN])} deployable"
        head += (", " + ", ".join(covered_bits) if covered_bits else "") + "):"
        parts.append(head)
        for i, p in enumerate(proposals[:_NOTE_MAX_PROPOSALS], 1):
            parts.append(_proposal_line(i, p))
        if n > _NOTE_MAX_PROPOSALS:
            parts.append(f"… {n - _NOTE_MAX_PROPOSALS} more on the Action Plan card.")
        parts.append("Approve a proposal (or a whole tier) on the Strategist Review card to send it to PACE.")
    else:
        parts.append("The recovery run produced NO proposals — open the review; it may be truncated or "
                     "observation-only (frozen client).")
    return {
        "title": title[:200],
        "summary": "\n".join(parts),
        "severity": "critical",
        "payload": {
            "link": link,
            "review_id": review.get("id"),
            "goal_ids": [g.get("goal_id") for g in goals],
            "weeks_behind": weeks,
            "fundable_count": fundable,
            "proposal_count": n,
            "tiers": ceilings,
        },
    }


def mark_superseded(proposals: list[dict]) -> tuple[list[dict], list[int]]:
    """``proposed`` → ``superseded`` (approved/dismissed untouched). Returns the
    new list and the indices that changed. Pure."""
    out, changed = [], []
    for i, p in enumerate(proposals or []):
        q = dict(p)
        if (q.get("status") or "proposed") == "proposed":
            q["status"] = "superseded"
            changed.append(i)
        out.append(q)
    return out, changed


def prior_open_recovery_proposals(open_proposals: Optional[dict]) -> list[dict]:
    """The digest's open_proposals items that came from earlier recovery runs. Pure."""
    items = (open_proposals or {}).get("items") or []
    return [p for p in items if p.get("trigger") == TRIGGER]


# ---------------------------------------------------------------------------
# Impure — gates, reads, enqueue, post-run side effects (all best-effort)
# ---------------------------------------------------------------------------
def gate_open() -> bool:
    return bool(settings.goal_recovery_enabled and settings.strategist_enabled
                and settings.goal_escalation_enabled)


def tiers() -> list[float]:
    return parse_tiers(settings.goal_recovery_tiers)


def clients_recovered_within(days: int) -> set[str]:
    """Clients with a COMPLETE recovery review inside the window (a failed run
    must not block the retry the next tick brings)."""
    if days <= 0:
        return set()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        rows = (
            get_supabase().table("strategy_reviews").select("client_id")
            .eq("trigger", TRIGGER).eq("status", "complete")
            .gte("created_at", cutoff).execute()
        ).data or []
    except Exception as exc:
        logger.warning("goal_recovery.recovered_within_read_failed", extra={"error": str(exc)})
        return set()
    return {r["client_id"] for r in rows if r.get("client_id")}


def enqueue_recovery_run(client_id: str, goals: list[dict]) -> tuple[str, Optional[str]]:
    """Enqueue one recovery run. Returns (status, review_id) with status one of
    ``enqueued`` / ``in_flight`` (a run for this client is already queued or
    running) / ``disabled`` (gate closed or the client opted out) / ``failed``."""
    from services import strategist

    if not gate_open():
        return "disabled", None
    try:
        if strategist._strategist_excluded(client_id):
            return "disabled", None
        review_id = strategist.enqueue_strategy_review(
            client_id, trigger=TRIGGER,
            escalation_context={"kind": NOTIFICATION_KIND, "goals": goals},
        )
    except Exception as exc:
        logger.warning("goal_recovery.enqueue_failed", extra={"client_id": client_id, "error": str(exc)})
        return "failed", None
    if review_id is None:
        return "in_flight", None
    return "enqueued", review_id


def load_recovery_context(client_id: str, escalation_context: Optional[dict],
                          digest: dict) -> dict:
    """Everything the run needs beyond the digest: the chronic goals (from the
    sweep's context, else re-derived for an on-demand run), the prior open
    recovery proposals, the budget envelope and tier ceilings. Best-effort —
    every read degrades to an empty section."""
    from services import recipe_engine

    goals = list((escalation_context or {}).get("goals") or [])
    if not goals:
        try:
            from services import campaign_goals, goal_escalation as ge

            today = date.today()
            supabase = get_supabase()
            evals = campaign_goals.assess_goals(client_id, today)
            open_rows = ge._open_escalations(supabase, client_id)
            items = []
            for g in evals:
                if not ge.is_critical(g.get("status")) or g.get("goal_type") == "custom":
                    continue
                row = open_rows.get(g.get("id")) or {
                    "goal_id": g.get("id"),
                    "behind_since": ge.initial_behind_since(g, today).isoformat(),
                    "worst_value": g.get("current_value"),
                }
                items.append((row, g))
            goals = goals_context(items, today)
        except Exception as exc:
            logger.warning("goal_recovery.goals_read_failed", extra={"client_id": client_id, "error": str(exc)})
            goals = []
    client = digest.get("client") or {}
    envelope: Optional[dict] = None
    try:
        retainer = client.get("retainer_monthly")
        envelope = recipe_engine.budget_envelope(
            float(retainer) if retainer not in (None, "") else None,
            margin=recipe_engine.DEFAULT_MARGIN,
            is_sab=bool(client.get("is_sab")),
        )
    except Exception as exc:
        logger.warning("goal_recovery.envelope_failed", extra={"client_id": client_id, "error": str(exc)})
    steps = tiers()
    return {
        "goals": goals,
        "prior_proposals": prior_open_recovery_proposals(digest.get("open_proposals")),
        "envelope": envelope,
        "ceilings": tier_ceilings((envelope or {}).get("deployable"), steps),
        "tiers": steps,
    }


def apply_budget(review_body: dict, recovery: dict) -> tuple[dict, dict]:
    """Tier the sanitized proposals + build the budget snapshot. Pure given its
    inputs (kept here so the run has one call)."""
    steps = recovery.get("tiers") or tiers()
    proposals, summary = assign_tiers(
        review_body.get("proposals") or [],
        (recovery.get("envelope") or {}).get("deployable"),
        steps,
    )
    body = dict(review_body)
    body["proposals"] = proposals
    budget = budget_snapshot(
        recovery.get("envelope"), summary, review_body.get("root_cause") or "",
        recovery.get("goals") or [], steps,
    )
    return body, budget


def supersede_prior_recovery(client_id: str, current_review_id: str,
                             client_name: Optional[str]) -> int:
    """Mark the still-open proposals of EARLIER recovery reviews ``superseded``
    (never weekly/escalation reviews), recording each in the action log.
    Returns the number superseded. Best-effort."""
    supabase = get_supabase()
    try:
        rows = (
            supabase.table("strategy_reviews").select("id, proposals")
            .eq("client_id", client_id).eq("trigger", TRIGGER).eq("status", "complete")
            .neq("id", current_review_id).order("created_at", desc=True).limit(20).execute()
        ).data or []
    except Exception as exc:
        logger.warning("goal_recovery.supersede_read_failed", extra={"client_id": client_id, "error": str(exc)})
        return 0
    total = 0
    for r in rows:
        updated, changed = mark_superseded(r.get("proposals") or [])
        if not changed:
            continue
        try:
            supabase.table("strategy_reviews").update({"proposals": updated}).eq("id", r["id"]).execute()
        except Exception as exc:
            logger.warning("goal_recovery.supersede_write_failed", extra={"review_id": r.get("id"), "error": str(exc)})
            continue
        total += len(changed)
        try:
            from services import sermastr_audit

            for idx in changed:
                sermastr_audit.record_superseded(
                    review_id=r["id"], idx=idx, proposal=updated[idx],
                    client_id=client_id, client_name=client_name, trigger=TRIGGER,
                )
        except Exception as exc:
            logger.warning("goal_recovery.supersede_audit_failed", extra={"review_id": r.get("id"), "error": str(exc)})
    return total


def stamp_escalations(goals: list[dict], now: datetime) -> int:
    """Advance ``last_escalated_at`` + ``escalation_count`` on the goal_escalations
    rows this run covered — the sweep deferred the stamp to the run so a failed
    run retries next tick. Returns rows stamped. Best-effort."""
    supabase = get_supabase()
    stamped = 0
    for g in goals or []:
        eid = g.get("escalation_id")
        if not eid:
            continue
        try:
            rows = (
                supabase.table("goal_escalations").select("id, escalation_count")
                .eq("id", eid).limit(1).execute()
            ).data or []
            count = (rows[0].get("escalation_count") if rows else 0) or 0
            supabase.table("goal_escalations").update({
                "last_escalated_at": now.isoformat(),
                "escalation_count": count + 1,
                "updated_at": now.isoformat(),
            }).eq("id", eid).execute()
            stamped += 1
        except Exception as exc:
            logger.warning("goal_recovery.stamp_failed", extra={"escalation_id": eid, "error": str(exc)})
    return stamped


def after_persist(client_id: str, review: dict, recovery: dict, budget: dict,
                  client_name: Optional[str]) -> None:
    """Post-run side effects for a persisted recovery review: supersede the prior
    plan, stamp the escalations, emit the ONE goal_chronic message. Each step is
    best-effort and independent — a failure in one never blocks the next."""
    from services import notifications

    review_id = review.get("id")
    # Only a review that actually carries a plan may retire the previous one —
    # a frozen (observation-only) or truncated run with zero proposals must not
    # erase the plan the owner could still approve.
    if review.get("proposals"):
        try:
            supersede_prior_recovery(client_id, str(review_id), client_name)
        except Exception as exc:
            logger.warning("goal_recovery.supersede_failed", extra={"client_id": client_id, "error": str(exc)})
    else:
        logger.info("goal_recovery.supersede_skipped_empty_plan",
                    extra={"client_id": client_id, "review_id": str(review_id)})
    try:
        stamp_escalations(recovery.get("goals") or [], datetime.now(timezone.utc))
    except Exception as exc:
        logger.warning("goal_recovery.stamp_all_failed", extra={"client_id": client_id, "error": str(exc)})
    try:
        note = build_recovery_notification(
            client_name or "client", recovery.get("goals") or [], review, budget,
            f"clients/{client_id}/action-plan",
        )
        notifications.emit(
            client_id=client_id, kind=NOTIFICATION_KIND, title=note["title"],
            summary=note["summary"], severity=note["severity"], payload=note["payload"],
        )
    except Exception as exc:
        logger.warning("goal_recovery.notify_failed", extra={"client_id": client_id, "error": str(exc)})

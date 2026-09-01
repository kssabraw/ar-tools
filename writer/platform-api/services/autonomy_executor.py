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

Two independent clamps keep this safe:
  * ``autonomy_enabled`` (default False) — the whole loop is dormant.
  * ``AUTO_EXECUTE`` — even enabled, only the free plan rebuild and the ONE safe
    content case run: a net-new Local SEO page for a "Create page" quick-win
    **whose keyword itself names a resolvable city** (so the target is explicit —
    no location guessing, no geo-mismatch, and a bare head term that would
    duplicate the client's primary-city page resolves to no city and is only
    proposed). Reoptimising an existing page (needs a URL the Action Plan item
    doesn't carry) and blog/service runs stay proposals recorded in the ledger +
    digest for a human. This is why a striking-distance keyword never silently
    becomes a cannibalising new page.

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
# Pure channel helpers shared with the Action Plan (#2 / #3) — no I/O, no cycle
# (reopt_planner never imports autonomy).
from services.reopt_planner import action_channel, goal_channels

logger = logging.getLogger(__name__)

# v1 auto-executable set — deliberately just the free, idempotent, reversible
# plan rebuild. Widen ONLY after a pilot gate run reads the ledger and trusts a
# class. Keys are action names understood by ``_execute``.
AUTO_EXECUTE: frozenset[str] = frozenset({"rebuild_action_plan", "generate_local_seo_page"})

_BEHIND = {"behind", "overdue"}

# Goal-type→lever routing (#3, owner-approved PROPOSAL-ONLY): when a client's
# BEHIND goal is measured on the local pack / GBP (the "maps" channel), the
# organic quick_win/opportunity items the existing pass emits are the wrong
# lever. This maps each local/GBP Action Plan kind to the lever a human would
# use, surfaced as a requires="approval" proposal so the ledger/digest shows the
# right-channel work. NONE of these ever auto-run: a requires="approval"
# candidate always classifies as "propose" (autonomy_policy rule 3), and even
# the AUTO_EXECUTE-listed generate_local_seo_page is held by that same rule. So
# no guardrail is loosened and AUTO_EXECUTE is untouched.
_MAPS_KIND_LEVER: dict[str, str] = {
    "maps_weak_area": "generate_local_seo_page",  # create the missing location page
    "maps_competitor_land_grab": "generate_local_seo_page",  # answer a rival's page in a weak zone
    "content_gap": "generate_local_seo_page",
    "gbp_gap": "schedule_gbp_posts",
    "review_gap": "schedule_gbp_posts",
    "local_relevance": "schedule_gbp_posts",
    "maps_decline": "schedule_gbp_posts",
    "maps_competitor": "schedule_gbp_posts",
    "maps_gradual_decline": "schedule_gbp_posts",
    "maps_solv_drop": "schedule_gbp_posts",
}


# --- Pure core --------------------------------------------------------------

def gather_candidates(
    goals: list[dict],
    action_plan: Optional[dict],
    resolve_city: Optional[Callable[[str], Optional[dict]]] = None,
) -> list[dict]:
    """Deterministic candidate actions for a client with behind/overdue goals.

    Pure (the only non-determinism is the injected ``resolve_city`` — a
    keyword→city lookup the impure caller wires to DataForSEO; tests inject a
    fake). Emits:
      * one free ``rebuild_action_plan`` whenever any goal is behind/overdue;
      * per Action Plan quick_win / opportunity item, a content candidate whose
        ACTION and AUTO-ELIGIBILITY follow the item's own signal:
          - a "Create page" quick-win **whose keyword itself names a resolvable
            city** (``resolve_city(keyword)`` returns a ``{location,
            location_code}``) → an auto-eligible ``generate_local_seo_page``
            (``requires="none"``) targeting exactly that city. This is the ONLY
            content that auto-runs, and it is safe on all three counts the pilot
            exposed: the target is the city written in the keyword (no guessing a
            location, no geo-mismatch), and a keyword that carries its own city
            is a distinct geo page (a bare head term — which would duplicate the
            client's primary-city page — resolves to no city and is proposed).
          - everything else — a "Reoptimize" quick-win or an opportunity (both
            want an EXISTING page improved, but the Action Plan item carries no
            URL), or a create-page item whose keyword names no resolvable city —
            stays ``requires="approval"`` (surfaced, never auto-run). The action
            name reflects intent (reoptimize_page vs generate_local_seo_page) so
            the proposal reads correctly and classifies at the right tier.

    Cost estimates are attached so the budget governor gates real spend.
    """
    behind = [g for g in goals if g.get("status") in _BEHIND]
    if not behind:
        return []

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

        city = resolve_city(kw) if (create_page and resolve_city) else None
        if create_page and city and city.get("location_code") is not None:
            # Auto-eligible: a net-new page for the city named in the keyword.
            out.append({
                "action": "generate_local_seo_page",
                "keyword": kw,
                "location": city["location"],
                "location_code": city["location_code"],
                "cost_usd": float(settings.autonomy_local_seo_cost_usd),
                "requires": "none",
                "source": source,
                "reason": reason,
            })
        else:
            # Proposal only: improving an existing page needs a URL the plan
            # doesn't carry, or a create-page keyword names no resolvable city
            # to target (a bare head term / a geo the lookup can't confirm).
            out.append({
                "action": "generate_local_seo_page" if create_page else "reoptimize_page",
                "keyword": kw,
                "cost_usd": float(settings.autonomy_content_cost_usd),
                "requires": "approval",
                "source": source,
                "reason": reason,
            })

    # Goal-type→lever routing (#3): a client whose BEHIND goal is measured on the
    # local pack / GBP needs its GBP/Maps levers, not (only) organic pages — but
    # the pass above reads only organic-channel quick_win/opportunity kinds. Add
    # the local/GBP Action Plan items as PROPOSAL-ONLY candidates so the ledger +
    # owner digest surface the right-channel work. Never auto (requires="approval"
    # ⇒ always "propose"); no spend reserved; AUTO_EXECUTE untouched.
    if "maps" in goal_channels(goals):
        for item in (action_plan or {}).get("items") or []:
            if action_channel(item.get("kind")) != "maps":
                continue
            lever = _MAPS_KIND_LEVER.get(item.get("kind"))
            if not lever:
                continue
            out.append({
                "action": lever,
                "keyword": (item.get("keyword") or "").strip() or None,
                "cost_usd": 0.0,  # proposal only — a human runs the lever; no budget reserved
                "requires": "approval",
                "source": f"action_plan:{item.get('kind')}",
                "reason": item.get("recommendation") or item.get("kind"),
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
        # runs the generator) — no inline pipeline. Location + location_code were
        # resolved from the keyword's own city in gather_candidates, so the
        # generator trusts the code (no re-resolution / no ambiguity). The
        # generated page lands as a Saved-Pages DRAFT; publishing stays human.
        get_supabase().table("async_jobs").insert({
            "job_type": "local_seo_generate",
            "entity_id": client_id,
            "payload": {
                "client_id": client_id,
                "keyword": candidate.get("keyword"),
                "location": candidate.get("location"),
                "location_code": candidate.get("location_code"),
                "user_id": "",
                "force_refresh": False,
                "entity_provider": None,
            },
        }).execute()
        return
    raise ValueError(f"no executor for action {action!r}")


# A city name is at most a few words ("West Palm Beach", "North Miami Beach").
_MAX_CITY_WORDS = 3


def _resolve_keyword_city(client: dict, keyword: str) -> Optional[dict]:
    """If the keyword ends in a real, DataForSEO-resolvable city, return
    ``{location, location_code}`` for it — else None.

    Tries the longest trailing word-window first ("… west palm beach" →
    "west palm beach") and accepts only an EXACT city-name match (the resolved
    location's first segment equals the window), so a service word that isn't a
    place resolves to nothing and the candidate falls through to a proposal
    (fail-closed). Requires ≥1 leading (service) word, so a keyword that is
    *only* a city isn't treated as a "<service> <city>" page. Best-effort:
    any lookup failure → None (proposal), never raises."""
    import asyncio

    from services import locations_service

    words = (keyword or "").strip().split()
    if len(words) < 2:  # need a leading service term + a trailing place
        return None

    async def _find() -> Optional[dict]:
        # window length capped at min(_MAX_CITY_WORDS, len-1): at least one word
        # must remain in front of the city.
        for n in range(min(_MAX_CITY_WORDS, len(words) - 1), 0, -1):
            window = " ".join(words[-n:]).strip()
            if len(window) < 3:
                continue
            try:
                matches = await locations_service.search_locations(client, window, limit=5)
            except Exception:  # noqa: BLE001 — a lookup failure is not a match
                return None
            for m in matches:
                first_seg = (m.get("location_name") or "").split(",")[0].strip().lower()
                if first_seg == window.lower() and m.get("location_code") is not None:
                    return {"location": m["location_name"], "location_code": m["location_code"]}
        return None

    try:
        return asyncio.run(_find())
    except Exception as exc:  # noqa: BLE001 — includes "loop already running"
        logger.warning("autonomy_city_resolve_failed",
                       extra={"keyword": keyword, "error": str(exc)})
        return None


def _keyword_city_resolver(client: dict) -> Callable[[str], Optional[dict]]:
    """A sync ``keyword -> {location, location_code} | None`` closure over the
    client, injected into the pure ``gather_candidates``."""
    return lambda keyword: _resolve_keyword_city(client, keyword)


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
        goals, _latest_action_plan(client_id), _keyword_city_resolver(client)
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
        # Director of Operations pre-flight veto (plan §5 decision 4; build
        # spec §8). Ships dark behind director_autonomy_veto_enabled — guards
        # a collision that hasn't been observed yet. Fail-open by construction
        # (director_veto.preflight_conflict never raises); placed BEFORE the
        # budget reserve so a vetoed candidate never touches spend.
        if settings.director_autonomy_veto_enabled:
            from services.director import veto as director_veto

            if director_veto.preflight_conflict(rec, client_id):
                rec["outcome"] = "propose"
                rec["policy_reason"] = "director veto: in-flight conflicting action on same target"
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
